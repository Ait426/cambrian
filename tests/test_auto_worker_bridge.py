from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_harness_engineer_design import pass_engineering_gate, prepare_engineering_project, run_cli


def _prepare_auto_worker_bridge(tmp_path: Path) -> dict:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    assert run_cli(tmp_path, "harness", "install", "--confirm", "--json").returncode == 0
    assert run_cli(tmp_path, "authority", "grant", "--mode", "full-authority", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "init", "--goal", "외부 AI 워커 브리지 골드패스 검증", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_auto_task_bridge_packet_contains_provider_neutral_worker_context(tmp_path: Path) -> None:
    payload = _prepare_auto_worker_bridge(tmp_path)
    task = yaml.safe_load((tmp_path / payload["task_refs"][0]).read_text(encoding="utf-8"))
    packet = yaml.safe_load((tmp_path / payload["packet_refs"][0]).read_text(encoding="utf-8"))

    job_bridge = task["job_bridge"]
    worker_bridge = packet["execution_contract"]["auto_worker_bridge"]

    assert job_bridge["status"] == "linked"
    assert packet["auto_step_result_contract"] == task["result_contract"]
    assert packet["execution_contract"]["auto_step_result_contract"] == task["result_contract"]
    assert worker_bridge["result_contract"] == task["result_contract"]
    assert worker_bridge["mission_context"]["final_goal"] == "외부 AI 워커 브리지 골드패스 검증"
    assert worker_bridge["mission_context"]["mission_ref"] == ".cambrian/auto/mission.yaml"
    assert worker_bridge["worker_context"]["owner"] == task["owner"]
    assert worker_bridge["worker_context"]["selected_agents"] == job_bridge["selected_agents"]
    assert worker_bridge["worker_context"]["selected_skills"] == job_bridge["selected_skills"]
    assert worker_bridge["evidence_context"]["evidence_paths"]
    assert worker_bridge["risk_boundaries"]["task_safety"]["requires_result_ingest"] is True
    assert worker_bridge["validation"]["result_intake_required"] is True
    assert "cambrian auto step ingest" in worker_bridge["validation"]["ingest_command"]
    assert worker_bridge["provider_adapter"]["provider_identity"] == "external_ai_worker"
    assert worker_bridge["provider_adapter"]["provider_lock_in"] is False
    assert {"codex", "claude", "gpt", "cursor"}.issubset(set(worker_bridge["provider_adapter"]["supported_providers"]))
    assert worker_bridge["contract_alignment"]["contracts_match"] is True
    assert job_bridge["contract_alignment"]["packet_result_contract_sha256"] == job_bridge["result_contract_sha256"]

    directive = (tmp_path / payload["directive_refs"][0]).read_text(encoding="utf-8")
    assert "provider_identity: external_ai_worker" in directive
    assert "contracts_match: True" in directive


def test_auto_task_bridge_rejects_reply_without_auto_result_contract(tmp_path: Path) -> None:
    payload = _prepare_auto_worker_bridge(tmp_path)
    task_ref = payload["task_refs"][0]
    bad_result = tmp_path / "bad_auto_worker_result.yaml"
    bad_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "계약을 일부러 빠뜨린 외부 AI 응답",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["role_outputs 누락"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(bad_result), "--json")

    assert result.returncode != 0
    rejection = json.loads(result.stdout)
    assert rejection["ok"] is False
    assert rejection["error"] == "invalid_result_contract"
    assert "role_outputs must be a mapping" in "\n".join(rejection["errors"])
    assert rejection["source_code_modified"] is False
    assert rejection["provider_api_called"] is False
