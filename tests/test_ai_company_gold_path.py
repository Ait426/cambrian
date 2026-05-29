from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_ai_company_golden_path_doc_records_capabilities() -> None:
    text = _read("docs/release/AI_COMPANY_GOLDEN_PATH.md")

    for phrase in [
        "AI Company Golden Path",
        "python scripts/smoke_ai_company_gold_path.py",
        "evolve propose",
        "evolve preview",
        "evolve apply --confirm",
        "MCP operability",
        "cambrian mcp verify --receipt dist/mcp_operability_receipt.json",
        "python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json",
        "MCP_EXTERNAL_CLIENT_CONNECT.md",
        "provider API key",
        "source code",
    ]:
        assert phrase in text


def test_ai_company_golden_path_is_linked_from_readme_and_checklist() -> None:
    readme = _read("README.md")
    checklist = _read("docs/release/RC_CHECKLIST.md")

    assert "scripts/smoke_ai_company_gold_path.py" in readme
    assert "docs/release/AI_COMPANY_GOLDEN_PATH.md" in readme
    assert "AI Company Golden Path Gate" in checklist
    assert "fresh installed wheel can generate, search, and fuse project skills" in checklist
    assert "fresh installed wheel can start `cambrian-mcp` and write an MCP operability receipt" in checklist
    assert "fresh installed wheel exposes `cambrian mcp verify --receipt dist/mcp_operability_receipt.json`" in checklist
    assert "MCP_EXTERNAL_CLIENT_CONNECT.md" in checklist
    assert "provider API key is not required for the golden path" in checklist


def test_ai_company_golden_path_smoke_runs_mcp_operability_gate() -> None:
    script = _read("scripts/smoke_ai_company_gold_path.py")

    assert '"mcp"' in script
    assert '"verify"' in script
    assert "mcp operability receipt" in script
    assert "installed cambrian-mcp entry point is operable" in script
    assert '(output_dir / "mcp_operability_receipt.json").resolve()' in script
    assert "--server-command-json" in script
