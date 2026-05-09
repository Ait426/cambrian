from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_final_commit_staging_handoff_exists_and_lists_all_slices() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "Final Commit Staging Handoff",
        "Slice 1: Packaging RC Runtime",
        "Slice 2: AI Company Auto Runtime",
        "Slice 3: Conversational Harness, Workforce, Skill System",
        "Slice 4: Pack, Template, Benchmark Advanced Surfaces",
        "Slice 5: Launch, Pilot, Release Docs",
        "Slice 6: Web And Tools",
        "Slice 7: Runtime Evidence Archive summary",
    ]:
        assert phrase in text


def test_final_commit_staging_handoff_records_latest_release_gate_and_policy() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "release-gate-20260509-180519",
        "Verdict: GO",
        "Do not stage all files at once.",
        "git diff --cached --stat",
        "release_gate_go",
        "Do not create a tag from this handoff alone.",
    ]:
        assert phrase in text


def test_final_commit_staging_handoff_has_slice_specific_gates() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "python scripts/smoke_installed_wheel.py",
        "tests/test_auto_runtime_slice_ready.py",
        "tests/test_harness_workforce_skill_slice_ready.py",
        "tests/test_pack_template_benchmark_slice_ready.py",
        "tests/test_launch_pilot_release_docs_slice_ready.py",
        "tests/test_web_tools_slice_ready.py",
        "tests/test_runtime_evidence_archive_slice_ready.py",
    ]:
        assert phrase in text


def test_final_commit_staging_handoff_excludes_sensitive_and_noisy_files() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "full `.cambrian/` runtime tree",
        "raw external AI replies",
        "private project paths",
        ".env or secret files",
        "pycache directories",
        "tools/__pycache__/",
    ]:
        assert phrase in text


def test_rc_checklist_links_final_commit_staging_handoff_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Final Commit Staging Handoff Gate",
        "docs/release/FINAL_COMMIT_STAGING_HANDOFF.md",
        "stage and commit one slice at a time",
        "latest auto release gate is GO",
        "git diff --cached --stat",
    ]:
        assert phrase in checklist
