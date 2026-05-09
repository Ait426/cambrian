from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_harness_workforce_skill_slice_ready_doc_exists_and_names_scope() -> None:
    text = _read("docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md")

    for phrase in [
        "Harness Workforce Skill Slice Readiness",
        "engine/project_harness_profile.py",
        "engine/project_workforce_builder.py",
        "engine/project_skill_builder.py",
        "engine/project_evolution.py",
        "Do Not Include",
    ]:
        assert phrase in text


def test_harness_workforce_skill_slice_ready_records_validation_results() -> None:
    text = _read("docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md")

    for phrase in [
        "tests/test_harness_engineer_design.py",
        "tests/test_workforce_builder.py",
        "tests/test_skill_generation.py",
        "tests/test_ai_company_bootstrap.py",
        "59 passed in 138.72s",
        "GO for review/staging as Slice 3",
    ]:
        assert phrase in text


def test_harness_workforce_skill_slice_ready_records_product_boundaries() -> None:
    text = _read("docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md")

    for phrase in [
        "Custom harness creation is the primary user-facing path",
        "Presets remain optional seeds",
        "Install does not dispatch agents",
        "job start",
        "does not call provider APIs",
        "apply source patches by itself",
    ]:
        assert phrase in text


def test_rc_checklist_links_harness_workforce_skill_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Harness Workforce Skill Slice Gate",
        "docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md",
        "harness workforce skill test gate is PASS",
        "staged diff contains only Slice 3 files",
    ]:
        assert phrase in checklist
