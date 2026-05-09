from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DOCS = ROOT / "docs" / "product"
STRONGEST_LANE = "Python + pytest + auth/login narrow bug fix"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _product_doc(name: str) -> str:
    return (PRODUCT_DOCS / name).read_text(encoding="utf-8")


def test_product_doctrine_docs_exist() -> None:
    required = [
        "00_INDEX.md",
        "01_PRODUCT_THESIS.md",
        "02_PRODUCT_DEFINITION.md",
        "03_WIN_LANE.md",
        "04_SYSTEM_ARCHITECTURE.md",
        "05_RUNTIME_STATE_MODEL.md",
        "06_PACKS_AND_INSTALL.md",
        "07_EXECUTION_LOOPS.md",
        "08_METRICS_AND_PROOF.md",
        "09_WEB_CONTROL_PLANE.md",
        "10_GLOSSARY.md",
        "11_ARCHITECTURE_INVENTORY.md",
    ]

    for name in required:
        assert (PRODUCT_DOCS / name).exists(), f"문서 누락: docs/product/{name}"


def test_strongest_lane_phrase_is_consistent() -> None:
    docs = [
        _read("README.md"),
        _read("docs/ALPHA_INSTALL.md"),
        _read("docs/FIRST_RUN_DEMO.md"),
        _read("docs/PROJECT_MODE_QUICKSTART.md"),
        _product_doc("00_INDEX.md"),
        _product_doc("03_WIN_LANE.md"),
        _read("engine/cli.py"),
        _read("engine/project_win_lane.py"),
    ]

    for text in docs:
        assert STRONGEST_LANE in text

    assert "test-first" in _product_doc("03_WIN_LANE.md")
    assert "narrow-scope" in _product_doc("03_WIN_LANE.md")
    assert "review-support" in _product_doc("03_WIN_LANE.md")


def test_product_positioning_terms_are_present() -> None:
    combined = "\n".join(
        [
            _read("README.md"),
            _product_doc("01_PRODUCT_THESIS.md"),
            _product_doc("02_PRODUCT_DEFINITION.md"),
        ]
    )

    for phrase in [
        "AI Worker Installer",
        "AI 인력 설치기",
        "AI workforce runtime",
        "harness engineering runtime",
        "evidence-based evolution engine",
    ]:
        assert phrase in combined


def test_web_control_plane_and_local_runtime_boundary_is_explicit() -> None:
    architecture = _product_doc("04_SYSTEM_ARCHITECTURE.md")
    web = _product_doc("09_WEB_CONTROL_PLANE.md")
    readme = _read("README.md")

    for text in [architecture, web, readme]:
        assert "Web control plane" in text or "web control plane" in text
        assert "Local Cambrian runtime" in text or "local Cambrian runtime" in text

    assert "source code execution" in web
    assert "cloud patch/apply" in web
    assert "pack install" in architecture
    assert "AI bridge" in architecture
    assert "Evidence / proof layer" in architecture
    assert "Evolution / canary / rollback layer" in architecture


def test_runtime_state_model_and_pack_taxonomy_are_present() -> None:
    state_model = _product_doc("05_RUNTIME_STATE_MODEL.md").lower()
    packs = _product_doc("06_PACKS_AND_INSTALL.md").lower()

    for phrase in [
        "runtime state",
        "library state",
        "bridge state",
        "metrics/benchmark/proof state",
        "improvement state",
        "lane playbook state",
    ]:
        assert phrase in state_model

    for phrase in ["worker pack", "team pack", "template pack", "lane pack"]:
        assert phrase in packs


def test_execution_loops_and_metrics_north_star_are_present() -> None:
    loops = _product_doc("07_EXECUTION_LOOPS.md")
    metrics = _product_doc("08_METRICS_AND_PROOF.md")

    for phrase in ["Install loop", "Work loop", "Proof loop", "Evolution loop"]:
        assert phrase in loops

    assert "North star metric is `validated_proposal_rate`" not in metrics
    assert "north star metric은 `validated_proposal_rate`" in metrics
    for metric in [
        "adoption_rate",
        "regression_free_apply_rate",
        "median_time_to_validated_proposal",
        "human_intervention_rate",
        "validation_autonomy_rate",
        "lead_agent_hit_rate",
        "team_template_recommendation_hit_rate",
        "reuse_lift",
        "repeat_task_improvement_rate",
    ]:
        assert metric in metrics


def test_glossary_required_terms_present() -> None:
    glossary = _product_doc("10_GLOSSARY.md")

    for term in [
        "harness",
        "worker",
        "agent",
        "worker pack",
        "team pack",
        "template pack",
        "lane pack",
        "bridge",
        "canary",
        "qualification",
        "proof pack",
        "improvement cycle",
        "persistent overlay",
    ]:
        assert re.search(rf"## {re.escape(term)}\b", glossary)


def test_readme_demo_and_onboarding_align_to_doctrine() -> None:
    for relative_path in [
        "README.md",
        "docs/FIRST_RUN_DEMO.md",
        "docs/ALPHA_INSTALL.md",
        "docs/PROJECT_MODE_QUICKSTART.md",
        "demo/README_DEMO.md",
        "engine/demo_project.py",
    ]:
        text = _read(relative_path)
        assert (
            "project-specific harness" in text
            or "custom AI harness" in text
            or "Project mode의 기본 spine" in text
            or "auth/login narrow bug fix" in text
        )
        assert "explicit apply" in text or "explicit apply/adoption" in text
        assert "source" in text


def test_no_forbidden_overclaim_in_product_docs() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PRODUCT_DOCS.glob("*.md")
    ).lower()

    forbidden_phrases = [
        "fully autonomous product manager",
        "automatic adoption by default",
        "replaces jira",
        "replaces amplitude",
        "automatic source changes without approval",
        "cloud patch/apply product",
    ]

    for phrase in forbidden_phrases:
        assert phrase not in combined
