from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DOCS = ROOT / "docs" / "product"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_leads_with_ai_company_runtime() -> None:
    readme = _read(ROOT / "README.md")
    first_lines = "\n".join(readme.splitlines()[:12])

    assert "Cambrian is an installable AI company runtime." in first_lines
    assert "Every project becomes an AI company." in first_lines
    assert "GitHub Release assets first" in first_lines
    assert "without pretending that the AI can run unsupervised" in first_lines


def test_ai_company_runtime_doc_defines_core_concepts() -> None:
    text = _read(PRODUCT_DOCS / "13_AI_COMPANY_RUNTIME.md")

    for phrase in [
        "Cambrian is an installable AI company runtime",
        "AI Company",
        "Harness",
        "Workforce",
        "Agent",
        "Skill",
        "Boardroom",
        "Authority Mode",
        "Auto Mode",
        "Claude / Codex",
        "Preset",
    ]:
        assert phrase in text


def test_product_constitution_is_current_source_of_truth() -> None:
    text = _read(PRODUCT_DOCS / "14_PRODUCT_CONSTITUTION.md")
    index = _read(PRODUCT_DOCS / "00_INDEX.md")

    assert "Cambrian is an installable AI company runtime." in text
    assert "Every project becomes an AI company." in text
    assert "MCP is an AI-tool connection surface, not the product core." in text
    assert "A 24-hour company loop is supervised by default." in text
    assert "cambrian-mcp" in text
    assert "no arbitrary shell execution through MCP" in text
    assert "The current source of truth is:" in index
    assert "14_PRODUCT_CONSTITUTION.md" in index
    assert index.index("14_PRODUCT_CONSTITUTION.md") < index.index("Legacy compatibility vocabulary")

    for phrase in [
        "AI Worker Installer",
        "worker pack",
        "team pack",
        "template pack",
        "lane pack",
    ]:
        assert phrase in text
        assert text.index(phrase) > text.index("Legacy Compatibility Vocabulary")


def test_product_docs_place_presets_below_ai_company_identity() -> None:
    combined = "\n".join(
        _read(PRODUCT_DOCS / name)
        for name in [
            "01_PRODUCT_THESIS.md",
            "02_PRODUCT_DEFINITION.md",
            "04_SYSTEM_ARCHITECTURE.md",
            "07_EXECUTION_LOOPS.md",
            "10_GLOSSARY.md",
            "11_CONVERSATIONAL_HARNESS_BUILDER.md",
            "12_HARNESS_ENGINEERING_SYSTEM.md",
            "13_AI_COMPANY_RUNTIME.md",
            "14_PRODUCT_CONSTITUTION.md",
        ]
    )

    assert "installable AI company runtime" in combined
    assert "AI company" in combined or "AI Company" in combined
    assert "Claude / Codex" in combined
    assert "Preset" in combined
    assert "auth-bug-core" in combined


def test_readme_core_flow_includes_authority_and_auto_mode() -> None:
    readme = _read(ROOT / "README.md")
    first_block = readme[: readme.index("## Built-in preset seeds")]

    for command in [
        "cambrian project scan",
        "cambrian harness interview start",
        "cambrian harness engineer design",
        "cambrian workforce generate",
        "cambrian skill generate",
        "cambrian authority grant --mode full-authority",
        "cambrian auto init --goal",
        "cambrian auto boardroom",
        "cambrian auto plan",
        "cambrian auto run --max-steps 5",
    ]:
        assert command in first_block

    assert first_block.index("cambrian auto init") < readme.index("## Built-in preset seeds")


def test_ten_year_architecture_places_mcp_inside_supervised_company_loop() -> None:
    text = _read(PRODUCT_DOCS / "42_TEN_YEAR_ARCHITECTURE.md")

    for phrase in [
        "Local MCP Adapter For AI Tool Operability",
        "cambrian-mcp",
        "MCP is the handle that lets an external AI operate Cambrian.",
        "Supervised 24-Hour Company Operating Model",
        "Cambrian decides the next bounded job.",
        "OS-11 remains the next task",
    ]:
        assert phrase in text

    assert text.index("Local MCP Adapter For AI Tool Operability") < text.index(
        "Supervised 24-Hour Company Operating Model"
    )
