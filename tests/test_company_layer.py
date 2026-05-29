from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_company_layer import (
    CompanyLayerError,
    build_context_promotion_review_packet,
    build_company_layer_status,
    convene_product_boardroom,
    ingest_product_boardroom_reply,
    init_company_layer_base,
    install_product_boardroom,
    load_company_loop_context,
    product_boardroom_status,
    promote_context_candidate,
    record_context_candidate,
    record_verification_entry,
    save_company_layer_status,
)

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str = "ok: true\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_ai_boardroom_reply(path: Path) -> None:
    payload = {
        "topic": "24h product direction",
        "role_views": {
            "ceo-agent": {
                "ai_agent": True,
                "turn_authorship": "ai_agent",
                "position": "External users need one verified trust proof before broader automation.",
                "decision": "Make the next cycle prove install and validation clarity.",
                "evidence_refs": [".cambrian/mission.yaml"],
                "assumptions": ["No external customer interview is attached to this test fixture."],
                "risks": ["Boardroom can become metadata if it does not change the next job."],
                "next_constraint": "Do not expand scope until one user-visible proof is validated.",
            },
            "cto-agent": {
                "ai_agent": True,
                "turn_authorship": "ai_agent",
                "position": "The AI boardroom must be a gated input, not deterministic template text.",
                "decision": "Require ingested AI-authored turns before ready_for_mission.",
                "evidence_refs": [".cambrian/company/product_boardroom/agents.yaml"],
                "assumptions": [],
                "risks": ["A template fallback would hide weak product reasoning."],
                "next_constraint": "Validation must record AI turn provenance.",
            },
            "coo-agent": {
                "ai_agent": True,
                "turn_authorship": "ai_agent",
                "position": "The operating loop needs one next job and one stop condition.",
                "decision": "Open one bounded mission job only after the AI boardroom packet is ready.",
                "evidence_refs": [".cambrian/company/product_boardroom/latest_ai_request.yaml"],
                "assumptions": [],
                "risks": ["Repeating the loop without fresh AI discussion creates stale execution."],
                "next_constraint": "Stop after evidence ingest and validation result.",
            },
        },
        "consensus": {
            "decision": "Use AI-authored CEO/CTO/COO turns as the pre-mission product gate.",
            "scope": "No source mutation, deploy, publish, spend, secrets, or migration.",
            "recommended_next_mission": "Open exactly one bounded mission job and validate before sync.",
        },
        "open_questions": [
            {"id": "ai-boardroom-proof-001", "question": "Did the AI boardroom change the next job?", "owner": "cto-agent"}
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_verified_mission_outcome(path: Path, job_id: str) -> None:
    payload = {
        "schema_version": "1.0.0",
        "status": "active",
        "goal": "Run a verified company loop",
        "last_outcome": {
            "job_id": job_id,
            "outcome": "success",
            "verdict": "pass",
            "trust_gate_status": "verified",
            "unchecked_count": 0,
            "latest_verdict_ref": ".cambrian/reports/latest_verdict.json",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _promote_one_context_record(project_root: Path) -> None:
    record_context_candidate(
        project_root,
        source="job-company-loop-proof",
        summary="Verified company loop context candidate",
        decision="Use verified mission outcomes and verification ledger entries as company readiness proof.",
        evidence_ref=".cambrian/jobs/job-company-loop-proof/outcome.yaml",
    )
    promote_context_candidate(project_root, "context-record-0001", confirm=True)


def test_company_layer_starts_as_planned_for_empty_project(tmp_path: Path) -> None:
    payload = build_company_layer_status(tmp_path)

    assert payload["status"] == "planned"
    assert payload["project_company_ready"] is False
    assert payload["auto_leadership_enabled"] is False
    assert payload["approval_required_for_plan_changes"] is True
    assert payload["offices"]["context"]["status"] == "planned"
    assert payload["offices"]["direction"]["status"] == "planned"
    assert payload["offices"]["execution"]["status"] == "planned"
    assert payload["offices"]["verification"]["status"] == "planned"
    assert payload["summary"]["current_capability"] == "planned_company_layer"


def test_company_layer_blocks_unnecessary_company_expansion_by_default(tmp_path: Path) -> None:
    payload = build_company_layer_status(tmp_path)

    gate = payload["necessity_gate"]
    assert gate["mode"] == "lean_project_company"
    assert gate["allowed_offices"] == ["context", "direction", "execution", "verification"]
    assert gate["office_count"] == 4
    assert gate["expansion_allowed"] is False
    assert gate["requires_evidence_for_new_office"] is True
    assert gate["requires_user_approval"] is True
    assert gate["blocked_expansion_types"] == [
        "extra_office",
        "decorative_role",
        "speculative_agent",
        "uncited_workflow",
    ]
    assert gate["next_allowed_work"]["task_id"] == "company-base-000"
    assert payload["summary"]["company_design_mode"] == "lean_project_company"
    assert payload["summary"]["expansion_allowed"] is False


def test_company_layer_detects_specialist_workforce_and_evidence(tmp_path: Path) -> None:
    _write(tmp_path / ".cambrian" / "profile.yaml")
    _write(tmp_path / ".cambrian" / "project" / "profile.yaml")
    _write(tmp_path / ".cambrian" / "harness.yaml")
    _write(tmp_path / ".cambrian" / "plan.yaml")
    _write(tmp_path / ".cambrian" / "workforce.yaml")
    _write(tmp_path / ".cambrian" / "agents.yaml")
    _write(tmp_path / ".cambrian" / "agents" / "worker.yaml")
    _write(tmp_path / ".cambrian" / "jobs" / "job-1" / "outcome.yaml")
    _write(tmp_path / ".cambrian" / "validation.yaml")
    _write(tmp_path / ".cambrian" / "evidence" / "validation" / "job-1.yaml")

    payload = build_company_layer_status(tmp_path)

    assert payload["status"] == "partial"
    assert payload["project_company_ready"] is False
    assert payload["summary"]["current_capability"] == "specialist_workforce_or_partial_company"
    assert payload["offices"]["context"]["status"] == "partial"
    assert payload["offices"]["direction"]["status"] == "partial"
    assert payload["offices"]["execution"]["status"] == "active"
    assert payload["offices"]["verification"]["status"] == "partial"
    assert "evidence_ledger" in payload["offices"]["verification"]["required_components"]


def test_company_layer_status_can_be_saved(tmp_path: Path) -> None:
    payload, saved = save_company_layer_status(tmp_path)

    assert payload["saved_path"] == ".cambrian/company/status.yaml"
    assert saved.is_file()
    saved_payload = yaml.safe_load(saved.read_text(encoding="utf-8"))
    assert saved_payload["project_company_ready"] is False
    assert saved_payload["offices"]["context"]["label"] == "Context Office"


def test_company_layer_init_creates_base_schedule(tmp_path: Path) -> None:
    payload = init_company_layer_base(tmp_path, goal="회사 베이스 완성")

    assert payload["ok"] is True
    assert payload["status"] == "base_planned"
    assert payload["base_initialized"] is True
    assert payload["project_company_ready"] is False
    assert payload["task_count"] == 4
    assert payload["auto_leadership_enabled"] is False
    assert ".cambrian/company/charter.yaml" in payload["saved_paths"]
    assert ".cambrian/company/task_schedule.yaml" in payload["saved_paths"]
    assert ".cambrian/company/offices/context.yaml" in payload["saved_paths"]

    schedule = yaml.safe_load((tmp_path / ".cambrian" / "company" / "task_schedule.yaml").read_text(encoding="utf-8"))
    assert schedule["principle"].startswith("베이스 회사 계층을 먼저 완성")
    assert schedule["necessity_policy"]["mode"] == "lean_project_company"
    assert schedule["necessity_policy"]["allowed_offices"] == ["context", "direction", "execution", "verification"]
    assert schedule["necessity_policy"]["no_extra_offices_without_evidence"] is True
    assert schedule["necessity_policy"]["no_decorative_roles"] is True
    assert "프로젝트 증거 없는 사무실 추가" in schedule["non_goals"]
    assert schedule["deferred_upgrades"][0]["id"] == "company-upgrade-later-001"
    assert schedule["deferred_upgrades"][0]["status"] == "deferred"
    assert [task["office"] for task in schedule["tasks"]] == ["context", "direction", "execution", "verification"]
    assert schedule["tasks"][0]["id"] == "company-base-001"

    charter = yaml.safe_load((tmp_path / ".cambrian" / "company" / "charter.yaml").read_text(encoding="utf-8"))
    assert charter["necessity_gate"]["mode"] == "lean_project_company"
    assert charter["necessity_gate"]["expansion_allowed"] is False
    assert charter["necessity_gate"]["requires_user_approval"] is True

    status_payload = build_company_layer_status(tmp_path)
    assert status_payload["status"] == "base_initialized"
    assert status_payload["base_initialized"] is True
    assert status_payload["project_company_ready"] is False
    assert status_payload["summary"]["current_capability"] == "company_base_initialized"
    assert "company loop proof is missing" in status_payload["summary"]["readiness_blockers"]


def test_company_context_record_creates_candidate_memory(tmp_path: Path) -> None:
    init_company_layer_base(tmp_path, goal="회사 베이스 완성")

    payload = record_context_candidate(
        tmp_path,
        source="job-123",
        summary="P2 작업 결과는 패치 적용 전 검증 기록으로 남긴다.",
        decision="자동 승격하지 않는다.",
        lesson="작업 결과는 먼저 context 후보에 쌓는다.",
        evidence_ref=".cambrian/jobs/job-123/outcome.yaml",
    )

    assert payload["ok"] is True
    assert payload["status"] == "context_recorded"
    assert payload["record_id"] == "context-record-0001"
    assert payload["promotion_status"] == "candidate"
    assert payload["saved_path"] == ".cambrian/company/context/records.yaml"
    assert payload["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"

    records_path = tmp_path / ".cambrian" / "company" / "context" / "records.yaml"
    records = yaml.safe_load(records_path.read_text(encoding="utf-8"))
    assert records["records"][0]["source"] == "job-123"
    assert records["records"][0]["signals"]["decision"] == "자동 승격하지 않는다."
    assert records["records"][0]["promotion_policy"]["auto_promote"] is False
    assert records["records"][0]["promotion_policy"]["secret_storage_forbidden"] is True
    review = yaml.safe_load((tmp_path / ".cambrian" / "company" / "context" / "promotion_review.yaml").read_text(encoding="utf-8"))
    assert review["status"] == "pending_user_review"
    assert review["review_items"][0]["record_id"] == "context-record-0001"
    assert review["review_items"][0]["approval_state"] == "pending_user_review"
    assert review["promotion_policy"]["auto_promote"] is False

    status_payload = build_company_layer_status(tmp_path)
    assert ".cambrian/company/context/records.yaml" in status_payload["offices"]["context"]["evidence_refs"]
    assert status_payload["context_promotion_exists"] is False
    assert status_payload["project_company_ready"] is False


def test_company_context_record_requires_source_and_summary(tmp_path: Path) -> None:
    try:
        record_context_candidate(tmp_path, source="", summary="요약")
    except CompanyLayerError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("source 없이 context 후보를 기록하면 안 된다.")

    try:
        record_context_candidate(tmp_path, source="job-123", summary="")
    except CompanyLayerError as exc:
        assert "summary" in str(exc)
    else:
        raise AssertionError("summary 없이 context 후보를 기록하면 안 된다.")


def test_company_context_promote_requires_confirm(tmp_path: Path) -> None:
    record_context_candidate(
        tmp_path,
        source="job-123",
        summary="기억 후보",
        decision="승격은 수동 승인으로만 한다.",
    )

    try:
        promote_context_candidate(tmp_path, "context-record-0001", confirm=False)
    except CompanyLayerError as exc:
        assert "--confirm" in str(exc)
    else:
        raise AssertionError("--confirm 없이 context 후보를 승격하면 안 된다.")


def test_company_context_promote_writes_long_term_ledgers(tmp_path: Path) -> None:
    record_context_candidate(
        tmp_path,
        source="job-123",
        summary="작업 결과를 장기 기억 후보로 남겼다.",
        decision="기억실 승격은 사용자 승인 후 진행한다.",
        lesson="context 후보를 먼저 만들면 다음 작업의 방향이 흔들리지 않는다.",
        mistake="승격 전 proof 없이 성능을 주장하면 안 된다.",
        evidence_ref=".cambrian/jobs/job-123/outcome.yaml",
    )

    payload = promote_context_candidate(tmp_path, "context-record-0001", confirm=True)

    assert payload["ok"] is True
    assert payload["status"] == "context_promoted"
    assert payload["promoted_targets"] == ["decision_history", "lessons", "mistakes"]
    assert payload["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"
    assert payload["auto_promote"] is False
    assert ".cambrian/company/context/decision_history.yaml" in payload["saved_paths"]
    assert ".cambrian/company/context/lessons.yaml" in payload["saved_paths"]
    assert ".cambrian/company/context/mistakes.yaml" in payload["saved_paths"]

    records = yaml.safe_load((tmp_path / ".cambrian" / "company" / "context" / "records.yaml").read_text(encoding="utf-8"))
    assert records["records"][0]["promotion_status"] == "promoted"
    assert records["records"][0]["promoted_targets"] == ["decision_history", "lessons", "mistakes"]

    decisions = yaml.safe_load((tmp_path / ".cambrian" / "company" / "context" / "decision_history.yaml").read_text(encoding="utf-8"))
    lessons = yaml.safe_load((tmp_path / ".cambrian" / "company" / "context" / "lessons.yaml").read_text(encoding="utf-8"))
    mistakes = yaml.safe_load((tmp_path / ".cambrian" / "company" / "context" / "mistakes.yaml").read_text(encoding="utf-8"))
    assert decisions["decisions"][0]["approval_state"] == "approved_by_user"
    review = yaml.safe_load((tmp_path / ".cambrian" / "company" / "context" / "promotion_review.yaml").read_text(encoding="utf-8"))
    assert review["status"] == "empty"
    loop_context = load_company_loop_context(tmp_path)
    assert loop_context["candidate_context_records"] == []
    assert loop_context["promoted_memory"]["total_count"] == 3
    assert decisions["decisions"][0]["decision"] == "기억실 승격은 사용자 승인 후 진행한다."
    assert lessons["lessons"][0]["lesson"] == "context 후보를 먼저 만들면 다음 작업의 방향이 흔들리지 않는다."
    assert mistakes["mistakes"][0]["mistake"] == "승격 전 proof 없이 성능을 주장하면 안 된다."

    status_payload = build_company_layer_status(tmp_path)
    assert ".cambrian/company/context/decision_history.yaml" in status_payload["offices"]["context"]["evidence_refs"]
    assert status_payload["context_promotion_exists"] is True
    assert "context promotion proof is missing" not in status_payload["summary"]["readiness_blockers"]
    assert status_payload["project_company_ready"] is False


def test_company_status_becomes_ready_with_synced_mission_and_verified_ledger(tmp_path: Path) -> None:
    init_company_layer_base(tmp_path, goal="Run a verified company loop")
    _promote_one_context_record(tmp_path)
    job_id = "job-company-loop-proof"
    _write_verified_mission_outcome(tmp_path / ".cambrian" / "mission.yaml", job_id)
    record_verification_entry(
        tmp_path,
        source="job:complete",
        job_id=job_id,
        stage="complete",
        validation_evidence_ref=".cambrian/evidence/validation/job-company-loop-proof.yaml",
        verdict_ref=".cambrian/reports/latest_verdict.json",
        verdict="pass",
        trust_gate_status="verified",
        validation_commands=["python -m pytest -q tests/test_company_layer.py"],
        checked_artifacts=["engine/project_company_layer.py", "tests/test_company_layer.py"],
        unchecked_items=[],
    )

    status_payload = build_company_layer_status(tmp_path)

    assert status_payload["status"] == "company_ready"
    assert status_payload["base_initialized"] is True
    assert status_payload["context_promotion_exists"] is True
    assert status_payload["company_loop_proof_exists"] is True
    assert status_payload["verification_ledger_proof_exists"] is True
    assert status_payload["project_company_ready"] is True
    assert status_payload["auto_leadership_enabled"] is False
    assert status_payload["summary"]["current_capability"] == "verified_company_loop"
    assert status_payload["summary"]["readiness_blockers"] == []
    assert status_payload["company_loop_proof"]["mission_last_outcome"]["job_id"] == job_id
    assert status_payload["company_loop_proof"]["verification_entry_matches_last_outcome"] is True
    assert status_payload["verification_ledger_proof"]["latest_verified_entry"]["job_id"] == job_id
    assert status_payload["necessity_gate"]["next_allowed_work"]["task_id"] == "company-loop-ready"


def test_company_status_requires_ledger_entry_matching_latest_mission_outcome(tmp_path: Path) -> None:
    init_company_layer_base(tmp_path, goal="Run a verified company loop")
    _promote_one_context_record(tmp_path)
    _write_verified_mission_outcome(tmp_path / ".cambrian" / "mission.yaml", "job-latest-mission")
    record_verification_entry(
        tmp_path,
        source="job:complete",
        job_id="job-older-proof",
        stage="complete",
        validation_evidence_ref=".cambrian/evidence/validation/job-older-proof.yaml",
        verdict="pass",
        trust_gate_status="verified",
        validation_commands=["python -m pytest -q tests/test_company_layer.py"],
        unchecked_items=[],
    )

    status_payload = build_company_layer_status(tmp_path)

    assert status_payload["verification_ledger_proof_exists"] is True
    assert status_payload["company_loop_proof_exists"] is False
    assert status_payload["project_company_ready"] is False
    assert "company loop proof is missing" in status_payload["summary"]["readiness_blockers"]
    assert "verification ledger proof is missing" not in status_payload["summary"]["readiness_blockers"]


def test_company_context_promote_blocks_duplicate_promotion(tmp_path: Path) -> None:
    record_context_candidate(
        tmp_path,
        source="job-123",
        summary="기억 후보",
        lesson="한 번만 승격한다.",
    )
    promote_context_candidate(tmp_path, "context-record-0001", confirm=True)

    try:
        promote_context_candidate(tmp_path, "context-record-0001", confirm=True)
    except CompanyLayerError as exc:
        assert "이미 승격" in str(exc)
    else:
        raise AssertionError("이미 승격한 context 후보를 다시 승격하면 안 된다.")


def test_product_boardroom_install_creates_ceo_cto_coo_agents(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Cambrian\n")
    _write(tmp_path / ".cambrian" / "mission.yaml", "goal: Ship Cambrian for external users\n")

    payload = install_product_boardroom(tmp_path)

    assert payload["ok"] is True
    assert payload["status"] == "product_boardroom_installed"
    assert payload["agent_ids"] == ["ceo-agent", "cto-agent", "coo-agent"]
    assert payload["agent_count"] == 3
    assert payload["agents_ref"] == ".cambrian/company/product_boardroom/agents.yaml"
    assert len(payload["agent_prompt_refs"]) == 3
    assert payload["meeting_protocol_ref"] == ".cambrian/company/product_boardroom/meeting_protocol.md"
    assert payload["agenda_ref"] == ".cambrian/company/product_boardroom/agenda.yaml"
    assert payload["decision_history_ref"] == ".cambrian/company/product_boardroom/decision_history.yaml"
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["provider_api_called_by_cambrian"] is False

    agents_path = tmp_path / ".cambrian" / "company" / "product_boardroom" / "agents.yaml"
    saved = yaml.safe_load(agents_path.read_text(encoding="utf-8"))
    saved_agents = saved["agents"]
    assert [agent["agent_id"] for agent in saved_agents] == ["ceo-agent", "cto-agent", "coo-agent"]
    assert all(agent["agent_kind"] == "ai_agent" for agent in saved_agents)
    assert all(agent["turn_source"] == "ai_agent_reply" for agent in saved_agents)
    assert all(agent["requires_ai_generated_turn"] is True for agent in saved_agents)
    assert all(agent["template_turn_allowed"] is False for agent in saved_agents)
    assert all(agent["approval_policy"] == "proposal_only" for agent in saved_agents)
    assert all(agent["can_modify_source"] is False for agent in saved_agents)
    assert all(agent["can_call_provider_api"] is False for agent in saved_agents)
    for prompt_ref in payload["agent_prompt_refs"]:
        prompt_path = tmp_path / prompt_ref
        assert prompt_path.is_file()
        prompt_body = prompt_path.read_text(encoding="utf-8")
        assert "AI Agent Contract" in prompt_body
        assert "Non-Negotiable Boundaries" in prompt_body
        assert "Required Questions" in prompt_body
    assert (tmp_path / payload["meeting_protocol_ref"]).is_file()
    assert (tmp_path / payload["agenda_ref"]).is_file()
    assert (tmp_path / payload["decision_history_ref"]).is_file()

    status = product_boardroom_status(tmp_path)
    assert status["status"] == "boardroom_ready"
    assert status["installed"] is True
    assert status["ai_agent_contract_ready"] is True
    assert len(status["agent_prompt_refs"]) == 3
    assert status["decision_count"] == 0


def test_product_boardroom_requires_ai_reply_before_decision_packet(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Cambrian\n")
    _write(tmp_path / "docs" / "product" / "42_TEN_YEAR_ARCHITECTURE.md", "# Architecture\n")
    _write(tmp_path / ".cambrian" / "mission.yaml", "goal: Run a verified 24h company loop\n")
    install_product_boardroom(tmp_path)

    request_payload = convene_product_boardroom(tmp_path, "24h product direction")

    assert request_payload["ok"] is True
    assert request_payload["status"] == "waiting_for_ai_agents"
    assert request_payload["ai_agent_required"] is True
    assert request_payload["ai_agent_turns_required"] is True
    assert request_payload["template_turn_allowed"] is False
    assert request_payload["agent_ids"] == ["ceo-agent", "cto-agent", "coo-agent"]
    assert len(request_payload["agent_prompt_refs"]) == 3
    assert request_payload["next_command"] == "cambrian company boardroom ingest ai_boardroom_reply.yaml --json"
    assert request_payload["source_code_modified_by_cambrian"] is False
    assert request_payload["provider_api_called_by_cambrian"] is False

    request_path = tmp_path / request_payload["ai_request_ref"]
    latest_request_path = tmp_path / request_payload["latest_ai_request_ref"]
    assert request_path.is_file()
    assert latest_request_path.is_file()
    request = yaml.safe_load(request_path.read_text(encoding="utf-8"))
    assert request["artifact_kind"] == "product_boardroom_ai_agent_request"
    assert request["status"] == "waiting_for_ai_agents"
    assert request["required_reply_shape"]["role_views"]["ceo-agent"]["ai_agent"] is True

    reply_path = tmp_path / "ai_boardroom_reply.yaml"
    _write_ai_boardroom_reply(reply_path)

    payload = ingest_product_boardroom_reply(tmp_path, reply_path)

    assert payload["ok"] is True
    assert payload["status"] == "product_boardroom_ai_decision_ingested"
    assert payload["ai_agent_turns_verified"] is True
    assert payload["mission_gate"]["ready_for_mission"] is True
    assert payload["mission_gate"]["requires_ai_agent_turns"] is True
    assert payload["mission_gate"]["ai_agent_turns_verified"] is True
    assert payload["mission_gate"]["auto_apply"] is False

    conversation_path = tmp_path / payload["conversation_ref"]
    decision_path = tmp_path / payload["decision_packet_ref"]
    questions_path = tmp_path / payload["open_questions_ref"]
    agenda_path = tmp_path / payload["agenda_ref"]
    history_path = tmp_path / payload["decision_history_ref"]
    assert conversation_path.is_file()
    assert decision_path.is_file()
    assert questions_path.is_file()
    assert agenda_path.is_file()
    assert history_path.is_file()

    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    assert decision["artifact_kind"] == "product_boardroom_decision_packet"
    assert decision["ai_agent_required"] is True
    assert decision["ai_agent_turns_verified"] is True
    assert decision["turn_source"] == "ai_agent_reply"
    assert decision["role_views"]["ceo-agent"]["title"] == "CEO"
    assert decision["role_views"]["cto-agent"]["title"] == "CTO"
    assert decision["role_views"]["coo-agent"]["title"] == "COO"
    assert decision["role_views"]["ceo-agent"]["ai_agent_verified"] is True
    assert decision["role_views"]["ceo-agent"]["agent_prompt_ref"] == ".cambrian/company/product_boardroom/agent_prompts/ceo-agent.md"
    assert len(decision["agent_prompt_refs"]) == 3
    assert decision["meeting_protocol_ref"] == ".cambrian/company/product_boardroom/meeting_protocol.md"
    assert decision["next_agenda_ref"] == ".cambrian/company/product_boardroom/agenda.yaml"
    assert decision["decision_history_ref"] == ".cambrian/company/product_boardroom/decision_history.yaml"
    assert decision["mission_gate"]["max_mission_jobs_per_tick"] == 1
    assert decision["source_code_modified_by_cambrian"] is False
    assert decision["provider_api_called_by_cambrian"] is False
    assert "source_patch_apply" in decision["forbidden_actions"]
    history = yaml.safe_load(history_path.read_text(encoding="utf-8"))
    assert len(history["decisions"]) == 1
    assert history["decisions"][0]["ai_agent_turns_verified"] is True
    agenda = yaml.safe_load(agenda_path.read_text(encoding="utf-8"))
    assert agenda["status"] == "ready"
    assert len(agenda["open_questions"]) == 1


def test_company_layer_cli_boardroom_install_and_convene_json(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Cambrian\n")
    _write(tmp_path / ".cambrian" / "mission.yaml", "goal: Keep the release path sharp\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    install_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "company",
            "boardroom",
            "install",
            "--goal",
            "Keep product discussion alive",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert install_completed.returncode == 0, install_completed.stderr
    install_payload = json.loads(install_completed.stdout)
    assert install_payload["status"] == "product_boardroom_installed"

    convene_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "company",
            "boardroom",
            "convene",
            "--topic",
            "next product decision",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert convene_completed.returncode == 0, convene_completed.stderr
    convene_payload = json.loads(convene_completed.stdout)
    assert convene_payload["status"] == "waiting_for_ai_agents"
    assert convene_payload["latest_ai_request_ref"] == ".cambrian/company/product_boardroom/latest_ai_request.yaml"

    reply_path = tmp_path / "ai_boardroom_reply.yaml"
    _write_ai_boardroom_reply(reply_path)
    ingest_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "company",
            "boardroom",
            "ingest",
            "ai_boardroom_reply.yaml",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert ingest_completed.returncode == 0, ingest_completed.stderr
    ingest_payload = json.loads(ingest_completed.stdout)
    assert ingest_payload["status"] == "product_boardroom_ai_decision_ingested"
    assert ingest_payload["decision_packet_ref"] == ".cambrian/company/product_boardroom/decision_packet.yaml"


def test_company_layer_cli_status_json(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "engine.cli", "company", "status", "--json"],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "planned"
    assert payload["project_company_ready"] is False
    assert payload["offices"]["execution"]["label"] == "Execution Office"


def test_company_layer_cli_init_json(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "company",
            "init",
            "--goal",
            "회사 베이스 완성",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "base_planned"
    assert payload["base_initialized"] is True
    assert payload["project_company_ready"] is False
    assert payload["task_count"] == 4
    assert ".cambrian/company/task_schedule.yaml" in payload["saved_paths"]
    assert (tmp_path / ".cambrian" / "company" / "task_schedule.yaml").is_file()


def test_company_layer_cli_context_record_json(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "company",
            "context",
            "record",
            "--source",
            "job-456",
            "--summary",
            "작업 결과를 기억 후보로 저장한다.",
            "--lesson",
            "기억실은 자동 승격하지 않는다.",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "context_recorded"
    assert payload["record_id"] == "context-record-0001"
    assert (tmp_path / ".cambrian" / "company" / "context" / "records.yaml").is_file()


def test_company_layer_cli_context_promote_json(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    record_context_candidate(
        tmp_path,
        source="job-789",
        summary="CLI 승격 후보",
        decision="CLI 승격도 confirm이 필요하다.",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "company",
            "context",
            "promote",
            "context-record-0001",
            "--confirm",
            "--json",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "context_promoted"
    assert payload["promoted_targets"] == ["decision_history"]
    assert (tmp_path / ".cambrian" / "company" / "context" / "decision_history.yaml").is_file()


def test_company_layer_cli_status_save(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "engine.cli", "company", "status", "--save", "--json"],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["saved_path"] == ".cambrian/company/status.yaml"
    assert (tmp_path / ".cambrian" / "company" / "status.yaml").is_file()
