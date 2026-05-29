from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tests.test_job_complete_evidence import (
    ROOT,
    complete_latest_job,
    ingest_and_validate_patch_candidate,
    mark_latest_validation_evidence_passed,
    prepare_custom_harness_project,
    run_cli,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expand_outcomes(root: Path, count: int = 10) -> None:
    outcomes_path = root / ".cambrian" / "evidence" / "outcomes.yaml"
    payload = yaml.safe_load(outcomes_path.read_text(encoding="utf-8"))
    seed = dict(payload["outcomes"][0])
    payload["outcomes"] = [{**seed, "job_id": f"job-maturity-{index:03d}"} for index in range(count)]
    outcomes_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


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


def test_evolve_apply_blocks_without_preview(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert payload["errors"] == [f"preview is required before apply: cambrian evolve preview {proposal_id} --json"]
    assert harness_path.read_text(encoding="utf-8") == harness_before


def test_evolve_apply_blocks_tampered_proposal_after_preview(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    proposal_path = tmp_path / ".cambrian" / "evolution" / "proposals" / f"{proposal_id}.yaml"
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    proposal["summary"] = "tampered after preview"
    proposal_path.write_text(yaml.safe_dump(proposal, allow_unicode=True, sort_keys=False), encoding="utf-8")
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert payload["errors"] == ["preview proposal digest mismatch"]
    assert harness_path.read_text(encoding="utf-8") == harness_before


def test_evolve_apply_blocks_tampered_preview_after_digest_lock(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    preview_path = tmp_path / preview_payload["preview_ref"]
    preview_record = yaml.safe_load(preview_path.read_text(encoding="utf-8"))
    preview_record["risk"] = "tampered_after_preview"
    preview_path.write_text(yaml.safe_dump(preview_record, allow_unicode=True, sort_keys=False), encoding="utf-8")
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert payload["errors"] == ["preview digest mismatch"]
    assert harness_path.read_text(encoding="utf-8") == harness_before


def test_evolve_apply_blocks_missing_preview_digest_lock(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    (tmp_path / preview_payload["preview_digest_ref"]).unlink()
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert payload["errors"] == ["preview digest lock is required before apply"]
    assert harness_path.read_text(encoding="utf-8") == harness_before


def test_evolve_apply_blocks_tampered_preview_digest_lock(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    digest_path = tmp_path / preview_payload["preview_digest_ref"]
    digest_lock = yaml.safe_load(digest_path.read_text(encoding="utf-8"))
    digest_lock["preview_sha256"] = "0" * 64
    digest_path.write_text(yaml.safe_dump(digest_lock, allow_unicode=True, sort_keys=False), encoding="utf-8")
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert payload["errors"] == ["preview digest mismatch"]
    assert harness_path.read_text(encoding="utf-8") == harness_before


def test_evolve_apply_blocks_insufficient_maturity_after_preview(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert "evolution maturity gate blocked apply: insufficient_data" in payload["errors"][0]


def test_evolve_apply_with_confirm_updates_local_metadata_only(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert ".cambrian/harness.yaml" in payload["changed_files"]
    assert ".cambrian/workforce.yaml" in payload["changed_files"]
    assert any(path.startswith(".cambrian/skills/") for path in payload["changed_files"])
    assert not any(path.startswith("backend/") for path in payload["changed_files"])
    assert payload["preview_ref"] == f".cambrian/evolution/previews/{proposal_id}.yaml"
    assert payload["preview_digest_ref"] == f".cambrian/evolution/previews/{proposal_id}.digest.yaml"
    assert payload["audit_ref"] == f".cambrian/evolution/audit/{proposal_id}.yaml"
    assert payload["rollback_ref"] == f".cambrian/evolution/rollback/{proposal_id}.yaml"
    assert payload["rollback_command"] == f"cambrian evolve rollback {proposal_id} --confirm --json"
    assert payload["next_command"] == f"cambrian evolve rollback {proposal_id} --confirm --json"
    assert payload["backup_refs"]
    assert (tmp_path / ".cambrian" / "evolution" / "applied" / f"{proposal_id}.yaml").exists()
    assert (tmp_path / ".cambrian" / "evolution" / "history.yaml").exists()
    proposal_path = tmp_path / ".cambrian" / "evolution" / "proposals" / f"{proposal_id}.yaml"
    preview_path = tmp_path / payload["preview_ref"]
    preview_digest_path = tmp_path / payload["preview_digest_ref"]
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    decision_ref = proposal["evidence"]["promotion_review_decision_ref"]
    decision_sha256 = proposal["evidence"]["promotion_review_decision_sha256"]
    proposal_sha256 = _sha256(proposal_path)
    preview_sha256 = _sha256(preview_path)
    assert payload["proposal_sha256"] == proposal_sha256
    assert payload["preview_sha256"] == preview_sha256
    digest_lock = yaml.safe_load(preview_digest_path.read_text(encoding="utf-8"))
    assert digest_lock["preview_ref"] == payload["preview_ref"]
    assert digest_lock["preview_sha256"] == preview_sha256
    assert payload["promotion_review_decision_ref"] == decision_ref
    assert payload["promotion_review_decision_sha256"] == decision_sha256
    applied_record = yaml.safe_load(
        (tmp_path / ".cambrian" / "evolution" / "applied" / f"{proposal_id}.yaml").read_text(encoding="utf-8")
    )
    audit = yaml.safe_load((tmp_path / payload["audit_ref"]).read_text(encoding="utf-8"))
    rollback = yaml.safe_load((tmp_path / payload["rollback_ref"]).read_text(encoding="utf-8"))
    history = yaml.safe_load((tmp_path / ".cambrian" / "evolution" / "history.yaml").read_text(encoding="utf-8"))
    assert audit["proposal_id"] == proposal_id
    assert audit["preview_ref"] == payload["preview_ref"]
    assert audit["preview_digest_ref"] == payload["preview_digest_ref"]
    assert audit["proposal_sha256"] == proposal_sha256
    assert audit["preview_sha256"] == preview_sha256
    assert audit["safety"]["source_code_modified"] is False
    assert audit["promotion_review_decision"]["ref"] == decision_ref
    assert audit["promotion_review_decision"]["sha256"] == decision_sha256
    assert audit["file_changes"]
    assert all(item["before_sha256"] for item in audit["file_changes"])
    assert all(item["after_sha256"] for item in audit["file_changes"])
    assert all(item["backup_sha256"] for item in audit["file_changes"])
    assert rollback["status"] == "manual_rollback_available"
    assert rollback["automatic_rollback_command"] is None
    assert rollback["rollback_command"] == f"cambrian evolve rollback {proposal_id} --confirm --json"
    assert all(item["backup_sha256"] for item in rollback["files"])
    assert rollback["proposal_sha256"] == proposal_sha256
    assert rollback["preview_ref"] == payload["preview_ref"]
    assert rollback["preview_digest_ref"] == payload["preview_digest_ref"]
    assert rollback["preview_sha256"] == preview_sha256
    assert rollback["promotion_review_decision"]["ref"] == decision_ref
    assert rollback["promotion_review_decision"]["sha256"] == decision_sha256
    assert applied_record["proposal_sha256"] == proposal_sha256
    assert applied_record["preview_digest_ref"] == payload["preview_digest_ref"]
    assert applied_record["preview_sha256"] == preview_sha256
    assert applied_record["promotion_review_decision"]["ref"] == decision_ref
    assert applied_record["promotion_review_decision"]["sha256"] == decision_sha256
    assert history["applied"][-1]["audit_ref"] == payload["audit_ref"]
    assert history["applied"][-1]["preview_ref"] == payload["preview_ref"]
    assert history["applied"][-1]["preview_digest_ref"] == payload["preview_digest_ref"]
    assert history["applied"][-1]["proposal_sha256"] == proposal_sha256
    assert history["applied"][-1]["preview_sha256"] == preview_sha256
    assert history["applied"][-1]["rollback_ref"] == payload["rollback_ref"]
    assert history["applied"][-1]["promotion_review_decision"]["ref"] == decision_ref
    assert history["applied"][-1]["promotion_review_decision"]["sha256"] == decision_sha256


def test_evolve_apply_blocks_pass_proposal_without_review_decision(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    mark_latest_validation_evidence_passed(tmp_path, validation)
    complete = run_cli(
        tmp_path,
        "job",
        "complete",
        "latest",
        "--outcome",
        "success",
        "--notes",
        "manual validation passed",
        "--json",
    )
    assert complete.returncode == 0, complete.stderr
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    assert proposed.returncode == 0, proposed.stderr
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    decision_path = tmp_path / ".cambrian" / "evolution" / "review_decisions" / "latest_promotion_review.yaml"
    decision_path.unlink()

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert "promotion review decision not found" in payload["errors"][0]


def test_evolve_apply_blocks_tampered_review_decision_digest(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    mark_latest_validation_evidence_passed(tmp_path, validation)
    complete = run_cli(
        tmp_path,
        "job",
        "complete",
        "latest",
        "--outcome",
        "success",
        "--notes",
        "manual validation passed",
        "--json",
    )
    assert complete.returncode == 0, complete.stderr
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    assert proposed.returncode == 0, proposed.stderr
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    decision_path = tmp_path / ".cambrian" / "evolution" / "review_decisions" / "latest_promotion_review.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision["auto_promote"] = True
    decision_path.write_text(yaml.safe_dump(decision, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["changed_files"] == []
    assert payload["errors"] == ["promotion review decision digest mismatch"]


def test_evolve_rollback_requires_confirm_and_restores_metadata(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    applied = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")
    assert applied.returncode == 0, applied.stderr
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["rollback_manifest_sha256"]
    assert harness_path.read_text(encoding="utf-8") != harness_before

    blocked = run_cli(tmp_path, "evolve", "rollback", proposal_id, "--json")
    assert blocked.returncode == 1
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["ok"] is False
    assert blocked_payload["error"] == "confirmation_required"
    assert blocked_payload["restored_files"] == []
    assert blocked_payload["next_command"] == f"cambrian evolve rollback {proposal_id} --confirm --json"

    result = run_cli(tmp_path, "evolve", "rollback", proposal_id, "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "rolled_back"
    assert payload["next_command"] == "cambrian evolve review --recent 5 --json"
    assert ".cambrian/harness.yaml" in payload["restored_files"]
    assert not any(path.startswith("backend/") for path in payload["restored_files"])
    assert payload["rollback_ref"] == f".cambrian/evolution/rollback/{proposal_id}.yaml"
    assert payload["rollback_applied_ref"] == f".cambrian/evolution/rollback/applied/{proposal_id}.yaml"
    assert payload["audit_ref"] == applied_payload["audit_ref"]
    assert payload["preview_ref"] == applied_payload["preview_ref"]
    assert payload["preview_digest_ref"] == applied_payload["preview_digest_ref"]
    assert payload["proposal_sha256"] == applied_payload["proposal_sha256"]
    assert payload["preview_sha256"] == applied_payload["preview_sha256"]
    assert payload["rollback_manifest_sha256"] == applied_payload["rollback_manifest_sha256"]
    assert payload["promotion_review_decision_ref"] == applied_payload["promotion_review_decision_ref"]
    assert payload["promotion_review_decision_sha256"] == applied_payload["promotion_review_decision_sha256"]
    assert harness_path.read_text(encoding="utf-8") == harness_before
    rollback_manifest = yaml.safe_load((tmp_path / payload["rollback_ref"]).read_text(encoding="utf-8"))
    rollback_record = yaml.safe_load((tmp_path / payload["rollback_applied_ref"]).read_text(encoding="utf-8"))
    history = yaml.safe_load((tmp_path / ".cambrian" / "evolution" / "history.yaml").read_text(encoding="utf-8"))
    assert rollback_manifest["audit_ref"] == applied_payload["audit_ref"]
    assert rollback_manifest["preview_ref"] == applied_payload["preview_ref"]
    assert rollback_manifest["preview_digest_ref"] == applied_payload["preview_digest_ref"]
    assert rollback_manifest["proposal_sha256"] == applied_payload["proposal_sha256"]
    assert rollback_manifest["preview_sha256"] == applied_payload["preview_sha256"]
    assert rollback_manifest["promotion_review_decision"]["ref"] == applied_payload["promotion_review_decision_ref"]
    assert rollback_manifest["promotion_review_decision"]["sha256"] == applied_payload["promotion_review_decision_sha256"]
    assert rollback_record["audit_ref"] == applied_payload["audit_ref"]
    assert rollback_record["preview_ref"] == applied_payload["preview_ref"]
    assert rollback_record["preview_digest_ref"] == applied_payload["preview_digest_ref"]
    assert rollback_record["proposal_sha256"] == applied_payload["proposal_sha256"]
    assert rollback_record["preview_sha256"] == applied_payload["preview_sha256"]
    assert rollback_record["rollback_manifest_sha256"] == applied_payload["rollback_manifest_sha256"]
    assert rollback_record["promotion_review_decision"]["ref"] == applied_payload["promotion_review_decision_ref"]
    assert rollback_record["promotion_review_decision"]["sha256"] == applied_payload["promotion_review_decision_sha256"]
    assert rollback_record["safety"]["source_code_modified"] is False
    assert rollback_record["restored_files"] == payload["restored_files"]
    assert history["rollbacks"][-1]["proposal_id"] == proposal_id
    assert history["rollbacks"][-1]["rollback_applied_ref"] == payload["rollback_applied_ref"]
    assert history["rollbacks"][-1]["audit_ref"] == applied_payload["audit_ref"]
    assert history["rollbacks"][-1]["preview_ref"] == applied_payload["preview_ref"]
    assert history["rollbacks"][-1]["preview_digest_ref"] == applied_payload["preview_digest_ref"]
    assert history["rollbacks"][-1]["proposal_sha256"] == applied_payload["proposal_sha256"]
    assert history["rollbacks"][-1]["preview_sha256"] == applied_payload["preview_sha256"]
    assert history["rollbacks"][-1]["rollback_manifest_sha256"] == applied_payload["rollback_manifest_sha256"]
    assert history["rollbacks"][-1]["promotion_review_decision"]["ref"] == applied_payload["promotion_review_decision_ref"]


def test_evolve_rollback_latest_alias_restores_latest_apply(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    applied = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")
    assert applied.returncode == 0, applied.stderr
    assert harness_path.read_text(encoding="utf-8") != harness_before

    result = run_cli(tmp_path, "evolve", "rollback", "latest", "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["proposal_id"] == proposal_id
    assert payload["rollback_ref"] == f".cambrian/evolution/rollback/{proposal_id}.yaml"
    assert harness_path.read_text(encoding="utf-8") == harness_before


def test_evolve_rollback_skips_tampered_backup_file(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    applied = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")
    assert applied.returncode == 0, applied.stderr
    applied_payload = json.loads(applied.stdout)
    assert harness_path.read_text(encoding="utf-8") != harness_before
    rollback_manifest = yaml.safe_load((tmp_path / applied_payload["rollback_ref"]).read_text(encoding="utf-8"))
    harness_entry = next(item for item in rollback_manifest["files"] if item["path"] == ".cambrian/harness.yaml")
    backup_path = tmp_path / harness_entry["backup_ref"]
    backup_path.write_text("tampered backup\n", encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "rollback", proposal_id, "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "rolled_back"
    assert ".cambrian/harness.yaml" not in payload["restored_files"]
    assert harness_path.read_text(encoding="utf-8") != harness_before
    rollback_record = yaml.safe_load((tmp_path / payload["rollback_applied_ref"]).read_text(encoding="utf-8"))
    assert f"backup sha256 mismatch: {harness_entry['backup_ref']}" in rollback_record["warnings"]


def test_evolve_rollback_blocks_tampered_manifest_digest(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    harness_before = harness_path.read_text(encoding="utf-8")

    applied = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")
    assert applied.returncode == 0, applied.stderr
    harness_after_apply = harness_path.read_text(encoding="utf-8")
    assert harness_after_apply != harness_before
    applied_payload = json.loads(applied.stdout)
    rollback_path = tmp_path / applied_payload["rollback_ref"]
    rollback_manifest = yaml.safe_load(rollback_path.read_text(encoding="utf-8"))
    rollback_manifest["files"][0]["rollback_hint"] = "변조된 rollback hint"
    rollback_path.write_text(yaml.safe_dump(rollback_manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "rollback", proposal_id, "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["restored_files"] == []
    assert payload["errors"] == ["rollback manifest digest mismatch"]
    assert harness_path.read_text(encoding="utf-8") == harness_after_apply


def test_evolution_apply_audit_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "23_EVOLUTION_APPLY_AUDIT_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian evolve apply",
        "preview_ref",
        "preview_digest_ref",
        "proposal_sha256",
        "preview_sha256",
        "audit_ref",
        "rollback_ref",
        "backup_refs",
        "backup_sha256",
        ".cambrian/evolution/audit",
        ".cambrian/evolution/rollback",
        "source code를 수정하지 않는다",
        "승격 검토 decision artifact",
        "promotion_review_decision_ref",
        "promotion_review_decision_sha256",
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
        "cambrian evolve rollback latest",
        "rollback_command",
        "next_command",
        "rollback_applied_ref",
        "restored_files",
        "audit_ref",
        "preview_ref",
        "preview_digest_ref",
        "proposal_sha256",
        "preview_sha256",
        "backup_sha256",
        "rollback_manifest_sha256",
        "promotion_review_decision_ref",
        ".cambrian/evolution/rollback/applied",
        "source code를 수정하지 않는다",
        "`--confirm` 없이는 복원하지 않는다",
    ]:
        assert phrase in text
    assert "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md" in readme
    assert "24_EVOLUTION_ROLLBACK_CONTRACT.md" in index
