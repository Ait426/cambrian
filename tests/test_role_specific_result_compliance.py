from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def _create_task(tmp_path: Path, max_steps: int = 1) -> tuple[str, dict]:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    result = run_cli(tmp_path, "auto", "run", "--max-steps", str(max_steps), "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    task_ref = str(payload["task_refs"][max_steps - 1])
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    return task_ref, task


def _base_success_payload() -> dict:
    return {
        "status": "success",
        "summary": "역할별 결과를 제출했다.",
        "changed_files": [],
        "tests": [{"command": "python -m pytest", "status": "passed"}],
        "blockers": [],
        "next_action": "cambrian auto report --json",
        "evidence": {"notes": ["검증 완료"], "artifacts": []},
    }


def test_success_result_requires_role_outputs(tmp_path: Path) -> None:
    task_ref, task = _create_task(tmp_path, max_steps=1)
    result_file = tmp_path / "missing_role_outputs.yaml"
    result_file.write_text(yaml.safe_dump(_base_success_payload(), allow_unicode=True, sort_keys=False), encoding="utf-8")

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 1
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_result_contract"
    assert f"role_outputs must be a mapping for {task['owner']}" in payload["errors"]
    assert payload["role_compliance"]["ok"] is False
    assert payload["role_compliance"]["required_role_output_keys"] == ["scope", "acceptance_criteria", "test_plan"]


def test_success_result_requires_each_role_output_key(tmp_path: Path) -> None:
    task_ref, _task = _create_task(tmp_path, max_steps=3)
    result_payload = _base_success_payload()
    result_payload["role_outputs"] = {
        "implementation_plan": "구현 계획",
        "changed_files": ["engine/project_auto_mode.py"],
    }
    result_file = tmp_path / "missing_engineering_key.yaml"
    result_file.write_text(yaml.safe_dump(result_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 1
    payload = json.loads(ingest.stdout)
    assert payload["error"] == "invalid_result_contract"
    assert "role_outputs.rollback_hint is required for engineering-agent" in payload["errors"]


def test_blocked_result_can_be_ingested_without_role_outputs(tmp_path: Path) -> None:
    task_ref, _task = _create_task(tmp_path, max_steps=1)
    result_file = tmp_path / "blocked_without_role_outputs.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "검증 단계에서 막혔다.",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["테스트 실패"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["실패 증거"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["status"] == "blocked"
    assert payload["role_compliance"]["ok"] is True


def test_valid_role_outputs_are_recorded(tmp_path: Path) -> None:
    task_ref, _task = _create_task(tmp_path, max_steps=1)
    result_payload = _base_success_payload()
    result_payload["role_outputs"] = {
        "scope": "auto task result compliance",
        "acceptance_criteria": ["role outputs accepted"],
        "test_plan": ["python -m pytest tests/test_role_specific_result_compliance.py"],
    }
    result_file = tmp_path / "valid_role_outputs.yaml"
    result_file.write_text(yaml.safe_dump(result_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is True
    assert payload["role_compliance"]["ok"] is True
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["result_role_outputs"]["scope"] == "auto task result compliance"
    result_record = yaml.safe_load((tmp_path / payload["result_ref"]).read_text(encoding="utf-8"))
    assert result_record["role_outputs"]["test_plan"]
    assert result_record["role_compliance"]["required_role_output_keys"] == ["scope", "acceptance_criteria", "test_plan"]


def test_role_specific_result_compliance_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "role_outputs",
        "pm-agent",
        "engineering-agent",
        "invalid_result_contract",
    ]:
        assert phrase in text
    assert "docs/product/35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md" in readme
    assert "35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md" in index
