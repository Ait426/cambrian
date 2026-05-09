from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_split_run_regression_gate_doc_exists_and_defines_policy() -> None:
    text = _read("docs/release/SPLIT_RUN_REGRESSION_GATE.md")

    for phrase in [
        "official regression gate is a split-run gate",
        "SPLIT_RUN_REQUIRED",
        "python scripts/smoke_installed_wheel.py",
        ".cambrian/auto/external_results/",
        "NO-GO is required",
    ]:
        assert phrase in text


def test_split_run_gate_records_current_evidence_baseline() -> None:
    text = _read("docs/release/SPLIT_RUN_REGRESSION_GATE.md")

    for phrase in [
        "Chunk 1: `281 passed`",
        "Chunk 6c isolated files: `73 passed`",
        "Chunk 7: `62 passed`",
        "Auto/release regression subset: `48 passed`",
        "Installed wheel smoke: `PASS`",
    ]:
        assert phrase in text


def test_rc_checklist_links_split_run_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Split-Run Regression Gate",
        "docs/release/SPLIT_RUN_REGRESSION_GATE.md",
        "SPLIT_RUN_REQUIRED",
        ".cambrian/auto/report.yaml",
    ]:
        assert phrase in checklist
