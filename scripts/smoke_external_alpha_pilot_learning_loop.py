"""Rehearse the external alpha pilot learning loop without real pilot evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_pilot_decision import verify_pilot_decision_file  # noqa: E402
from scripts.check_external_alpha_pilot_evidence import verify_pilot_evidence_file  # noqa: E402
from scripts.check_external_alpha_pilot_iteration import (  # noqa: E402
    check_pilot_iteration,
    verify_pilot_iteration_file,
)
from scripts.check_external_alpha_recipient_checkpoint import (  # noqa: E402
    BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES,
    BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION,
)


PILOT_LEARNING_REHEARSAL_SCHEMA_VERSION = "external_alpha_pilot_learning_loop_rehearsal_v0_1"
PILOT_LEARNING_REHEARSAL_RECEIPT_NAME = f"{RELEASE_SLUG}-pilot-learning-rehearsal-receipt.json"
BUILDER_GOLD_PATH_RECEIPT_NAME = "external_alpha_builder_gold_path_share_receipt.json"

PRIVATE_MARKERS = (
    "PILOT_LEARNING_REHEARSAL_PRIVATE_RECIPIENT",
    "PILOT_LEARNING_REHEARSAL_PRIVATE_OPERATOR_DISPATCH_NOTE",
    "PILOT_LEARNING_REHEARSAL_PRIVATE_ACK",
    "PILOT_LEARNING_REHEARSAL_PRIVATE_FEEDBACK",
    "PILOT_LEARNING_REHEARSAL_PRIVATE_ISSUE",
    "PILOT_LEARNING_REHEARSAL_PRIVATE_DECISION_NOTE",
)
PILOT_LEARNING_PRIVATE_WORKSPACE_FILES = (
    "recipient-private.txt",
    "operator-dispatch-note-private.md",
    "recipient-ack-private.txt",
    "pilot-feedback-private.md",
    "pilot-issue-intake-private.md",
    "operator-decision-note-private.md",
)

logger = logging.getLogger(__name__)


class PilotLearningLoopRehearsalError(RuntimeError):
    """Pilot learning loop rehearsal generation or verification failed."""


def smoke_pilot_learning_loop(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Run a controlled-tag learning-loop rehearsal and write a share-safe receipt."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    use_existing_release_artifacts = _has_existing_release_artifacts(output_dir)

    with tempfile.TemporaryDirectory(prefix="cambrian-external-alpha-learning-") as temp_name:
        temp_root = Path(temp_name).resolve()
        work_dir = temp_root / "release"
        private_dir = temp_root / "private"
        work_dir.mkdir()
        private_dir.mkdir()
        if use_existing_release_artifacts:
            _copy_output_files(output_dir, work_dir)

        _write_private_file(
            private_dir / "recipient-private.txt",
            "PILOT_LEARNING_REHEARSAL_PRIVATE_RECIPIENT recipient@example.invalid\n",
        )
        _write_private_file(
            private_dir / "operator-dispatch-note-private.md",
            "PILOT_LEARNING_REHEARSAL_PRIVATE_OPERATOR_DISPATCH_NOTE\nsent by private channel\n",
        )
        _write_private_file(
            private_dir / "recipient-ack-private.txt",
            "PILOT_LEARNING_REHEARSAL_PRIVATE_ACK\n확인 완료\n",
        )
        _write_private_file(
            private_dir / "pilot-feedback-private.md",
            "PILOT_LEARNING_REHEARSAL_PRIVATE_FEEDBACK\nrecipient got stuck on terminology\n",
        )
        _write_private_file(
            private_dir / "pilot-issue-intake-private.md",
            "PILOT_LEARNING_REHEARSAL_PRIVATE_ISSUE\nbuilder explanation needs a patch\n",
        )
        _write_private_file(
            private_dir / "operator-decision-note-private.md",
            "PILOT_LEARNING_REHEARSAL_PRIVATE_DECISION_NOTE\nfix before next pilot\n",
        )
        builder_receipt_file = _write_builder_gold_path_share_receipt(
            private_dir / BUILDER_GOLD_PATH_RECEIPT_NAME
        )

        result = check_pilot_iteration(
            output_dir=work_dir,
            skip_build=use_existing_release_artifacts,
            sent_at_utc="2026-05-15T00:00:00+00:00",
            builder_gold_path_share_receipt=builder_receipt_file,
            operator_decision="fix_before_next",
            outcome_tag="partial",
            friction_tags=["docs", "terminology"],
            missing_skill_tags=["skill_search"],
            private_workspace_dir=private_dir,
        )

        iteration_path = Path(str(result["pilot_iteration_json"]))
        decision_path = Path(str(result["pilot_decision_json"]))
        evidence_path = work_dir / f"{RELEASE_SLUG}-pilot-evidence.json"
        iteration = verify_pilot_iteration_file(iteration_path)
        decision = verify_pilot_decision_file(decision_path)
        evidence = verify_pilot_evidence_file(evidence_path)
        generated_text = _generated_text(work_dir)
        payload = _rehearsal_payload(
            iteration=iteration,
            decision=decision,
            evidence=evidence,
            generated_text=generated_text,
            temp_root=temp_root,
            private_workspace_file_names={path.name for path in private_dir.iterdir() if path.is_file()},
        )

    receipt_path = output_dir / PILOT_LEARNING_REHEARSAL_RECEIPT_NAME
    _write_json(receipt_path, payload)
    verify_pilot_learning_rehearsal_receipt_file(receipt_path)
    _assert_shareable_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "archive_sha256": payload["release"]["archive_sha256"],
        "receipt_body_sha256": payload["pilot_learning_rehearsal_receipt_body_sha256"],
    }


def verify_pilot_learning_rehearsal_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_pilot_learning_rehearsal_receipt_payload(payload)
    return payload


def verify_pilot_learning_rehearsal_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PILOT_LEARNING_REHEARSAL_SCHEMA_VERSION:
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "REHEARSAL_PASS":
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal safe_to_share must be true.")
    if payload.get("real_pilot_evidence") is not False:
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal must not claim real pilot evidence.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal checks failed.")
    if payload.get("pilot_learning_rehearsal_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal receipt body hash mismatch.")
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden = [str(ROOT), str(Path.home()), *PRIVATE_MARKERS]
    leaked = [item for item in forbidden if item and item in serialized]
    if leaked:
        raise PilotLearningLoopRehearsalError("pilot learning rehearsal receipt contains private material.")


def _rehearsal_payload(
    *,
    iteration: dict[str, Any],
    decision: dict[str, Any],
    evidence: dict[str, Any],
    generated_text: str,
    temp_root: Path,
    private_workspace_file_names: set[str],
) -> dict[str, Any]:
    release = iteration.get("release") if isinstance(iteration.get("release"), dict) else {}
    iteration_plan = iteration.get("iteration_plan") if isinstance(iteration.get("iteration_plan"), dict) else {}
    learning_summary = (
        iteration.get("pilot_learning_summary")
        if isinstance(iteration.get("pilot_learning_summary"), dict)
        else {}
    )
    private_evidence = (
        evidence.get("private_evidence_fingerprints")
        if isinstance(evidence.get("private_evidence_fingerprints"), dict)
        else {}
    )
    decision_payload = decision.get("decision") if isinstance(decision.get("decision"), dict) else {}
    metrics = iteration.get("metrics") if isinstance(iteration.get("metrics"), dict) else {}
    publish_boundary = (
        iteration.get("publish_boundary") if isinstance(iteration.get("publish_boundary"), dict) else {}
    )
    temp_path = str(temp_root)
    checks = {
        "pilot_evidence_ready": evidence.get("verdict") == "READY_FOR_DECISION"
        and evidence.get("decision_allowed") is True,
        "pilot_decision_recorded": decision.get("verdict") == "FIX_BEFORE_NEXT"
        and decision_payload.get("selected") == "fix_before_next"
        and decision_payload.get("recorded") is True,
        "pilot_iteration_patch_required": iteration.get("verdict") == "PATCH_BEFORE_NEXT"
        and iteration_plan.get("max_next_participants") == 0,
        "controlled_learning_tags_only": learning_summary.get("summary_kind") == "controlled_tags_only"
        and learning_summary.get("raw_feedback_included") is False
        and learning_summary.get("raw_issue_included") is False
        and learning_summary.get("free_text_included") is False,
        "private_feedback_hashes_present": _looks_like_sha256(private_evidence.get("feedback_form_sha256"))
        and _looks_like_sha256(private_evidence.get("issue_intake_sha256")),
        "operator_decision_note_hash_present": _looks_like_sha256(decision_payload.get("operator_note_sha256")),
        "private_workspace_dir_shortcut_used": True,
        "standard_private_workspace_filenames_used": set(PILOT_LEARNING_PRIVATE_WORKSPACE_FILES).issubset(
            private_workspace_file_names
        ),
        "explicit_private_file_args_omitted": True,
        "explicit_private_sha256_args_omitted": True,
        "scaling_blocked": iteration_plan.get("scaling_allowed") is False
        and publish_boundary.get("cohort_scaling_allowed") is False,
        "claim_boundaries_locked": metrics.get("proof_claim_allowed") is False
        and metrics.get("sale_ready") is False
        and metrics.get("success_rate") is None
        and publish_boundary.get("public_claim_allowed") is False
        and publish_boundary.get("marketplace_listing_allowed") is False
        and publish_boundary.get("proof_badge_allowed") is False,
        "raw_private_content_omitted": not any(marker in generated_text for marker in PRIVATE_MARKERS),
        "temporary_paths_omitted": temp_path not in generated_text,
        "real_pilot_evidence_not_claimed": True,
    }
    payload: dict[str, Any] = {
        "schema_version": PILOT_LEARNING_REHEARSAL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "REHEARSAL_PASS" if all(checks.values()) else "REHEARSAL_FAIL",
        "safe_to_share": True,
        "real_pilot_evidence": False,
        "purpose": (
            "Operator-only rehearsal of controlled pilot learning. This receipt is not evidence that a "
            "real external pilot produced feedback, issues, or a market signal."
        ),
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "rehearsed_flow": {
            "pilot_evidence_verdict": evidence.get("verdict"),
            "pilot_decision_verdict": decision.get("verdict"),
            "pilot_iteration_verdict": iteration.get("verdict"),
            "pilot_evidence_body_sha256": evidence.get("pilot_evidence_body_sha256"),
            "pilot_decision_body_sha256": decision.get("pilot_decision_body_sha256"),
            "pilot_iteration_body_sha256": iteration.get("pilot_iteration_body_sha256"),
            "artifact_chain_depth": len(iteration.get("artifact_chain", []))
            if isinstance(iteration.get("artifact_chain"), list)
            else 0,
        },
        "learning_summary": {
            "outcome_tag": learning_summary.get("outcome_tag"),
            "friction_tags": learning_summary.get("friction_tags"),
            "missing_skill_tags": learning_summary.get("missing_skill_tags"),
            "raw_feedback_included": False,
            "raw_issue_included": False,
            "free_text_included": False,
        },
        "private_input_policy": {
            "private_files_used_in_temp_workspace": True,
            "private_workspace_dir_shortcut_used": True,
            "standard_private_workspace_files": list(PILOT_LEARNING_PRIVATE_WORKSPACE_FILES),
            "explicit_private_file_args_used": False,
            "explicit_private_sha256_args_used": False,
            "stored_private_values": False,
            "stored_private_paths": False,
            "stored_private_hashes_only": True,
            "feedback_hash_present": _looks_like_sha256(private_evidence.get("feedback_form_sha256")),
            "issue_intake_hash_present": _looks_like_sha256(private_evidence.get("issue_intake_sha256")),
            "operator_decision_note_hash_present": _looks_like_sha256(decision_payload.get("operator_note_sha256")),
        },
        "iteration_boundary": {
            "decision": decision_payload.get("selected"),
            "max_next_participants": iteration_plan.get("max_next_participants"),
            "scaling_allowed": iteration_plan.get("scaling_allowed"),
            "required_before_next": iteration_plan.get("required_before_next"),
        },
        "claim_boundaries": {
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "sale_ready": False,
            "market_validated": False,
            "marketplace_listing_allowed": False,
        },
        "checks": checks,
    }
    payload["pilot_learning_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _write_builder_gold_path_share_receipt(path: Path) -> Path:
    capabilities = {name: True for name in sorted(BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES)}
    payload = {
        "schema_version": BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION,
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "builder_golden_path_completed": True,
            "manual_no_api_runner_used": True,
            "promotion_audit_lineage_verified": True,
            "raw_browser_storage_excluded": True,
        },
        "capabilities_verified": capabilities,
        "proof_claim_allowed": False,
        "success_rate_claim_allowed": False,
        "sale_ready": False,
    }
    _write_json(path, payload)
    return path


def _has_existing_release_artifacts(output_dir: Path) -> bool:
    required = (
        f"{RELEASE_SLUG}.zip",
        f"{RELEASE_SLUG}.manifest.json",
        "external_alpha_release_verification_receipt.json",
        f"{RELEASE_SLUG}-handoff.json",
        f"{RELEASE_SLUG}-send-ready.json",
        f"{RELEASE_SLUG}-pilot-ready.json",
        f"{RELEASE_SLUG}-bundle-smoke-receipt.json",
    )
    return all((output_dir / name).is_file() for name in required)


def _copy_output_files(source_dir: Path, target_dir: Path) -> None:
    for path in sorted(item for item in source_dir.iterdir() if item.is_file()):
        shutil.copy2(path, target_dir / path.name)


def _write_private_file(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _generated_text(work_dir: Path) -> str:
    chunks: list[str] = []
    for path in sorted(item for item in work_dir.rglob("*") if item.is_file()):
        if path.suffix.lower() in {".json", ".md"}:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "pilot_learning_rehearsal_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PilotLearningLoopRehearsalError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PilotLearningLoopRehearsalError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PilotLearningLoopRehearsalError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_shareable_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [str(ROOT), str(Path.home()), *PRIVATE_MARKERS]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise PilotLearningLoopRehearsalError(f"pilot learning rehearsal receipt contains private material: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse external alpha controlled pilot learning loop.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing pilot learning rehearsal receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_pilot_learning_rehearsal_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
            logger.error("[FAIL] external alpha pilot learning loop rehearsal verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha pilot learning loop rehearsal verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pilot_learning_rehearsal_receipt_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = smoke_pilot_learning_loop(Path(args.output_dir))
    except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
        logger.error("[FAIL] external alpha pilot learning loop rehearsal: %s", exc)
        return 1

    logger.info("[PASS] external alpha pilot learning loop rehearsal")
    logger.info("verdict: REHEARSAL_PASS")
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
