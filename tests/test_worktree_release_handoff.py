from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_worktree_release_handoff_doc_exists_and_names_change_areas() -> None:
    text = _read("docs/release/WORKTREE_RELEASE_HANDOFF.md")

    for phrase in [
        "Installable RC Runtime",
        "AI Company Runtime",
        "Conversational Harness / Workforce / Skill System",
        "Pack And Template Systems",
        "Launch / Pilot / Release Docs",
    ]:
        assert phrase in text


def test_worktree_release_handoff_records_validation_and_safety_gates() -> None:
    text = _read("docs/release/WORKTREE_RELEASE_HANDOFF.md")

    for phrase in [
        "Installed wheel smoke: PASS",
        "Latest auto release gate: GO",
        "No source code was automatically patched by auto mode.",
        "Run split-run regression gates instead of a single long full pytest command.",
        "The worktree is intentionally large and should be committed in coherent slices",
    ]:
        assert phrase in text


def test_rc_checklist_links_worktree_release_handoff_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Worktree Release Handoff Gate",
        "docs/release/WORKTREE_RELEASE_HANDOFF.md",
        "latest auto release gate verdict is GO",
        "commit slices are planned",
    ]:
        assert phrase in checklist
