from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_packaging_slice_ready_doc_exists_and_names_slice_scope() -> None:
    text = _read("docs/release/PACKAGING_SLICE_READY.md")

    for phrase in [
        "fix(packaging): 설치형 wheel pack catalog 경로 안정화",
        "engine/_data/packs/",
        "scripts/smoke_installed_wheel.py",
        "tests/test_installed_wheel_pack_rc.py",
        "Do Not Include",
    ]:
        assert phrase in text


def test_packaging_slice_ready_records_validation_results() -> None:
    text = _read("docs/release/PACKAGING_SLICE_READY.md")

    for phrase in [
        "python scripts/smoke_installed_wheel.py",
        "Result: PASS",
        "60 passed in 73.78s",
        ".launch_runs/installed_wheel_latest",
        "GO for review/staging as Slice 1",
    ]:
        assert phrase in text


def test_rc_checklist_links_packaging_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Packaging Slice Gate",
        "docs/release/PACKAGING_SLICE_READY.md",
        "packaging test gate is PASS",
        "staged diff contains only Slice 1 files",
    ]:
        assert phrase in checklist
