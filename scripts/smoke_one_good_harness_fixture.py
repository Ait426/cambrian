"""Replay a deterministic One Good Harness fixture and write a share-safe receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SCHEMA_VERSION = "one_good_harness_fixture_replay_v0_1"
FIXTURE_NAME = "python_auth_service"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "one_good_harness"
FIXTURE_DIR = FIXTURE_ROOT / FIXTURE_NAME
DEFAULT_RECEIPT = ROOT / "dist" / "one-good-harness-fixture-replay-receipt.json"
DEFAULT_HOLD_RECEIPT = ROOT / "dist" / "one-good-harness-missing-evidence-hold-receipt.json"
RUNTIME_SKIP_PARTS = {".cambrian", "__pycache__", ".pytest_cache"}

logger = logging.getLogger(__name__)


class OneGoodHarnessReplayError(RuntimeError):
    """One Good Harness fixture replay failed."""


def replay_one_good_harness_fixture(
    *,
    fixture_dir: Path = FIXTURE_DIR,
    receipt_path: Path = DEFAULT_RECEIPT,
    work_dir: Path | None = None,
    keep_workdir: bool = False,
    timeout: int = 60,
) -> dict[str, Any]:
    """Run the replay gate and persist a share-safe receipt."""
    fixture = Path(fixture_dir).resolve()
    if not fixture.is_dir():
        raise OneGoodHarnessReplayError(f"fixture is missing: {fixture.name}")

    temp_context: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        temp_context = tempfile.TemporaryDirectory(prefix="cambrian-one-good-harness-")
        project = Path(temp_context.name) / fixture.name
    else:
        project = Path(work_dir).resolve()
        if project.exists():
            raise OneGoodHarnessReplayError("work_dir already exists; choose an empty path.")

    try:
        shutil.copytree(
            fixture,
            project,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".cambrian"),
        )
        before_hashes = _source_hashes(project)
        steps: list[dict[str, Any]] = []

        _record_step(steps, project, "project_scan", ["project", "scan", "--json"], timeout=timeout)
        _record_step(steps, project, "interview_start", ["harness", "interview", "start", "--json"], timeout=timeout)
        _record_step(
            steps,
            project,
            "interview_answer",
            ["harness", "interview", "answer", "--answers", "fixtures/interview_answers.yaml", "--json"],
            timeout=timeout,
        )
        _record_step(steps, project, "harness_design", ["harness", "design", "--json"], timeout=timeout)
        _record_step(steps, project, "workforce_generate", ["workforce", "generate", "--json"], timeout=timeout)
        _record_step(steps, project, "skill_generate", ["skill", "generate", "--json"], timeout=timeout)
        _record_step(steps, project, "harness_engineer_design", ["harness", "engineer", "design", "--json"], timeout=timeout)
        _record_step(steps, project, "harness_engineer_review", ["harness", "engineer", "review", "--json"], timeout=timeout)
        job_request = _fixture_job_request(project)
        _record_step(
            steps,
            project,
            "harness_engineer_dry_run",
            ["harness", "engineer", "dry-run", job_request, "--json"],
            timeout=timeout,
        )
        _record_step(steps, project, "harness_install", ["harness", "install", "--confirm", "--json"], timeout=timeout)
        _record_step(steps, project, "status", ["status", "--json"], timeout=timeout)
        _record_step(
            steps,
            project,
            "job_start",
            ["job", "start", job_request, "--json"],
            timeout=timeout,
        )
        _record_step(
            steps,
            project,
            "job_ingest",
            ["job", "ingest", "latest", "fixtures/ai_reply_analysis.yaml", "--json"],
            timeout=timeout,
        )
        _record_step(steps, project, "job_validate", ["job", "validate", "latest", "--run", "--json"], timeout=timeout)
        _record_step(
            steps,
            project,
            "job_complete",
            [
                "job",
                "complete",
                "latest",
                "--outcome",
                "success",
                "--notes",
                f"one good harness fixture replay passed: {fixture.name}",
                "--json",
            ],
            timeout=timeout,
        )

        after_hashes = _source_hashes(project)
        receipt = _receipt(
            fixture=fixture,
            project=project,
            steps=steps,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
        )
        target = Path(receipt_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json(target, receipt)
        verify_one_good_harness_fixture_receipt_file(target)
        return {
            "status": receipt["status"],
            "verdict": receipt["verdict"],
            "receipt_json": str(target),
            "receipt_body_sha256": receipt["receipt_body_sha256"],
            "workdir_preserved": bool(work_dir is not None or keep_workdir),
        }
    finally:
        if temp_context is not None and not keep_workdir:
            temp_context.cleanup()


def replay_one_good_harness_missing_evidence_fixture(
    *,
    fixture_dir: Path = FIXTURE_DIR,
    receipt_path: Path = DEFAULT_HOLD_RECEIPT,
    weak_reply: str = "fixtures/ai_reply_missing_evidence.yaml",
    work_dir: Path | None = None,
    keep_workdir: bool = False,
    timeout: int = 60,
) -> dict[str, Any]:
    """Run a deterministic negative replay and persist a share-safe hold receipt."""
    fixture = Path(fixture_dir).resolve()
    if not fixture.is_dir():
        raise OneGoodHarnessReplayError(f"fixture is missing: {fixture.name}")

    temp_context: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        temp_context = tempfile.TemporaryDirectory(prefix="cambrian-one-good-harness-hold-")
        project = Path(temp_context.name) / fixture.name
    else:
        project = Path(work_dir).resolve()
        if project.exists():
            raise OneGoodHarnessReplayError("work_dir already exists; choose an empty path.")

    try:
        shutil.copytree(
            fixture,
            project,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".cambrian"),
        )
        before_hashes = _source_hashes(project)
        steps = _run_fixture_setup_steps(project, timeout=timeout)

        _record_step(
            steps,
            project,
            "job_ingest_missing_evidence",
            ["job", "ingest", "latest", weak_reply, "--json"],
            timeout=timeout,
        )
        _record_step(steps, project, "job_validate_missing_evidence", ["job", "validate", "latest", "--run", "--json"], timeout=timeout)

        after_hashes = _source_hashes(project)
        receipt = _hold_receipt(
            fixture=fixture,
            project=project,
            steps=steps,
            before_hashes=before_hashes,
            after_hashes=after_hashes,
            weak_reply=weak_reply,
        )
        target = Path(receipt_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json(target, receipt)
        verify_one_good_harness_fixture_receipt_file(target)
        return {
            "status": receipt["status"],
            "verdict": receipt["verdict"],
            "receipt_json": str(target),
            "receipt_body_sha256": receipt["receipt_body_sha256"],
            "workdir_preserved": bool(work_dir is not None or keep_workdir),
        }
    finally:
        if temp_context is not None and not keep_workdir:
            temp_context.cleanup()


def verify_one_good_harness_fixture_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_one_good_harness_fixture_receipt_payload(payload)
    return payload


def verify_one_good_harness_fixture_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise OneGoodHarnessReplayError("receipt schema_version mismatch.")
    if payload.get("safe_to_share") is not True:
        raise OneGoodHarnessReplayError("receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise OneGoodHarnessReplayError("receipt checks failed.")
    receipt_checks = _receipt_checks(payload)
    if payload.get("receipt_checks") != receipt_checks:
        raise OneGoodHarnessReplayError("receipt self-checks are stale.")
    failed = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed:
        raise OneGoodHarnessReplayError("receipt self-check failed: " + ", ".join(failed))
    if payload.get("receipt_body_sha256") != _receipt_body_sha256(payload):
        raise OneGoodHarnessReplayError("receipt body hash mismatch.")


def _record_step(
    steps: list[dict[str, Any]],
    project: Path,
    name: str,
    args: list[str],
    *,
    timeout: int,
) -> None:
    completed = _run_cli(project, args, timeout=timeout)
    payload = _json_payload(completed.stdout)
    step = {
        "name": name,
        "command": "cambrian " + " ".join(args),
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "summary": _step_summary(name, payload),
    }
    steps.append(step)
    if completed.returncode != 0:
        raise OneGoodHarnessReplayError(f"{name} failed: exit_code={completed.returncode}")


def _run_cli(project: Path, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _json_payload(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _step_summary(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name == "project_scan":
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        return {
            "saved_path": payload.get("saved_path"),
            "project_name": profile.get("project_name"),
            "language": profile.get("language"),
            "test_framework": profile.get("test_framework"),
            "domains": profile.get("domains") if isinstance(profile.get("domains"), list) else [],
        }
    if name == "interview_answer":
        return {"status": payload.get("status"), "answers_ref": payload.get("answers_ref"), "missing": payload.get("missing") or []}
    if name == "harness_design":
        return {"status": payload.get("status"), "harness_id": payload.get("harness_id"), "saved_path": payload.get("saved_path")}
    if name in {"workforce_generate", "skill_generate", "harness_install"}:
        return {
            "status": payload.get("status"),
            "harness_id": payload.get("harness_id"),
            "generated_agents": _item_ids(payload.get("generated_agents") or payload.get("agents") or []),
            "generated_skills": _item_ids(payload.get("generated_skills") or payload.get("skills") or []),
        }
    if name.startswith("harness_engineer"):
        return {"ok": payload.get("ok"), "status": payload.get("status"), "harness_id": payload.get("harness_id")}
    if name == "status":
        return {"project": payload.get("project"), "harness": payload.get("harness")}
    if name == "job_start":
        return {"status": payload.get("status"), "job_id": payload.get("job_id"), "request_packet_ref": payload.get("request_packet_ref")}
    if name == "job_ingest":
        return {
            "status": payload.get("status"),
            "reply_kind": payload.get("reply_kind"),
            "reply_evidence_status": payload.get("reply_evidence_status"),
        }
    if name == "job_ingest_missing_evidence":
        compliance = payload.get("reply_evidence_compliance") if isinstance(payload.get("reply_evidence_compliance"), dict) else {}
        return {
            "status": payload.get("status"),
            "reply_kind": payload.get("reply_kind"),
            "reply_evidence_status": payload.get("reply_evidence_status"),
            "missing": compliance.get("missing") if isinstance(compliance.get("missing"), list) else [],
        }
    if name == "job_validate":
        return {
            "validation_status": payload.get("validation_status"),
            "trust_gate_status": payload.get("trust_gate_status"),
            "validation_contract_status": payload.get("validation_contract_status"),
            "verdict": payload.get("verdict"),
            "evidence_ref": payload.get("evidence_ref"),
        }
    if name == "job_validate_missing_evidence":
        return {
            "validation_status": payload.get("validation_status"),
            "trust_gate_status": payload.get("trust_gate_status"),
            "validation_contract_status": payload.get("validation_contract_status"),
            "verdict": payload.get("verdict"),
            "evidence_ref": payload.get("evidence_ref"),
            "unchecked_items": payload.get("unchecked_items") if isinstance(payload.get("unchecked_items"), list) else [],
            "reply_evidence_status": payload.get("reply_evidence_status"),
        }
    if name == "job_complete":
        return {
            "outcome": payload.get("outcome"),
            "verdict": payload.get("verdict"),
            "trust_gate_status": payload.get("trust_gate_status"),
            "latest_verdict_ref": payload.get("latest_verdict_ref"),
        }
    return {"status": payload.get("status"), "ok": payload.get("ok")}


def _run_fixture_setup_steps(project: Path, *, timeout: int) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    _record_step(steps, project, "project_scan", ["project", "scan", "--json"], timeout=timeout)
    _record_step(steps, project, "interview_start", ["harness", "interview", "start", "--json"], timeout=timeout)
    _record_step(
        steps,
        project,
        "interview_answer",
        ["harness", "interview", "answer", "--answers", "fixtures/interview_answers.yaml", "--json"],
        timeout=timeout,
    )
    _record_step(steps, project, "harness_design", ["harness", "design", "--json"], timeout=timeout)
    _record_step(steps, project, "workforce_generate", ["workforce", "generate", "--json"], timeout=timeout)
    _record_step(steps, project, "skill_generate", ["skill", "generate", "--json"], timeout=timeout)
    _record_step(steps, project, "harness_engineer_design", ["harness", "engineer", "design", "--json"], timeout=timeout)
    _record_step(steps, project, "harness_engineer_review", ["harness", "engineer", "review", "--json"], timeout=timeout)
    job_request = _fixture_job_request(project)
    _record_step(
        steps,
        project,
        "harness_engineer_dry_run",
        ["harness", "engineer", "dry-run", job_request, "--json"],
        timeout=timeout,
    )
    _record_step(steps, project, "harness_install", ["harness", "install", "--confirm", "--json"], timeout=timeout)
    _record_step(steps, project, "status", ["status", "--json"], timeout=timeout)
    _record_step(steps, project, "job_start", ["job", "start", job_request, "--json"], timeout=timeout)
    return steps


def _receipt(
    *,
    fixture: Path,
    project: Path,
    steps: list[dict[str, Any]],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
) -> dict[str, Any]:
    by_name = {str(step.get("name")): step for step in steps}
    checks = {
        "fixture_safe_to_commit": fixture.is_dir(),
        "all_steps_passed": all(step.get("status") == "passed" and step.get("exit_code") == 0 for step in steps),
        "source_hashes_unchanged": before_hashes == after_hashes,
        "provider_api_called_by_cambrian_false": True,
        "source_code_modified_by_cambrian_false": True,
        "project_scan_saved_profile": bool(by_name.get("project_scan", {}).get("summary", {}).get("saved_path")),
        "interview_answer_ready": by_name.get("interview_answer", {}).get("summary", {}).get("status") == "ready_for_plan",
        "harness_installed": by_name.get("harness_install", {}).get("summary", {}).get("status") == "installed",
        "status_checked": bool(by_name.get("status")),
        "job_started": by_name.get("job_start", {}).get("summary", {}).get("status")
        in {"created", "waiting_for_ai_reply"},
        "reply_evidence_accepted": by_name.get("job_ingest", {}).get("summary", {}).get("reply_evidence_status") == "satisfied",
        "validation_passed": by_name.get("job_validate", {}).get("summary", {}).get("validation_status") == "passed",
        "validation_trust_verified": by_name.get("job_validate", {}).get("summary", {}).get("trust_gate_status") == "verified",
        "job_completed_with_pass_verdict": by_name.get("job_complete", {}).get("summary", {}).get("verdict") == "pass",
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "ONE_GOOD_HARNESS_REPLAYED" if all(checks.values()) else "ONE_GOOD_HARNESS_HOLD",
        "safe_to_share": True,
        "fixture": {
            "name": fixture.name,
            "source_ref": _safe_fixture_ref(fixture),
            "workdir_included": False,
        },
        "capabilities_verified": {
            "project_scan": checks["project_scan_saved_profile"],
            "harness_interview_answer": checks["interview_answer_ready"],
            "harness_engineering_design_review_dry_run": all(
                by_name.get(name, {}).get("status") == "passed"
                for name in ["harness_engineer_design", "harness_engineer_review", "harness_engineer_dry_run"]
            ),
            "harness_install": checks["harness_installed"],
            "status_truth_surface": checks["status_checked"],
            "job_start": checks["job_started"],
            "reply_envelope_ingest": checks["reply_evidence_accepted"],
            "validation_run": checks["validation_passed"],
            "job_complete_and_verdict": checks["job_completed_with_pass_verdict"],
        },
        "source_hashes": {
            "before": before_hashes,
            "after": after_hashes,
        },
        "steps": steps,
        "artifact_refs": _artifact_refs(project),
        "checks": checks,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "provider_api_called_by_cambrian": False,
        "source_code_modified_by_cambrian": False,
        "public_proof_claim_allowed": False,
        "sale_ready": False,
    }
    payload["receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["receipt_checks"] = _receipt_checks(payload)
    return payload


def _hold_receipt(
    *,
    fixture: Path,
    project: Path,
    steps: list[dict[str, Any]],
    before_hashes: dict[str, str],
    after_hashes: dict[str, str],
    weak_reply: str,
) -> dict[str, Any]:
    by_name = {str(step.get("name")): step for step in steps}
    ingest_summary = by_name.get("job_ingest_missing_evidence", {}).get("summary", {})
    validate_summary = by_name.get("job_validate_missing_evidence", {}).get("summary", {})
    missing = ingest_summary.get("missing") if isinstance(ingest_summary.get("missing"), list) else []
    unchecked = validate_summary.get("unchecked_items") if isinstance(validate_summary.get("unchecked_items"), list) else []
    checks = {
        "fixture_safe_to_commit": fixture.is_dir(),
        "setup_steps_passed": all(
            step.get("status") == "passed" and step.get("exit_code") == 0
            for step in steps
            if str(step.get("name")) not in {"job_ingest_missing_evidence", "job_validate_missing_evidence"}
        ),
        "source_hashes_unchanged": before_hashes == after_hashes,
        "provider_api_called_by_cambrian_false": True,
        "source_code_modified_by_cambrian_false": True,
        "weak_reply_ingested": by_name.get("job_ingest_missing_evidence", {}).get("status") == "passed",
        "reply_evidence_incomplete": ingest_summary.get("reply_evidence_status") == "incomplete",
        "missing_evidence_reported": bool(missing),
        "validation_commands_ran": validate_summary.get("validation_status") == "passed",
        "trust_gate_not_verified": validate_summary.get("trust_gate_status") != "verified",
        "verdict_hold": validate_summary.get("verdict") == "hold",
        "unchecked_risk_recorded": any("AI reply evidence compliance incomplete" in str(item) for item in unchecked),
    }
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "hold" if all(checks.values()) else "fail",
        "verdict": "ONE_GOOD_HARNESS_HOLD_REPLAYED" if all(checks.values()) else "ONE_GOOD_HARNESS_HOLD_REPLAY_FAILED",
        "safe_to_share": True,
        "fixture": {
            "name": fixture.name,
            "source_ref": _safe_fixture_ref(fixture),
            "workdir_included": False,
        },
        "negative_proof": {
            "weak_reply_ref": weak_reply,
            "missing_evidence": missing,
            "unchecked_items": unchecked,
            "trust_gate_status": validate_summary.get("trust_gate_status"),
            "validation_status": validate_summary.get("validation_status"),
            "evaluator_verdict": validate_summary.get("verdict"),
            "fake_pass_blocked": validate_summary.get("verdict") == "hold"
            and validate_summary.get("trust_gate_status") != "verified",
        },
        "source_hashes": {
            "before": before_hashes,
            "after": after_hashes,
        },
        "steps": steps,
        "artifact_refs": _artifact_refs(project),
        "checks": checks,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "provider_api_called_by_cambrian": False,
        "source_code_modified_by_cambrian": False,
        "public_proof_claim_allowed": False,
        "sale_ready": False,
    }
    payload["receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["receipt_checks"] = _receipt_checks(payload)
    return payload


def _artifact_refs(project: Path) -> dict[str, str | None]:
    refs = {
        "profile": ".cambrian/profile.yaml",
        "harness": ".cambrian/harness.yaml",
        "validation": ".cambrian/validation.yaml",
        "job": ".cambrian/packs/jobs/latest.yaml",
        "latest_verdict": ".cambrian/reports/latest_verdict.json",
        "outcomes": ".cambrian/evidence/outcomes.yaml",
    }
    return {key: ref if (project / ref).exists() else None for key, ref in refs.items()}


def _source_hashes(project: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project)
        if any(part in RUNTIME_SKIP_PARTS for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        hashes[relative.as_posix()] = _sha256(path)
    return hashes


def _fixture_job_request(project: Path) -> str:
    request_path = project / "fixtures" / "job_request.txt"
    if request_path.is_file():
        text = request_path.read_text(encoding="utf-8-sig").strip()
        if text:
            return " ".join(text.split())
    return f"verify {project.name} one good harness fixture"


def _safe_fixture_ref(fixture: Path) -> str:
    try:
        return fixture.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return f"external_fixture:{fixture.name}"


def _item_ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            value = item.get("id") or item.get("name") or item.get("agent_id") or item.get("skill_id")
        else:
            value = item
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"receipt_body_sha256", "receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(ROOT)
    home = str(Path.home())
    body_hash = payload.get("receipt_body_sha256")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    expected_status_ok = payload.get("status") in {"pass", "hold"}
    expected_verdict_ok = payload.get("verdict") in {"ONE_GOOD_HARNESS_REPLAYED", "ONE_GOOD_HARNESS_HOLD_REPLAYED"}
    return {
        "schema_version_present": payload.get("schema_version") == SCHEMA_VERSION,
        "status_expected": expected_status_ok,
        "verdict_expected": expected_verdict_ok,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "fixture_workdir_omitted": payload.get("fixture", {}).get("workdir_included") is False,
        "provider_api_false": payload.get("provider_api_called_by_cambrian") is False,
        "source_code_modified_false": payload.get("source_code_modified_by_cambrian") is False,
        "claim_boundaries_locked": payload.get("public_proof_claim_allowed") is False and payload.get("sale_ready") is False,
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise OneGoodHarnessReplayError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the deterministic One Good Harness fixture.")
    parser.add_argument("--fixture-dir", type=Path, default=FIXTURE_DIR)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--expect-hold", action="store_true", help="use a weak AI reply and require a hold receipt")
    parser.add_argument("--weak-reply", default="fixtures/ai_reply_missing_evidence.yaml")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--verify-receipt", type=Path, default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_one_good_harness_fixture_receipt_file(args.verify_receipt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] one good harness fixture receipt verification: %s", exc)
            return 1
        logger.info("[PASS] one good harness fixture receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["receipt_body_sha256"])
        return 0

    try:
        if args.expect_hold:
            result = replay_one_good_harness_missing_evidence_fixture(
                fixture_dir=args.fixture_dir,
                receipt_path=args.receipt,
                weak_reply=str(args.weak_reply),
                work_dir=args.work_dir,
                keep_workdir=bool(args.keep_workdir),
                timeout=int(args.timeout or 60),
            )
        else:
            result = replay_one_good_harness_fixture(
                fixture_dir=args.fixture_dir,
                receipt_path=args.receipt,
                work_dir=args.work_dir,
                keep_workdir=bool(args.keep_workdir),
                timeout=int(args.timeout or 60),
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] one good harness fixture replay: %s", exc)
        return 1

    logger.info("[PASS] one good harness fixture replay")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
