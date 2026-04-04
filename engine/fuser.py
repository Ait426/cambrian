"""Cambrian 스킬 융합 엔진."""

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
from engine.loader import SkillLoader
from engine.llm import LLMProvider, create_provider
from engine.models import FuseRequest, FuseResult, Skill
from engine.registry import SkillRegistry
from engine.security import SecurityScanner
from engine.validator import SkillValidator

logger = logging.getLogger(__name__)

# 출력 ID 정규식: 소문자 시작, 영소문자/숫자/언더스코어, 2~64자
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

FUSE_SYSTEM_PROMPT = """You are a Cambrian skill fusion specialist.
You combine two existing skills into ONE new skill with a specific unified purpose.

You receive:
- Skill A: metadata summary, input/output interface, SKILL.md instruction
- Skill B: same structure
- Fusion Goal: what the combined skill should accomplish

Your job:
1. Analyze both skills' interfaces and instructions
2. Design a NEW unified interface:
   - CHAIN pattern: If A's output naturally feeds B's input → fused input = A's input, fused output = B's output
   - MERGE pattern: If both skills handle independent aspects → fused input = union, fused output = union
   - SELECTIVE pattern: Use parts of each skill as the goal dictates
3. Write a complete new SKILL.md that:
   - Is SELF-CONTAINED (must NOT reference "Skill A" or "Skill B" by name)
   - Describes the unified purpose clearly
   - Includes a precise ## Output Format section with JSON specification
   - Handles edge cases
4. Create matching meta.yaml and interface.yaml

CRITICAL RULES:
- interface.yaml: every property MUST have both "type" and "description"
- interface.yaml: input and output sections MUST have "type: object", "properties", and "required"
- meta.yaml: mode MUST be "a"
- SKILL.md: MUST include ## Output Format with exact JSON structure
- Do NOT invent capabilities neither skill has
- Do NOT remove existing safeguards from either skill

Respond with ONLY a JSON object:
{
  "meta_yaml": "<full meta.yaml content as string>",
  "interface_yaml": "<full interface.yaml content as string>",
  "skill_md": "<full SKILL.md content as string>",
  "fusion_rationale": "<brief explanation of fusion pattern and design choices>"
}"""


class SkillFuser:
    """스킬 2개를 융합하여 새 스킬을 생성한다."""

    def __init__(
        self,
        loader: SkillLoader,
        validator: SkillValidator,
        scanner: SecurityScanner,
        registry: SkillRegistry,
        skill_pool_dir: str | Path,
        provider: LLMProvider | None = None,
    ) -> None:
        """초기화.

        Args:
            loader: SkillLoader 인스턴스
            validator: SkillValidator 인스턴스
            scanner: SecurityScanner 인스턴스
            registry: SkillRegistry 인스턴스
            skill_pool_dir: 스킬 풀 디렉토리 경로
            provider: LLM 프로바이더. None이면 호출 시 자동 생성.
        """
        self._loader = loader
        self._validator = validator
        self._scanner = scanner
        self._registry = registry
        self._pool_dir = Path(skill_pool_dir)
        self._provider = provider

    # ═══════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═══════════════════════════════════════════════════════════════

    def fuse(self, request: FuseRequest) -> FuseResult:
        """스킬 2개를 융합한다.

        Args:
            request: FuseRequest 융합 요청

        Returns:
            FuseResult 융합 결과
        """
        source_ids = [request.skill_id_a, request.skill_id_b]
        fail_result = lambda msg, **kw: FuseResult(
            success=False, skill_id="", skill_path="",
            source_ids=source_ids, goal=request.goal,
            fusion_rationale="", output_mode=request.output_mode,
            validation_passed=False, **kw,
        )

        # 1. 입력 검증
        if len(request.goal.strip()) < 5:
            raise ValueError("goal은 최소 5자 이상이어야 합니다")
        if request.skill_id_a == request.skill_id_b:
            return fail_result(
                "같은 스킬을 자기 자신과 융합할 수 없음",
                warnings=["같은 스킬을 자기 자신과 융합할 수 없음"],
            )
        if request.output_mode != "a":
            raise ValueError("v1에서는 output_mode='a'만 지원합니다")

        # 2. 소스 로드
        try:
            skill_a, skill_b = self._load_sources(request)
        except SkillNotFoundError as exc:
            return fail_result(
                str(exc), warnings=[str(exc)],
            )

        # 3. 호환성 검사
        compatible, reasons = self._check_compatibility(skill_a, skill_b)
        if not compatible:
            return fail_result("호환성 검사 실패", warnings=reasons)

        # 4. 출력 ID 결정
        output_id = self._resolve_output_id(request, skill_a, skill_b)

        # 5. LLM 호출
        temp_dir: Path | None = None
        try:
            llm_output = self._generate_fused_skill(
                skill_a, skill_b, request.goal, output_id,
            )
            if llm_output is None:
                return fail_result(
                    "LLM 응답 파싱 실패",
                    warnings=["LLM이 유효한 JSON을 반환하지 않음"],
                )

            # 6. 파일 작성
            temp_dir = self._write_skill_files(
                output_id, llm_output, skill_a, skill_b, request.goal,
            )

            # 7. meta.yaml guardrail
            self._apply_meta_guardrails(
                temp_dir / "meta.yaml", output_id,
                request.output_mode, skill_a, skill_b,
            )

            # 8. 검증 + 배치 + 등록
            deploy_result = self.validate_and_deploy(
                temp_dir, output_id, request.output_mode, request.dry_run,
            )

            return FuseResult(
                success=deploy_result["success"],
                skill_id=output_id,
                skill_path=deploy_result["skill_path"],
                source_ids=source_ids,
                goal=request.goal,
                fusion_rationale=llm_output.get("fusion_rationale", ""),
                output_mode=request.output_mode,
                validation_passed=deploy_result["validation_passed"],
                validation_errors=deploy_result["validation_errors"],
                security_passed=deploy_result["security_passed"],
                security_violations=deploy_result["security_violations"],
                registered=deploy_result["registered"],
                dry_run=request.dry_run,
                warnings=deploy_result["warnings"],
            )
        finally:
            # dry_run 시에는 temp_dir 유지
            if temp_dir is not None and temp_dir.exists() and not request.dry_run:
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ═══════════════════════════════════════════════════════════════
    # Step 1: 소스 로드
    # ═══════════════════════════════════════════════════════════════

    def _load_sources(self, request: FuseRequest) -> tuple[Skill, Skill]:
        """소스 스킬 2개를 로드한다.

        Args:
            request: 융합 요청

        Returns:
            (skill_a, skill_b) 튜플

        Raises:
            SkillNotFoundError: 스킬이 registry에 없을 때
        """
        data_a = self._registry.get(request.skill_id_a)
        skill_a = self._loader.load(data_a["skill_path"])

        data_b = self._registry.get(request.skill_id_b)
        skill_b = self._loader.load(data_b["skill_path"])

        return skill_a, skill_b

    # ═══════════════════════════════════════════════════════════════
    # Step 2: 호환성 검사
    # ═══════════════════════════════════════════════════════════════

    def _check_compatibility(
        self, skill_a: Skill, skill_b: Skill,
    ) -> tuple[bool, list[str]]:
        """두 스킬의 융합 호환성을 검사한다.

        Args:
            skill_a: 첫 번째 스킬
            skill_b: 두 번째 스킬

        Returns:
            (호환 여부, 거부 사유 리스트)
        """
        reasons: list[str] = []

        if skill_a.runtime.language != "python":
            reasons.append(
                f"Python 이외 언어 스킬은 v1에서 지원하지 않음: '{skill_a.id}' ({skill_a.runtime.language})"
            )
        if skill_b.runtime.language != "python":
            reasons.append(
                f"Python 이외 언어 스킬은 v1에서 지원하지 않음: '{skill_b.id}' ({skill_b.runtime.language})"
            )

        # registry에서 최신 상태 확인 (meta.yaml의 lifecycle과 다를 수 있음)
        for skill in [skill_a, skill_b]:
            try:
                data = self._registry.get(skill.id)
                if data["status"] == "fossil":
                    reasons.append(f"화석화된(fossil) 스킬 '{skill.id}'는 융합 대상으로 부적합")
            except SkillNotFoundError:
                pass

        if skill_a.skill_md_content is None:
            reasons.append(f"SKILL.md가 없는 스킬 '{skill_a.id}'는 융합할 수 없음")
        if skill_b.skill_md_content is None:
            reasons.append(f"SKILL.md가 없는 스킬 '{skill_b.id}'는 융합할 수 없음")

        return len(reasons) == 0, reasons

    # ═══════════════════════════════════════════════════════════════
    # Step 3: 출력 ID 결정
    # ═══════════════════════════════════════════════════════════════

    def _resolve_output_id(
        self, request: FuseRequest, skill_a: Skill, skill_b: Skill,
    ) -> str:
        """결과 스킬 ID를 결정한다.

        Args:
            request: 융합 요청
            skill_a: 첫 번째 스킬
            skill_b: 두 번째 스킬

        Returns:
            유효한 스킬 ID 문자열
        """
        if request.output_id is not None:
            candidate = request.output_id
            if not _ID_PATTERN.match(candidate):
                raise ValueError(
                    f"잘못된 output_id 형식: '{candidate}' "
                    "(소문자 시작, 영소문자/숫자/_, 2~64자)"
                )
        else:
            # 자동 생성: skill_a_id + "_" + skill_b_id (64자 제한)
            combined = f"{skill_a.id}_{skill_b.id}"
            if len(combined) > 64:
                half = 31
                combined = f"{skill_a.id[:half]}_{skill_b.id[:half]}"
            candidate = combined

        # 중복 검사
        final_id = candidate
        suffix = 2
        while True:
            try:
                self._registry.get(final_id)
                # 존재하면 접미사 추가
                final_id = f"{candidate}_{suffix}"
                suffix += 1
            except SkillNotFoundError:
                break

        return final_id

    # ═══════════════════════════════════════════════════════════════
    # Step 4: LLM 호출
    # ═══════════════════════════════════════════════════════════════

    def _generate_fused_skill(
        self,
        skill_a: Skill,
        skill_b: Skill,
        goal: str,
        output_id: str,
    ) -> dict | None:
        """LLM을 호출하여 융합 스킬 파일을 생성한다.

        Args:
            skill_a: 첫 번째 스킬
            skill_b: 두 번째 스킬
            goal: 융합 목적
            output_id: 결과 스킬 ID

        Returns:
            파싱된 LLM 출력 dict 또는 None (2회 실패 시)
        """
        provider = self._provider or create_provider()
        system_prompt, user_message = self._build_llm_context(
            skill_a, skill_b, goal, output_id,
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

        # 2차 시도 (에러 피드백 포함)
        logger.warning("LLM 응답 파싱 실패, 재시도합니다")
        retry_user = (
            f"{user_message}\n\n"
            "## IMPORTANT: Previous attempt failed\n"
            "Your previous response was not valid JSON. "
            "Respond with ONLY a JSON object with keys: "
            "meta_yaml, interface_yaml, skill_md, fusion_rationale. "
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
        skill_a: Skill,
        skill_b: Skill,
        goal: str,
        output_id: str,
    ) -> tuple[str, str]:
        """LLM 입력 컨텍스트를 구성한다.

        Args:
            skill_a: 첫 번째 스킬
            skill_b: 두 번째 스킬
            goal: 융합 목적
            output_id: 결과 스킬 ID

        Returns:
            (system_prompt, user_message) 튜플
        """
        interface_a = yaml.safe_dump(
            {"input": skill_a.interface_input, "output": skill_a.interface_output},
            allow_unicode=True, sort_keys=False,
        )
        interface_b = yaml.safe_dump(
            {"input": skill_b.interface_input, "output": skill_b.interface_output},
            allow_unicode=True, sort_keys=False,
        )

        skill_md_a = skill_a.skill_md_content or "(no SKILL.md)"
        skill_md_b = skill_b.skill_md_content or "(no SKILL.md)"

        # 토큰 폭주 방지
        max_md = 3000
        if len(skill_md_a) > max_md:
            skill_md_a = skill_md_a[:max_md] + "\n... (truncated)"
        if len(skill_md_b) > max_md:
            skill_md_b = skill_md_b[:max_md] + "\n... (truncated)"

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        user_message = (
            f"## Fusion Goal\n{goal}\n\n"
            f"## Output Skill ID\n{output_id}\n\n"
            f"## Skill A: {skill_a.id}\n"
            f"Name: {skill_a.name}\n"
            f"Description: {skill_a.description}\n"
            f"Domain: {skill_a.domain}\n"
            f"Tags: {', '.join(skill_a.tags)}\n"
            f"Mode: {skill_a.mode}\n\n"
            f"### Interface A\n{interface_a}\n"
            f"### SKILL.md A\n{skill_md_a}\n\n"
            f"## Skill B: {skill_b.id}\n"
            f"Name: {skill_b.name}\n"
            f"Description: {skill_b.description}\n"
            f"Domain: {skill_b.domain}\n"
            f"Tags: {', '.join(skill_b.tags)}\n"
            f"Mode: {skill_b.mode}\n\n"
            f"### Interface B\n{interface_b}\n"
            f"### SKILL.md B\n{skill_md_b}\n\n"
            f"## Today's Date\n{today}"
        )

        return FUSE_SYSTEM_PROMPT, user_message

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

        required_keys = {"meta_yaml", "interface_yaml", "skill_md", "fusion_rationale"}
        if not required_keys.issubset(parsed.keys()):
            missing = required_keys - set(parsed.keys())
            logger.warning("LLM 응답에 필수 키 누락: %s", missing)
            return None

        for key in required_keys:
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
        import re as _re
        match = _re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=_re.DOTALL,
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
    # Step 5: 파일 작성
    # ═══════════════════════════════════════════════════════════════

    def _write_skill_files(
        self,
        output_id: str,
        llm_output: dict,
        skill_a: Skill,
        skill_b: Skill,
        goal: str,
    ) -> Path:
        """임시 디렉토리에 스킬 파일을 작성한다.

        Args:
            output_id: 결과 스킬 ID
            llm_output: LLM 파싱 결과
            skill_a: 첫 번째 소스 스킬
            skill_b: 두 번째 소스 스킬
            goal: 융합 목적

        Returns:
            임시 디렉토리 Path
        """
        temp_dir = Path(tempfile.mkdtemp(prefix=f"cambrian_fuse_{output_id}_"))

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
        (temp_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        # provenance 파일
        provenance = {
            "parent_ids": [skill_a.id, skill_b.id],
            "fusion_goal": goal,
            "fusion_rationale": llm_output.get("fusion_rationale", ""),
            "fused_at": datetime.now(timezone.utc).isoformat(),
        }
        (temp_dir / "_cambrian_fuse.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return temp_dir

    # ═══════════════════════════════════════════════════════════════
    # Step 6: meta.yaml guardrail
    # ═══════════════════════════════════════════════════════════════

    def _apply_meta_guardrails(
        self,
        meta_path: Path,
        output_id: str,
        output_mode: str,
        skill_a: Skill,
        skill_b: Skill,
    ) -> None:
        """LLM이 생성한 meta.yaml을 강제 교정한다.

        Args:
            meta_path: meta.yaml 경로
            output_id: 결과 스킬 ID
            output_mode: 결과 모드
            skill_a: 첫 번째 소스 스킬
            skill_b: 두 번째 소스 스킬
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

        # 핵심 필드 강제 교정
        meta["id"] = output_id
        meta["version"] = "1.0.0"
        meta["mode"] = output_mode
        meta["author"] = "cambrian-fuser"
        meta["created_at"] = today
        meta["updated_at"] = today

        # name/description 기본값
        meta.setdefault("name", f"Fused: {skill_a.name} + {skill_b.name}")
        meta.setdefault("description", f"Fusion of {skill_a.id} and {skill_b.id}")
        meta.setdefault("domain", skill_a.domain)
        meta.setdefault("tags", list(set(skill_a.tags + skill_b.tags)))

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

    # ═══════════════════════════════════════════════════════════════
    # Step 7: 검증 + 배치 + 등록 (public — generate에서도 재사용)
    # ═══════════════════════════════════════════════════════════════

    def validate_and_deploy(
        self,
        temp_dir: Path,
        output_id: str,
        output_mode: str,
        dry_run: bool,
    ) -> dict:
        """검증 → 배치 → 등록 파이프라인. generator에서도 재사용.

        Args:
            temp_dir: 스킬 파일이 있는 임시 디렉토리
            output_id: 결과 스킬 ID
            output_mode: 결과 모드
            dry_run: True면 등록 안 함

        Returns:
            결과 dict: success, validation_passed, validation_errors,
            security_passed, security_violations, registered, skill_path, warnings
        """
        result: dict = {
            "success": False,
            "validation_passed": False,
            "validation_errors": [],
            "security_passed": True,
            "security_violations": [],
            "registered": False,
            "skill_path": str(temp_dir),
            "warnings": [],
        }

        # 1. validator 검증
        validation = self._validator.validate(temp_dir)
        if not validation.valid:
            # loader와 동일한 필터링 — lifecycle 필수 필드 누락은 무시
            filtered = [
                e for e in validation.errors
                if e != "[meta.yaml] 필수 필드 누락: 'lifecycle'"
            ]
            if filtered:
                result["validation_errors"] = filtered
                return result

        result["validation_passed"] = True

        # 2. security 검사 (Mode B만)
        if output_mode == "b":
            violations = self._scanner.scan_skill(temp_dir, needs_network=False)
            if violations:
                result["security_passed"] = False
                result["security_violations"] = violations
                return result

        # 3. dry_run 체크
        if dry_run:
            result["success"] = True
            result["skill_path"] = str(temp_dir)
            return result

        # 4. skill_pool 배치
        dest = self._pool_dir / output_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(temp_dir, dest)
        result["skill_path"] = str(dest)

        # 5. 로드 확인
        try:
            skill = self._loader.load(dest)
        except Exception as exc:
            logger.error("생성된 스킬 로드 실패: %s", exc)
            shutil.rmtree(dest, ignore_errors=True)
            result["warnings"].append(f"로드 실패: {exc}")
            return result

        # 6. registry 등록
        try:
            self._registry.register(skill)
            result["registered"] = True
        except Exception as exc:
            logger.error("registry 등록 실패: %s", exc)
            result["warnings"].append(f"등록 실패: {exc}")
            return result

        result["success"] = True
        return result
