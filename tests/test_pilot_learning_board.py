from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "docs" / "launch"

LEARNING_DOCS = [
    "PILOT_FEEDBACK_TRIAGE.md",
    "PILOT_LEARNING_BOARD.md",
    "PILOT_DECISION_LOG.md",
    "PILOT_SUMMARY_TEMPLATE.md",
    "PILOT_NEXT_ACTION_RULES.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _learning_text() -> str:
    return "\n".join(_read(LAUNCH / name) for name in LEARNING_DOCS)


def test_pilot_learning_docs_exist() -> None:
    for name in LEARNING_DOCS:
        assert (LAUNCH / name).exists()


def test_triage_severity_levels_exist() -> None:
    triage = _read(LAUNCH / "PILOT_FEEDBACK_TRIAGE.md")

    for severity in [
        "### P0 - Launch blocker",
        "### P1 - Pilot conversion blocker",
        "### P2 - Product improvement",
        "### P3 - Later / nice-to-have",
    ]:
        assert severity in triage

    for trigger in [
        "3+ out of 5 users cannot understand",
        "install / activate / start repeatedly fails",
        "fake proof or overclaim",
        "API key or external network",
    ]:
        assert trigger in triage


def test_feedback_categories_exist() -> None:
    triage = _read(LAUNCH / "PILOT_FEEDBACK_TRIAGE.md")

    for category in [
        "understanding",
        "install friction",
        "activation friction",
        "first-job friction",
        "validation/proof confusion",
        "value signal",
        "buying signal",
        "trust concern",
        "requested pack",
        "messaging confusion",
    ]:
        assert category in triage


def test_learning_board_has_required_sections() -> None:
    board = _read(LAUNCH / "PILOT_LEARNING_BOARD.md")

    for heading in [
        "## Snapshot",
        "## Understanding",
        "## Golden Path Friction",
        "## Value Signals",
        "## Trust / Proof Concerns",
        "## Requested Packs",
        "## Top 5 Learnings",
        "## Top 5 Fixes Before Next Pilot Round",
    ]:
        assert heading in board


def test_decision_log_has_template_and_initial_scope_decision() -> None:
    decision_log = _read(LAUNCH / "PILOT_DECISION_LOG.md")

    for phrase in [
        "## Decision Template",
        "D-001",
        "Continue / adjust message / fix UX / add pack / defer / stop",
        "## D-000 - Initial launch scope",
        "Keep launch scope limited to Auth Bug Core.",
        "remote registry",
        "marketplace",
        "provider API automation",
    ]:
        assert phrase in decision_log


def test_summary_template_has_quantitative_and_qualitative_signals() -> None:
    summary = _read(LAUNCH / "PILOT_SUMMARY_TEMPLATE.md")

    for heading in [
        "## Quantitative Signals",
        "## Qualitative Summary",
        "### What landed",
        "### What confused users",
        "### What felt valuable",
        "### What felt overclaimed",
        "### Most requested packs",
        "## Launch Verdict",
        "## Next 5 Actions",
    ]:
        assert heading in summary


def test_next_action_rules_cover_required_feedback_types() -> None:
    rules = _read(LAUNCH / "PILOT_NEXT_ACTION_RULES.md")

    for heading in [
        "## Understanding issue",
        "## Install friction",
        "## Pack concept confusion",
        "## First-job friction",
        "## Proof skepticism",
        "## Buying signal",
        "## Requested pack",
    ]:
        assert heading in rules

    for phrase in [
        "rewrite hero copy",
        "fix install docs",
        "add exact next command",
        "avoid fake public metrics",
        "schedule assisted install",
        "consider next pack candidate",
    ]:
        assert phrase in rules


def test_privacy_warning_exists_in_all_learning_docs() -> None:
    for name in LEARNING_DOCS:
        text = _read(LAUNCH / name)
        assert "Do not commit real participant names" in text
        assert "Use anonymized IDs such as P01, P02." in text
        assert "private location outside the repo" in text


def test_readme_and_launch_kits_link_to_learning_docs() -> None:
    readme = _read(ROOT / "README.md")
    public_kit = _read(LAUNCH / "PUBLIC_DEMO_KIT.md")
    outreach = _read(LAUNCH / "PILOT_OUTREACH_KIT.md")

    assert "docs/launch/PILOT_LEARNING_BOARD.md" in readme
    assert "PILOT_FEEDBACK_TRIAGE.md" in public_kit
    assert "PILOT_LEARNING_BOARD.md" in public_kit
    assert "PILOT_DECISION_LOG.md" in public_kit

    for link in [
        "PILOT_FEEDBACK_TRIAGE.md",
        "PILOT_LEARNING_BOARD.md",
        "PILOT_DECISION_LOG.md",
        "PILOT_SUMMARY_TEMPLATE.md",
        "PILOT_NEXT_ACTION_RULES.md",
    ]:
        assert link in outreach


def test_learning_docs_have_no_fake_proof_or_overclaim_terms() -> None:
    combined = "\n".join(
        [
            _learning_text(),
            _read(LAUNCH / "PILOT_OUTREACH_KIT.md"),
            _read(ROOT / "README.md"),
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "replaces developers",
        "proven best",
        "all-purpose ai company",
    ]:
        assert forbidden not in combined


def test_learning_templates_do_not_require_real_names_or_emails() -> None:
    combined = _learning_text().lower()

    for forbidden in [
        "john doe",
        "jane doe",
        "alice@example.com",
        "bob@example.com",
        "@example.com",
    ]:
        assert forbidden not in combined

    assert "p01" in combined
    assert "p02" in combined
