from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def make_typescript_auth_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "routes" / "auth.ts", "export function authRoute() {}\n")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def write_complete_answers(root: Path) -> None:
    answers = root / ".cambrian" / "interview" / "answers.yaml"
    answers.parent.mkdir(parents=True, exist_ok=True)
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Investigate auth and reservation bugs safely.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply", "no DB schema changes"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": "Relevant Jest tests pass and regression risk is explained.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def prepare_engineering_project(root: Path) -> None:
    make_typescript_auth_project(root)
    assert run_cli(root, "project", "scan", "--json").returncode == 0
    assert run_cli(root, "harness", "interview", "start", "--json").returncode == 0
    write_complete_answers(root)
    assert run_cli(root, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0


def pass_engineering_gate(root: Path) -> tuple[dict, dict, dict]:
    design = run_cli(root, "harness", "engineer", "design", "--json")
    assert design.returncode == 0, design.stderr
    review = run_cli(root, "harness", "engineer", "review", "--json")
    assert review.returncode == 0, review.stderr
    dry_run = run_cli(root, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json")
    assert dry_run.returncode == 0, dry_run.stderr
    return json.loads(design.stdout), json.loads(review.stdout), json.loads(dry_run.stdout)


def test_harness_bootstrap_requests_answers_when_missing(tmp_path: Path) -> None:
    make_typescript_auth_project(tmp_path)

    result = run_cli(tmp_path, "harness", "bootstrap", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "answers_required"
    assert payload["answers_ref"] == ".cambrian/interview/answers.yaml"
    assert payload["answers_draft_ref"] == ".cambrian/interview/answers.draft.yaml"
    assert payload["assistant_handoff_prompt_ref"] == ".cambrian/interview/assistant_bootstrap_prompt.md"
    assert (tmp_path / ".cambrian" / "interview" / "questions.yaml").exists()
    draft = yaml.safe_load((tmp_path / ".cambrian" / "interview" / "answers.draft.yaml").read_text(encoding="utf-8"))
    assert draft["draft_status"] == "review_required"
    assert draft["draft_policy"]["auto_install_allowed"] is False
    assert draft["answers"]["test_command"] == "npm test"
    assert draft["answers"]["change_policy"] == "proposal_only"
    assert "backend/src/middleware/authMiddleware.ts" in draft["answers"]["important_paths"]
    prompt = (tmp_path / ".cambrian" / "interview" / "assistant_bootstrap_prompt.md").read_text(encoding="utf-8")
    assert "Cambrian Harness Bootstrap Handoff" in prompt
    assert "answers.draft.yaml" in prompt
    assert ".env" in prompt
    assert "answers.yaml" in prompt
    assert "cambrian harness bootstrap" in prompt
    assert any("harness bootstrap" in item for item in payload["next_commands"])


def test_harness_bootstrap_installs_and_starts_job(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)

    result = run_cli(
        tmp_path,
        "harness",
        "bootstrap",
        "--confirm",
        "--request",
        "로그인 세션 검증 위험을 점검해줘",
        "--start-job",
        "로그인 세션 검증 위험을 evidence 기반으로 분석해줘",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "installed"
    assert payload["harness_id"].startswith("custom-")
    assert payload["generated_agents"]
    assert payload["company_export_manifest_ref"] == ".cambrian/company/export_manifest.yaml"
    assert [step["step"] for step in payload["steps"]] == [
        "project_scan",
        "interview_start",
        "interview_answer",
        "engineer_design",
        "engineer_review",
        "engineer_dry_run",
        "harness_install",
        "job_start",
    ]
    packet_ref = payload["pack_job"]["packet_ref"]
    packet = yaml.safe_load((tmp_path / packet_ref).read_text(encoding="utf-8"))
    assert packet["execution_contract"]["context_intent_snapshot"]["context_policy"]["memory_is_not_context"] is True
    assert packet["execution_contract"]["context_intent_snapshot"]["quality_gate"]["target_product_level"] == "upper"


def test_harness_bootstrap_preserves_mission_company_identity_over_auth_scan(tmp_path: Path) -> None:
    make_typescript_auth_project(tmp_path)
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "mission-company-identity-test",
                "answers": {
                    "primary_goal": "Install a 24-hour mission company that opens bounded jobs and syncs only linked outcomes.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply", "no provider calls"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": ["mission job bridge is verified", "linked outcome sync is verified"],
                    "agent_roles": [
                        "mission-control-architect",
                        "evidence-gate-reviewer",
                        "release-loop-qa",
                        "safety-boundary-reviewer",
                    ],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        tmp_path,
        "harness",
        "bootstrap",
        "--answers",
        ".cambrian/interview/answers.yaml",
        "--request",
        "Verify the mission company install boundary.",
        "--confirm",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["harness_id"].endswith("-mission-company")
    assert "auth" not in payload["harness_id"]
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    harness = yaml.safe_load((tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8"))
    assert candidate["harness"]["id"] == payload["harness_id"]
    assert harness["id"] == payload["harness_id"]
    assert "mission-control-architect" in payload["generated_agents"]
    assert any(skill in payload["generated_skills"] for skill in ["inspect-pytest-regression", "inspect-jest-regression"])
    assert "inspect-pytest-auth-test" not in payload["generated_skills"]
    assert "inspect-jest-auth-test" not in payload["generated_skills"]


def test_harness_engineer_design_creates_candidate(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)

    result = run_cli(tmp_path, "harness", "engineer", "design", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "candidate"
    assert payload["harness_id"].startswith("custom-")
    assert payload["quality_score"] >= 70
    assert ".cambrian/harness.yaml" in payload["generated_files_preview"]
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    assert candidate["harness"]["type"] == "custom"
    assert 3 <= len(candidate["workforce"]["agents"]) <= 5
    assert candidate["skills"]
    assert candidate["domain_spec"]["task_description"] == "Investigate auth and reservation bugs safely."
    assert candidate["domain_spec"]["validation_commands"] == ["npm test", "npm run build"]
    assert candidate["evaluator_contract"]["verdicts"] == ["pass", "hold", "rollback"]
    assert candidate["candidate_lineage"]["generation_id"] == "initial"
    assert candidate["execution_boundary"]["approval_policy"] == "explicit"
    assert candidate["company_blueprint"]["compiler_version"] == "company_os_compiler_v1"
    assert candidate["company_blueprint"]["product_position"]["cambrian_os"] == "core"
    assert candidate["company_blueprint"]["product_position"]["auto_development"] == "execution_layer"
    assert candidate["company_blueprint"]["marketplace_boundary"]["sale_ready"] is False
    assert {"ceo-agent", "cto-agent", "coo-agent"}.issubset(set(candidate["project_discussion_layer"]["roles"]))
    assert "project_discussion_layer" in candidate["company_blueprint"]["harness_os"]["required_contracts"]
    assert candidate["harness_os_contract"]["identity"] == "Cambrian Company OS"
    assert "project_discussion_layer" in candidate["harness_os_contract"]["required_context_layers"]
    assert candidate["relearning_policy"]["auto_promote"] is False
    assert candidate["marketplace_boundary"]["public_listing_allowed"] is False


def test_harness_engineer_design_uses_codebase_evidence_for_icp_domains(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(tmp_path / "tsconfig.json", "{}")
    _write(
        tmp_path / "src" / "outboundWorker.ts",
        """
        import { createClient } from '@supabase/supabase-js'

        export function verifyWebhook(rawBody: string, signature: string) {
          return Boolean(signature) && rawBody.includes('webhook')
        }

        export function scoreCustomer(customer: { icp: string }) {
          const scorecard = customer.icp === 'enterprise' ? 100 : 10
          return scorecard
        }

        export async function sendCampaign(recipient: string, suppressionList: Set<string>) {
          if (suppressionList.has(recipient)) return 'blocked'
          return createClient('url', 'anon').from('leads').select('*')
        }
        """,
    )
    _write(tmp_path / "tests" / "outboundWorker.test.ts", "test('outbound safety', () => {})\n")
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Review outbound suppression, webhook HMAC, Supabase, and scorecard logic safely.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply", "do not edit applied migrations"],
                    "important_paths": ["src/outboundWorker.ts", "tests/outboundWorker.test.ts"],
                    "validation_standard": "Relevant Jest tests pass and risky send behavior is explained.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0

    design = run_cli(tmp_path, "harness", "engineer", "design", "--json")
    assert design.returncode == 0, design.stderr
    review = run_cli(tmp_path, "harness", "engineer", "review", "--json")
    assert review.returncode == 0, review.stderr
    dry_run = run_cli(tmp_path, "harness", "engineer", "dry-run", "check webhook HMAC and suppression send scorecard", "--json")
    assert dry_run.returncode == 0, dry_run.stderr

    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    agent_ids = [agent["id"] for agent in candidate["workforce"]["agents"]]
    skill_ids = [skill["id"] for skill in candidate["skills"]]
    evidence = candidate["codebase_evidence"]
    assert evidence["status"] == "grounded"
    assert evidence["evidence_graph"]["status"] == "available"
    assert "src/outboundWorker.ts" in evidence["existing_important_paths"]
    assert evidence["test_framework_evidence"]["framework"] == "jest"
    assert "tests/outboundWorker.test.ts" in evidence["test_framework_evidence"]["test_paths"]
    assert evidence["risk_boundaries"]["requires_manual_approval"] is True
    assert "supabase" in evidence["risk_boundaries"]["external_systems"]
    assert "outbound_delivery" in evidence["risk_boundaries"]["external_systems"]
    assert candidate["domain_spec"]["codebase_evidence_status"] == "grounded"
    assert candidate["domain_spec"]["test_framework_evidence"]["framework"] == "jest"
    assert candidate["domain_spec"]["risk_boundaries"]["auto_apply"] is False
    assert "codebase_evidence.test_framework_evidence" in candidate["evaluator_contract"]["evidence_required"]
    assert "risk_boundaries must be checked before patch proposal" in candidate["validation"]["evidence_required"]
    assert "webhook-signature-reviewer" in agent_ids
    assert "outbound-safety-reviewer" in agent_ids
    assert "supabase-schema-reviewer" in agent_ids
    assert "scorecard-logic-reviewer" in agent_ids
    assert "trace-webhook-hmac" in skill_ids
    assert "review-suppression-policy" in skill_ids
    assert "trace-send-pipeline" in skill_ids
    assert "review-supabase-migrations" in skill_ids
    assert "trace-scorecard-logic" in skill_ids
    webhook_agent = next(agent for agent in candidate["workforce"]["agents"] if agent["id"] == "webhook-signature-reviewer")
    assert webhook_agent["codebase_evidence"]["status"] == "grounded"
    assert "codebase evidence path cited" in webhook_agent["validation"]["required"]
    webhook_skill = next(skill for skill in candidate["skills"] if skill["id"] == "trace-webhook-hmac")
    assert webhook_skill["codebase_evidence"]["test_framework"] == "jest"
    assert "risk boundary checked" in webhook_skill["validation"]["required"]
    dry_payload = json.loads(dry_run.stdout)
    assert "webhook-signature-reviewer" in dry_payload["selected_agents"]
    assert "trace-webhook-hmac" in dry_payload["selected_skills"]


def test_harness_engineer_keeps_weak_outbound_tool_words_out_of_platform_workforce(tmp_path: Path) -> None:
    _write(
        tmp_path / "AGENTS.md",
        """
        본체는 브라우저에서 AI 에이전트를 만들고 다운로드하는 독립 플랫폼이다.
        Cambrian은 추후 붙일 수 있는 선택형 런타임, 검증기, 진화 엔진 후보로 둔다.
        """,
    )
    _write(tmp_path / "TODO.md", "대화형 에이전트 제작 -> .agent-pack.json 다운로드 -> Import 검증\n")
    _write(tmp_path / "index.html", "<main>Builder Download agent-pack Workspace Preview</main>")
    _write(
        tmp_path / "tools" / "verify_static_project.py",
        """
        def verify_words():
            return "send pipeline outbound delivery"
        """,
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

    design = run_cli(tmp_path, "harness", "engineer", "design", "--json")

    assert design.returncode == 0, design.stderr
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    agent_ids = [agent["id"] for agent in candidate["workforce"]["agents"]]
    skill_ids = [skill["id"] for skill in candidate["skills"]]
    evidence = candidate["codebase_evidence"]
    assert candidate["harness"]["id"].startswith("custom-")
    assert "agent_marketplace_platform" in candidate["project_profile"]["domains"]
    assert evidence["domain_confidence"]["candidates"]["agent_marketplace_platform"]["confidence"] == "confirmed"
    assert evidence["domain_confidence"]["candidates"]["send_pipeline"]["confidence"] == "weak"
    assert "outbound-safety-reviewer" not in agent_ids
    assert "review-suppression-policy" not in skill_ids
    assert "trace-send-pipeline" not in skill_ids
    assert "agent-platform-contract-reviewer" in agent_ids
    assert "review-agent-pack-contract" in skill_ids
    assert candidate["quality_gate"]["status"] == "caution"
    assert candidate["quality_gate"]["manual_review_required"] is True


def test_harness_engineer_handles_avf_pipeline_answers_without_domain_drift(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "requirements.txt", "anthropic\npytest\n")
    _write(tmp_path / "avf.py", "from core.orchestrator import run_pipeline\n")
    _write(tmp_path / "core" / "orchestrator.py", "from core.ddmq import DDMQ\n\ndef run_pipeline():\n    return DDMQ()\n")
    _write(tmp_path / "core" / "ddmq.py", "class DDMQ:\n    def enqueue(self, item):\n        return item\n")
    _write(tmp_path / "core" / "schema_registry.py", "STAGE_SCHEMAS = {'stage1': {'type': 'object'}}\n")
    _write(tmp_path / "core" / "validators" / "schema_validator.py", "def validate_stage_schema(payload):\n    return bool(payload)\n")
    _write(tmp_path / "plugins" / "stage1_seeker.py", "STAGE_NAME = 'stage1'\n")
    _write(tmp_path / "plugins" / "stage2_gatekeeper.py", "STAGE_NAME = 'stage2'\n")
    _write(tmp_path / "tests" / "test_pipeline.py", "def test_pipeline_contract():\n    assert True\n")
    _write(
        tmp_path / "CLAUDE.md",
        """
        Tool permission instructions mention approval prompts, auth, login, sessions,
        hotel booking examples, and review suppression policy examples.
        These are agent instructions, not this product's domain.
        """,
    )
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    stale_profile = tmp_path / ".cambrian" / "project" / "profile.yaml"
    stale_profile.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-05-20T00:00:00+00:00",
                "project_root": str(tmp_path),
                "project_name": tmp_path.name,
                "language": "python",
                "languages": ["python"],
                "test_framework": "pytest",
                "test_frameworks": ["pytest"],
                "detected_files": {},
                "detected_paths": {"python": ["avf.py", "core/orchestrator.py"], "tests": ["tests/test_pipeline.py"]},
                "domains": ["agent_marketplace_platform", "hotel_site", "auth", "tests"],
                "recommended_harnesses": [],
                "summary": ["stale noisy profile"],
                "evidence_card": {},
                "domain_confidence": {
                    "candidates": {
                        "agent_marketplace_platform": {"confidence": "confirmed", "evidence": ["CLAUDE.md"]},
                        "hotel_site": {"confidence": "confirmed", "evidence": ["CLAUDE.md"]},
                        "auth": {"confidence": "confirmed", "evidence": ["CLAUDE.md"]},
                        "tests": {"confidence": "suspected", "evidence": ["tests/test_pipeline.py"]},
                    },
                },
                "evidence_graph": {},
                "warnings": [],
                "errors": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.parent.mkdir(parents=True, exist_ok=True)
    answers.write_text(
        f"""primary_goal: "AVF Stage 1-5 pipeline automation: debug DDMQ, Anthropic API failures, and stage schema validation."
test_command: python -m pytest tests/ -v
build_command: python -m py_compile avf.py core/orchestrator.py
change_policy: 제안만 하고 자동 적용 금지
forbidden_scope: |
  .env
  no automatic patch apply
important_paths: |
  {tmp_path / "core" / "orchestrator.py"}
  core\\ddmq.py
  - core/schema_registry.py
  core/validators/schema_validator.py
  plugins/stage1_seeker.py
  avf.py
agent_roles: |
  DDMQ debugger: inspect queue and dead-letter behavior
  Anthropic API error analyst: classify provider and rate-limit failures
  Stage schema validator: verify stage IO schema contracts
validation_standard: Existing pytest command passes and schema risks are cited.
""",
        encoding="utf-8",
    )

    design = run_cli(tmp_path, "harness", "engineer", "design", "--json")
    assert design.returncode == 0, design.stderr
    review = run_cli(tmp_path, "harness", "engineer", "review", "--json")
    assert review.returncode == 0, review.stderr

    payload = json.loads(design.stdout)
    review_payload = json.loads(review.stdout)
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    evidence = candidate["codebase_evidence"]
    agent_ids = [agent["id"] for agent in candidate["workforce"]["agents"]]
    skill_ids = [skill["id"] for skill in candidate["skills"]]

    assert payload["quality_score"] >= 80
    assert review_payload["status"] == "ready_for_dry_run"
    assert evidence["status"] == "grounded"
    assert evidence["missing_important_paths"] == []
    assert "core/orchestrator.py" in evidence["existing_important_paths"]
    assert "core/ddmq.py" in evidence["existing_important_paths"]
    assert "auth" not in candidate["project_profile"]["domains"]
    assert "hotel_site" not in candidate["project_profile"]["domains"]
    assert "auth" not in candidate["harness"]["id"]
    assert "hotel" not in candidate["harness"]["id"]
    assert "pipeline" in candidate["harness"]["id"]
    assert candidate["harness"]["change_policy"] == "proposal_only"
    assert candidate["execution_boundary"]["change_policy"] == "proposal_only"
    assert agent_ids == ["ddmq-debugger", "anthropic-api-error-analyst", "stage-schema-validator"]
    assert "debug-ddmq-queue-flow" in skill_ids
    assert "review-anthropic-api-errors" in skill_ids
    assert "validate-stage-schema-contract" in skill_ids


def test_api_reviewer_gets_real_api_route_evidence(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"node --version","build":"node --version"},"devDependencies":{}}')
    _write(tmp_path / "src" / "app" / "api" / "leads" / "route.ts", "export async function GET() { return Response.json({ data: [] }) }\n")
    _write(tmp_path / "src" / "lib" / "client.ts", "export const client = {}\n")
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Review API response contract for the lead route.",
                    "test_command": "node --version",
                    "build_command": "node --version",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply"],
                    "important_paths": ["src/app/api/leads/route.ts", "src/lib/client.ts"],
                    "validation_standard": "API route contract is cited and validation command is selected.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0

    design = run_cli(tmp_path, "harness", "engineer", "design", "--json")

    assert design.returncode == 0, design.stderr
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    api_agent = next(agent for agent in candidate["workforce"]["agents"] if agent["id"] == "api-contract-reviewer")
    assert "src/app/api/leads/route.ts" in api_agent["codebase_evidence"]["paths"]


def test_important_code_paths_promote_suspected_domains_to_confirmed(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"node --version","build":"node --version"},"devDependencies":{}}')
    _write(tmp_path / "src" / "webhook" / "handler.ts", "export function verifyWebhook() { return true }\n")
    _write(tmp_path / "src" / "outbound" / "suppression.ts", "export function suppression() { return true }\n")
    _write(tmp_path / "src" / "outbound" / "sendPipeline.ts", "export function sendPipeline() { return true }\n")
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Review webhook, suppression, and send pipeline safety.",
                    "test_command": "node --version",
                    "build_command": "",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply"],
                    "important_paths": [
                        "src/webhook/handler.ts",
                        "src/outbound/suppression.ts",
                        "src/outbound/sendPipeline.ts",
                    ],
                    "validation_standard": "Core domain evidence is cited before patch proposals.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0

    design = run_cli(tmp_path, "harness", "engineer", "design", "--json")

    assert design.returncode == 0, design.stderr
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    confidence = candidate["codebase_evidence"]["domain_confidence"]
    assert confidence["candidates"]["webhook"]["confidence"] == "confirmed"
    assert confidence["candidates"]["suppression"]["confidence"] == "confirmed"
    assert confidence["candidates"]["send_pipeline"]["confidence"] == "confirmed"
