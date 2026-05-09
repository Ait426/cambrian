from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_evidence_archive_slice_ready_doc_exists_and_names_scope() -> None:
    text = _read("docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md")

    for phrase in [
        "Runtime Evidence Archive Slice Readiness",
        "Slice 7",
        ".cambrian/auto",
        "docs/release/",
        "Do Not Include",
        "evidence artifact commit",
    ]:
        assert phrase in text


def test_runtime_evidence_archive_records_selected_release_gates() -> None:
    text = _read("docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md")

    for phrase in [
        "release-gate-20260509-162228",
        "release-gate-20260509-162905",
        "release-gate-20260509-163438",
        "release-gate-20260509-171309",
        "release-gate-20260509-173239",
        "release-gate-20260509-174102",
        "Quality score: 95",
        "Required before release: none",
    ]:
        assert phrase in text


def test_runtime_evidence_archive_default_policy_excludes_raw_runtime_tree() -> None:
    text = _read("docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md")

    for phrase in [
        "Do not commit the raw .cambrian runtime evidence tree",
        "full `.cambrian/` runtime tree by default",
        "private project paths, user data, or raw external AI replies",
        ".env or secret files",
        "pycache directories",
    ]:
        assert phrase in text


def test_runtime_evidence_archive_records_safety_boundaries() -> None:
    text = _read("docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md")

    for phrase in [
        "must not introduce product runtime behavior",
        "must not call provider APIs",
        "deploy",
        "access secrets",
        "apply source patches",
        "GO for review/staging as Slice 7",
    ]:
        assert phrase in text


def test_rc_checklist_links_runtime_evidence_archive_slice_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Runtime Evidence Archive Slice Gate",
        "docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md",
        "evidence archive test gate is PASS",
        "full `.cambrian/` runtime tree is excluded by default",
        "staged diff contains only Slice 7 files",
    ]:
        assert phrase in checklist
