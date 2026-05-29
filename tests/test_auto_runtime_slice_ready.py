from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_auto_runtime_slice_ready_doc_exists_and_names_scope() -> None:
    text = _read("docs/release/AUTO_RUNTIME_SLICE_READY.md")

    for phrase in [
        "AI Company Auto Runtime Slice Readiness",
        "engine/project_authority.py",
        "engine/project_auto_mode.py",
        "quality-aware plan selection tests",
        "Do Not Include",
    ]:
        assert phrase in text


def test_auto_runtime_slice_ready_records_validation_results() -> None:
    text = _read("docs/release/AUTO_RUNTIME_SLICE_READY.md")

    for phrase in [
        "tests/test_authority_mode.py",
        "tests/test_auto_release_gate.py",
        "tests/test_auto_loop_dogfood.py",
        "93 passed in 270.48s",
        "SPLIT_RUN_REQUIRED",
        "GO for review/staging as Slice 2",
    ]:
        assert phrase in text


def test_auto_runtime_slice_ready_records_safety_boundaries() -> None:
    text = _read("docs/release/AUTO_RUNTIME_SLICE_READY.md")

    for phrase in [
        "proposal_only remains the safe default",
        "full_authority is explicit",
        "bounded cycles",
        "does not call provider APIs",
        "apply source patches by itself",
    ]:
        assert phrase in text


def test_rc_checklist_links_auto_runtime_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Auto Runtime Slice Gate",
        "docs/release/AUTO_RUNTIME_SLICE_READY.md",
        "auto runtime test gate is PASS",
        "staged diff contains only Slice 2 files",
    ]:
        assert phrase in checklist
