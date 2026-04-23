"""Cambrian brain generation feedback / next seed 모듈."""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml


SCHEMA_VERSION = "1.0.0"


def _now_iso() -> str:
    """현재 시각을 ISO 8601 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _make_id(prefix: str) -> str:
    """짧은 랜덤 ID를 만든다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{secrets.token_hex(2)}"


def _unique_strings(values: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_list(value: object) -> list[str]:
    """문자열 또는 리스트 입력을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, str):
        return _unique_strings([value])
    if isinstance(value, list):
        return _unique_strings([str(item) for item in value])
    return _unique_strings([str(value)])


def _path_ref(path: Path, project_root: Path) -> str:
    """project_root 하위 경로는 상대경로로 저장한다."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(project_root.resolve()))
    except ValueError:
        return str(resolved)


def _sanitize_name(value: str) -> str:
    """파일명에 안전한 짧은 이름으로 바꾼다."""
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return text or "generation"


def _resolve_source_path(
    raw_path: str | None,
    source_path: Path,
    project_root: Path,
) -> Path | None:
    """source가 가리키는 보조 artifact 경로를 해석한다."""
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate

    project_candidate = (project_root / candidate).resolve()
    if project_candidate.exists():
        return project_candidate

    source_parent_candidate = (source_path.parent / candidate).resolve()
    if source_parent_candidate.exists():
        return source_parent_candidate

    return project_candidate


def _load_json_file(path: Path) -> dict:
    """JSON object 파일을 읽는다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _load_yaml_file(path: Path) -> dict:
    """YAML object 파일을 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML object expected: {path}")
    return payload


@dataclass
class GenerationFeedbackRecord:
    """세대 결과 분석과 다음 세대 seed 생성용 기록."""

    schema_version: str
    feedback_id: str
    created_at: str
    source_type: str
    source_ref: str
    brain_run_id: str | None
    adoption_id: str | None
    winner_variant_id: str | None
    outcome: str
    outcome_reasons: list[str] = field(default_factory=list)
    hypothesis_status: str | None = None
    competitive_status: str | None = None
    adoption_status: str | None = None
    post_apply_test_status: str | None = None
    keep_patterns: list[str] = field(default_factory=list)
    avoid_patterns: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    suggested_next_actions: list[str] = field(default_factory=list)
    human_feedback: dict = field(default_factory=dict)
    source_artifacts: dict = field(default_factory=dict)
    next_generation_seed_path: str | None = None

    def to_dict(self) -> dict:
        """JSON 저장용 dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationFeedbackRecord":
        """dict에서 기록을 복원한다."""
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            feedback_id=str(data.get("feedback_id", "")),
            created_at=str(data.get("created_at", "")),
            source_type=str(data.get("source_type", "brain_report")),
            source_ref=str(data.get("source_ref", "")),
            brain_run_id=data.get("brain_run_id"),
            adoption_id=data.get("adoption_id"),
            winner_variant_id=data.get("winner_variant_id"),
            outcome=str(data.get("outcome", "inconclusive")),
            outcome_reasons=_normalize_list(data.get("outcome_reasons")),
            hypothesis_status=data.get("hypothesis_status"),
            competitive_status=data.get("competitive_status"),
            adoption_status=data.get("adoption_status"),
            post_apply_test_status=data.get("post_apply_test_status"),
            keep_patterns=_normalize_list(data.get("keep_patterns")),
            avoid_patterns=_normalize_list(data.get("avoid_patterns")),
            missing_evidence=_normalize_list(data.get("missing_evidence")),
            suggested_next_actions=_normalize_list(
                data.get("suggested_next_actions")
            ),
            human_feedback=dict(data.get("human_feedback") or {}),
            source_artifacts=dict(data.get("source_artifacts") or {}),
            next_generation_seed_path=data.get("next_generation_seed_path"),
        )


class GenerationAutopsy:
    """brain report / adoption record를 다음 세대 입력으로 분석한다."""

    def analyze(
        self,
        source_path: Path,
        project_root: Path,
        human_feedback: dict | None = None,
    ) -> GenerationFeedbackRecord:
        """source artifact를 분석해 feedback record를 만든다."""
        source = Path(source_path)
        root = Path(project_root).resolve()
        feedback = self._base_record(source, root, human_feedback)

        if not source.exists():
            feedback.outcome = "inconclusive"
            feedback.outcome_reasons = [f"source artifact not found: {source}"]
            feedback.missing_evidence = ["source artifact is missing"]
            feedback.suggested_next_actions = [
                "Provide a valid brain report or adoption record",
            ]
            return feedback

        try:
            payload = _load_json_file(source)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            feedback.outcome = "inconclusive"
            feedback.outcome_reasons = [f"source artifact parse failed: {exc}"]
            feedback.missing_evidence = ["source artifact could not be parsed"]
            feedback.suggested_next_actions = [
                "Repair or replace the malformed source artifact",
            ]
            return feedback

        source_type = self._detect_source_type(payload)
        feedback.source_type = source_type

        hypothesis = payload.get("hypothesis_evaluation")
        if not isinstance(hypothesis, dict):
            hypothesis = {}
        competitive = payload.get("competitive_generation")
        if not isinstance(competitive, dict):
            competitive = {}
        remaining_risks = _normalize_list(payload.get("remaining_risks"))
        next_actions = _normalize_list(payload.get("next_actions"))
        winner_variant_id = (
            payload.get("winner_variant_id")
            or competitive.get("winner_variant_id")
        )
        brain_run_id = payload.get("brain_run_id") or payload.get("run_id")
        adoption_id = payload.get("adoption_id")
        adoption_status = payload.get("adoption_status")
        post_apply_tests = payload.get("post_apply_tests")
        if not isinstance(post_apply_tests, dict):
            post_apply_tests = {}

        task_spec_context = self._load_task_spec_context(
            source_type=source_type,
            payload=payload,
            source_path=source,
            project_root=root,
        )

        feedback.brain_run_id = (
            str(brain_run_id) if brain_run_id is not None else None
        )
        feedback.adoption_id = (
            str(adoption_id) if adoption_id is not None else None
        )
        feedback.winner_variant_id = (
            str(winner_variant_id) if winner_variant_id is not None else None
        )
        feedback.hypothesis_status = (
            str(hypothesis.get("status")) if hypothesis.get("status") else None
        )
        feedback.competitive_status = (
            str(competitive.get("status"))
            if competitive.get("status") is not None
            else None
        )
        feedback.adoption_status = (
            str(adoption_status) if adoption_status is not None else None
        )
        feedback.post_apply_test_status = self._classify_post_apply_tests(
            post_apply_tests
        )
        feedback.source_artifacts = self._build_source_artifacts(
            source_type=source_type,
            source_path=source,
            project_root=root,
            payload=payload,
            task_spec_context=task_spec_context,
        )

        outcome, reasons = self._classify_outcome(
            source_type=source_type,
            payload=payload,
            hypothesis=hypothesis,
            competitive=competitive,
            remaining_risks=remaining_risks,
            post_apply_tests=post_apply_tests,
            winner_variant_id=feedback.winner_variant_id,
        )
        feedback.outcome = outcome
        feedback.outcome_reasons = reasons

        feedback.keep_patterns = self._build_keep_patterns(
            payload=payload,
            hypothesis=hypothesis,
            competitive=competitive,
            outcome=outcome,
            winner_variant_id=feedback.winner_variant_id,
        )
        feedback.avoid_patterns = self._build_avoid_patterns(
            payload=payload,
            hypothesis=hypothesis,
            competitive=competitive,
            outcome=outcome,
        )
        feedback.missing_evidence = self._build_missing_evidence(
            source_type=source_type,
            payload=payload,
            hypothesis=hypothesis,
            competitive=competitive,
            post_apply_tests=post_apply_tests,
        )
        feedback.suggested_next_actions = self._build_next_actions(
            outcome=outcome,
            existing_actions=next_actions,
            missing_evidence=feedback.missing_evidence,
            hypothesis=hypothesis,
            competitive=competitive,
        )
        return feedback

    def _base_record(
        self,
        source_path: Path,
        project_root: Path,
        human_feedback: dict | None,
    ) -> GenerationFeedbackRecord:
        """분석 기본값을 만든다."""
        normalized_human = self._normalize_human_feedback(human_feedback)
        return GenerationFeedbackRecord(
            schema_version=SCHEMA_VERSION,
            feedback_id=_make_id("feedback"),
            created_at=_now_iso(),
            source_type="brain_report",
            source_ref=_path_ref(source_path, project_root),
            brain_run_id=None,
            adoption_id=None,
            winner_variant_id=None,
            outcome="inconclusive",
            human_feedback=normalized_human,
        )

    @staticmethod
    def _normalize_human_feedback(human_feedback: dict | None) -> dict:
        """사람 입력을 구조화한다."""
        data = dict(human_feedback or {})
        note = str(data.get("note", "")).strip()
        rating = data.get("rating")
        keep = _normalize_list(data.get("keep"))
        avoid = _normalize_list(data.get("avoid"))

        normalized: dict[str, object] = {}
        if note:
            normalized["note"] = note
        if rating is not None and str(rating).strip():
            normalized["rating"] = str(rating).strip()
        if keep:
            normalized["keep"] = keep
        if avoid:
            normalized["avoid"] = avoid
        return normalized

    @staticmethod
    def _detect_source_type(payload: dict) -> str:
        """source artifact 타입을 감지한다."""
        adoption_status = str(payload.get("adoption_status", "") or "")
        action_type = str(payload.get("action_type", "") or "")
        if action_type == "rollback" or adoption_status == "rollback":
            return "rollback_record"
        if payload.get("adoption_type") or payload.get("adoption_id"):
            if adoption_status == "failed":
                return "failed_adoption"
            return "adoption_record"
        return "brain_report"

    def _load_task_spec_context(
        self,
        source_type: str,
        payload: dict,
        source_path: Path,
        project_root: Path,
    ) -> dict:
        """source가 참조하는 task spec을 읽는다."""
        if source_type == "brain_report":
            provenance = payload.get("provenance_handoff")
            if not isinstance(provenance, dict):
                provenance = {}
            raw_path = provenance.get("task_spec_path")
        else:
            raw_path = payload.get("source_task_spec_path")

        resolved = _resolve_source_path(raw_path, source_path, project_root)
        if resolved is None:
            return {}
        try:
            task_spec = _load_yaml_file(resolved)
        except (OSError, yaml.YAMLError, ValueError):
            return {
                "task_spec_path": _path_ref(resolved, project_root),
                "task_spec_load_failed": True,
            }

        return {
            "task_spec_path": _path_ref(resolved, project_root),
            "goal": task_spec.get("goal"),
            "task_id": task_spec.get("task_id"),
            "related_tests": _normalize_list(task_spec.get("related_tests")),
            "hypothesis": (
                dict(task_spec.get("hypothesis"))
                if isinstance(task_spec.get("hypothesis"), dict)
                else None
            ),
        }

    def _build_source_artifacts(
        self,
        source_type: str,
        source_path: Path,
        project_root: Path,
        payload: dict,
        task_spec_context: dict,
    ) -> dict:
        """seed builder가 다시 사용할 source 메타데이터를 모은다."""
        source_artifacts: dict[str, object] = {
            "source_path": _path_ref(source_path, project_root),
            "task_id": payload.get("task_id") or task_spec_context.get("task_id"),
            "goal": payload.get("goal") or task_spec_context.get("goal"),
            "task_spec_path": task_spec_context.get("task_spec_path"),
            "task_spec_hypothesis": task_spec_context.get("hypothesis"),
            "related_tests": task_spec_context.get("related_tests") or [],
        }
        if source_type == "brain_report":
            provenance = payload.get("provenance_handoff")
            if not isinstance(provenance, dict):
                provenance = {}
            source_artifacts["tests_executed"] = _normalize_list(
                provenance.get("tests_executed")
            )
            source_artifacts["files_created"] = _normalize_list(
                provenance.get("files_created")
            )
            source_artifacts["files_modified"] = _normalize_list(
                provenance.get("files_modified")
            )
        else:
            source_artifacts["human_reason"] = payload.get("human_reason")
            source_artifacts["applied_files"] = [
                dict(item)
                for item in (payload.get("applied_files") or [])
                if isinstance(item, dict)
            ]
            source_artifacts["post_apply_tests"] = dict(
                payload.get("post_apply_tests") or {}
            )
        return source_artifacts

    def _classify_outcome(
        self,
        source_type: str,
        payload: dict,
        hypothesis: dict,
        competitive: dict,
        remaining_risks: list[str],
        post_apply_tests: dict,
        winner_variant_id: str | None,
    ) -> tuple[str, list[str]]:
        """source 결과를 outcome으로 분류한다."""
        reasons: list[str] = []
        hypothesis_status = str(hypothesis.get("status", "") or "")
        competitive_status = str(competitive.get("status", "") or "")
        report_status = str(payload.get("status", "") or "")
        adoption_status = str(payload.get("adoption_status", "") or "")
        post_apply_failed = int(post_apply_tests.get("failed", 0) or 0)

        if source_type == "rollback_record":
            return "rollback", ["rollback record provided"]

        if source_type in ("adoption_record", "failed_adoption"):
            if adoption_status == "blocked":
                return "blocked", ["adoption was blocked"]
            if adoption_status == "rollback":
                return "rollback", ["adoption was rolled back"]
            if post_apply_failed > 0:
                return "failure", ["post-apply tests failed"]
            if hypothesis_status == "contradicted":
                return "failure", ["hypothesis contradicted"]
            if competitive_status == "failure":
                return "failure", ["competitive generation failed"]
            if adoption_status == "adopted":
                reasons.append("adoption record marked adopted")
                if winner_variant_id:
                    reasons.append(f"winner variant adopted: {winner_variant_id}")
                if remaining_risks:
                    reasons.append("remaining risks present after adoption")
                    return "mixed", reasons
                return "success", reasons
            if adoption_status == "failed":
                return "failure", ["adoption record marked failed"]
            return "inconclusive", ["adoption record lacks decisive status"]

        if competitive_status == "no_winner" and not winner_variant_id:
            return "no_winner", ["competitive generation produced no winner"]
        if report_status == "failed":
            return "failure", ["brain run status is failed"]
        if hypothesis_status == "contradicted":
            return "failure", ["hypothesis contradicted"]
        if competitive_status == "failure":
            return "failure", ["competitive generation failed"]
        if report_status == "blocked":
            return "blocked", ["brain run status is blocked"]
        if report_status == "completed":
            if competitive_status == "success" and winner_variant_id:
                reasons.append("brain run completed with competitive winner")
                if hypothesis_status == "inconclusive":
                    reasons.append("hypothesis evidence was inconclusive")
                    return "mixed", reasons
                if remaining_risks:
                    reasons.append("remaining risks recorded in report")
                    return "mixed", reasons
                return "success", reasons
            if hypothesis_status == "inconclusive":
                return "mixed", ["brain run completed but hypothesis was inconclusive"]
            if remaining_risks:
                return "mixed", ["brain run completed with remaining risks"]
            return "success", ["brain run completed"]
        return "inconclusive", ["insufficient evidence to classify outcome"]

    def _build_keep_patterns(
        self,
        payload: dict,
        hypothesis: dict,
        competitive: dict,
        outcome: str,
        winner_variant_id: str | None,
    ) -> list[str]:
        """유지할 패턴을 만든다."""
        keep: list[str] = []
        hypothesis_id = str(hypothesis.get("hypothesis_id") or "")
        hypothesis_statement = str(hypothesis.get("statement") or "")
        selection_reason = str(competitive.get("selection_reason") or "")

        if outcome in ("success", "mixed"):
            if winner_variant_id:
                keep.append(f"Keep winner variant pattern: {winner_variant_id}")
            if hypothesis.get("status") == "supported":
                if hypothesis_id:
                    keep.append(f"Keep supported hypothesis: {hypothesis_id}")
                elif hypothesis_statement:
                    keep.append(
                        f"Keep supported hypothesis statement: {hypothesis_statement}"
                    )
            if selection_reason:
                keep.append(f"Keep selection reason: {selection_reason}")

            for file_path in _normalize_list(
                payload.get("provenance_handoff", {}).get("files_created")
                if isinstance(payload.get("provenance_handoff"), dict)
                else []
            ):
                keep.append(f"Keep successfully created file: {file_path}")
            for item in payload.get("applied_files", []) or []:
                if isinstance(item, dict) and item.get("target_path"):
                    keep.append(
                        f"Keep successfully applied file: {item['target_path']}"
                    )
            human_reason = str(payload.get("human_reason") or "").strip()
            if human_reason:
                keep.append(f"Keep human adoption reason: {human_reason}")

        return _unique_strings(keep)

    def _build_avoid_patterns(
        self,
        payload: dict,
        hypothesis: dict,
        competitive: dict,
        outcome: str,
    ) -> list[str]:
        """피해야 할 패턴을 만든다."""
        avoid: list[str] = []
        hypothesis_id = str(hypothesis.get("hypothesis_id") or "")

        if hypothesis.get("status") == "contradicted":
            if hypothesis_id:
                avoid.append(f"Avoid contradicted hypothesis: {hypothesis_id}")
            else:
                avoid.append("Avoid contradicted hypothesis pattern")

        variants = competitive.get("variants")
        if not isinstance(variants, list):
            variants = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            variant_id = str(variant.get("variant_id") or "")
            variant_status = str(variant.get("status") or "")
            hypothesis_status = str(variant.get("hypothesis_status") or "")
            failed = int((variant.get("test_results") or {}).get("failed", 0) or 0)
            if not variant_id:
                continue
            if outcome in ("failure", "no_winner", "blocked", "rollback"):
                if variant_status in ("failure", "error"):
                    avoid.append(f"Avoid previously failed variant: {variant_id}")
                if hypothesis_status == "contradicted":
                    avoid.append(
                        f"Avoid contradicted variant hypothesis: {variant_id}"
                    )
                if failed > 0:
                    avoid.append(f"Avoid failing test variant: {variant_id}")

        if outcome == "no_winner":
            run_id = payload.get("run_id") or payload.get("brain_run_id")
            if run_id:
                avoid.append(
                    f"Avoid no_winner generation pattern from {run_id}"
                )

        if outcome == "failure" and payload.get("post_apply_tests"):
            avoid.append("Avoid post-apply failure pattern")

        return _unique_strings(avoid)

    def _build_missing_evidence(
        self,
        source_type: str,
        payload: dict,
        hypothesis: dict,
        competitive: dict,
        post_apply_tests: dict,
    ) -> list[str]:
        """부족한 증거 목록을 만든다."""
        missing: list[str] = []
        if source_type == "brain_report":
            if "status" not in payload:
                missing.append("report status is missing")
            if "competitive_generation" not in payload:
                missing.append("competitive_generation section missing")
        else:
            if not payload.get("adoption_status"):
                missing.append("adoption_status missing")
            if not post_apply_tests:
                missing.append("post_apply_tests missing")

        if not hypothesis:
            missing.append("hypothesis_evaluation section missing")
        for check in hypothesis.get("checks", []) or []:
            if not isinstance(check, dict):
                continue
            if check.get("status") == "inconclusive":
                reason = str(check.get("reason") or "").strip()
                if reason:
                    missing.append(reason)

        if not competitive:
            missing.append("competitive_generation section missing")

        for action in _normalize_list(payload.get("next_actions")):
            if "evidence" in action.lower():
                missing.append(action)

        remaining_risks = _normalize_list(payload.get("remaining_risks"))
        for risk in remaining_risks:
            if "evidence" in risk.lower():
                missing.append(risk)

        return _unique_strings(missing)

    def _build_next_actions(
        self,
        outcome: str,
        existing_actions: list[str],
        missing_evidence: list[str],
        hypothesis: dict,
        competitive: dict,
    ) -> list[str]:
        """다음 세대 액션을 만든다."""
        actions = list(existing_actions)

        if outcome == "failure":
            actions.extend([
                "Revise hypothesis or actions before next generation",
                "Inspect failed hypothesis checks before rerun",
            ])
        elif outcome == "no_winner":
            actions.extend([
                "Revise hypothesis before next generation",
                "Generate alternative variant actions for next generation",
                "Reduce scope and inspect failed checks",
            ])
        elif outcome == "blocked":
            actions.append("Resolve blocked conditions before next generation")
        elif outcome == "rollback":
            actions.append("Review rollback cause before next generation")
        elif outcome == "mixed":
            actions.append("Tighten evidence collection before next generation")
        elif outcome == "inconclusive":
            actions.append("Collect missing evidence before next generation")
        else:
            actions.append("Use successful winner as baseline for next generation")

        if hypothesis.get("status") == "contradicted":
            actions.append("Use contradicted hypothesis checks as input for revision")

        if competitive.get("status") == "no_winner":
            actions.append("Inspect failed variants and revise hypothesis or actions")

        for evidence in missing_evidence:
            actions.append(f"Collect missing evidence: {evidence}")

        return _unique_strings(actions)

    @staticmethod
    def _classify_post_apply_tests(post_apply_tests: dict) -> str | None:
        """post-apply tests 상태를 요약한다."""
        if not post_apply_tests:
            return None
        failed = int(post_apply_tests.get("failed", 0) or 0)
        exit_code = int(post_apply_tests.get("exit_code", -1) or -1)
        if failed == 0 and exit_code in (0, 5):
            return "passed"
        return "failed"


class GenerationFeedbackStore:
    """feedback record 저장소."""

    @staticmethod
    def default_path(
        feedback: GenerationFeedbackRecord,
        out_dir: Path,
    ) -> Path:
        """기본 feedback 기록 경로."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        source_short = _sanitize_name(
            feedback.brain_run_id
            or feedback.adoption_id
            or Path(feedback.source_ref).stem
        )
        return Path(out_dir) / f"feedback_{timestamp}_{source_short}.json"

    def save(
        self,
        feedback: GenerationFeedbackRecord,
        out_path: Path,
    ) -> Path:
        """feedback record를 JSON으로 저장한다."""
        self._atomic_write_json(Path(out_path), feedback.to_dict())
        return Path(out_path)

    @staticmethod
    def load(path: Path) -> GenerationFeedbackRecord:
        """JSON 파일에서 feedback record를 읽는다."""
        return GenerationFeedbackRecord.from_dict(_load_json_file(Path(path)))

    @staticmethod
    def _atomic_write_json(target_path: Path, payload: dict) -> None:
        """JSON 파일을 원자적으로 쓴다."""
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        GenerationFeedbackStore._atomic_write_bytes(target_path, data)

    @staticmethod
    def _atomic_write_bytes(target_path: Path, data: bytes) -> None:
        """bytes 파일을 원자적으로 쓴다."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=str(target_path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(data)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, target_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


class NextGenerationSeedBuilder:
    """feedback record를 partial seed YAML로 변환한다."""

    @staticmethod
    def default_path(
        feedback: GenerationFeedbackRecord,
        out_dir: Path,
    ) -> Path:
        """기본 seed 경로."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        source_short = _sanitize_name(
            feedback.brain_run_id
            or feedback.adoption_id
            or Path(feedback.source_ref).stem
        )
        return Path(out_dir) / f"next_generation_{timestamp}_{source_short}.yaml"

    def build(
        self,
        feedback: GenerationFeedbackRecord,
        feedback_path: Path | str | None = None,
        out_path: Path | None = None,
    ) -> Path:
        """feedback record를 seed YAML로 저장한다."""
        target = Path(out_path) if out_path is not None else self.default_path(
            feedback,
            Path.cwd() / ".cambrian" / "next_generation",
        )
        seed_payload = self._build_payload(feedback, feedback_path)
        self._atomic_write_yaml(target, seed_payload)
        return target

    def _build_payload(
        self,
        feedback: GenerationFeedbackRecord,
        feedback_path: Path | str | None,
    ) -> dict:
        """seed payload를 구성한다."""
        source_artifacts = feedback.source_artifacts or {}
        human_feedback = feedback.human_feedback or {}
        keep = _unique_strings(
            list(feedback.keep_patterns) + _normalize_list(human_feedback.get("keep"))
        )
        avoid = _unique_strings(
            list(feedback.avoid_patterns) + _normalize_list(human_feedback.get("avoid"))
        )
        suggested = list(feedback.suggested_next_actions)
        note = str(human_feedback.get("note", "") or "").strip()
        if note:
            suggested.append(f"Review human feedback note: {note}")

        hypothesis_seed = self._build_hypothesis_seed(feedback)
        competitive_seed = self._build_competitive_seed(feedback)

        return {
            "source_feedback_ref": (
                str(feedback_path) if feedback_path is not None else feedback.source_ref
            ),
            "source_brain_run_id": feedback.brain_run_id,
            "source_adoption_id": feedback.adoption_id,
            "generation_intent": self._infer_generation_intent(feedback.outcome),
            "goal": (
                source_artifacts.get("goal")
                or "Next generation based on feedback from previous run"
            ),
            "previous_outcome": {
                "outcome": feedback.outcome,
                "reasons": list(feedback.outcome_reasons),
            },
            "lessons": {
                "keep": keep,
                "avoid": avoid,
                "missing_evidence": list(feedback.missing_evidence),
            },
            "suggested_next_actions": _unique_strings(suggested),
            "hypothesis_seed": hypothesis_seed,
            "competitive_seed": competitive_seed,
        }

    def _build_hypothesis_seed(self, feedback: GenerationFeedbackRecord) -> dict:
        """다음 세대용 hypothesis seed를 만든다."""
        source_artifacts = feedback.source_artifacts or {}
        task_hypothesis = source_artifacts.get("task_spec_hypothesis")
        if isinstance(task_hypothesis, dict) and task_hypothesis:
            seed = dict(task_hypothesis)
        else:
            seed = {
                "statement": "A revised variant should pass related tests with zero failures.",
                "predicts": {
                    "tests": {
                        "passed_min": 1,
                        "failed_max": 0,
                    },
                },
            }

        predicts = seed.get("predicts")
        if not isinstance(predicts, dict):
            predicts = {}
            seed["predicts"] = predicts

        tests_predict = predicts.get("tests")
        if not isinstance(tests_predict, dict):
            tests_predict = {}
            predicts["tests"] = tests_predict

        related_tests = _normalize_list(source_artifacts.get("related_tests"))
        if related_tests:
            tests_predict.setdefault("passed_min", 1)
            tests_predict.setdefault("failed_max", 0)

        return seed

    def _build_competitive_seed(
        self,
        feedback: GenerationFeedbackRecord,
    ) -> dict:
        """다음 세대 competitive seed를 만든다."""
        avoid_variant_ids: list[str] = []
        recommended_variant_count = 2
        if feedback.outcome in ("no_winner", "failure", "blocked", "rollback"):
            recommended_variant_count = 3
        elif feedback.outcome == "inconclusive":
            recommended_variant_count = 2

        for text in feedback.avoid_patterns:
            if text.startswith("Avoid previously failed variant: "):
                avoid_variant_ids.append(text.split(": ", 1)[1])
            if text.startswith("Avoid contradicted variant hypothesis: "):
                avoid_variant_ids.append(text.split(": ", 1)[1])

        return {
            "recommended_variant_count": recommended_variant_count,
            "avoid_variant_ids": _unique_strings(avoid_variant_ids),
        }

    @staticmethod
    def _infer_generation_intent(outcome: str) -> str:
        """outcome에 맞는 다음 세대 의도를 만든다."""
        if outcome == "success":
            return "extend_success"
        if outcome == "rollback":
            return "recover_after_rollback"
        return "revise_and_retry"

    @staticmethod
    def _atomic_write_yaml(target_path: Path, payload: dict) -> None:
        """YAML 파일을 원자적으로 쓴다."""
        data = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8")
        GenerationFeedbackStore._atomic_write_bytes(target_path, data)
