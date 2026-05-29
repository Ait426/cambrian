from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_commit_slicing_plan_exists_and_lists_required_slices() -> None:
    text = _read("docs/release/COMMIT_SLICING_PLAN.md")

    for phrase in [
        "Slice 1 — Packaging RC Runtime",
        "Slice 2 — AI Company Auto Runtime",
        "Slice 3 — Conversational Harness, Workforce, Skill System",
        "Slice 4 — Pack, Template, Benchmark Advanced Surfaces",
        "Slice 5 — Launch, Pilot, Release Docs",
        "Slice 6 — Web And Tools",
        "Slice 7 — Runtime Evidence Archive",
    ]:
        assert phrase in text


def test_commit_slicing_plan_has_validation_gates_and_secret_safety() -> None:
    text = _read("docs/release/COMMIT_SLICING_PLAN.md")

    for phrase in [
        "python scripts/check_final_commit_staging_handoff.py --worktree --all-slices --json",
        "--untracked-files=all",
        "File-level git status entries: 188",
        "Active candidate paths: 188",
        "Excluded by default: 0",
        "Receipt-Locked Slice Snapshot",
        "--verify-all-artifacts",
        "receipt_all_artifacts_current",
        "dist/final-commit-test-gate-evidence/*.template.json",
        "test_gate_evidence_ready",
        "test_gate_evidence_file",
        "evidence_ref",
        "evidence_sha256",
        "dist/final-commit-test-gate-logs/",
        "--verify-prestage-from-receipt",
        "--verify-commit-ready-from-receipt",
        "dist/final-commit-staging-runbook.md",
        "receipt-locked suggested commit message",
        "git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec",
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        "1239b3a69d9169fa85cb5f2ed8480902adff70a090d99d074c156e0bd48cb78f",
        "python scripts/smoke_installed_wheel.py",
        "tests/test_authority_mode.py",
        "tests/test_project_harness_profile.py",
        "docs/release/SPLIT_RUN_REGRESSION_GATE.md",
        "Confirm no `.env` or secret file is staged.",
        "git diff --cached --stat",
    ]:
        assert phrase in text


def test_rc_checklist_links_commit_slicing_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Commit Slicing Gate",
        "docs/release/COMMIT_SLICING_PLAN.md",
        "each commit slice has a suggested commit message",
        ".cambrian/` evidence is not committed by default",
    ]:
        assert phrase in checklist
