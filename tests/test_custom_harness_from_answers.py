from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_agent_dispatch import AgentDispatcher
from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_engineering import build_harness_quality_gate, design_harness_candidate, dry_run_harness_candidate, review_harness_candidate
from engine.project_harness_plan import HarnessInstaller, HarnessPlanner
from engine.project_skill_builder import build_skill_payloads, skill_mapping
from engine.project_workforce_builder import build_agent_payloads, build_workforce_payload


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _complete_answers(root: Path) -> None:
    HarnessInterviewBuilder().start(root)
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "ONMI-STAY의 인증/예약 관련 버그를 안정적으로 수정하고 검증한다.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": ["관련 테스트 통과", "기존 인증 흐름 회귀 없음"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = HarnessInterviewAnswerHandler().answer(root, path)
    assert result.status == "ready_for_plan"


def test_custom_harness_plan_install_and_dispatch_from_answers(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _complete_answers(tmp_path)

    plan = HarnessPlanner().build(tmp_path)
    assert plan.plan_type == "custom"
    assert plan.status == "draft"
    assert plan.harness_id is not None
    assert plan.harness_id.startswith("custom-")
    assert plan.validation["policy"] == "proposal_only"

    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"
    install = HarnessInstaller().install(tmp_path, confirm=True)
    assert install.status == "installed"

    harness = yaml.safe_load((tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8"))
    assert harness["type"] == "custom"
    assert harness["policy"]["auto_apply"] is False
    assert harness["domain_spec"]["task_description"] == "ONMI-STAY의 인증/예약 관련 버그를 안정적으로 수정하고 검증한다."
    assert harness["domain_spec"]["validation_commands"] == ["npm test", "npm run build"]
    assert harness["codebase_evidence"]["status"] == "grounded"
    assert "backend/src/middleware/authMiddleware.ts" in harness["codebase_evidence"]["existing_important_paths"]
    assert harness["domain_spec"]["codebase_evidence_status"] == "grounded"
    assert harness["domain_spec"]["test_framework_evidence"]["framework"] == "jest"
    assert harness["domain_spec"]["risk_boundaries"]["auto_apply"] is False
    assert "codebase_evidence.risk_boundaries" in harness["evaluator_contract"]["evidence_required"]
    assert harness["evaluator_contract"]["verdicts"] == ["pass", "hold", "rollback"]
    assert harness["candidate_lineage"]["generation_id"] == "installed-initial"
    assert {"ceo-agent", "cto-agent", "coo-agent"}.issubset(set(harness["project_discussion_layer"]["roles"]))
    assert harness["project_discussion_layer"]["meeting_policy"]["auto_decision"] is False
    assert (tmp_path / ".cambrian" / "company" / "discussion" / "agents.yaml").exists()
    validation = yaml.safe_load((tmp_path / ".cambrian" / "validation.yaml").read_text(encoding="utf-8"))
    assert validation["validation"]["test_commands"] == ["npm test", "npm run build"]

    dispatch = AgentDispatcher().dispatch(tmp_path, "로그인 에러 수정해")
    payload = dispatch.to_dict()
    assert payload["ok"] is True
    assert payload["harness_id"] == plan.harness_id
    assert payload["change_policy"] == "proposal_only"
    assert payload["job_id"].startswith("job-custom-")


def test_generated_agents_have_distinct_contracts_for_auth_api_jest_risk() -> None:
    plan = {
        "harness_id": "custom-sample-auth-api",
        "project": {
            "domains": ["auth", "api", "tests"],
            "language": "typescript",
            "test_framework": "jest",
        },
        "validation": {
            "test_commands": ["npm test"],
        },
        "policy": {
            "forbidden": ["no automatic patch apply"],
        },
        "important_paths": ["backend/src/routes/auth.ts", "backend/tests/auth.test.ts"],
    }

    agents = build_agent_payloads(plan)
    by_id = {agent["id"]: agent for agent in agents}

    for agent_id in ["auth-flow-investigator", "jest-regression-guardian", "api-contract-reviewer", "risk-reviewer"]:
        assert agent_id in by_id
    signatures = {
        (
            tuple(agent.get("inputs", [])),
            tuple(agent.get("outputs", [])),
            tuple(agent.get("validation", {}).get("required", [])),
        )
        for agent in by_id.values()
    }
    assert len(signatures) == len(by_id)
    assert "auth boundary map" in by_id["auth-flow-investigator"]["outputs"]
    assert "Jest command plan" in by_id["jest-regression-guardian"]["outputs"]
    assert "API contract risk notes" in by_id["api-contract-reviewer"]["outputs"]
    assert "operational risk register" in by_id["risk-reviewer"]["outputs"]


def test_generated_workforce_maps_lean_company_roles_without_duplicate_agents() -> None:
    plan = {
        "harness_id": "custom-sample-auth-api",
        "project": {
            "domains": ["auth", "api", "tests"],
            "language": "typescript",
            "test_framework": "jest",
        },
        "validation": {
            "test_commands": ["npm test"],
        },
        "policy": {
            "forbidden": ["no automatic patch apply"],
        },
        "important_paths": ["backend/src/routes/auth.ts", "backend/tests/auth.test.ts"],
        "codebase_evidence": {
            "status": "grounded",
            "existing_important_paths": ["backend/src/routes/auth.ts", "backend/tests/auth.test.ts"],
            "domain_evidence": {
                "auth": ["backend/src/routes/auth.ts"],
                "api": ["backend/src/routes/auth.ts"],
                "tests": ["backend/tests/auth.test.ts"],
            },
            "test_framework_evidence": {
                "framework": "jest",
                "test_paths": ["backend/tests/auth.test.ts"],
            },
            "risk_boundaries": {
                "auto_apply": False,
                "requires_manual_approval": True,
            },
        },
    }

    workforce = build_workforce_payload(plan)
    company = workforce["company_structure"]
    roles = company["roles"]

    assert company["mode"] == "lean_project_company"
    assert company["status"] == "ready"
    assert {"context_manager", "direction_owner", "execution_lead", "verification_owner"}.issubset(set(roles))
    assert roles["context_manager"]["agent_id"] in workforce["agents"]
    assert roles["execution_lead"]["agent_id"] in workforce["agents"]
    assert roles["verification_owner"]["agent_id"] == "jest-regression-guardian"
    assert roles["specialist_api_contract_reviewer"]["agent_id"] == "api-contract-reviewer"
    assert workforce["duplicate_guard"]["agent_count"] == len(workforce["agents"])
    assert workforce["duplicate_guard"]["unique_agent_count"] == len(set(workforce["agents"]))
    assert workforce["duplicate_guard"]["extra_agent_requires_codebase_evidence"] is True
    assert workforce["responsibility_matrix"][roles["verification_owner"]["agent_id"]] == ["verification_owner"]


def test_explicit_interview_roles_drive_company_agents_and_skills() -> None:
    plan = {
        "harness_id": "custom-stay-ledger-generator-work",
        "project": {
            "domains": ["tests"],
            "language": "python",
            "test_framework": "pytest",
        },
        "agents": [
            {"id": "custom-agent-1", "role": "ledger-generation-reviewer: Excel ledger generation and template contract review"},
            {"id": "custom-agent-2", "role": "web-input-flow-reviewer: FastAPI form input and download response review"},
            {"id": "custom-agent-3", "role": "pytest-regression-guardian: pytest regression command owner"},
            {"id": "custom-agent-4", "role": "risk-boundary-reviewer: outputs/logs/template mutation risk owner"},
        ],
        "validation": {
            "test_commands": ["python -m pytest tests/test_generator.py"],
        },
        "policy": {
            "forbidden": ["do not edit generated outputs", "no automatic patch apply"],
        },
        "important_paths": ["app/main.py", "app/generator.py", "templates/stay_hotel_master.xlsx", "tests/test_generator.py"],
        "codebase_evidence": {
            "status": "grounded",
            "existing_important_paths": ["app/main.py", "app/generator.py", "templates/stay_hotel_master.xlsx", "tests/test_generator.py"],
            "domain_confidence": {
                "candidates": {
                    "tests": {"confidence": "suspected", "evidence": ["tests/test_generator.py"]},
                },
            },
            "domain_evidence": {
                "tests": ["tests/test_generator.py"],
            },
            "test_framework_evidence": {
                "framework": "pytest",
                "test_paths": ["tests/test_generator.py"],
            },
            "risk_boundaries": {
                "auto_apply": False,
                "requires_manual_approval": True,
            },
        },
    }

    agents = build_agent_payloads(plan)
    agent_ids = [agent["id"] for agent in agents]
    workforce = build_workforce_payload(plan)
    skills = build_skill_payloads(plan, workforce)
    mapping = skill_mapping(skills)
    roles = workforce["company_structure"]["roles"]
    gate = build_harness_quality_gate(
        {
            "project_profile": plan["project"],
            "validation": plan["validation"],
            "workforce": {"agents": agents},
            "codebase_evidence": plan["codebase_evidence"],
        }
    )

    assert agent_ids == [
        "ledger-generation-reviewer",
        "web-input-flow-reviewer",
        "pytest-regression-guardian",
        "risk-boundary-reviewer",
    ]
    assert roles["execution_lead"]["agent_id"] == "ledger-generation-reviewer"
    assert roles["verification_owner"]["agent_id"] == "pytest-regression-guardian"
    assert roles["direction_owner"]["agent_id"] == "risk-boundary-reviewer"
    assert "trace-failure-flow" in mapping["ledger-generation-reviewer"]
    assert "inspect-pytest-regression" in mapping["pytest-regression-guardian"]
    assert "review-regression-risk" in mapping["risk-boundary-reviewer"]
    assert "propose-safe-patch" in mapping["risk-boundary-reviewer"]
    assert "root-cause-investigator" not in agent_ids
    assert gate["status"] == "caution"
    assert gate["manual_review_required"] is True
    assert "tests/api evidence cannot define harness identity" in " ".join(gate["warnings"])


def test_avf_custom_roles_install_specific_harness_agents_and_policy(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "avf.py", "from core.orchestrator import process\n")
    _write(tmp_path / "core" / "orchestrator.py", "def process(stage):\n    return stage\n")
    _write(tmp_path / "core" / "ddmq.py", "class DDMQ:\n    HALT_STAGES = {2}\n")
    _write(tmp_path / "core" / "schema_registry.py", "STAGE_SCHEMAS = {'stage1': {}, 'stage2': {}}\n")
    _write(tmp_path / "core" / "validators" / "schema_validator.py", "def validate(data, stage):\n    return True\n")
    _write(tmp_path / "plugins" / "stage1_seeker.py", "STAGE_NAME = 'stage1'\n")
    _write(tmp_path / "plugins" / "stage2_gatekeeper.py", "ANTHROPIC_MODEL = 'claude'\n")
    _write(tmp_path / "plugins" / "stage3_builder.py", "def build():\n    return None\n")
    _write(tmp_path / "tests" / "test_pipeline.py", "def test_pipeline():\n    assert True\n")

    HarnessInterviewBuilder().start(tmp_path)
    answers_path = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "avf-one-good-harness",
                "answers": {
                    "primary_goal": "AVF Stage 1-5 pipeline harness: debug DDMQ, Anthropic API failures, stage schema validation, and pytest proof.",
                    "test_command": "python -m pytest tests/ -v",
                    "change_policy": "자동 적용 금지, 제안까지만",
                    "forbidden_scope": [".env", "API keys", "git push", "automatic source mutation"],
                    "important_paths": [
                        "avf.py",
                        "core/orchestrator.py",
                        "core/ddmq.py",
                        "core/schema_registry.py",
                        "core/validators/schema_validator.py",
                        "plugins/stage2_gatekeeper.py",
                        "tests/test_pipeline.py",
                    ],
                    "agent_roles": [
                        "DDMQ debugger: inspect dropzone queues, stage handoff, archive, errors, and duplicate event risks",
                        "Anthropic API error analyst: classify provider failures, key absence, rate limits, and response parsing errors",
                        "Stage schema validator: verify STAGE_SCHEMAS, schema_validator, Null Mandate, and Stage 2 HALT",
                        "pytest regression guardian: own pytest command selection and regression evidence",
                        "risk boundary reviewer: guard .env, API keys, outbound/payment side effects, and proof claims",
                    ],
                    "validation_standard": [
                        "pytest command is selected",
                        "DDMQ paths are cited",
                        "stage schema compatibility is checked",
                        "unproven completion is blocked",
                    ],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert HarnessInterviewAnswerHandler().answer(tmp_path, answers_path).status == "ready_for_plan"
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "debug AVF stage pipeline failure").status == "ready_for_install"

    install = HarnessInstaller().install(tmp_path, confirm=True)

    assert install.status == "installed"
    harness = yaml.safe_load((tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8"))
    workforce = yaml.safe_load((tmp_path / ".cambrian" / "workforce.yaml").read_text(encoding="utf-8"))
    installed_skills = {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in (tmp_path / ".cambrian" / "skills").glob("*.yaml")
    }
    agent_ids = set(workforce["agents"])
    assert harness["policy"]["change_mode"] == "proposal_only"
    assert "auth" not in harness["id"]
    assert {
        "ddmq-debugger",
        "anthropic-api-error-analyst",
        "stage-schema-validator",
        "pytest-regression-guardian",
        "risk-boundary-reviewer",
    }.issubset(agent_ids)
    assert "debug-ddmq-queue-flow" in installed_skills
    assert installed_skills["debug-ddmq-queue-flow"]["assigned_agents"] == ["ddmq-debugger"]
    assert "review-anthropic-api-errors" in installed_skills
    assert "validate-stage-schema-contract" in installed_skills


def test_complex_project_builds_project_fit_company_with_specialists() -> None:
    plan = {
        "harness_id": "custom-icp-engine-work",
        "project": {
            "domains": ["webhook", "suppression", "send_pipeline", "outbound", "supabase", "scoring", "customer", "api", "tests"],
            "language": "typescript",
            "test_framework": "jest",
        },
        "validation": {
            "test_commands": ["npm test", "npm run build"],
        },
        "policy": {
            "forbidden": ["do not edit applied migrations", "no automatic patch apply"],
        },
        "important_paths": [
            "src/outboundWorker.ts",
            "src/webhook.ts",
            "src/scorecard.ts",
            "src/supabaseClient.ts",
            "src/api/routes.ts",
            "tests/outboundWorker.test.ts",
            "tests/webhook.test.ts",
            "supabase/migrations/001.sql",
            "README.md",
            "package.json",
        ],
        "codebase_evidence": {
            "status": "grounded",
            "existing_important_paths": [
                "src/outboundWorker.ts",
                "src/webhook.ts",
                "src/scorecard.ts",
                "src/supabaseClient.ts",
                "src/api/routes.ts",
                "tests/outboundWorker.test.ts",
                "tests/webhook.test.ts",
                "supabase/migrations/001.sql",
                "README.md",
                "package.json",
            ],
            "domain_confidence": {
                "candidates": {
                    "webhook": {"confidence": "confirmed", "evidence": ["src/webhook.ts"]},
                    "suppression": {"confidence": "confirmed", "evidence": ["src/outboundWorker.ts"]},
                    "send_pipeline": {"confidence": "confirmed", "evidence": ["src/outboundWorker.ts"]},
                    "outbound": {"confidence": "confirmed", "evidence": ["src/outboundWorker.ts"]},
                    "supabase": {"confidence": "confirmed", "evidence": ["src/supabaseClient.ts"]},
                    "scoring": {"confidence": "confirmed", "evidence": ["src/scorecard.ts"]},
                    "customer": {"confidence": "confirmed", "evidence": ["src/scorecard.ts"]},
                    "api": {"confidence": "suspected", "evidence": ["src/api/routes.ts"]},
                    "tests": {"confidence": "suspected", "evidence": ["tests/outboundWorker.test.ts"]},
                },
            },
            "domain_evidence": {
                "webhook": ["src/webhook.ts"],
                "suppression": ["src/outboundWorker.ts"],
                "send_pipeline": ["src/outboundWorker.ts"],
                "outbound": ["src/outboundWorker.ts"],
                "supabase": ["src/supabaseClient.ts", "supabase/migrations/001.sql"],
                "scoring": ["src/scorecard.ts"],
                "customer": ["src/scorecard.ts"],
                "api": ["src/api/routes.ts"],
                "tests": ["tests/outboundWorker.test.ts", "tests/webhook.test.ts"],
            },
            "test_framework_evidence": {
                "framework": "jest",
                "test_paths": ["tests/outboundWorker.test.ts", "tests/webhook.test.ts"],
            },
            "risk_boundaries": {
                "auto_apply": False,
                "requires_manual_approval": True,
                "external_systems": ["supabase", "webhook_provider", "outbound_delivery", "api_clients"],
            },
        },
    }

    agents = build_agent_payloads(plan)
    agent_ids = [agent["id"] for agent in agents]
    workforce = build_workforce_payload(plan)
    company = workforce["company_structure"]
    roles = company["roles"]
    skills = build_skill_payloads(plan, workforce)
    mapping = skill_mapping(skills)

    assert company["mode"] == "project_fit_company"
    assert company["company_scale"]["company_size"] == "departmental"
    assert company["duplicate_guard"]["max_agents"] == 8
    assert company["target_lift"]["pct"] == 30
    for expected in [
        "webhook-signature-reviewer",
        "outbound-safety-reviewer",
        "supabase-schema-reviewer",
        "scorecard-logic-reviewer",
        "jest-regression-guardian",
        "api-contract-reviewer",
        "risk-reviewer",
    ]:
        assert expected in agent_ids
        assert expected in workforce["responsibility_matrix"]
        assert expected in mapping
    assert roles["specialist_outbound_safety_reviewer"]["agent_id"] == "outbound-safety-reviewer"
    assert roles["specialist_supabase_schema_reviewer"]["agent_id"] == "supabase-schema-reviewer"
    assert roles["specialist_scorecard_logic_reviewer"]["agent_id"] == "scorecard-logic-reviewer"
    assert "trace-webhook-hmac" in mapping["webhook-signature-reviewer"]
    assert "review-supabase-migrations" in mapping["supabase-schema-reviewer"]
    assert "trace-scorecard-logic" in mapping["scorecard-logic-reviewer"]
