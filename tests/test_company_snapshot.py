from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.project_auto_mode import generate_company_snapshot, validate_company_snapshot
from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import run_cli


def _seed_company_runtime(project_root: Path) -> None:
    prepare_auto(project_root)
    assert run_cli(project_root, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(project_root, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(project_root, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    task = yaml.safe_load((project_root / task_ref).read_text(encoding="utf-8"))
    result_file = project_root / "snapshot_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "snapshot seed result with private marker excluded",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated summary only"], "artifacts": []},
                "role_outputs": {
                    key: f"{key} evidence"
                    for key in task["result_contract"]["required_role_output_keys"]
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(project_root, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0
    assert run_cli(project_root, "auto", "report", "--json").returncode == 0


def test_company_snapshot_validates_and_includes_proof_lineage(tmp_path: Path) -> None:
    _seed_company_runtime(tmp_path)

    result = generate_company_snapshot(tmp_path)

    assert result["ok"] is True
    snapshot = result["snapshot"]
    assert validate_company_snapshot(snapshot)["status"] == "pass"
    assert snapshot["snapshot_kind"] == "company_snapshot_v0_1"
    assert snapshot["proof_summary"]["raw_runtime_outputs_included"] is False
    assert snapshot["evolution_lineage"]["source_refs"]
    assert snapshot["provenance"]["source_sha256"]
    assert snapshot["marketplace"]["sale_ready"] is False
    assert snapshot["marketplace"]["proof_claim_allowed"] is False
    assert (tmp_path / result["snapshot_ref"]).exists()


def test_company_snapshot_excludes_raw_private_project_data(tmp_path: Path) -> None:
    _seed_company_runtime(tmp_path)
    secret = "sk-test-super-secret-private-marker"
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")
    (tmp_path / "private_notes.md").write_text(f"customer secret: {secret}\n", encoding="utf-8")

    result = generate_company_snapshot(tmp_path)
    dumped = yaml.safe_dump(result["snapshot"], allow_unicode=True, sort_keys=False)

    assert result["snapshot"]["privacy_boundary"]["raw_private_project_data_included"] is False
    assert result["snapshot"]["privacy_boundary"]["source_file_contents_included"] is False
    assert secret not in dumped
    assert "customer secret" not in dumped
    assert "OPENAI_API_KEY" not in dumped


def test_company_snapshot_has_signature_ready_hash(tmp_path: Path) -> None:
    _seed_company_runtime(tmp_path)

    result = generate_company_snapshot(tmp_path)

    assert len(result["body_sha256"]) == 64
    assert result["snapshot"]["provenance"]["signature_ready"] is True
    assert result["snapshot"]["validation"]["checks"]["body_hash_present"] is True


def test_company_snapshot_cli_generates_private_artifact(tmp_path: Path) -> None:
    _seed_company_runtime(tmp_path)

    proc = run_cli(tmp_path, "company", "snapshot", "--json")

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "snapshot_generated"
    assert payload["snapshot"]["validation"]["status"] == "pass"
    assert payload["snapshot"]["privacy_boundary"]["raw_private_project_data_included"] is False
    assert payload["snapshot"]["marketplace"]["sale_ready"] is False
    assert (tmp_path / payload["snapshot_ref"]).exists()
