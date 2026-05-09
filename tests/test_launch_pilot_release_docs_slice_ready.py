from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_launch_pilot_release_docs_slice_ready_doc_exists_and_names_scope() -> None:
    text = _read("docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md")

    for phrase in [
        "Launch Pilot Release Docs Slice Readiness",
        "docs/launch/",
        "docs/release/",
        "private pilot outreach",
        "commit slicing",
        "Do Not Include",
    ]:
        assert phrase in text


def test_launch_pilot_release_docs_slice_ready_records_validation_results() -> None:
    text = _read("docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md")

    for phrase in [
        "tests/test_public_demo_kit.py",
        "tests/test_launch_assets.py",
        "tests/test_pilot_outreach_kit.py",
        "tests/test_pilot_learning_board.py",
        "tests/test_pack_template_benchmark_slice_ready.py",
        "90 passed in 1.96s",
        "GO for review/staging as Slice 5",
    ]:
        assert phrase in text


def test_launch_pilot_release_docs_slice_ready_records_safety_boundaries() -> None:
    text = _read("docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md")

    for phrase in [
        "avoid fake proof claims",
        "should not contain real participant names",
        "marketplace, payment, cloud execution",
        "split-run validation evidence",
        "does not add product runtime behavior",
    ]:
        assert phrase in text


def test_rc_checklist_links_launch_pilot_release_docs_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Launch Pilot Release Docs Slice Gate",
        "docs/release/LAUNCH_PILOT_RELEASE_DOCS_SLICE_READY.md",
        "launch pilot release docs test gate is PASS",
        "staged diff contains only Slice 5 files",
    ]:
        assert phrase in checklist
