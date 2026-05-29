from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_evidence import complete_job


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def prepare_custom_harness_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "routes" / "auth.ts", "export function route() {}\n")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")
    assert run_cli(root, "project", "scan", "--json").returncode == 0
    assert run_cli(root, "harness", "interview", "start", "--json").returncode == 0
    answers = root / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Investigate auth and reservation bugs safely.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply", "no DB schema changes"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": "Relevant Jest tests pass.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(root, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert run_cli(root, "harness", "design", "--json").returncode == 0
    assert run_cli(root, "workforce", "generate", "--json").returncode == 0
    assert run_cli(root, "skill", "generate", "--json").returncode == 0
    assert run_cli(root, "harness", "engineer", "design", "--json").returncode == 0
    assert run_cli(root, "harness", "engineer", "review", "--json").returncode == 0
    assert run_cli(root, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json").returncode == 0
    assert run_cli(root, "harness", "install", "--confirm", "--json").returncode == 0
    started = run_cli(root, "job", "start", "check refresh token login failure", "--json")
    assert started.returncode == 0, started.stderr
    payload = json.loads(started.stdout)
    assert payload["job_id"]


def complete_latest_job(root: Path) -> dict:
    result = run_cli(
        root,
        "job",
        "complete",
        "latest",
        "--outcome",
        "partial",
        "--notes",
        "test command was wrong and refresh token path was missed",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def ingest_and_validate_patch_candidate(root: Path) -> dict:
    reply = root / "ai_reply_patch_candidate.yaml"
    reply.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "reason": "Authorization header must strip Bearer before verification.",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(root, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")
    assert ingest.returncode == 0, ingest.stderr
    validate = run_cli(root, "job", "validate", "latest", "--json")
    assert validate.returncode != 0
    return json.loads(validate.stdout)


def mark_latest_validation_evidence_passed(root: Path, validation: dict) -> None:
    evidence_ref = str(validation.get("evidence_ref") or "")
    assert evidence_ref
    evidence_path = root / evidence_ref
    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
    evidence["validation_status"] = "passed"
    evidence["validation_contract_status"] = "commands_executed"
    evidence["trust_gate_status"] = "verified"
    evidence["manual_validation_required"] = False
    evidence["unchecked_items"] = []
    execution = evidence.get("validation_command_execution")
    if isinstance(execution, dict):
        execution["status"] = "passed"
        results = execution.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    item["status"] = "passed"
                    item["returncode"] = 0
                    item["stderr"] = ""
    evidence_path.write_text(yaml.safe_dump(evidence, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_job_complete_records_outcome_and_evidence(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)

    payload = complete_latest_job(tmp_path)

    assert payload["ok"] is True
    assert payload["status"] == "recorded"
    assert payload["outcome"] == "partial"
    assert payload["outcome_ref"]
    assert payload["evidence_ref"] == ".cambrian/evidence/outcomes.yaml"
    assert (tmp_path / payload["outcome_ref"]).exists()
    evidence = yaml.safe_load((tmp_path / ".cambrian" / "evidence" / "outcomes.yaml").read_text(encoding="utf-8"))
    assert evidence["outcomes"][0]["outcome"] == "partial"
    assert "trace-auth-token-flow" in evidence["outcomes"][0]["selected_skills"]


def test_job_complete_outcome_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "20_JOB_COMPLETE_OUTCOME_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian job complete",
        "validation_evidence_ref",
        "ready_for_evolution",
        ".cambrian/evidence/outcomes.yaml",
        "source_code_modified_by_cambrian",
    ]:
        assert phrase in text
    assert "docs/product/20_JOB_COMPLETE_OUTCOME_CONTRACT.md" in readme
    assert "20_JOB_COMPLETE_OUTCOME_CONTRACT.md" in index


def test_job_complete_links_validation_evidence_for_evolution(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)

    payload = complete_latest_job(tmp_path)

    assert payload["ok"] is True
    assert payload["validation_evidence_ref"] == validation["evidence_ref"]
    assert payload["validation_contract_status"] == "manual_validation_required"
    assert payload["trust_gate_status"] == "manual_required"
    assert payload["ready_for_evolution"] is True
    assert payload["source_code_modified_by_cambrian"] is False
    assert "npm test" in payload["validation_commands"]
    assert payload["checked_artifacts"]
    assert "Patch proposal was not applied to source code" not in payload["unchecked_items"]
    assert any("AI reply evidence compliance incomplete" in item for item in payload["unchecked_items"])
    outcome = yaml.safe_load((tmp_path / payload["outcome_ref"]).read_text(encoding="utf-8"))
    assert outcome["validation_evidence_ref"] == validation["evidence_ref"]
    assert outcome["ready_for_evolution"] is True
    assert outcome["source_code_modified_by_cambrian"] is False
    ledger = yaml.safe_load((tmp_path / ".cambrian" / "evidence" / "outcomes.yaml").read_text(encoding="utf-8"))
    assert ledger["outcomes"][0]["validation_evidence_ref"] == validation["evidence_ref"]


def test_job_company_loop_records_ledgers_and_feeds_next_job_start(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)

    payload = complete_latest_job(tmp_path)

    assert validation["company_verification_record"]["status"] == "verification_recorded"
    assert payload["company_context_record"]["status"] == "context_recorded"
    assert payload["company_context_record"]["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"
    assert payload["company_verification_record"]["status"] == "verification_recorded"
    context_records = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "context" / "records.yaml").read_text(encoding="utf-8")
    )
    assert context_records["records"][0]["promotion_status"] == "candidate"
    assert context_records["records"][0]["promotion_policy"]["auto_promote"] is False
    promotion_review = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "context" / "promotion_review.yaml").read_text(encoding="utf-8")
    )
    assert promotion_review["status"] == "pending_user_review"
    assert promotion_review["review_items"][0]["approval_state"] == "pending_user_review"
    assert promotion_review["review_items"][0]["auto_promote"] is False
    verification_ledger = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "verification" / "ledger.yaml").read_text(encoding="utf-8")
    )
    stages = [entry["stage"] for entry in verification_ledger["entries"]]
    assert stages == ["validate", "complete"]
    assert verification_ledger["entries"][0]["validation_evidence_ref"] == validation["evidence_ref"]
    assert verification_ledger["entries"][0]["unchecked_risk_count"] >= 1
    assert verification_ledger["entries"][0]["context_intent"]["target_product_level"] == "upper"
    assert verification_ledger["entries"][0]["context_intent"]["candidate_context_is_unapproved_signal"] is True
    assert verification_ledger["entries"][1]["context_evidence_ref"] == payload["company_context_record"]["saved_path"]
    assert verification_ledger["entries"][1]["promotion_policy"]["auto_promote"] is False
    assert verification_ledger["entries"][1]["context_intent"]["target_product_level"] == "upper"

    next_start = run_cli(tmp_path, "job", "start", "follow up on prior unchecked validation risk", "--json")

    assert next_start.returncode == 0, next_start.stderr
    next_payload = json.loads(next_start.stdout)
    packet = yaml.safe_load((tmp_path / next_payload["request_packet_ref"]).read_text(encoding="utf-8"))
    loop_context = packet["execution_contract"]["company_loop_context"]
    assert loop_context["status"] == "available"
    assert loop_context["context_records"]
    assert loop_context["candidate_context_records"]
    assert loop_context["promoted_memory"]["total_count"] == 0
    assert loop_context["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"
    assert loop_context["verification_entries"]
    assert loop_context["promotion_policy"]["auto_promote"] is False
    intent_snapshot = packet["execution_contract"]["context_intent_snapshot"]
    assert intent_snapshot["detected_intent"]["primary"] == "validation_followup"
    assert intent_snapshot["detected_intent"]["confidence"] == "high"
    assert intent_snapshot["context_policy"]["memory_is_not_context"] is True
    assert intent_snapshot["context_policy"]["candidate_context_is_unapproved_signal"] is True
    assert intent_snapshot["relevance_filter"]["selected_context_count"] >= 1
    assert intent_snapshot["relevance_filter"]["discarded_as_irrelevant_count"] >= 0
    assert any("company_loop_context" in item for item in packet["execution_contract"]["must_do"])
    assert any("promoted_memory" in item for item in packet["execution_contract"]["must_do"])
    assert any("context_intent_snapshot" in item for item in packet["execution_contract"]["must_do"])
    assert "Company ledger" in packet["codex_claude_instruction"]
    assert "Context intent:" in packet["codex_claude_instruction"]

    promote = run_cli(tmp_path, "company", "context", "promote", "context-record-0001", "--confirm", "--json")
    assert promote.returncode == 0, promote.stderr
    promote_payload = json.loads(promote.stdout)
    assert promote_payload["status"] == "context_promoted"
    assert promote_payload["auto_promote"] is False

    promoted_start = run_cli(tmp_path, "job", "start", "use approved company memory only", "--json")
    assert promoted_start.returncode == 0, promoted_start.stderr
    promoted_payload = json.loads(promoted_start.stdout)
    promoted_packet = yaml.safe_load((tmp_path / promoted_payload["request_packet_ref"]).read_text(encoding="utf-8"))
    promoted_loop = promoted_packet["execution_contract"]["company_loop_context"]
    assert promoted_loop["candidate_context_records"] == []
    assert promoted_loop["promoted_memory"]["total_count"] >= 1


def test_job_complete_logs_malformed_validation_evidence(caplog, tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    bad_evidence = tmp_path / ".cambrian" / "evidence" / "validation" / "zz_bad.yaml"
    bad_evidence.parent.mkdir(parents=True, exist_ok=True)
    bad_evidence.write_text("broken: [\n", encoding="utf-8")

    caplog.set_level(logging.WARNING, logger="engine.project_evidence")
    result = complete_job(
        tmp_path,
        "latest",
        "partial",
        "malformed validation evidence should be logged and skipped",
    )

    assert result.status == "recorded"
    assert result.validation_evidence_ref is None
    assert any("검증 evidence 파일을 읽지 못해 건너뜁니다" in record.message for record in caplog.records)
