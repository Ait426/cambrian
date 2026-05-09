from __future__ import annotations

import json
from pathlib import Path

from tests.test_job_complete_evidence import (
    ROOT,
    complete_latest_job,
    ingest_and_validate_patch_candidate,
    prepare_custom_harness_project,
    run_cli,
)


def test_evolve_review_summarizes_recent_job_evidence(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["reviewed_jobs"] == 1
    assert "backend/src/routes/auth.ts" in payload["signals"]["repeated_missing_paths"]
    assert "npm test" in payload["signals"]["wrong_test_commands"]
    assert "trace-auth-token-flow" in payload["signals"]["skills_to_improve"]
    assert (tmp_path / ".cambrian" / "evidence" / "repeated_failures.yaml").exists()


def test_evolve_review_uses_validation_evidence_signals(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    signals = payload["signals"]
    assert validation["evidence_ref"] in signals["validation_evidence_refs"]
    assert signals["trust_gate_status_counts"]["manual_required"] == 1
    assert "manual_validation_required" in signals["validation_contract_statuses"]
    assert signals["manual_validation_required_jobs"]
    assert "npm test" in signals["validation_commands_needing_manual_run"]
    assert "Patch proposal was not applied to source code" in signals["unchecked_items"]
    assert signals["outcome_counts"]["partial"] == 1
    assert signals["evidence_gaps"] == []


def test_evolution_review_signal_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian evolve review",
        "validation_commands_needing_manual_run",
        "trust_gate_status_counts",
        "manual_validation_required_jobs",
        "evidence_gaps",
    ]:
        assert phrase in text
    assert "docs/product/21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md" in readme
    assert "21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md" in index
