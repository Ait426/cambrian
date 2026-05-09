from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "docs" / "launch"
WEB = ROOT / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _quickstart_block() -> str:
    readme = _read(ROOT / "README.md")
    start = readme.index("## Quickstart")
    end = readme.index("## Built-in preset compatibility")
    return readme[start:end]


def _hero_text() -> str:
    text = _read(WEB / "index.html")
    start = text.index('<section class="hero"')
    end = text.index("</section>", start)
    return text[start:end].lower()


def test_go_no_go_document_exists_and_has_verdict() -> None:
    path = LAUNCH / "GO_NO_GO.md"
    text = _read(path)

    assert path.exists()
    assert "## Verdict" in text
    assert "GO" in text
    assert "## Final Decision" in text


def test_go_no_go_lists_golden_path_and_dry_run_result() -> None:
    text = _read(LAUNCH / "GO_NO_GO.md")

    for command in [
        "cambrian pack show auth-bug-core",
        "cambrian install pack auth-bug-core",
        "cambrian install doctor",
        "cambrian pack activate auth-bug-core",
        "cambrian pack doctor auth-bug-core",
        "cambrian pack start",
        "cambrian pack job-ingest",
        "cambrian pack job-validate",
        "cambrian pack proof auth-bug-core",
    ]:
        assert command in text

    assert ".launch_runs/latest" in text
    assert "result: PASS" in text
    assert "failed steps: none" in text


def test_go_no_go_defers_post_launch_work() -> None:
    text = _read(LAUNCH / "GO_NO_GO.md")

    for phrase in [
        "ProjectStatusReader split",
        "CLI handler extraction",
        "command surface cleanup",
        "sub-package cleanup",
    ]:
        assert phrase in text


def test_readme_quickstart_matches_launch_docs() -> None:
    quickstart = _quickstart_block()
    golden = _read(LAUNCH / "LAUNCH_GOLDEN_PATH.md")
    runbook = _read(LAUNCH / "DEMO_RUNBOOK.md")

    for command in [
        "cambrian project scan",
        "cambrian harness plan",
        "cambrian harness install",
        "cambrian agent dispatch",
    ]:
        assert command in quickstart
    for command in [
        "cambrian pack show auth-bug-core",
        "cambrian install pack auth-bug-core",
        "cambrian pack start",
    ]:
        assert command in golden
        assert command in runbook


def test_launch_docs_have_no_fake_proof_claims() -> None:
    combined = "\n".join(
        _read(path)
        for path in [
            ROOT / "README.md",
            LAUNCH / "LAUNCH_GOLDEN_PATH.md",
            LAUNCH / "DEMO_RUNBOOK.md",
            LAUNCH / "LAUNCH_RC_REPORT.md",
            LAUNCH / "GO_NO_GO.md",
            WEB / "index.html",
            WEB / "packs" / "auth-bug-core.html",
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "proven best",
        "72% validated proposal rate",
        "100% success",
        "production-ready evidence",
    ]:
        assert forbidden not in combined


def test_launch_checklist_reflects_dry_run_and_go_no_go() -> None:
    checklist = _read(LAUNCH / "LAUNCH_CHECKLIST.md")

    for phrase in [
        "- [x] Launch dry run passes",
        "- [x] transcript generated",
        "- [x] LAUNCH_RC_REPORT.md updated",
        "- [x] GO_NO_GO.md created",
        "- [x] canned AI reply validated",
        "- [x] no provider API call required",
        "- [x] no fake proof claim",
    ]:
        assert phrase in checklist


def test_latest_runner_output_is_referenced_when_available() -> None:
    summary_path = ROOT / ".launch_runs" / "latest" / "summary.json"
    go_no_go = _read(LAUNCH / "GO_NO_GO.md")

    if summary_path.exists():
        summary = json.loads(_read(summary_path))
        assert summary["status"] == "passed"
        assert summary["validated"] is True
        assert ".launch_runs/latest" in go_no_go


def test_launch_hero_does_not_center_advanced_lifecycle_terms() -> None:
    hero = _hero_text()

    for excluded in [
        "remote registry",
        "dependency resolver",
        "rollout",
        "vnext",
        "marketplace",
        "payment",
        "cloud execution",
        "canary",
    ]:
        assert excluded not in hero
