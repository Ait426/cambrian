from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.project_auto_mode import (
    _skill_knowledge_guidance_for_task,
    record_skill_knowledge_candidate,
    record_worker_performance_event,
    suppress_skill_knowledge_candidate,
)
from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def prepare_plan(tmp_path: Path, *, full_authority: bool = True) -> None:
    if full_authority:
        prepare_auto(tmp_path)
    else:
        assert run_cli(tmp_path, "authority", "init", "--json").returncode == 0
        assert run_cli(tmp_path, "auto", "init", "--goal", "제품을 설치형 RC로 완성", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0


def test_auto_run_respects_max_steps_and_writes_execution_log(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "2", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["authority"] == "full_authority"
    assert payload["max_steps"] == 2
    assert payload["executed_steps"] == 2
    assert payload["blocked_steps"] == []
    assert payload["source_code_modified"] is False

    log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    assert len(log["runs"]) == 1
    assert len(log["runs"][0]["executed_steps"]) == 2
    assert log["runs"][0]["changed_files"] == []


def test_auto_run_creates_codex_task_directives_without_source_changes(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["waiting_for_result"] == 1
    assert payload["task_refs"]
    assert payload["directive_refs"]
    task_path = tmp_path / payload["task_refs"][0]
    directive_path = tmp_path / payload["directive_refs"][0]
    assert task_path.exists()
    assert directive_path.exists()
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    directive = directive_path.read_text(encoding="utf-8")
    assert task["status"] == "waiting_for_result"
    assert task["directive_type"] == "role_specific_auto_task"
    assert task["execution_engine"] == "Codex or Claude"
    assert task["safety"]["source_code_modified_by_auto_run"] is False
    assert "Cambrian Auto Task Directive" in directive
    assert "역할별 작업 지시" in directive
    assert "결과 계약" in directive
    assert "status:" in directive
    assert "evidence:" in directive

    log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    run = log["runs"][0]
    assert run["waiting_for_result"] == 1
    assert run["task_refs"] == payload["task_refs"]
    assert run["directive_refs"] == payload["directive_refs"]
    assert run["executed_steps"][0]["status"] == "waiting_for_result"
    assert run["changed_files"] == []


def test_auto_step_ingest_validates_result_and_updates_task(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    run_payload = json.loads(run_result.stdout)
    task_ref = run_payload["task_refs"][0]
    result_file = tmp_path / "step_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "작업 결과를 검증 가능한 형태로 정리했다.",
                "changed_files": ["docs/product/example.md"],
                "tests": [{"command": "python -m pytest tests/test_example.py", "status": "passed"}],
                "blockers": [],
                "next_action": "auto report로 상태를 확인한다.",
                "evidence": {"notes": ["테스트 통과"], "artifacts": []},
                "role_outputs": {
                    "scope": "문서 예시 변경",
                    "acceptance_criteria": ["테스트 통과"],
                    "test_plan": ["python -m pytest tests/test_example.py"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "validated"
    assert payload["next_state"] == "VALIDATION"
    assert payload["source_code_modified"] is False
    assert (tmp_path / payload["result_ref"]).exists()
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["status"] == "validated"
    assert task["result_ref"] == "step_result.yaml"
    assert task["result_tests"][0]["status"] == "passed"
    log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    assert log["step_results"][-1]["status"] == "validated"
    assert log["step_results"][-1]["source_code_modified_by_ingest"] is False
    assert log["step_results"][-1]["company_verification_record"]["status"] == "verification_recorded"
    assert log["step_results"][-1]["company_context_record"]["status"] == "context_recorded"

    assert payload["company_verification_record"]["status"] == "verification_recorded"
    assert payload["company_context_record"]["status"] == "context_recorded"
    assert payload["company_context_record"]["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"
    saved_result = yaml.safe_load((tmp_path / payload["result_ref"]).read_text(encoding="utf-8"))
    assert saved_result["promotion_policy"]["auto_promote"] is False
    assert saved_result["company_verification_record"]["status"] == "verification_recorded"
    assert saved_result["company_context_record"]["status"] == "context_recorded"

    verification_ledger = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "verification" / "ledger.yaml").read_text(encoding="utf-8")
    )
    assert verification_ledger["entries"][-1]["stage"] == "auto_step_ingest"
    assert verification_ledger["entries"][-1]["job_id"] == payload["task_id"]
    assert verification_ledger["entries"][-1]["validation_commands"] == ["python -m pytest tests/test_example.py"]
    assert verification_ledger["entries"][-1]["promotion_policy"]["auto_promote"] is False

    context_records = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "context" / "records.yaml").read_text(encoding="utf-8")
    )
    assert context_records["records"][-1]["kind"] == "auto_step_result"
    assert context_records["records"][-1]["source"] == payload["task_id"]
    assert context_records["records"][-1]["promotion_status"] == "candidate"
    promotion_review = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "context" / "promotion_review.yaml").read_text(encoding="utf-8")
    )
    assert promotion_review["status"] == "pending_user_review"
    assert promotion_review["review_items"][-1]["approval_state"] == "pending_user_review"
    assert promotion_review["review_items"][-1]["auto_promote"] is False


def test_auto_report_summarizes_validated_step_result(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "validated_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "step complete",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "validated result",
                    "acceptance_criteria": ["report can summarize result"],
                    "test_plan": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")

    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    assert payload["ok"] is True
    summary = payload["report"]["step_results"]
    assert summary["total"] == 1
    assert summary["validated"] == 1
    assert summary["blocked"] == 0
    assert payload["report"]["task_statuses"]["waiting_for_result"] == 0
    assert payload["decision_handoff"]["status"] == "ready_for_release_or_next_plan"
    assert payload["decision_handoff"]["next_command"] == "cambrian auto plan --json"


def test_auto_plan_uses_company_ledger_after_step_ingest(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "validated_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "validated step with company ledger follow-up",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "validated company ledger result",
                    "acceptance_criteria": ["next plan carries company ledger context"],
                    "test_plan": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert boardroom.returncode == 0, boardroom.stderr
    plan_result = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan_result.returncode == 0, plan_result.stderr
    plan_payload = json.loads(plan_result.stdout)
    assert plan_payload["company_ledger_guidance"]["status"] == "available"
    assert plan_payload["company_ledger_guidance"]["candidate_context_count"] >= 1
    assert plan_payload["company_ledger_guidance"]["recent_verification_entries"]
    assert plan_payload["company_ledger_guidance"]["next_step_focus"] == "advance_from_candidate_context"
    assert plan_payload["company_ledger_guidance"]["duplicate_guard"]["requires_new_acceptance_delta"] is True
    assert plan_payload["steps"][0]["company_ledger_guidance"]["status"] == "available"
    assert "company ledger context reviewed" in plan_payload["steps"][0]["success_criteria"]
    assert "prior candidate context not repeated" in plan_payload["steps"][0]["success_criteria"]
    assert "new acceptance delta defined" in plan_payload["steps"][0]["success_criteria"]
    assert "Do not repeat prior auto result" in plan_payload["steps"][0]["task"]
    plan = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "plan.yaml").read_text(encoding="utf-8"))
    assert plan["company_loop_context"]["status"] == "available"
    assert plan["company_ledger_guidance"]["promotion_policy"]["auto_promote"] is False

    run_again = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")

    assert run_again.returncode == 0, run_again.stderr
    run_again_payload = json.loads(run_again.stdout)
    directive = (tmp_path / run_again_payload["directive_refs"][0]).read_text(encoding="utf-8")
    assert "## Company Ledger" in directive
    assert ".cambrian/company/context/records.yaml" in directive
    assert ".cambrian/company/verification/ledger.yaml" in directive
    assert "next_step_focus: advance_from_candidate_context" in directive
    assert "requires_new_acceptance_delta: True" in directive
    task = yaml.safe_load((tmp_path / run_again_payload["task_refs"][0]).read_text(encoding="utf-8"))
    assert task["company_ledger_guidance"]["status"] == "available"
    assert task["company_ledger_guidance"]["promotion_policy"]["auto_promote"] is False
    assert "Do not repeat prior auto result" in task["task"]
    assert "company_ledger_compliance" in task["result_contract"]["required_fields"]
    assert task["result_contract"]["company_ledger_compliance_required"] is True
    ledger_task_role_outputs = {
        key: f"{key} evidence"
        for key in task["result_contract"]["required_role_output_keys"]
    }

    missing_compliance_result = tmp_path / "missing_company_ledger_compliance.yaml"
    missing_compliance_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "result that forgot to prove company ledger use",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": ledger_task_role_outputs,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    invalid = run_cli(
        tmp_path,
        "auto",
        "step",
        "ingest",
        run_again_payload["task_refs"][0],
        "--result",
        str(missing_compliance_result),
        "--json",
    )

    assert invalid.returncode == 1
    invalid_payload = json.loads(invalid.stdout)
    assert invalid_payload["error"] == "invalid_result_contract"
    assert "company_ledger_compliance" in invalid_payload["required_fields"]
    assert "missing required field: company_ledger_compliance" in invalid_payload["errors"]
    assert "company_ledger_compliance" in invalid_payload["example"]

    compliant_result = tmp_path / "company_ledger_compliant_result.yaml"
    compliant_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "result that proves company ledger use",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated with ledger"], "artifacts": []},
                "role_outputs": ledger_task_role_outputs,
                "company_ledger_compliance": {
                    "ledger_reviewed": True,
                    "duplicate_guard_checked": True,
                    "promotion_policy_respected": True,
                    "new_acceptance_delta": "Added a new acceptance delta beyond the prior candidate context.",
                    "unchecked_items_addressed": [],
                    "validation_commands_selected": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    valid = run_cli(
        tmp_path,
        "auto",
        "step",
        "ingest",
        run_again_payload["task_refs"][0],
        "--result",
        str(compliant_result),
        "--json",
    )

    assert valid.returncode == 0, valid.stderr
    valid_payload = json.loads(valid.stdout)
    assert valid_payload["ok"] is True
    assert valid_payload["result_quality"]["company_ledger_compliance"]["required"] is True
    assert valid_payload["result_quality"]["company_ledger_compliance"]["ok"] is True
    assert valid_payload["result_quality"]["company_ledger_compliance"]["status"] == "compliant"
    saved = yaml.safe_load((tmp_path / valid_payload["result_ref"]).read_text(encoding="utf-8"))
    assert saved["company_ledger_compliance"]["ledger_reviewed"] is True
    assert saved["result_quality"]["score"] == 100
    assert saved["result_quality"]["status"] == "strong"
    assert saved["result_quality"]["company_ledger_compliance"]["score_bonus"] == 5


def test_company_ledger_compliance_affects_result_quality_and_release_gate(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "validated_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "validated seed result",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "seed result",
                    "acceptance_criteria": ["seed result is valid"],
                    "test_plan": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_again = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_again.returncode == 0, run_again.stderr
    task = yaml.safe_load((tmp_path / json.loads(run_again.stdout)["task_refs"][0]).read_text(encoding="utf-8"))
    role_outputs = {key: f"{key} evidence" for key in task["result_contract"]["required_role_output_keys"]}
    compliant_result = tmp_path / "ledger_compliant.yaml"
    compliant_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "ledger-compliant strong result",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated with ledger"], "artifacts": []},
                "role_outputs": role_outputs,
                "company_ledger_compliance": {
                    "ledger_reviewed": True,
                    "duplicate_guard_checked": True,
                    "promotion_policy_respected": True,
                    "new_acceptance_delta": "New acceptance delta recorded.",
                    "unchecked_items_addressed": [],
                    "validation_commands_selected": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(
        tmp_path,
        "auto",
        "step",
        "ingest",
        json.loads(run_again.stdout)["task_refs"][0],
        "--result",
        str(compliant_result),
        "--json",
    )
    assert ingest.returncode == 0, ingest.stderr
    ingest_payload = json.loads(ingest.stdout)
    assert ingest_payload["result_quality"]["status"] == "strong"
    assert ingest_payload["result_quality"]["company_ledger_compliance"]["ok"] is True

    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "release_gate"
    assert "company ledger context reviewed" in plan_payload["steps"][0]["success_criteria"]

    release_gate = run_cli(tmp_path, "auto", "release-gate", "--json")

    assert release_gate.returncode == 0, release_gate.stderr
    gate_payload = json.loads(release_gate.stdout)
    assert gate_payload["evidence_checklist"]["company_ledger_compliance"] is True
    assert "company ledger compliance proof" not in gate_payload["required_before_release"]


def test_auto_step_ingest_records_blocked_result(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "blocked_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "검증 명령이 실패했다.",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["테스트 실패 원인 확인 필요"],
                "next_action": "boardroom에서 다음 결정을 다시 잡는다.",
                "evidence": {"notes": ["테스트 실패"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "blocked"
    assert payload["next_state"] == "REVIEW"
    assert payload["blockers"] == ["테스트 실패 원인 확인 필요"]
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["status"] == "blocked"


def test_skill_knowledge_candidate_requires_evidence(tmp_path: Path) -> None:
    result = record_skill_knowledge_candidate(
        tmp_path,
        source="manual-test",
        skill_ids=["trace-auth-token-flow"],
        summary="candidate without evidence",
        warning="this must not be stored",
        evidence_refs=[],
    )

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["reason"] == "evidence_refs required"
    assert not (tmp_path / ".cambrian" / "skills" / "knowledge_ledger.yaml").exists()


def test_worker_performance_repeated_rejection_stays_low_data_and_penalized(tmp_path: Path) -> None:
    task = {
        "task_id": "task-1",
        "owner": "pm-agent",
        "job_bridge": {
            "selected_agents": ["planner-agent"],
            "selected_skills": ["scope-breakdown"],
        },
    }
    first = record_worker_performance_event(
        tmp_path,
        task=task,
        outcome="rejected",
        status="invalid_result_contract",
        evidence_refs=[".cambrian/auto/rejections/r1.yaml"],
        errors=["missing required field: evidence"],
    )
    second = record_worker_performance_event(
        tmp_path,
        task=task,
        outcome="rejected",
        status="invalid_result_contract",
        evidence_refs=[".cambrian/auto/rejections/r2.yaml"],
        errors=["missing required field: role_outputs"],
    )

    assert first["status"] == "recorded"
    assert second["status"] == "recorded"
    ledger = yaml.safe_load((tmp_path / ".cambrian" / "workers" / "performance_ledger.yaml").read_text(encoding="utf-8"))
    aggregate = ledger["aggregates"]["planner_agent__scope_breakdown"]
    assert aggregate["sample_count"] == 2
    assert aggregate["rejection_count"] == 2
    assert aggregate["confidence"] == "low_data"
    assert aggregate["caution"] == "low_sample_size"
    assert aggregate["performance_score"] < 50
    assert ledger["dispatch_policy"]["hard_lock_choices"] is False
    relearning_review = yaml.safe_load((tmp_path / ".cambrian" / "relearning" / "review.yaml").read_text(encoding="utf-8"))
    assert relearning_review["review_items"][-1]["category"] == "worker_performance"
    assert relearning_review["review_items"][-1]["auto_apply"] is False


def test_repeated_verified_skill_candidate_is_promotion_ready_not_promoted(tmp_path: Path) -> None:
    latest = None
    for index in range(3):
        latest = record_skill_knowledge_candidate(
            tmp_path,
            source=f"verified-{index}",
            skill_ids=["auto-result-contract"],
            summary="Always include evidence and role outputs in auto step results.",
            warning="Verified result contract habit.",
            evidence_refs=[f".cambrian/auto/results/{index}.yaml"],
            knowledge_kind="verified_success_pattern",
        )

    assert latest is not None
    ledger = yaml.safe_load((tmp_path / ".cambrian" / "skills" / "knowledge_ledger.yaml").read_text(encoding="utf-8"))
    candidate = ledger["candidates"][-1]
    assert candidate["approval_status"] == "promotion_ready"
    assert candidate["promotion_ready"] is True
    assert candidate["auto_promote"] is False
    assert candidate["promotion_policy"]["requires_user_review"] is True
    assert ledger["approved_knowledge"] == []


def test_suppressed_skill_candidate_is_not_injected(tmp_path: Path) -> None:
    created = record_skill_knowledge_candidate(
        tmp_path,
        source="bad-candidate",
        skill_ids=["auto-result-contract"],
        summary="Candidate that should not be reused.",
        warning="Do not inject this after suppression.",
        evidence_refs=[".cambrian/auto/results/bad.yaml"],
        knowledge_kind="verified_success_pattern",
    )
    suppressed = suppress_skill_knowledge_candidate(
        tmp_path,
        created["candidate_id"],
        reason="user rejected this knowledge",
    )

    assert suppressed["status"] == "suppressed"
    guidance = _skill_knowledge_guidance_for_task(
        tmp_path,
        {"owner": "pm-agent", "job_bridge": {"selected_skills": ["auto-result-contract"]}},
    )
    assert guidance["status"] == "empty"
    ledger = yaml.safe_load((tmp_path / ".cambrian" / "skills" / "knowledge_ledger.yaml").read_text(encoding="utf-8"))
    assert ledger["candidates"][0]["status"] == "suppressed"
    assert ledger["candidates"][0]["suppression"]["auto_inject"] is False


def test_auto_step_ingest_rejects_invalid_result_contract(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "invalid_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "missing required contract fields",
                "tests": [{"command": "python -m pytest", "status": "passed"}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 1
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_result_contract"
    assert "missing required field: evidence" in payload["errors"]
    assert payload["source_code_modified"] is False
    assert payload["provider_api_called"] is False
    assert payload["rejection_ref"]
    assert payload["correction_directive_ref"]
    assert payload["corrected_result_template_ref"]
    assert payload["worker_performance_record"]["status"] == "recorded"
    rejection = yaml.safe_load((tmp_path / payload["rejection_ref"]).read_text(encoding="utf-8"))
    assert rejection["status"] == "rejected"
    assert rejection["error"] == "invalid_result_contract"
    assert rejection["task_ref"] == task_ref
    assert rejection["correction_directive_ref"] == payload["correction_directive_ref"]
    assert rejection["corrected_result_template_ref"] == payload["corrected_result_template_ref"]
    assert rejection["safety"]["source_code_modified_by_ingest"] is False
    assert rejection["skill_knowledge_candidate"]["status"] == "candidate"
    assert rejection["skill_knowledge_candidate"]["auto_promote"] is False
    knowledge_ledger = yaml.safe_load(
        (tmp_path / ".cambrian" / "skills" / "knowledge_ledger.yaml").read_text(encoding="utf-8")
    )
    assert knowledge_ledger["approved_knowledge"] == []
    assert knowledge_ledger["candidates"][0]["status"] == "candidate"
    assert knowledge_ledger["candidates"][0]["auto_promote"] is False
    assert knowledge_ledger["candidates"][0]["evidence_refs"]
    assert "auto-result-contract" in knowledge_ledger["candidates"][0]["skill_ids"]
    performance_ledger = yaml.safe_load(
        (tmp_path / ".cambrian" / "workers" / "performance_ledger.yaml").read_text(encoding="utf-8")
    )
    assert performance_ledger["events"][0]["outcome"] == "rejected"
    assert performance_ledger["aggregates"]
    assert performance_ledger["dispatch_policy"]["hard_lock_choices"] is False
    relearning_review = yaml.safe_load((tmp_path / ".cambrian" / "relearning" / "review.yaml").read_text(encoding="utf-8"))
    assert relearning_review["status"] == "pending_review"
    assert relearning_review["review_items"]
    assert {item["category"] for item in relearning_review["review_items"]} >= {"worker_performance", "skill_knowledge"}
    correction_directive = (tmp_path / payload["correction_directive_ref"]).read_text(encoding="utf-8")
    assert "Auto Result Contract Correction" in correction_directive
    assert "missing required field: evidence" in correction_directive
    assert "Corrected Result Template" in correction_directive
    correction_template = yaml.safe_load((tmp_path / payload["corrected_result_template_ref"]).read_text(encoding="utf-8"))
    assert "evidence" in correction_template
    assert "changed_files" in correction_template
    log = yaml.safe_load((tmp_path / payload["execution_log_ref"]).read_text(encoding="utf-8"))
    assert log["step_rejections"][0]["error"] == "invalid_result_contract"
    assert log["step_rejections"][0]["task_ref"] == task_ref
    assert log["step_rejections"][0]["correction_directive_ref"] == payload["correction_directive_ref"]
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["status"] == "waiting_for_result"

    report = run_cli(tmp_path, "auto", "report", "--json")
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "needs_result_contract_correction"
    assert report_payload["report"]["result_rejections"]["open_count"] == 1
    assert report_payload["report"]["result_rejections"]["latest"]["rejection_ref"] == payload["rejection_ref"]
    assert report_payload["report"]["result_rejections"]["latest"]["correction_directive_ref"] == payload["correction_directive_ref"]

    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert boardroom.returncode == 0, boardroom.stderr
    boardroom_payload = json.loads(boardroom.stdout)
    assert boardroom_payload["auto_report_summary"]["handoff_status"] == "needs_result_contract_correction"

    plan = run_cli(tmp_path, "auto", "plan", "--json")
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "result_contract_correction"
    assert "missing required field: evidence" in plan_payload["steps"][0]["task"]
    assert plan_payload["steps"][0]["rejection_ref"] == payload["rejection_ref"]
    assert plan_payload["steps"][0]["correction_directive_ref"] == payload["correction_directive_ref"]
    assert plan_payload["steps"][0]["corrected_result_template_ref"] == payload["corrected_result_template_ref"]

    role_outputs = {
        key: f"{key} evidence"
        for key in task["result_contract"]["required_role_output_keys"]
    }
    corrected_result = tmp_path / "corrected_result.yaml"
    corrected_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "corrected result satisfies the auto contract",
                "changed_files": [],
                "tests": [{"command": "python -m pytest tests/test_auto_run_limits.py", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["corrected contract"], "artifacts": []},
                "role_outputs": role_outputs,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    corrected = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(corrected_result), "--json")
    assert corrected.returncode == 0, corrected.stderr
    corrected_payload = json.loads(corrected.stdout)
    assert corrected_payload["resolved_rejections"]["status"] == "resolved"
    assert corrected_payload["resolved_rejections"]["count"] == 1
    resolved_rejection = yaml.safe_load((tmp_path / payload["rejection_ref"]).read_text(encoding="utf-8"))
    assert resolved_rejection["status"] == "resolved"
    assert resolved_rejection["resolved_by_result_ref"] == corrected_payload["result_ref"]
    resolved_log = yaml.safe_load((tmp_path / corrected_payload["execution_log_ref"]).read_text(encoding="utf-8"))
    assert resolved_log["step_rejections"][0]["status"] == "resolved"
    assert resolved_log["step_rejection_resolutions"][0]["resolved_by_result_ref"] == corrected_payload["result_ref"]

    resolved_report = run_cli(tmp_path, "auto", "report", "--json")
    assert resolved_report.returncode == 0, resolved_report.stderr
    resolved_report_payload = json.loads(resolved_report.stdout)
    assert resolved_report_payload["report"]["result_rejections"]["open_count"] == 0
    assert resolved_report_payload["report"]["result_rejections"]["resolved_count"] == 1
    assert resolved_report_payload["report"]["recovery_loop"]["status"] == "resolved_guidance_available"
    assert resolved_report_payload["report"]["recovery_loop"]["promotion_policy"]["auto_promote"] is False
    assert resolved_report_payload["report"]["recovery_loop"]["promotion_policy"]["candidate_warning_only"] is True
    assert resolved_report_payload["report"]["result_contract_guidance"]["status"] == "available"
    assert resolved_report_payload["report"]["result_contract_guidance"]["guidance_kind"] == "candidate_warning_not_promoted_memory"
    assert resolved_report_payload["report"]["result_contract_guidance"]["recovery_loop"]["status"] == "resolved_guidance_available"
    assert "missing required field: evidence" in resolved_report_payload["report"]["result_contract_guidance"]["recent_errors"]
    assert resolved_report_payload["report"]["skill_knowledge"]["status"] == "available"
    assert resolved_report_payload["report"]["skill_knowledge"]["candidate_count"] >= 2
    assert resolved_report_payload["report"]["skill_knowledge"]["approved_count"] == 0
    assert resolved_report_payload["report"]["skill_knowledge"]["candidates"]
    assert resolved_report_payload["report"]["worker_performance"]["status"] == "available"
    assert resolved_report_payload["report"]["worker_performance"]["event_count"] >= 2
    assert resolved_report_payload["report"]["worker_performance"]["low_data_count"] >= 1
    assert resolved_report_payload["report"]["relearning_review"]["status"] == "pending_user_review"
    assert resolved_report_payload["report"]["relearning_review"]["pending_count"] >= 1
    assert resolved_report_payload["decision_handoff"]["status"] != "needs_result_contract_correction"

    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    follow_up_plan = run_cli(tmp_path, "auto", "plan", "--json")
    assert follow_up_plan.returncode == 0, follow_up_plan.stderr
    follow_up_plan_payload = json.loads(follow_up_plan.stdout)
    assert follow_up_plan_payload["result_contract_guidance"]["resolved_count"] == 1
    assert follow_up_plan_payload["result_contract_guidance"]["recovery_loop"]["promotion_policy"]["auto_promote"] is False
    assert follow_up_plan_payload["steps"][0]["result_contract_guidance"]["status"] == "available"
    assert "Do not repeat prior result contract error" in follow_up_plan_payload["steps"][0]["task"]
    assert "candidate warning guidance" in follow_up_plan_payload["steps"][0]["task"]
    assert "result contract history reviewed" in follow_up_plan_payload["steps"][0]["success_criteria"]

    follow_up_run = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert follow_up_run.returncode == 0, follow_up_run.stderr
    follow_up_run_payload = json.loads(follow_up_run.stdout)
    follow_up_task = yaml.safe_load((tmp_path / follow_up_run_payload["task_refs"][0]).read_text(encoding="utf-8"))
    assert follow_up_task["result_contract_guidance"]["resolved_count"] == 1
    assert follow_up_task["result_contract_guidance"]["recovery_loop"]["status"] == "resolved_guidance_available"
    assert follow_up_task["skill_knowledge_guidance"]["status"] == "candidate_available"
    assert follow_up_task["skill_knowledge_guidance"]["approved_count"] == 0
    assert follow_up_task["skill_knowledge_guidance"]["candidate_warnings"]
    assert follow_up_task["worker_performance_guidance"]["status"] == "available"
    assert follow_up_task["worker_performance_guidance"]["low_data_caution"] is True
    assert follow_up_task["worker_performance_guidance"]["dispatch_policy"]["hard_lock_choices"] is False
    follow_up_directive = (tmp_path / follow_up_run_payload["directive_refs"][0]).read_text(encoding="utf-8")
    assert "## Result Contract History" in follow_up_directive
    assert "## Skill Knowledge Ledger" in follow_up_directive
    assert "## Worker Performance Ledger" in follow_up_directive
    assert "low_sample_size" in follow_up_directive
    assert "approved_count: 0" in follow_up_directive
    assert "missing required field: evidence" in follow_up_directive
    assert "candidate_warning_not_promoted_memory" in follow_up_directive
    assert "candidate_warning_only: True" in follow_up_directive


def test_auto_report_hands_blocked_step_back_to_boardroom(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "blocked_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked by test failure",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["test failure"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["blocked"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")

    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    summary = payload["report"]["step_results"]
    assert summary["blocked"] == 1
    assert summary["open_blockers"][0]["blockers"] == ["test failure"]
    assert payload["decision_handoff"]["status"] == "needs_boardroom_review"
    assert payload["decision_handoff"]["next_command"] == "cambrian auto boardroom --json"


def test_auto_report_uses_latest_step_result_per_task(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    blocked_result = tmp_path / "blocked_result.yaml"
    blocked_result.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked by timeout",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["timeout"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["blocked"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    first_ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(blocked_result), "--json")
    assert first_ingest.returncode == 0, first_ingest.stderr
    blocked_report = run_cli(tmp_path, "auto", "report", "--json")
    assert blocked_report.returncode == 0, blocked_report.stderr
    blocked_payload = json.loads(blocked_report.stdout)
    assert blocked_payload["report"]["step_results"]["blocked"] == 1

    resolved_result = tmp_path / "resolved_result.yaml"
    resolved_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "timeout resolved with split-run evidence",
                "changed_files": [],
                "tests": [{"command": "python -m pytest tests/test_auto_run_limits.py", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "validated timeout recovery",
                    "acceptance_criteria": ["stale blockers are not counted after resolution"],
                    "test_plan": ["python -m pytest tests/test_auto_run_limits.py"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    second_ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(resolved_result), "--json")
    assert second_ingest.returncode == 0, second_ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")

    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    summary = payload["report"]["step_results"]
    assert summary["total"] == 1
    assert summary["blocked"] == 0
    assert summary["validated"] == 1
    assert summary["open_blockers"] == []
    assert payload["report"]["task_statuses"]["blocked"] == 0
    assert payload["decision_handoff"]["status"] == "ready_for_release_or_next_plan"


def test_auto_task_directive_bridge_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "25_AUTO_TASK_DIRECTIVE_BRIDGE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto run",
        "waiting_for_result",
        ".cambrian/auto/tasks",
        "Codex 또는 Claude",
        "source code를 직접 수정하지 않는다",
    ]:
        assert phrase in text
    assert "docs/product/25_AUTO_TASK_DIRECTIVE_BRIDGE.md" in readme
    assert "25_AUTO_TASK_DIRECTIVE_BRIDGE.md" in index


def test_auto_step_result_intake_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "26_AUTO_STEP_RESULT_INTAKE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto step ingest",
        ".cambrian/auto/results",
        ".cambrian/auto/tasks",
        "execution_log.yaml",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/26_AUTO_STEP_RESULT_INTAKE.md" in readme
    assert "26_AUTO_STEP_RESULT_INTAKE.md" in index


def test_auto_result_report_handoff_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "27_AUTO_RESULT_REPORT_HANDOFF.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto report",
        "decision_handoff",
        "waiting_for_external_result",
        "needs_boardroom_review",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/27_AUTO_RESULT_REPORT_HANDOFF.md" in readme
    assert "27_AUTO_RESULT_REPORT_HANDOFF.md" in index


def test_codex_result_contract_hardening_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "31_CODEX_RESULT_CONTRACT_HARDENING.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "invalid_result_contract",
        "status",
        "summary",
        "changed_files",
        "evidence",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/31_CODEX_RESULT_CONTRACT_HARDENING.md" in readme
    assert "31_CODEX_RESULT_CONTRACT_HARDENING.md" in index


def test_auto_run_blocks_steps_without_authority(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=False)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["authority"] == "proposal_only"
    assert payload["blocked_steps"]
    missing = [permission for step in payload["blocked_steps"] for permission in step["missing_permissions"]]
    assert "filesystem_write" in missing
    assert "command_exec" in missing
    assert "build_artifact" in missing


def test_auto_run_requires_plan(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "5", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "auto plan is missing" in payload["errors"]
