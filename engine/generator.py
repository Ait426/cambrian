"""Cambrian 스킬 자동 생성 엔진."""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.exceptions import SkillNotFoundError
from engine.fuser import SkillFuser
from engine.llm import LLMProvider, create_provider
from engine.loader import SkillLoader
from engine.models import (
    GenerateRequest,
    GenerateResult,
    SearchQuery,
    Skill,
)
from engine.registry import SkillRegistry

logger = logging.getLogger(__name__)

# 출력 ID 정규식
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

GENERATE_SYSTEM_PROMPT = """You are a Cambrian skill generator.
You create complete, production-ready skill packages from a goal description.

A skill package consists of 3 files:
1. meta.yaml — identity and runtime configuration
2. interface.yaml — input/output JSON schema contract
3. SKILL.md — LLM instruction document (for mode "a" skills)

RULES:
1. meta.yaml MUST follow this exact structure:
   id: <will be overridden by system>
   version: "1.0.0"
   name: <clear, concise name>
   description: <one-line description of what the skill does>
   domain: <domain>
   tags: [<relevant tags>]
   author: "cambrian-generator"
   created_at: <will be overridden>
   updated_at: <will be overridden>
   mode: "a"
   runtime:
     language: "python"
     needs_network: false
     needs_filesystem: false
     timeout_seconds: 30

2. interface.yaml MUST define input and output sections:
   - Each: type: object, properties (each with type + description), required
   - Design inputs that are minimal but sufficient for the goal
   - Design outputs as a structured JSON object

3. SKILL.md MUST be a complete, self-contained LLM instruction that:
   - Clearly states the purpose in a ## Purpose section
   - Describes step-by-step how to process the input
   - Specifies the EXACT JSON output format in a ## Output Format section
   - Includes at least one example in a ## Examples section
   - Handles edge cases (empty input, missing fields)

4. Do NOT invent capabilities beyond the stated goal
5. Keep the skill focused on ONE clear purpose
6. If reference skills are provided, learn from their style but create something NEW

Respond with ONLY a JSON object:
{
  "meta_yaml": "<full meta.yaml content>",
  "interface_yaml": "<full interface.yaml content>",
  "skill_md": "<full SKILL.md content>",
  "generation_rationale": "<brief explanation of design choices>"
}"""


class SkillGenerator:
    """스킬을 0에서 자동 생성한다. fuser.validate_and_deploy()를 재사용."""

    def __init__(
        self,
        fuser: SkillFuser,
        registry: SkillRegistry,
        loader: SkillLoader,
        searcher: "SkillSearcher | None" = None,
        provider: LLMProvider | None = None,
    ) -> None:
        """초기화.

        Args:
            fuser: SkillFuser 인스턴스 (validate_and_deploy 재사용)
            registry: SkillRegistry 인스턴스
            loader: SkillLoader 인스턴스
            searcher: SkillSearcher 인스턴스. None이면 사전 검색 불가.
            provider: LLM 프로바이더. None이면 호출 시 자동 생성.
        """
        self._fuser = fuser
        self._registry = registry
        self._loader = loader
        self._searcher = searcher
        self._provider = provider

    # ═══════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═══════════════════════════════════════════════════════════════

    def generate(self, request: GenerateRequest) -> GenerateResult:
        """스킬을 0에서 생성한다.

        Args:
            request: GenerateRequest 생성 요청

        Returns:
            GenerateResult 생성 결과
        """
        fail_kwargs = {
            "skill_id": "", "skill_path": "", "goal": request.goal,
            "domain": request.domain, "tags": request.tags,
            "output_mode": request.output_mode, "generation_rationale": "",
        }

        # 1. 입력 검증
        errors = self._validate_request(request)
        if errors:
            return GenerateResult(
                success=False, warnings=errors, **fail_kwargs,
            )

        # 2. 출력 ID 결정
        try:
            output_id = self._resolve_output_id(request)
        except ValueError as exc:
            return GenerateResult(
                success=False, warnings=[str(exc)], **fail_kwargs,
            )

        # 3. 유사 스킬 사전 검색
        similar_results = []
        if not request.skip_search and self._searcher is not None:
            similar_results = self._find_similar_skills(request)

        # 4. generate 필요 여부 판정
        if similar_results:
            should, alternatives = self._should_generate(similar_results)
            if not should:
                return GenerateResult(
                    success=False,
                    skill_id=output_id,
                    skill_path="",
                    goal=request.goal,
                    domain=request.domain,
                    tags=request.tags,
                    output_mode=request.output_mode,
                    generation_rationale="",
                    existing_alternatives=alternatives,
                    warnings=["기존 스킬로 충분합니다. 'cambrian search ...' 참고"],
                )

        # 5. few-shot 참고 스킬 수집
        references = self._collect_references(request, similar_results)

        # 6. LLM 호출
        temp_dir: Path | None = None
        try:
            llm_output = self._generate_skill_files(request, output_id, references)
            if llm_output is None:
                return GenerateResult(
                    success=False,
                    skill_id=output_id,
                    skill_path="",
                    goal=request.goal,
                    domain=request.domain,
                    tags=request.tags,
                    output_mode=request.output_mode,
                    generation_rationale="",
                    reference_skill_ids=[r.id for r in references],
                    warnings=["LLM이 유효한 JSON을 반환하지 않음"],
                )

            # 7. 파일 작성 + guardrail
            temp_dir = self._write_and_guard(output_id, llm_output, request)

            # 8. validate_and_deploy (fuser 재사용)
            deploy = self._fuser.validate_and_deploy(
                temp_dir, output_id, request.output_mode, request.dry_run,
            )

            return GenerateResult(
                success=deploy["success"],
                skill_id=output_id,
                skill_path=deploy["skill_path"],
                goal=request.goal,
                domain=request.domain,
                tags=request.tags,
                output_mode=request.output_mode,
                generation_rationale=llm_output.get("generation_rationale", ""),
                reference_skill_ids=[r.id for r in references],
                validation_passed=deploy["validation_passed"],
                validation_errors=deploy.get("validation_errors", []),
                security_passed=deploy.get("security_passed", True),
                security_violations=deploy.get("security_violations", []),
                registered=deploy.get("registered", False),
                dry_run=request.dry_run,
                warnings=deploy.get("warnings", []),
            )
        finally:
            if temp_dir is not None and temp_dir.exists() and not request.dry_run:
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ═══════════════════════════════════════════════════════════════
    # Step 1: 입력 검증
    # ═══════════════════════════════════════════════════════════════

    def _validate_request(self, request: GenerateRequest) -> list[str]:
        """요청의 유효성을 검증한다.

        Args:
            request: 생성 요청

        Returns:
            에러 메시지 리스트. 빈 리스트면 통과.
        """
        errors: list[str] = []

        if len(request.goal.strip()) < 10:
            errors.append("goal은 최소 10자 이상이어야 합니다")

        if not request.domain or not request.domain.strip():
            errors.append("domain은 비어있을 수 없습니다")

        if not request.tags or len(request.tags) == 0:
            errors.append("tags는 최소 1개 이상이어야 합니다")

        if request.output_mode != "a":
            errors.append("v1에서는 output_mode='a'만 지원합니다")

        if request.project_path is not None:
            if not Path(request.project_path).exists():
                errors.append(f"project_path가 존재하지 않음: {request.project_path}")

        return errors

    # ═══════════════════════════════════════════════════════════════
    # Step 2: 출력 ID 결정
    # ═══════════════════════════════════════════════════════════════

    def _resolve_output_id(self, request: GenerateRequest) -> str:
        """결과 스킬 ID를 결정한다.

        Args:
            request: 생성 요청

        Returns:
            유효한 스킬 ID

        Raises:
            ValueError: 잘못된 output_id 형식
        """
        if request.output_id is not None:
            candidate = request.output_id
            if not _ID_PATTERN.match(candidate):
                raise ValueError(
                    f"잘못된 output_id 형식: '{candidate}' "
                    "(소문자 시작, 영소문자/숫자/_, 2~64자)"
                )
        else:
            # 자동 생성: domain_tags[0]
            tag_part = request.tags[0] if request.tags else "skill"
            combined = f"{request.domain}_{tag_part}"
            # 특수문자 제거
            combined = re.sub(r"[^a-z0-9_]", "_", combined.lower())
            if not combined[0].isalpha():
                combined = "s_" + combined
            candidate = combined[:64]

        # 중복 검사
        final_id = candidate
        suffix = 2
        while True:
            try:
                self._registry.get(final_id)
                final_id = f"{candidate}_{suffix}"
                suffix += 1
            except SkillNotFoundError:
                break

        return final_id

    # ═══════════════════════════════════════════════════════════════
    # Step 3: 유사 스킬 사전 검색
    # ═══════════════════════════════════════════════════════════════

    def _find_similar_skills(self, request: GenerateRequest) -> list:
        """유사 스킬을 사전 검색한다.

        Args:
            request: 생성 요청

        Returns:
            SearchResult 리스트
        """
        if self._searcher is None:
            return []

        query = SearchQuery(
            text=request.goal,
            domain=request.domain,
            tags=request.tags,
            include_external=False,
            limit=5,
        )
        report = self._searcher.search(query)
        return report.results

    # ═══════════════════════════════════════════════════════════════
    # Step 4: generate 필요 여부 판정
    # ═══════════════════════════════════════════════════════════════

    def _should_generate(
        self, similar_results: list,
    ) -> tuple[bool, list[dict]]:
        """generate가 필요한지 판정한다.

        Args:
            similar_results: 유사 검색 결과

        Returns:
            (should_generate, alternatives)
        """
        if not similar_results:
            return True, []

        # strong 매칭 (relevance >= 0.7) 존재 여부
        strong_matches = [
            r for r in similar_results if r.relevance_score >= 0.7
        ]

        if strong_matches:
            alternatives = [
                {
                    "skill_id": r.skill_id,
                    "name": r.name,
                    "relevance_score": r.relevance_score,
                    "source": r.source,
                }
                for r in strong_matches
            ]
            return False, alternatives

        # partial 매칭만 → generate 진행
        return True, []

    # ═══════════════════════════════════════════════════════════════
    # Step 5: few-shot 참고 스킬 수집
    # ═══════════════════════════════════════════════════════════════

    def _collect_references(
        self,
        request: GenerateRequest,
        similar_results: list,
    ) -> list[Skill]:
        """few-shot 참고 스킬을 수집한다.

        Args:
            request: 생성 요청
            similar_results: 사전 검색 결과

        Returns:
            로드된 Skill 객체 리스트 (최대 3개)
        """
        skill_ids: list[str] = []

        # 명시적 참고 스킬이 지정된 경우
        if request.reference_skills:
            skill_ids = list(request.reference_skills)
        elif similar_results:
            # 검색 결과 상위 2개
            skill_ids = [r.skill_id for r in similar_results[:2]]

        references: list[Skill] = []
        for sid in skill_ids[:3]:
            try:
                data = self._registry.get(sid)
                skill = self._loader.load(data["skill_path"])
                references.append(skill)
            except Exception as exc:
                logger.warning("참고 스킬 '%s' 로드 실패: %s", sid, exc)

        return references

    # ═══════════════════════════════════════════════════════════════
    # Step 6: LLM 호출
    # ═══════════════════════════════════════════════════════════════

    def _generate_skill_files(
        self,
        request: GenerateRequest,
        output_id: str,
        references: list[Skill],
    ) -> dict | None:
        """LLM을 호출하여 스킬 파일을 생성한다.

        Args:
            request: 생성 요청
            output_id: 결과 스킬 ID
            references: 참고 스킬 리스트

        Returns:
            파싱된 LLM 출력 dict 또는 None
        """
        provider = self._provider or create_provider()
        system_prompt, user_message = self._build_llm_context(
            request, output_id, references,
        )

        # 1차 시도
        try:
            response = provider.complete(
                system=system_prompt, user=user_message, max_tokens=8192,
            )
        except Exception as exc:
            logger.error("LLM 호출 실패: %s", exc)
            return None

        parsed = self._parse_llm_output(response)
        if parsed is not None:
            return parsed

        # 2차 시도 (에러 피드백)
        logger.warning("LLM 응답 파싱 실패, 재시도합니다")
        retry_user = (
            f"{user_message}\n\n"
            "## IMPORTANT: Previous attempt failed\n"
            "Your previous response was not valid JSON. "
            "Respond with ONLY a JSON object with keys: "
            "meta_yaml, interface_yaml, skill_md, generation_rationale. "
            "No markdown fences, no explanation."
        )

        try:
            response2 = provider.complete(
                system=system_prompt, user=retry_user, max_tokens=8192,
            )
        except Exception as exc:
            logger.error("LLM 재시도 실패: %s", exc)
            return None

        return self._parse_llm_output(response2)

    def _build_llm_context(
        self,
        request: GenerateRequest,
        output_id: str,
        references: list[Skill],
    ) -> tuple[str, str]:
        """LLM 입력 컨텍스트를 구성한다.

        Args:
            request: 생성 요청
            output_id: 결과 스킬 ID
            references: 참고 스킬 리스트

        Returns:
            (system_prompt, user_message) 튜플
        """
        ref_sections: list[str] = []
        for ref in references:
            interface_text = yaml.safe_dump(
                {"input": ref.interface_input, "output": ref.interface_output},
                allow_unicode=True, sort_keys=False,
            )
            skill_md = ref.skill_md_content or "(empty)"
            if len(skill_md) > 2000:
                skill_md = skill_md[:2000] + "\n... (truncated)"

            ref_sections.append(
                f"### Reference: {ref.id}\n"
                f"Name: {ref.name}\n"
                f"Description: {ref.description}\n"
                f"Domain: {ref.domain}\n"
                f"Tags: {', '.join(ref.tags)}\n\n"
                f"#### Interface\n{interface_text}\n"
                f"#### SKILL.md\n{skill_md}"
            )

        ref_text = "\n\n".join(ref_sections) if ref_sections else "(no reference skills)"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # goal 길이 제한
        goal_text = request.goal[:500]

        user_message = (
            f"## Goal\n{goal_text}\n\n"
            f"## Skill Identity\n"
            f"ID: {output_id}\n"
            f"Domain: {request.domain}\n"
            f"Tags: {', '.join(request.tags)}\n\n"
            f"## Reference Skills (learn style, create something NEW)\n"
            f"{ref_text}\n\n"
            f"## Today's Date\n{today}"
        )

        return GENERATE_SYSTEM_PROMPT, user_message

    def _parse_llm_output(self, response_text: str) -> dict | None:
        """LLM 응답에서 JSON을 파싱하고 필수 키를 검증한다.

        Args:
            response_text: LLM 응답 전문

        Returns:
            검증된 dict 또는 None
        """
        parsed = self._extract_json(response_text)
        if parsed is None:
            return None

        required = {"meta_yaml", "interface_yaml", "skill_md", "generation_rationale"}
        if not required.issubset(parsed.keys()):
            missing = required - set(parsed.keys())
            logger.warning("LLM 응답에 필수 키 누락: %s", missing)
            return None

        for key in required:
            if not isinstance(parsed[key], str):
                logger.warning("LLM 응답의 '%s' 키가 문자열이 아님", key)
                return None

        return parsed

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """텍스트에서 JSON 객체를 추출한다. 3단계 시도.

        Args:
            text: 파싱할 텍스트

        Returns:
            dict 또는 None
        """
        stripped = text.strip()

        # 1단계: 전체 텍스트 직접 파싱
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # 2단계: 코드 블록 추출
        match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL,
        )
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        # 3단계: 첫 { ~ 마지막 } 추출
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                parsed = json.loads(stripped[start:end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    # ═══════════════════════════════════════════════════════════════
    # Step 7: 파일 작성 + guardrail
    # ═══════════════════════════════════════════════════════════════

    def _write_and_guard(
        self,
        output_id: str,
        llm_output: dict,
        request: GenerateRequest,
    ) -> Path:
        """임시 디렉토리에 스킬 파일을 작성하고 guardrail을 적용한다.

        Args:
            output_id: 결과 스킬 ID
            llm_output: LLM 파싱 결과
            request: 생성 요청

        Returns:
            임시 디렉토리 Path
        """
        temp_dir = Path(tempfile.mkdtemp(prefix=f"cambrian_gen_{output_id}_"))

        # meta.yaml
        (temp_dir / "meta.yaml").write_text(
            llm_output["meta_yaml"], encoding="utf-8",
        )

        # interface.yaml
        (temp_dir / "interface.yaml").write_text(
            llm_output["interface_yaml"], encoding="utf-8",
        )

        # SKILL.md
        skill_md = llm_output["skill_md"]
        if len(skill_md) < 100:
            logger.warning("생성된 SKILL.md가 100자 미만 (%d자)", len(skill_md))
        if "## Output Format" not in skill_md:
            logger.warning("생성된 SKILL.md에 '## Output Format' 섹션이 없음")
        (temp_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        # guardrail 적용
        self._apply_meta_guardrails(temp_dir / "meta.yaml", output_id, request)

        # provenance 파일
        self._write_provenance(
            temp_dir, request, output_id, [],
            llm_output.get("generation_rationale", ""),
        )

        return temp_dir

    def _apply_meta_guardrails(
        self,
        meta_path: Path,
        output_id: str,
        request: GenerateRequest,
    ) -> None:
        """LLM이 생성한 meta.yaml을 강제 교정한다.

        Args:
            meta_path: meta.yaml 경로
            output_id: 결과 스킬 ID
            request: 생성 요청
        """
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("meta.yaml 파싱 실패, 기본값으로 생성: %s", exc)
            meta = {}

        if not isinstance(meta, dict):
            meta = {}

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        meta["id"] = output_id
        meta["version"] = "1.0.0"
        meta["mode"] = request.output_mode
        meta["author"] = "cambrian-generator"
        meta["created_at"] = today
        meta["updated_at"] = today

        # domain/tags는 request 값 우선
        if request.domain:
            meta["domain"] = request.domain
        meta.setdefault("domain", "general")

        if request.tags:
            meta["tags"] = request.tags
        meta.setdefault("tags", ["generated"])

        meta.setdefault("name", f"Generated: {request.goal[:50]}")
        meta.setdefault("description", request.goal[:200])

        # runtime 강제
        runtime = meta.get("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
        runtime["language"] = "python"
        runtime["needs_network"] = False
        runtime["needs_filesystem"] = False
        runtime.setdefault("timeout_seconds", 30)
        meta["runtime"] = runtime

        with open(meta_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)

    @staticmethod
    def _write_provenance(
        temp_dir: Path,
        request: GenerateRequest,
        output_id: str,
        references: list[Skill],
        rationale: str,
    ) -> None:
        """provenance 파일을 작성한다.

        Args:
            temp_dir: 스킬 디렉토리
            request: 생성 요청
            output_id: 결과 스킬 ID
            references: 참고 스킬 리스트
            rationale: 생성 근거
        """
        provenance = {
            "generated_by": "cambrian-generator",
            "goal": request.goal,
            "domain": request.domain,
            "tags": request.tags,
            "reference_skill_ids": [r.id for r in references],
            "generation_rationale": rationale,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        (temp_dir / "_cambrian_generate.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
