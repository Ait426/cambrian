from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


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


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _install_sample_contract(root: Path) -> None:
    _write_yaml(
        root / ".cambrian" / "harness.yaml",
        {
            "schema_version": "1.0.0",
            "id": "custom-ave-ddmq-stage_pipeline",
            "type": "custom",
            "language": "python",
            "test_framework": "pytest",
            "policy": {"change_mode": "proposal_only"},
            "important_paths": ["avf.py", "core/ddmq.py", "tests/test_ddmq.py"],
            "domain_spec": {
                "task_description": "AVF DDMQ stage pipeline",
                "validation_commands": ["python -m pytest tests/ -v"],
            },
            "codebase_evidence": {
                "status": "strong",
                "existing_important_paths": ["avf.py", "core/ddmq.py", "tests/test_ddmq.py"],
                "missing_important_paths": [],
            },
            "evaluator_contract": {
                "validation_commands": ["python -m pytest tests/ -v"],
                "success_criteria": ["pytest passes"],
            },
        },
    )
    _write_yaml(
        root / ".cambrian" / "validation.yaml",
        {
            "schema_version": "1.0.0",
            "validation": {"test_commands": ["python -m pytest tests/ -v"]},
        },
    )
    _write_yaml(
        root / ".cambrian" / "agents.yaml",
        {
            "schema_version": "1.0.0",
            "agents": [{"id": "ddmq-debugger"}, {"id": "stage-schema-validator"}],
        },
    )


def _install_ready_product_boardroom(root: Path) -> None:
    install = run_cli(
        root,
        "company",
        "boardroom",
        "install",
        "--goal",
        "Keep product direction ready for the mission scheduler",
        "--json",
    )
    assert install.returncode == 0, install.stderr
    convene = run_cli(
        root,
        "company",
        "boardroom",
        "convene",
        "--topic",
        "mission scheduler readiness",
        "--json",
    )
    assert convene.returncode == 0, convene.stderr
    _write_yaml(
        root / "ai_boardroom_reply.yaml",
        {
            "role_views": {
                "ceo-agent": {
                    "ai_agent": True,
                    "turn_authorship": "ai_agent",
                    "position": "Keep one user-visible trust proof ahead of automation expansion.",
                    "decision": "Use a verified boardroom packet before each mission job.",
                    "evidence_refs": [".cambrian/mission.yaml"],
                    "assumptions": [],
                    "risks": ["A non-AI boardroom would repeat static metadata."],
                    "next_constraint": "Do not run more than one mission job before validation.",
                },
                "cto-agent": {
                    "ai_agent": True,
                    "turn_authorship": "ai_agent",
                    "position": "The boardroom must ingest AI-authored turns before ready_for_mission.",
                    "decision": "Block scheduler readiness when AI turn provenance is missing.",
                    "evidence_refs": [".cambrian/company/product_boardroom/agents.yaml"],
                    "assumptions": [],
                    "risks": ["Template decisions can mask weak technical judgment."],
                    "next_constraint": "Require validation evidence after the mission job.",
                },
                "coo-agent": {
                    "ai_agent": True,
                    "turn_authorship": "ai_agent",
                    "position": "The next operation must be a bounded job with a stop condition.",
                    "decision": "Open exactly one mission job and stop for evidence ingest.",
                    "evidence_refs": [".cambrian/company/product_boardroom/latest_ai_request.yaml"],
                    "assumptions": [],
                    "risks": ["The loop can overrun if it opens multiple jobs."],
                    "next_constraint": "Stop after one linked job packet.",
                },
            },
            "consensus": {
                "decision": "Proceed only with verified CEO/CTO/COO AI agent turns.",
                "scope": "No source mutation or external side effects.",
                "recommended_next_mission": "Open one bounded mission job and validate before sync.",
            },
        },
    )
    ingest = run_cli(root, "company", "boardroom", "ingest", "ai_boardroom_reply.yaml", "--json")
    assert ingest.returncode == 0, ingest.stderr


def test_mission_install_creates_bounded_24h_company_state(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)

    result = run_cli(tmp_path, "mission", "install", "--goal", "Ship Cambrian to external users", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "installed"
    assert payload["loop_kind"] == "bounded_24h_company"
    assert payload["project_contract"]["harness_id"] == "custom-ave-ddmq-stage_pipeline"
    assert payload["project_contract"]["validation_commands"] == ["python -m pytest tests/ -v"]
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["provider_api_called_by_cambrian"] is False
    assert payload["next_command"] == "cambrian mission run --max-steps 1 --json"

    mission = yaml.safe_load((tmp_path / ".cambrian" / "mission.yaml").read_text(encoding="utf-8"))
    assert mission["status"] == "active"
    assert mission["company_roles"][0]["id"] == "ceo"
    assert any(gate["id"] == "deploy" for gate in mission["hard_gates"])


def test_mission_run_creates_worker_directive_with_evidence_gate(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0

    result = run_cli(tmp_path, "mission", "run", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "waiting_for_ai_worker"
    assert payload["executed_steps"] == 0
    assert payload["created_directives"] == 1
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["provider_api_called_by_cambrian"] is False
    task_ref = payload["task_refs"][0]
    assert task_ref.startswith(".cambrian/mission/tasks/mission-step-")

    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    directive = task["worker_directive"]
    assert directive["bounded_scope"]["source_apply_requires_confirm"] is True
    assert "codebase_evidence_path_citation" in directive["required_evidence_envelope"]
    assert "validation_command_selection" in directive["required_evidence_envelope"]
    assert directive["validation_commands"] == ["python -m pytest tests/ -v"]
    assert any(gate["id"] == "public_release" for gate in directive["hard_gates"])

    status = run_cli(tmp_path, "mission", "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["run_count"] == 1
    assert status_payload["last_task_ref"] == task_ref


def test_mission_install_uses_project_fallback_before_harness_exists(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"sample\"\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Sample\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    result = run_cli(tmp_path, "mission", "install", "--goal", "Create a release-ready product", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    contract = payload["project_contract"]
    assert contract["contract_source"] == "project_fallback"
    assert contract["validation_commands"] == ["python -m pytest -q"]
    assert "pyproject.toml" in contract["important_paths"]
    assert "tests" in contract["important_paths"]


def test_mission_run_start_job_links_directive_to_custom_job(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0

    result = run_cli(tmp_path, "mission", "run", "--max-steps", "1", "--start-job", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "waiting_for_ai_reply"
    assert payload["linked_jobs"][0]["status"] == "created"
    assert payload["linked_jobs"][0]["job_ref"].startswith(".cambrian/packs/jobs/")
    assert payload["linked_jobs"][0]["packet_ref"].startswith(".cambrian/bridge/packets/")
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["provider_api_called_by_cambrian"] is False

    task = yaml.safe_load((tmp_path / payload["task_refs"][0]).read_text(encoding="utf-8"))
    assert task["linked_job"]["job_ref"] == payload["linked_jobs"][0]["job_ref"]
    assert "[mission:" in task["linked_job"]["request"]
    job = yaml.safe_load((tmp_path / payload["linked_jobs"][0]["job_ref"]).read_text(encoding="utf-8"))
    assert job["entry_mode"] == "mission"
    assert job["status"] == "waiting_for_ai_reply"

    status = run_cli(tmp_path, "mission", "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["last_job_ref"] == payload["linked_jobs"][0]["job_ref"]


def test_mission_run_start_job_blocks_without_custom_harness(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"sample\"\n", encoding="utf-8")
    assert run_cli(tmp_path, "mission", "install", "--goal", "Create a release-ready product", "--json").returncode == 0

    result = run_cli(tmp_path, "mission", "run", "--start-job", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["blocked_job_starts"][0]["reason"] == "custom harness is not installed"
    assert payload["blocked_job_starts"][0]["next_command"] == "cambrian harness engineer design --json"


def test_mission_sync_absorbs_latest_job_outcome(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    run = run_cli(tmp_path, "mission", "run", "--start-job", "--json")
    assert run.returncode == 0, run.stderr
    linked_job = json.loads(run.stdout)["linked_jobs"][0]
    outcomes_path = tmp_path / ".cambrian" / "evidence" / "outcomes.yaml"
    _write_yaml(
        outcomes_path,
        {
            "schema_version": "1.0.0",
            "outcomes": [
                {
                    "recorded_at": "2026-05-21T00:00:00+00:00",
                    "job_id": linked_job["job_id"],
                    "job_ref": linked_job["job_ref"],
                    "outcome": "success",
                    "trust_gate_status": "verified",
                    "validation_contract_status": "passed",
                    "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
                    "validation_commands": ["python -m pytest tests/ -v"],
                    "unchecked_items": [],
                    "evaluator_verdict": {
                        "verdict": "pass",
                        "verdict_reason": "manual_outcome_success_with_verified_evidence",
                        "promotion_readiness": "review_ready",
                    },
                }
            ],
        },
    )

    result = run_cli(tmp_path, "mission", "sync", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "synced"
    assert payload["last_outcome"]["job_id"] == linked_job["job_id"]
    assert payload["last_outcome"]["verdict"] == "pass"
    assert payload["next_command"] == "cambrian mission run --max-steps 1 --start-job --json"
    mission = yaml.safe_load((tmp_path / ".cambrian" / "mission.yaml").read_text(encoding="utf-8"))
    assert mission["last_outcome"]["trust_gate_status"] == "verified"
    assert mission["synced_outcome_keys"]

    second = run_cli(tmp_path, "mission", "sync", "--json")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["status"] == "up_to_date"


def test_mission_sync_ignores_unlinked_old_outcome(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    _write_yaml(
        tmp_path / ".cambrian" / "evidence" / "outcomes.yaml",
        {
            "schema_version": "1.0.0",
            "outcomes": [
                {
                    "recorded_at": "2026-05-01T00:00:00+00:00",
                    "job_id": "old-job",
                    "job_ref": ".cambrian/packs/jobs/old-job.yaml",
                    "outcome": "failed",
                    "evaluator_verdict": {"verdict": "rollback"},
                }
            ],
        },
    )

    result = run_cli(tmp_path, "mission", "sync", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "no_outcome"
    mission = yaml.safe_load((tmp_path / ".cambrian" / "mission.yaml").read_text(encoding="utf-8"))
    assert "last_outcome" not in mission


def test_mission_sync_clears_stale_unlinked_outcome(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    mission_path = tmp_path / ".cambrian" / "mission.yaml"
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    mission["last_outcome"] = {"job_id": "old-job", "verdict": "rollback"}
    mission_path.write_text(yaml.safe_dump(mission, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "mission", "sync", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "no_outcome"
    assert payload["cleared_stale_outcome"] is True
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    assert "last_outcome" not in mission


def test_mission_operator_blocks_scheduler_while_job_waits_for_ai_reply(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    assert run_cli(tmp_path, "mission", "run", "--start-job", "--json").returncode == 0

    result = run_cli(tmp_path, "mission", "operator", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "waiting_for_ai_reply"
    assert payload["scheduler_readiness"]["safe_to_schedule"] is False
    assert payload["tick_contract"]["max_mission_jobs_per_tick"] == 1
    assert payload["tick_contract"]["must_not_fabricate_ai_reply"] is True
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["provider_api_called_by_cambrian"] is False
    assert "evidence envelope" in payload["blockers"][0]


def test_mission_operator_reports_scheduler_ready_after_three_verified_cycles(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    run = run_cli(tmp_path, "mission", "run", "--start-job", "--json")
    assert run.returncode == 0, run.stderr
    linked_job = json.loads(run.stdout)["linked_jobs"][0]
    _write_yaml(
        tmp_path / ".cambrian" / "evidence" / "outcomes.yaml",
        {
            "schema_version": "1.0.0",
            "outcomes": [
                {
                    "recorded_at": "2026-05-21T00:00:00+00:00",
                    "job_id": linked_job["job_id"],
                    "job_ref": linked_job["job_ref"],
                    "outcome": "success",
                    "trust_gate_status": "verified",
                    "validation_contract_status": "commands_executed",
                    "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
                    "validation_commands": ["python -m pytest tests/ -v"],
                    "unchecked_items": [],
                    "evaluator_verdict": {"verdict": "pass"},
                }
            ],
        },
    )
    assert run_cli(tmp_path, "mission", "sync", "--json").returncode == 0
    mission_path = tmp_path / ".cambrian" / "mission.yaml"
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    mission["run_count"] = 3
    mission_path.write_text(yaml.safe_dump(mission, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _install_ready_product_boardroom(tmp_path)

    result = run_cli(tmp_path, "mission", "operator", "--save", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "operator_ready"
    assert payload["scheduler_readiness"]["safe_to_schedule"] is True
    assert payload["scheduler_readiness"]["product_boardroom_ready"] is True
    assert payload["scheduler_readiness"]["recommended_tick_command"] == "cambrian mission run --max-steps 1 --start-job --json"
    assert payload["tick_contract"]["requires_product_boardroom_ready"] is True
    assert payload["product_boardroom_gate"]["ready"] is True
    assert payload["operator_ref"] == ".cambrian/mission/operator.yaml"
    assert (tmp_path / ".cambrian" / "mission" / "operator.yaml").exists()


def test_mission_operator_requires_product_boardroom_before_scheduler_ready(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    run = run_cli(tmp_path, "mission", "run", "--start-job", "--json")
    assert run.returncode == 0, run.stderr
    linked_job = json.loads(run.stdout)["linked_jobs"][0]
    _write_yaml(
        tmp_path / ".cambrian" / "evidence" / "outcomes.yaml",
        {
            "schema_version": "1.0.0",
            "outcomes": [
                {
                    "recorded_at": "2026-05-21T00:00:00+00:00",
                    "job_id": linked_job["job_id"],
                    "job_ref": linked_job["job_ref"],
                    "outcome": "success",
                    "trust_gate_status": "verified",
                    "validation_contract_status": "commands_executed",
                    "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
                    "validation_commands": ["python -m pytest tests/ -v"],
                    "unchecked_items": [],
                    "evaluator_verdict": {"verdict": "pass"},
                }
            ],
        },
    )
    assert run_cli(tmp_path, "mission", "sync", "--json").returncode == 0
    mission_path = tmp_path / ".cambrian" / "mission.yaml"
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    mission["run_count"] = 3
    mission_path.write_text(yaml.safe_dump(mission, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "mission", "operator", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "boardroom_required"
    assert payload["scheduler_readiness"]["safe_to_schedule"] is False
    assert payload["scheduler_readiness"]["product_boardroom_ready"] is False
    assert payload["product_boardroom_gate"]["ready"] is False
    assert "product boardroom" in " ".join(payload["blockers"])
    assert payload["next_command"].startswith("cambrian company boardroom")


def test_mission_operator_allows_verified_sync_without_reconvening_boardroom(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    _install_ready_product_boardroom(tmp_path)
    run = run_cli(tmp_path, "mission", "run", "--start-job", "--json")
    assert run.returncode == 0, run.stderr
    linked_job = json.loads(run.stdout)["linked_jobs"][0]
    _write_yaml(
        tmp_path / ".cambrian" / "evidence" / "outcomes.yaml",
        {
            "schema_version": "1.0.0",
            "outcomes": [
                {
                    "recorded_at": "2026-05-21T00:00:00+00:00",
                    "job_id": linked_job["job_id"],
                    "job_ref": linked_job["job_ref"],
                    "outcome": "success",
                    "trust_gate_status": "verified",
                    "validation_contract_status": "commands_executed",
                    "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
                    "validation_commands": ["python -m pytest tests/ -v"],
                    "unchecked_items": [],
                    "evaluator_verdict": {"verdict": "pass"},
                }
            ],
        },
    )
    assert run_cli(tmp_path, "mission", "sync", "--json").returncode == 0
    mission_path = tmp_path / ".cambrian" / "mission.yaml"
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    mission["run_count"] = 3
    mission_path.write_text(yaml.safe_dump(mission, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "mission", "operator", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "operator_ready"
    assert payload["scheduler_readiness"]["safe_to_schedule"] is True
    assert payload["product_boardroom_gate"]["ready"] is True
    assert payload["product_boardroom_gate"]["freshness_basis"] == "mission_direction_updated_at"
    assert payload["next_command"] == "cambrian mission run --max-steps 1 --start-job --json"


def test_mission_operator_requires_fresh_product_boardroom_when_direction_changes(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    _install_ready_product_boardroom(tmp_path)
    mission_path = tmp_path / ".cambrian" / "mission.yaml"
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    mission["run_count"] = 3
    mission["last_outcome"] = {
        "job_id": "job-direction-change",
        "job_ref": ".cambrian/packs/jobs/job-direction-change.yaml",
        "outcome": "success",
        "verdict": "pass",
        "trust_gate_status": "verified",
        "validation_contract_status": "commands_executed",
        "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
        "outcomes_ref": ".cambrian/evidence/outcomes.yaml",
        "unchecked_count": 0,
        "validation_commands": ["python -m pytest tests/ -v"],
    }
    mission["next_action"] = "cambrian mission run --max-steps 1 --start-job --json"
    mission["direction_updated_at"] = "2999-01-01T00:00:00+00:00"
    mission_path.write_text(yaml.safe_dump(mission, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "mission", "operator", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "boardroom_required"
    assert payload["scheduler_readiness"]["safe_to_schedule"] is False
    assert payload["product_boardroom_gate"]["ready"] is False
    assert "older than mission direction" in " ".join(payload["blockers"])
    assert payload["product_boardroom_gate"]["freshness_basis"] == "mission_direction_updated_at"
    assert payload["next_command"] == 'cambrian company boardroom convene --topic "next product decision" --json'


def test_mission_tick_skips_when_latest_job_is_waiting_for_ai_reply(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    assert run_cli(tmp_path, "mission", "run", "--start-job", "--json").returncode == 0

    result = run_cli(tmp_path, "mission", "tick", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "tick_skipped"
    assert payload["operator_status"] == "waiting_for_ai_reply"
    assert payload["opened_job"] is None
    assert payload["next_command"] == "cambrian job ingest latest ai_reply_patch_candidate.yaml --json"
    mission = yaml.safe_load((tmp_path / ".cambrian" / "mission.yaml").read_text(encoding="utf-8"))
    assert mission["run_count"] == 1


def test_mission_tick_starts_one_job_when_operator_is_ready(tmp_path: Path) -> None:
    _install_sample_contract(tmp_path)
    assert run_cli(tmp_path, "mission", "install", "--goal", "Finish product release path", "--json").returncode == 0
    run = run_cli(tmp_path, "mission", "run", "--start-job", "--json")
    assert run.returncode == 0, run.stderr
    linked_job = json.loads(run.stdout)["linked_jobs"][0]
    _write_yaml(
        tmp_path / ".cambrian" / "evidence" / "outcomes.yaml",
        {
            "schema_version": "1.0.0",
            "outcomes": [
                {
                    "recorded_at": "2026-05-21T00:00:00+00:00",
                    "job_id": linked_job["job_id"],
                    "job_ref": linked_job["job_ref"],
                    "outcome": "success",
                    "trust_gate_status": "verified",
                    "validation_contract_status": "commands_executed",
                    "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
                    "validation_commands": ["python -m pytest tests/ -v"],
                    "unchecked_items": [],
                    "evaluator_verdict": {"verdict": "pass"},
                }
            ],
        },
    )
    assert run_cli(tmp_path, "mission", "sync", "--json").returncode == 0
    mission_path = tmp_path / ".cambrian" / "mission.yaml"
    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    mission["run_count"] = 3
    mission_path.write_text(yaml.safe_dump(mission, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _install_ready_product_boardroom(tmp_path)

    result = run_cli(tmp_path, "mission", "tick", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "tick_started_job"
    assert payload["operator_status"] == "operator_ready"
    assert payload["run_count"] == 4
    assert payload["opened_job"]["status"] == "created"
    assert payload["opened_job"]["job_ref"].startswith(".cambrian/packs/jobs/")
    assert payload["next_command"] == "cambrian job ingest latest ai_reply_patch_candidate.yaml --json"
    assert payload["tick_contract"]["max_mission_jobs_per_tick"] == 1
    assert payload["tick_contract"]["requires_product_boardroom_ready"] is True
    assert payload["product_boardroom_gate"]["ready"] is True
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["provider_api_called_by_cambrian"] is False
