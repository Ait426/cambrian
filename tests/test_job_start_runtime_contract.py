from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from tests.test_harness_engineer_design import pass_engineering_gate, prepare_engineering_project, run_cli


ROOT = Path(__file__).resolve().parents[1]


def test_job_start_runtime_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "16_JOB_START_RUNTIME_CONTRACT.md"
    packet_doc = ROOT / "docs" / "product" / "17_CODEX_CLAUDE_REQUEST_PACKET.md"
    ingest_doc = ROOT / "docs" / "product" / "18_AI_REPLY_INGEST_CONTRACT.md"
    validate_doc = ROOT / "docs" / "product" / "19_JOB_VALIDATE_TRUST_GATE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    assert packet_doc.exists()
    assert ingest_doc.exists()
    assert validate_doc.exists()
    text = doc.read_text(encoding="utf-8")
    packet_text = packet_doc.read_text(encoding="utf-8")
    ingest_text = ingest_doc.read_text(encoding="utf-8")
    validate_text = validate_doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian job start",
        "waiting_for_ai_reply",
        "request_packet_ref",
        "execution_contract",
        "codex_claude_instruction",
        "ai_provider_called",
        "source_code_modified",
        ".cambrian/bridge/packets/",
        ".cambrian/packs/jobs/",
        "manual_validation_required",
        "trust_gate_status",
        ".cambrian/evidence/validation/",
    ]:
        assert phrase in f"{text}\n{packet_text}\n{ingest_text}\n{validate_text}"
    assert "docs/product/16_JOB_START_RUNTIME_CONTRACT.md" in readme
    assert "docs/product/17_CODEX_CLAUDE_REQUEST_PACKET.md" in readme
    assert "docs/product/18_AI_REPLY_INGEST_CONTRACT.md" in readme
    assert "docs/product/19_JOB_VALIDATE_TRUST_GATE.md" in readme
    assert "16_JOB_START_RUNTIME_CONTRACT.md" in index
    assert "17_CODEX_CLAUDE_REQUEST_PACKET.md" in index
    assert "18_AI_REPLY_INGEST_CONTRACT.md" in index
    assert "19_JOB_VALIDATE_TRUST_GATE.md" in index


def test_job_start_json_exposes_runtime_contract(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    export_manifest = yaml.safe_load((tmp_path / ".cambrian" / "company" / "export_manifest.yaml").read_text(encoding="utf-8"))
    assert export_manifest["boundary"]["sale_ready"] is False
    assert export_manifest["boundary"]["proof_claim_allowed"] is False
    assert export_manifest["exportable_artifacts"]["company_blueprint"] == ".cambrian/harness.yaml#company_blueprint"
    assert export_manifest["exportable_artifacts"]["project_discussion_layer"] == ".cambrian/company/discussion/agents.yaml"
    discussion_artifact = yaml.safe_load(
        (tmp_path / ".cambrian" / "company" / "discussion" / "agents.yaml").read_text(encoding="utf-8")
    )
    assert {"ceo-agent", "cto-agent", "coo-agent"}.issubset(
        {agent["role_id"] for agent in discussion_artifact["agents"]}
    )

    result = run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    expected_fields = {
        "ok",
        "status",
        "job_id",
        "job_status",
        "harness_id",
        "workforce_id",
        "selected_agents",
        "selected_skills",
        "dispatch_reason",
        "change_policy",
        "validation_commands",
        "request_packet",
        "request_packet_ref",
        "job_ref",
        "ai_provider_called",
        "source_code_modified",
        "next_commands",
        "pack_job",
    }
    assert expected_fields.issubset(payload)
    assert payload["ok"] is True
    assert payload["job_status"] == "waiting_for_ai_reply"
    assert payload["request_packet_ref"] == payload["request_packet"]
    assert payload["ai_provider_called"] is False
    assert payload["source_code_modified"] is False
    assert payload["selected_agents"]
    assert payload["selected_skills"]
    assert "npm test" in payload["validation_commands"]
    packet_path = tmp_path / payload["request_packet_ref"]
    assert packet_path.exists()
    assert (tmp_path / payload["job_ref"]).exists()
    packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
    assert "codex_claude_instruction" in packet
    assert "execution_contract" in packet
    assert packet["harness_summary"]["project_type"] == "custom_harness"
    assert packet["harness_summary"]["test_command"] == "npm test"
    assert "jest" in packet["harness_summary"]["stack"]
    assert "type : unknown" not in payload["pack_job"]["packet_preview"]
    assert "tests: none" not in payload["pack_job"]["packet_preview"]
    active_context = packet["active_pack_context"]
    assert active_context["codebase_evidence"]["status"] == "grounded"
    assert active_context["codebase_evidence"]["test_framework_evidence"]["framework"] == "jest"
    assert active_context["risk_boundaries"]["auto_apply"] is False
    assert "codebase_evidence.risk_boundaries" in active_context["evaluator_contract"]["evidence_required"]
    assert "backend/src/middleware/authMiddleware.ts" in active_context["agent_evidence_context"]["auth-flow-investigator"]["paths"]
    assert "risk boundary checked" in active_context["agent_evidence_context"]["auth-flow-investigator"]["validation_required"]
    assert active_context["company_structure"]["mode"] == "lean_project_company"
    assert active_context["company_blueprint"]["compiler_version"] == "company_os_compiler_v1"
    assert active_context["harness_os_contract"]["identity"] == "Cambrian Company OS"
    assert active_context["relearning_policy"]["auto_promote"] is False
    assert active_context["marketplace_boundary"]["sale_ready"] is False
    assert {"ceo-agent", "cto-agent", "coo-agent"}.issubset(set(active_context["project_discussion_layer"]["roles"]))
    assert active_context["project_discussion_layer"]["meeting_policy"]["source_mutation"] is False
    assert active_context["context_intent_snapshot"]["snapshot_kind"] == "context_intent_snapshot"
    assert active_context["context_intent_snapshot"]["context_policy"]["memory_is_not_context"] is True
    assert active_context["context_intent_snapshot"]["context_policy"]["discard_irrelevant_recent_memory"] is True
    assert active_context["context_intent_snapshot"]["quality_gate"]["target_product_level"] == "upper"
    assert active_context["company_structure"]["company_scale"]["target_lift_pct"] == 30
    assert active_context["company_structure"]["target_lift"]["pct"] == 30
    fit_report = active_context["company_structure"]["company_fit_report"]
    assert fit_report["target_lift_pct"] == 30
    assert fit_report["selected_agent_count"] == len(payload["selected_agents"])
    assert fit_report["selected_skill_count"] == len(payload["selected_skills"])
    assert fit_report["required_roles_present"]["context_manager"] is True
    assert fit_report["required_roles_present"]["verification_owner"] is True
    assert "context_manager" in active_context["company_structure"]["roles"]
    assert active_context["company_roles"]["execution_lead"]["agent_id"] in payload["selected_agents"]
    assert active_context["duplicate_guard"]["extra_agent_requires_codebase_evidence"] is True
    contract = packet["execution_contract"]
    assert contract["role"] == "Cambrian 프로젝트 AI 회사의 실행 엔진"
    assert contract["task"]
    assert contract["harness_id"] == payload["harness_id"]
    assert contract["workforce_id"] == payload["workforce_id"]
    assert contract["selected_agents"] == payload["selected_agents"]
    assert contract["selected_skills"] == payload["selected_skills"]
    assert contract["llm_invocation_required"] is True
    assert set(contract["llm_required_agents"]) == set(payload["selected_agents"])
    assert all(
        item["requires_llm_call"] is True
        for item in contract["agent_runtime_contracts"].values()
    )
    assert contract["codebase_evidence"]["status"] == "grounded"
    assert contract["agent_evidence_context"]["auth-flow-investigator"]["paths"]
    assert contract["risk_boundaries"]["auto_apply"] is False
    assert contract["evaluator_contract"]["evidence_required"]
    assert contract["company_structure"]["mode"] == "lean_project_company"
    assert contract["company_fit_report"]["target_lift_pct"] == 30
    assert contract["company_blueprint"]["product_position"]["cambrian_os"] == "core"
    assert contract["harness_os_contract"]["proof_boundary"]["proof_claim_allowed_without_runtime_evidence"] is False
    assert contract["relearning_policy"]["auto_evolve"] is False
    assert contract["marketplace_boundary"]["public_listing_allowed"] is False
    assert contract["project_discussion_layer"]["meeting_policy"]["auto_decision"] is False
    assert contract["context_intent_snapshot"]["context_policy"]["candidate_context_is_unapproved_signal"] is True
    assert contract["context_intent_snapshot"]["quality_gate"]["target_product_level"] == "upper"
    assert contract["company_fit_report"]["selected_agent_count"] == len(payload["selected_agents"])
    assert contract["company_roles"]["verification_owner"]["agent_id"] in payload["selected_agents"]
    assert contract["responsibility_matrix"]
    assert contract["duplicate_guard"]["unique_agent_count"] == contract["duplicate_guard"]["agent_count"]
    assert contract["manual_review_required"] is False
    assert "codebase evidence path citation" in packet["response_contract"]["evidence_required_keys"]
    assert "risk boundary check" in packet["response_contract"]["evidence_required_keys"]
    assert "validation command selection" in packet["response_contract"]["evidence_required_keys"]
    assert "context intent resolution" in packet["response_contract"]["evidence_required_keys"]
    assert "project discussion role check" in packet["response_contract"]["evidence_required_keys"]
    assert "llm invocation evidence" in packet["response_contract"]["evidence_required_keys"]
    assert "company_guidance" in packet["response_contract"]
    assert "npm test" in contract["validation_commands"]
    assert "패치를 적용했다고 말하지 않는다." in contract["must_not_do"]
    assert any("codebase_evidence" in item for item in contract["must_do"])
    assert any("AI company role" in item for item in contract["must_do"])
    assert any("company_fit_report" in item for item in contract["must_do"])
    assert any("company_blueprint" in item for item in contract["must_do"])
    assert any("project_discussion_layer" in item for item in contract["must_do"])
    assert any("relearning_policy" in item for item in contract["must_do"])
    assert any("context_intent_snapshot" in item for item in contract["must_do"])
    assert "codebase evidence" in packet["codex_claude_instruction"]
    assert "AI company roles" in packet["codex_claude_instruction"]
    assert "Project discussion layer:" in packet["codex_claude_instruction"]
    assert "Context intent:" in packet["codex_claude_instruction"]
    assert "company fit:" in payload["pack_job"]["packet_preview"]
    assert "target lift: 30%" in payload["pack_job"]["packet_preview"]
    assert "company os: company_os_compiler_v1" in payload["pack_job"]["packet_preview"]
    assert "project discussion:" in payload["pack_job"]["packet_preview"]
    assert "context intent:" in payload["pack_job"]["packet_preview"]
    assert contract["handoff_back"] == [
        "AI 응답을 ai_reply_patch_candidate.yaml 파일로 저장한다.",
        "cambrian job ingest latest ai_reply_patch_candidate.yaml",
        "cambrian job validate latest",
    ]


def test_job_start_keeps_required_company_roles_active_for_specialist_request(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"node --version","build":"node --version"},"devDependencies":{}}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "auth" / "session.ts").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "auth" / "session.ts").write_text("export function session() { return true }\n", encoding="utf-8")
    (tmp_path / "src" / "webhook" / "route.ts").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "webhook" / "route.ts").write_text("export function webhook() { return true }\n", encoding="utf-8")
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Review auth context and webhook signature handling safely.",
                    "test_command": f'"{sys.executable}" -c "print(\'ok\')"',
                    "build_command": "",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply"],
                    "important_paths": ["src/auth/session.ts", "src/webhook/route.ts"],
                    "validation_standard": "Validation command passes and role coverage is explicit.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "review", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "dry-run", "check webhook", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "install", "--confirm", "--json").returncode == 0

    result = run_cli(tmp_path, "job", "start", "check webhook signature only", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    packet = yaml.safe_load((tmp_path / payload["request_packet_ref"]).read_text(encoding="utf-8"))
    fit_report = packet["execution_contract"]["company_fit_report"]
    assert fit_report["required_roles_present"]["context_manager"] is True
    assert fit_report["required_roles_present"]["direction_owner"] is True
    assert fit_report["required_roles_present"]["verification_owner"] is True
    assert packet["execution_contract"]["company_roles"]["context_manager"]["agent_id"] in payload["selected_agents"]


def test_job_validate_run_executes_configured_validation_command(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    command = f'"{sys.executable}" -c "print(\'validation ok\')"'
    (tmp_path / ".cambrian" / "validation.yaml").write_text(
        yaml.safe_dump({"schema_version": "1.0.0", "validation": {"test_commands": [command]}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    start = run_cli(tmp_path, "job", "start", "run local validation command", "--json")
    assert start.returncode == 0, start.stderr

    result = run_cli(tmp_path, "job", "validate", "latest", "--run", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["validation_status"] == "passed"
    assert payload["validation_contract_status"] == "commands_executed"
    assert payload["manual_validation_required"] is False
    execution = payload["validation_command_execution"]
    assert execution["status"] == "passed"
    assert execution["results"][0]["status"] == "passed"
    assert "validation ok" in execution["results"][0]["stdout"]


def test_job_start_marks_weak_evidence_for_manual_review(tmp_path: Path) -> None:
    cambrian = tmp_path / ".cambrian"
    cambrian.mkdir(parents=True)
    (cambrian / "harness.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": "custom-weak-evidence",
                "type": "custom",
                "language": "typescript",
                "test_framework": "unknown",
                "policy": {"change_mode": "proposal_only", "auto_apply": False, "forbidden": ["no automatic patch apply"]},
                "domain_spec": {
                    "task_description": "weak evidence test",
                    "validation_commands": ["npm test"],
                    "pass_criteria": {"success_criteria": ["manual review required"]},
                },
                "codebase_evidence": {
                    "status": "weak",
                    "existing_important_paths": [],
                    "missing_important_paths": ["src/missing.ts"],
                    "domain_evidence": {},
                    "test_framework_evidence": {"status": "weak", "framework": "unknown"},
                    "risk_boundaries": {"requires_manual_approval": True, "auto_apply": False, "default_forbidden": [".env"]},
                },
                "evaluator_contract": {
                    "validation_commands": ["npm test"],
                    "success_criteria": ["manual review required"],
                    "evidence_required": ["codebase_evidence.existing_important_paths"],
                    "verdicts": ["pass", "hold", "rollback"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (cambrian / "validation.yaml").write_text(
        yaml.safe_dump({"schema_version": "1.0.0", "validation": {"test_commands": ["npm test"]}}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (cambrian / "agents.yaml").write_text(
        yaml.safe_dump({"schema_version": "1.0.0", "agents": [{"id": "root-cause-investigator"}]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "job", "start", "missing evidence issue", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    packet = yaml.safe_load((tmp_path / payload["request_packet_ref"]).read_text(encoding="utf-8"))
    contract = packet["execution_contract"]
    assert contract["evidence_status"] == "weak"
    assert contract["manual_review_required"] is True
    assert "manual review required" in contract["evidence_warnings"]
    assert any("manual review required" in item for item in contract["must_do"])
    assert packet["active_pack_context"]["codebase_evidence"]["status"] == "weak"


def test_job_start_packet_includes_evidence_card_domain_confidence_and_quality_gate(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "본체는 브라우저에서 AI 에이전트를 만들고 다운로드하는 독립 플랫폼이다. Cambrian은 선택형 런타임 후보로 둔다.",
        encoding="utf-8",
    )
    (tmp_path / "TODO.md").write_text("Builder -> agent-pack 다운로드 -> Import 검증\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<main>Builder Download agent-pack Workspace Preview</main>", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "verify_static_project.py").write_text(
        "def verify_words():\n    return 'send pipeline outbound delivery'\n",
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "브라우저에서 AI 에이전트를 만들고 agent pack으로 다운로드하는 플랫폼을 안전하게 개선한다.",
                    "test_command": "python tools/verify_static_project.py",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["Cambrian Runtime 본체로 취급 금지", "자동 patch apply 금지"],
                    "important_paths": ["AGENTS.md", "TODO.md", "index.html", "tools/verify_static_project.py"],
                    "validation_standard": "정적 검증이 통과하고 agent pack 다운로드 계약이 유지된다.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "review", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "dry-run", "Builder pack 다운로드 계약 점검", "--json").returncode == 0
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr

    result = run_cli(tmp_path, "job", "start", "Builder pack 다운로드 계약 점검", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    packet = yaml.safe_load((tmp_path / payload["request_packet_ref"]).read_text(encoding="utf-8"))
    context = packet["active_pack_context"]
    contract = packet["execution_contract"]
    assert context["evidence_card"]["identity_evidence"]
    assert context["domain_confidence"]["candidates"]["agent_marketplace_platform"]["confidence"] == "confirmed"
    assert context["domain_confidence"]["candidates"]["send_pipeline"]["confidence"] == "weak"
    assert context["quality_gate"]["status"] == "caution"
    assert context["manual_review_required"] is True
    assert "agent-platform-contract-reviewer" in payload["selected_agents"]
    assert "outbound-safety-reviewer" not in payload["selected_agents"]
    assert contract["quality_gate"]["status"] == "caution"
    assert any("domain_confidence" in item for item in contract["must_do"])
    assert any("weak keyword evidence" in item for item in packet["response_contract"]["evidence_guidance"])


def test_job_start_prioritizes_selected_agent_domain_evidence(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}',
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "webhookHandler.ts").write_text(
        "export function verifyWebhook(rawBody: string, signature: string) { return rawBody.includes('webhook') && Boolean(signature) }\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "outboundSender.ts").write_text(
        "export function sendCampaign(recipient: string, suppression: Set<string>) { return suppression.has(recipient) ? 'blocked' : 'send' }\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "webhookHandler.test.ts").write_text("test('webhook', () => {})\n", encoding="utf-8")
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Review webhook signature and outbound safety separately.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply"],
                    "important_paths": ["src/webhookHandler.ts", "src/outboundSender.ts", "tests/webhookHandler.test.ts"],
                    "validation_standard": "Relevant Jest tests pass and risk is explained.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "review", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "dry-run", "webhook signature issue", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "install", "--confirm", "--json").returncode == 0

    result = run_cli(tmp_path, "job", "start", "webhook signature issue", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    packet = yaml.safe_load((tmp_path / payload["request_packet_ref"]).read_text(encoding="utf-8"))
    webhook_context = packet["execution_contract"]["agent_evidence_context"]["webhook-signature-reviewer"]
    assert "src/webhookHandler.ts" in webhook_context["paths"]
    assert "src/outboundSender.ts" not in webhook_context["paths"]
    assert "webhook-signature-reviewer" in packet["execution_contract"]["selected_agents"]


def test_job_ingest_accepts_nested_patch_candidate_without_applying(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    source_path = tmp_path / "backend" / "src" / "middleware" / "authMiddleware.ts"
    source_before = source_path.read_text(encoding="utf-8")
    start = run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "ai_reply_patch_candidate.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "reason": "Authorization 헤더에서 Bearer 접두사를 제거해야 한다.",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["reply_kind"] == "patch_candidate"
    assert payload["reply_contract_status"] == "accepted_patch_candidate"
    assert payload["reply_evidence_compliance"]["status"] == "incomplete"
    assert "codebase_evidence_path_citation" in payload["reply_evidence_compliance"]["missing"]
    assert payload["status"] == "validation_ready"
    assert payload["patch_candidate_accepted"] is True
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert payload["ai_provider_called"] is False
    assert payload["request_packet_ref"]
    assert payload["reply_file_ref"]
    assert payload["patch_intent_ref"]
    assert "cambrian job validate" in "\n".join(payload["next_commands"])
    assert source_path.read_text(encoding="utf-8") == source_before
    reply = yaml.safe_load((tmp_path / payload["bridge_reply_ref"]).read_text(encoding="utf-8"))
    assert reply["content"]["target_path"] == "backend/src/middleware/authMiddleware.ts"
    assert reply["source_reply_path"] == "ai_reply_patch_candidate.yaml"


def test_job_ingest_records_satisfied_reply_evidence_compliance(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    start = run_cli(tmp_path, "job", "start", "login session expiry issue", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "ai_reply_patch_candidate.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "reason": "Authorization header must strip the Bearer prefix.",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
                "codebase_evidence_paths": ["backend/src/middleware/authMiddleware.ts"],
                "risk_boundary_check": "auto_apply false and forbidden paths checked",
                    "validation_command_selection": {
                        "command": "npm test",
                        "reason": "Jest is the detected test framework for this harness.",
                    },
                "patch_application_state": {
                    "patch_applied": False,
                    "source_code_modified": False,
                    "summary": "proposal_only reply; no source mutation was performed",
                },
                "verdict_rationale": "The proposal cites the auth middleware path, stays inside risk boundaries, and selects npm test for validation.",
                "context_intent_resolution": {
                    "resolved": True,
                    "intent": "bug_fix",
                    "reason": "The request asks about login session expiry.",
                },
                "project_discussion_role_check": {
                    "checked": True,
                    "role": "cto-agent",
                    "reason": "This is a technical execution issue, not a product direction change.",
                },
                "llm_invocation_evidence": {
                    "called": True,
                    "mode": "external_ai_worker",
                    "provider": "codex",
                    "agent_ids": ["auth-flow-investigator", "jest-regression-guardian", "risk-reviewer"],
                    "summary": "The reply was produced by the external AI worker for the selected generated AI agents.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")
    assert ingest.returncode == 0, ingest.stderr
    ingest_payload = json.loads(ingest.stdout)
    assert ingest_payload["reply_evidence_compliance"]["status"] == "satisfied"
    assert ingest_payload["reply_evidence_compliance"]["missing"] == []
    assert "backend/src/middleware/authMiddleware.ts" in ingest_payload["reply_evidence_compliance"]["evidence_paths"]
    assert ingest_payload["reply_evidence_compliance"]["context_intent_resolved"] is True
    assert ingest_payload["reply_evidence_compliance"]["patch_application_state"]["stated"] is True
    assert ingest_payload["reply_evidence_compliance"]["verdict_rationale"]

    validate = run_cli(tmp_path, "job", "validate", "latest", "--json")
    assert validate.returncode != 0
    validate_payload = json.loads(validate.stdout)
    assert validate_payload["reply_evidence_compliance"]["status"] == "satisfied"
    evidence = yaml.safe_load((tmp_path / validate_payload["evidence_ref"]).read_text(encoding="utf-8"))
    assert evidence["reply_evidence_compliance"]["status"] == "satisfied"


def test_job_ingest_requires_llm_invocation_evidence_for_ai_agents(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    start = run_cli(tmp_path, "job", "start", "login session expiry issue", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "ai_reply_patch_candidate.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "reason": "Authorization header must strip the Bearer prefix.",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
                "codebase_evidence_paths": ["backend/src/middleware/authMiddleware.ts"],
                "risk_boundary_check": "auto_apply false and forbidden paths checked",
                "validation_command_selection": {
                    "command": "npm test",
                    "reason": "Jest is the detected test framework for this harness.",
                },
                "patch_application_state": {
                    "patch_applied": False,
                    "source_code_modified": False,
                    "summary": "proposal_only reply; no source mutation was performed",
                },
                "verdict_rationale": "The proposal cites the auth middleware path, stays inside risk boundaries, and selects npm test for validation.",
                "context_intent_resolution": {
                    "resolved": True,
                    "intent": "bug_fix",
                    "reason": "The request asks about login session expiry.",
                },
                "project_discussion_role_check": {
                    "checked": True,
                    "role": "cto-agent",
                    "reason": "This is a technical execution issue, not a product direction change.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    compliance = payload["reply_evidence_compliance"]
    assert compliance["status"] == "incomplete"
    assert "llm_invocation_evidence" in compliance["required"]
    assert compliance["missing"] == ["llm_invocation_evidence"]
    assert compliance["llm_invocation_evidence"]["satisfied"] is False
    assert compliance["manual_review_required"] is True


def test_job_validate_returns_trust_gate_and_evidence_for_manual_custom_validation(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    start = run_cli(tmp_path, "job", "start", "login session expiry issue", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "ai_reply_patch_candidate.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "reason": "Authorization header must strip the Bearer prefix.",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")
    assert ingest.returncode == 0, ingest.stderr

    result = run_cli(tmp_path, "job", "validate", "latest", "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["validation_status"] == "not_ready"
    assert payload["validation_contract_status"] == "manual_validation_required"
    assert payload["trust_gate_status"] == "manual_required"
    assert payload["manual_validation_required"] is True
    assert "npm test" in payload["validation_commands"]
    assert payload["evidence_ref"]
    assert (tmp_path / payload["evidence_ref"]).exists()
    assert payload["request_packet_ref"]
    assert payload["reply_file_ref"]
    assert payload["patch_intent_ref"]
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert payload["ai_provider_called"] is False
    assert payload["reply_evidence_compliance"]["status"] == "incomplete"
    assert "risk_boundary_check" in payload["reply_evidence_compliance"]["missing"]
    assert payload["relearning_gate"]["status"] == "review_required"
    assert payload["relearning_gate"]["recommended_action"] == "revise"
    assert "reply evidence compliance incomplete" in payload["relearning_gate"]["triggers"]
    assert payload["outcome_snapshot"]["company_structure"]["company_fit_report"]["target_lift_pct"] == 30
    assert payload["outcome_snapshot"]["company_structure"]["company_fit_report"]["selected_agent_count"] == len(
        payload["outcome_snapshot"]["selected_agents"]
    )
    assert "npm test" in payload["outcome_snapshot"]["company_structure"]["company_fit_report"]["validation_commands"]
    assert any("AI reply evidence compliance incomplete" in item for item in payload["unchecked_items"])
    assert any(item.endswith("ai_reply_patch_candidate.yaml") for item in payload["checked_artifacts"])
    assert "Patch proposal was not applied to source code" not in payload["unchecked_items"]
    assert "patch_application_state" in payload["reply_evidence_compliance"]["missing"]
    assert "verdict_rationale" in payload["reply_evidence_compliance"]["missing"]
    assert "cambrian job complete" in "\n".join(payload["next_commands"])
    evidence = yaml.safe_load((tmp_path / payload["evidence_ref"]).read_text(encoding="utf-8"))
    assert evidence["trust_gate_status"] == "manual_required"
    assert evidence["source_code_modified"] is False
    assert evidence["reply_evidence_compliance"]["status"] == "incomplete"
    assert evidence["relearning_gate"]["auto_promote"] is False
    assert evidence["outcome_snapshot"]["company_structure"]["company_fit_report"]["target_lift_pct"] == 30


def test_success_outcome_requires_passed_validation_and_clean_envelope() -> None:
    from engine.project_custom_harness import _outcome_verdict_from_evidence

    assert _outcome_verdict_from_evidence(
        manual_outcome="success",
        validation_status="passed",
        has_validation_evidence=True,
        unchecked_items=[],
    ) == ("pass", "manual_outcome_success_with_verified_evidence", None)
    assert _outcome_verdict_from_evidence(
        manual_outcome="success",
        validation_status="not_ready",
        has_validation_evidence=True,
        unchecked_items=[],
    )[0] == "hold"
    assert _outcome_verdict_from_evidence(
        manual_outcome="success",
        validation_status="passed",
        has_validation_evidence=True,
        unchecked_items=["AI reply evidence compliance incomplete: verdict_rationale"],
    )[0] == "hold"


def test_job_ingest_blocks_invalid_patch_candidate_with_contract_error(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    start = run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "bad_reply.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Missing new text",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "old_text": "export function auth() {}",
                    "reason": "new_text 누락 테스트",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "job", "ingest", "latest", "bad_reply.yaml", "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["reply_contract_status"] == "blocked"
    assert payload["patch_candidate_accepted"] is False
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert "new_text is required for patch_candidate" in "\n".join(payload["errors"])
