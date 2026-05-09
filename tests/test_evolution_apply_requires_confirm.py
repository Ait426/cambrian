from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_job_complete_evidence import ROOT, complete_latest_job, prepare_custom_harness_project, run_cli


def test_evolve_apply_requires_confirm(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "confirmation_required"
    assert payload["changed_files"] == []


def test_evolve_apply_with_confirm_updates_local_metadata_only(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert ".cambrian/harness.yaml" in payload["changed_files"]
    assert ".cambrian/workforce.yaml" in payload["changed_files"]
    assert any(path.startswith(".cambrian/skills/") for path in payload["changed_files"])
    assert not any(path.startswith("backend/") for path in payload["changed_files"])
    assert payload["audit_ref"] == f".cambrian/evolution/audit/{proposal_id}.yaml"
    assert payload["rollback_ref"] == f".cambrian/evolution/rollback/{proposal_id}.yaml"
    assert payload["backup_refs"]
    assert (tmp_path / ".cambrian" / "evolution" / "applied" / f"{proposal_id}.yaml").exists()
    assert (tmp_path / ".cambrian" / "evolution" / "history.yaml").exists()
    audit = yaml.safe_load((tmp_path / payload["audit_ref"]).read_text(encoding="utf-8"))
    rollback = yaml.safe_load((tmp_path / payload["rollback_ref"]).read_text(encoding="utf-8"))
    history = yaml.safe_load((tmp_path / ".cambrian" / "evolution" / "history.yaml").read_text(encoding="utf-8"))
    assert audit["proposal_id"] == proposal_id
    assert audit["safety"]["source_code_modified"] is False
    assert audit["file_changes"]
    assert all(item["before_sha256"] for item in audit["file_changes"])
    assert all(item["after_sha256"] for item in audit["file_changes"])
    assert rollback["status"] == "manual_rollback_available"
    assert rollback["automatic_rollback_command"] is None
    assert history["applied"][-1]["audit_ref"] == payload["audit_ref"]
    assert history["applied"][-1]["rollback_ref"] == payload["rollback_ref"]


def test_evolve_rollback_requires_confirm_and_restores_metadata(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    applied = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")
    assert applied.returncode == 0, applied.stderr
    assert harness_path.read_text(encoding="utf-8") != harness_before

    blocked = run_cli(tmp_path, "evolve", "rollback", proposal_id, "--json")
    assert blocked.returncode == 1
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["ok"] is False
    assert blocked_payload["error"] == "confirmation_required"
    assert blocked_payload["restored_files"] == []

    result = run_cli(tmp_path, "evolve", "rollback", proposal_id, "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "rolled_back"
    assert ".cambrian/harness.yaml" in payload["restored_files"]
    assert not any(path.startswith("backend/") for path in payload["restored_files"])
    assert payload["rollback_ref"] == f".cambrian/evolution/rollback/{proposal_id}.yaml"
    assert payload["rollback_applied_ref"] == f".cambrian/evolution/rollback/applied/{proposal_id}.yaml"
    assert harness_path.read_text(encoding="utf-8") == harness_before
    rollback_record = yaml.safe_load((tmp_path / payload["rollback_applied_ref"]).read_text(encoding="utf-8"))
    history = yaml.safe_load((tmp_path / ".cambrian" / "evolution" / "history.yaml").read_text(encoding="utf-8"))
    assert rollback_record["safety"]["source_code_modified"] is False
    assert rollback_record["restored_files"] == payload["restored_files"]
    assert history["rollbacks"][-1]["proposal_id"] == proposal_id
    assert history["rollbacks"][-1]["rollback_applied_ref"] == payload["rollback_applied_ref"]


def test_evolution_apply_audit_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "23_EVOLUTION_APPLY_AUDIT_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian evolve apply",
        "audit_ref",
        "rollback_ref",
        "backup_refs",
        ".cambrian/evolution/audit",
        ".cambrian/evolution/rollback",
        "source code를 수정하지 않는다",
    ]:
        assert phrase in text
    assert "docs/product/23_EVOLUTION_APPLY_AUDIT_CONTRACT.md" in readme
    assert "23_EVOLUTION_APPLY_AUDIT_CONTRACT.md" in index


def test_evolution_rollback_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "24_EVOLUTION_ROLLBACK_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian evolve rollback",
        "rollback_applied_ref",
        "restored_files",
        ".cambrian/evolution/rollback/applied",
        "source code를 수정하지 않는다",
        "`--confirm` 없이는 복원하지 않는다",
    ]:
        assert phrase in text
    assert "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md" in readme
    assert "24_EVOLUTION_ROLLBACK_CONTRACT.md" in index
