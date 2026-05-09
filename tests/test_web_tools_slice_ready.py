from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_web_tools_slice_ready_doc_exists_and_names_scope() -> None:
    text = _read("docs/release/WEB_TOOLS_SLICE_READY.md")

    for phrase in [
        "Web Tools Slice Readiness",
        "web/",
        "tools/generate_web_catalog.py",
        "tools/run_launch_demo.py",
        "tests/test_web_catalog.py",
        "Do Not Include",
    ]:
        assert phrase in text


def test_web_tools_slice_ready_records_validation_results_and_fix() -> None:
    text = _read("docs/release/WEB_TOOLS_SLICE_READY.md")

    for phrase in [
        "python tools/generate_web_catalog.py",
        "python -m pytest -q tests/test_web_catalog.py",
        "2 failed, 4 passed",
        "6 passed in 0.24s",
        "cambrian pack proof auth-bug-core",
        "GO for review/staging as Slice 6",
    ]:
        assert phrase in text


def test_web_tools_slice_ready_records_product_boundaries() -> None:
    text = _read("docs/release/WEB_TOOLS_SLICE_READY.md")

    for phrase in [
        "hiring desk, not the runtime",
        "install, job handoff, validation, and proof",
        "do not mutate `.cambrian/` runtime state",
        "makes no fake proof claims",
        "does not call provider APIs",
    ]:
        assert phrase in text


def test_rc_checklist_links_web_tools_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Web Tools Slice Gate",
        "docs/release/WEB_TOOLS_SLICE_READY.md",
        "web catalog test gate is PASS",
        "staged diff contains only Slice 6 files",
    ]:
        assert phrase in checklist
