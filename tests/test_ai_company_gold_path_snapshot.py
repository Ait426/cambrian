from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke_ai_company_gold_path.py"
DOC = ROOT / "docs" / "release" / "AI_COMPANY_GOLDEN_PATH.md"
README = ROOT / "README.md"


def test_ai_company_gold_path_includes_company_snapshot_gate() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    doc = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert '"company", "snapshot", "--json"' in smoke
    assert "company snapshot is private-safe artifact" in smoke
    assert '"company_snapshot_generated"' in smoke
    assert ".cambrian/company/snapshots" in smoke

    assert "private-safe AI company snapshot" in doc
    assert "company snapshot" in doc
    assert "sale_ready: false" in doc
    assert "raw private project data export" in doc

    assert "company snapshot" in readme
