from __future__ import annotations

from pathlib import Path

from engine.project_harness_profile import ProjectHarnessScanner


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_recommends_auth_bug_core_for_python_pytest_auth_project(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample-auth"\nversion = "0.1.0"\n')
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "src" / "auth.py", "def login(user):\n    return user\n")
    _write(tmp_path / "tests" / "test_auth.py", "def test_login():\n    assert True\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert profile.language == "python"
    assert profile.test_framework == "pytest"
    assert "auth" in profile.domains
    assert "tests" in profile.domains
    assert profile.recommended_harnesses == ["auth-bug-core"]


def test_scan_does_not_force_python_preset_on_typescript_auth_project(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(tmp_path / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(tmp_path / "backend" / "src" / "api" / "authRoutes.ts", 'export const route = "/api/auth/login";\n')
    _write(tmp_path / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(tmp_path / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "typescript" in profile.languages
    assert "jest" in profile.test_frameworks
    assert profile.language == "typescript"
    assert profile.test_framework == "jest"
    assert "api" in profile.domains
    assert profile.recommended_harnesses == ["typescript-jest-auth-core"]


def test_scan_reads_code_content_for_icp_engine_domains(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(tmp_path / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(
        tmp_path / "src" / "outboundWorker.ts",
        """
        import { createClient } from '@supabase/supabase-js'

        export async function verifyWebhook(rawBody: string, signature: string) {
          return Boolean(signature) && rawBody.includes('webhook')
        }

        export async function scoreCustomer(customer: { icp: string }) {
          const scorecard = customer.icp === 'enterprise' ? 100 : 10
          return scorecard
        }

        export async function sendCampaign(recipient: string, suppressionList: Set<string>) {
          if (suppressionList.has(recipient)) return 'blocked'
          return createClient('url', 'anon').from('leads').select('*')
        }
        """,
    )
    _write(tmp_path / "tests" / "outboundWorker.test.ts", "test('send pipeline', () => {})\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "webhook" in profile.domains
    assert "suppression" in profile.domains
    assert "send_pipeline" in profile.domains
    assert "scoring" in profile.domains
    assert "supabase" in profile.domains
    assert "customer" in profile.domains
    assert "src/outboundWorker.ts" in profile.detected_paths["webhook"]
    assert "src/outboundWorker.ts" in profile.detected_paths["suppression"]


def test_scan_does_not_promote_generic_migration_word_to_supabase(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(
        tmp_path / "core" / "scoring" / "signal_scorer.py",
        """
        import re

        MIGRATION_WORDS = [re.compile(r"(?:onboard|migration|rollout|deploy)", re.I)]

        def score_customer(item):
            return item.get("score", 0)
        """,
    )
    _write(tmp_path / "tests" / "test_score.py", "def test_score():\n    assert True\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "supabase" not in profile.domains
    supabase_candidate = profile.domain_confidence["candidates"].get("supabase")
    if supabase_candidate is not None:
        assert supabase_candidate["confidence"] == "weak"
        assert supabase_candidate["usable_for_harness_core"] is False


def test_scan_does_not_promote_auth_domain_from_filename_only(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(tmp_path / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(
        tmp_path / "backend" / "src" / "routes" / "auth.ts",
        """
        export function healthRoute() {
          return { ok: true }
        }
        """,
    )
    _write(
        tmp_path / "src" / "outboundWorker.ts",
        """
        export function scoreCustomer(customer: { icp: string }) {
          return customer.icp === 'enterprise' ? 100 : 10
        }

        export function sendCampaign(recipient: string, suppressionList: Set<string>) {
          if (suppressionList.has(recipient)) return 'blocked'
          return 'queued'
        }
        """,
    )
    _write(tmp_path / "tests" / "auth.test.ts", "test('health route', () => {})\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "auth" not in profile.domains
    assert "login" not in profile.domains
    assert "send_pipeline" in profile.domains
    assert "scoring" in profile.domains
    assert profile.detected_paths["auth"] == []
    assert profile.recommended_harnesses == []


def test_scan_uses_evidence_card_and_keeps_tool_keyword_domains_weak(tmp_path: Path) -> None:
    _write(
        tmp_path / "AGENTS.md",
        """
        본체는 브라우저에서 AI 에이전트를 만들고 다운로드하는 독립 플랫폼이다.
        Cambrian은 추후 붙일 수 있는 선택형 런타임 후보로 둔다.
        """,
    )
    _write(
        tmp_path / "TODO.md",
        """
        대화형 에이전트 제작 -> agent-pack 다운로드 -> 로컬 실행 준비.
        """,
    )
    _write(tmp_path / "index.html", "<button>Builder</button><a>Download agent-pack</a>")
    _write(
        tmp_path / "tools" / "verify_static_project.py",
        """
        def check_outbound_words():
            return "send pipeline outbound delivery"
        """,
    )

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "agent_marketplace_platform" in profile.domains
    assert "cambrian_local_bridge" in profile.domains
    assert "send_pipeline" not in profile.domains
    assert "outbound" not in profile.domains
    assert profile.domain_confidence["candidates"]["agent_marketplace_platform"]["confidence"] == "confirmed"
    assert profile.domain_confidence["candidates"]["send_pipeline"]["confidence"] == "weak"
    assert profile.domain_confidence["candidates"]["outbound"]["confidence"] == "weak"
    assert profile.evidence_card["identity_evidence"]
    assert profile.evidence_graph["status"] == "available"
    assert profile.evidence_graph["confidence_summary"]["confirmed"]
    assert "send_pipeline" in profile.evidence_graph["confidence_summary"]["weak"]
    assert any(node["kind"] == "domain" and node["domain"] == "agent_marketplace_platform" for node in profile.evidence_graph["nodes"])


def test_scan_ignores_claude_instruction_domain_noise_for_avf_pipeline(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "avf.py", "from core.orchestrator import run_pipeline\n")
    _write(tmp_path / "core" / "orchestrator.py", "def run_pipeline():\n    return 'ok'\n")
    _write(tmp_path / "core" / "ddmq.py", "class DDMQ: pass\n")
    _write(tmp_path / "core" / "schema_registry.py", "STAGE_SCHEMAS = {'stage1': {}}\n")
    _write(tmp_path / "core" / "validators" / "schema_validator.py", "def validate_stage_schema(payload):\n    return True\n")
    _write(tmp_path / "plugins" / "stage1_seeker.py", "STAGE_NAME = 'stage1'\n")
    _write(tmp_path / "tests" / "test_pipeline.py", "def test_pipeline():\n    assert True\n")
    _write(
        tmp_path / "CLAUDE.md",
        """
        Approval mode examples mention auth, login, hotel, booking, and review suppression.
        Those words are process instructions, not the product domain.
        """,
    )

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "auth" not in profile.domains
    assert "login" not in profile.domains
    assert "hotel_site" not in profile.domains
    assert "ddmq" in profile.domains
    assert "schema_validation" in profile.domains
    assert "pipeline_automation" in profile.domains
    assert profile.domain_confidence["candidates"]["ddmq"]["confidence"] == "suspected"


def test_scan_keeps_archive_corpus_and_stage_words_out_of_hotel_domain(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "core" / "orchestrator.py", "def run_stage_pipeline():\n    return 'stage'\n")
    _write(tmp_path / "plugins" / "stage1_seeker.py", "STAGE_NAME = 'stage1'\n")
    _write(tmp_path / "tests" / "test_stage.py", "def test_stage():\n    assert True\n")
    _write(
        tmp_path / "README.md",
        """
        이 프로젝트는 스테이지 파이프라인과 stage schema를 검증한다.
        booking, reservation 같은 단어는 원본 입력 데이터에만 있을 수 있다.
        """,
    )
    _write(
        tmp_path / "archive" / "processed_inputs" / "reddit_sample.txt",
        """
        A random Reddit corpus line mentions hotel booking reservation keywords.
        This corpus must never define the product domain.
        """,
    )

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "stage_pipeline" in profile.domains
    assert "hotel_site" not in profile.domains
    assert "hotel_site" not in profile.domain_confidence["candidates"]


def test_scan_does_not_treat_external_adapter_auth_words_as_auth_product(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "avf.py", "from plugins.stage2_gatekeeper import call_source\n")
    _write(
        tmp_path / "plugins" / "stage2_gatekeeper.py",
        """
        def call_source(headers):
            headers['Authorization'] = 'Bearer token'
            return 'login required by upstream provider'
        """,
    )
    _write(
        tmp_path / "core" / "sources" / "reddit_adapter.py",
        """
        def fetch(headers):
            return {'auth': headers.get('Authorization'), 'login_url': 'https://provider/login'}
        """,
    )
    _write(tmp_path / "tests" / "test_stage.py", "def test_stage():\n    assert True\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "auth" not in profile.domains
    assert "login" not in profile.domains
    assert profile.recommended_harnesses == []


def test_scan_skips_generated_pytest_and_launch_run_artifacts(tmp_path: Path) -> None:
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "core" / "orchestrator.py", "def run_stage_pipeline():\n    return 'stage'\n")
    _write(tmp_path / "tests" / "test_stage.py", "def test_stage():\n    assert True\n")
    _write(
        tmp_path / ".pytest-basetemp-noise" / "workdir" / "src" / "hotel_booking.py",
        """
        def reserve_room():
            return 'hotel booking reservation auth login'
        """,
    )
    _write(
        tmp_path / ".launch_runs" / "latest" / "workdir" / "package.json",
        '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}',
    )

    profile = ProjectHarnessScanner().scan(tmp_path)
    all_paths = [path for values in profile.detected_paths.values() for path in values]

    assert "hotel_site" not in profile.domains
    assert profile.language == "python"
    assert profile.test_framework == "pytest"
    assert not any(".pytest-basetemp-noise" in path for path in all_paths)
    assert not any(".launch_runs" in path for path in all_paths)
    assert ".pytest*/" in profile.evidence_card["document_authority"]["excluded_generated_artifacts"]
    assert ".launch_runs/" in profile.evidence_card["document_authority"]["excluded_generated_artifacts"]
    assert profile.evidence_card["noise_filter"]["excluded_dir_prefixes"] == [".pytest", ".launch_runs"]


def test_scan_exposes_document_authority_policy_in_evidence_card(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Durable Project\n\nThis is the source of truth.")
    _write(tmp_path / "pyproject.toml", '[project]\nname = "durable-project"\nversion = "0.1.0"\n')
    _write(tmp_path / "tests" / "test_ok.py", "def test_ok():\n    assert True\n")

    profile = ProjectHarnessScanner().scan(tmp_path)
    authority = profile.evidence_card["document_authority"]

    assert "source_of_truth" in authority
    assert "weak_without_code_support" in authority
    assert "excluded_generated_artifacts" in authority
    assert "promotion_rule" in authority
    assert "generated, demo, sample" in authority["promotion_rule"]


def test_scan_keeps_demo_examples_and_skill_pool_out_of_project_identity(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Durable Project\n\nNo product domain is declared here.")
    _write(
        tmp_path / "demo" / "src" / "auth_flow.py",
        "def login():\n    return 'auth login session jwt'\n",
    )
    _write(
        tmp_path / "examples" / "send_pipeline.js",
        "export const topic = 'outbound recipient delivery pipeline';\n",
    )
    _write(
        tmp_path / "skill_pool" / "customer_scoring.py",
        "def score_customer():\n    return 'customer scoring icp'\n",
    )

    profile = ProjectHarnessScanner().scan(tmp_path)
    all_paths = [path for values in profile.detected_paths.values() for path in values]

    assert profile.language == "unknown"
    assert "auth" not in profile.domains
    assert "send_pipeline" not in profile.domains
    assert "customer" not in profile.domains
    assert not any(path.startswith(("demo/", "examples/", "skill_pool/")) for path in all_paths)
    excluded = profile.evidence_card["document_authority"]["excluded_generated_artifacts"]
    assert "demo/" in excluded
    assert "examples/" in excluded
    assert "skill_pool/" in excluded
