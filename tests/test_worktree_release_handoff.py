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
        "Total git status entries: 188",
        "Slice candidate entries: 188",
        "Excluded-by-default entries: 0",
        "Manual review entries: 0",
        "Launch/pilot/release docs slice entries: 173",
        "Installed wheel smoke: PASS",
        "Packaging and launch focused gate: `61 passed`",
        "Auto runtime focused gate: `93 passed`",
        "Harness/company focused split groups: `132 passed`",
        ".cambrian/auto/report.yaml` open blockers: `0`",
        "Auto report source code modified: `false`",
        "Latest auto release gate: GO",
        "No source code was automatically patched by auto mode.",
        "[x] `.env`, API keys, private usernames, and private project data are not included in release candidate docs or tests.",
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


def test_release_candidate_docs_do_not_contain_operator_local_paths() -> None:
    forbidden_markers = [
        r"C:\Users\user",
        "C:/Users/user",
        "AVE_MCP_CHECK",
        "_프로젝트",
        "ICP Engine",
        r"Desktop\AVE",
        "Desktop/_",
    ]
    docs = [
        path
        for folder in [ROOT / "docs" / "release", ROOT / "docs" / "product"]
        for path in folder.glob("*.md")
        if path.name != "NEXT_SESSION_HANDOFF.md"
    ]
    offenders: list[str] = []
    for path in docs:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden_markers:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker}")

    assert offenders == []
