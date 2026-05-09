from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "docs" / "launch"

PILOT_DOCS = [
    "PILOT_OUTREACH_KIT.md",
    "PILOT_INVITE_MESSAGES.md",
    "PILOT_INTERVIEW_GUIDE.md",
    "PILOT_FEEDBACK_FORM.md",
    "PILOT_ISSUE_INTAKE.md",
    "PILOT_TRACKER_TEMPLATE.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pilot_text() -> str:
    return "\n".join(_read(LAUNCH / name) for name in PILOT_DOCS)


def test_pilot_docs_exist() -> None:
    for name in PILOT_DOCS:
        assert (LAUNCH / name).exists()


def test_invite_messages_include_korean_and_english_versions() -> None:
    invites = _read(LAUNCH / "PILOT_INVITE_MESSAGES.md")

    assert "## Korean DM short" in invites
    assert "## Korean slightly formal" in invites
    assert "## English short" in invites
    assert "## Follow-up message" in invites
    assert "I'm building Cambrian" in invites
    assert "Auth Bug Core" in invites
    assert "5-minute product walkthrough" in invites


def test_interview_guide_covers_before_during_after_and_buying_signal() -> None:
    guide = _read(LAUNCH / "PILOT_INTERVIEW_GUIDE.md")

    for heading in [
        "## Before walkthrough",
        "## During walkthrough",
        "## After walkthrough",
        "## Buying signal questions",
    ]:
        assert heading in guide

    for phrase in [
        "AI worker pack",
        "pack install / activate / start",
        "money",
        "company/team",
    ]:
        assert phrase in guide


def test_feedback_form_covers_understanding_use_intent_and_trust() -> None:
    form = _read(LAUNCH / "PILOT_FEEDBACK_FORM.md")

    for heading in [
        "## Participant",
        "## Understanding",
        "## Product Run Reaction",
        "## Use Intent",
        "## Trust",
        "## Notes",
    ]:
        assert heading in form

    assert "Understood product in 60 seconds" in form
    assert "Would try on own project" in form
    assert "Did anything feel overclaimed" in form


def test_issue_intake_includes_severity_and_classification() -> None:
    intake = _read(LAUNCH / "PILOT_ISSUE_INTAKE.md")

    assert "Severity: P0 / P1 / P2 / P3" in intake
    assert "## Classification" in intake
    for classification in [
        "messaging confusion",
        "install failure",
        "activation failure",
        "job start failure",
        "reply ingest failure",
        "validation failure",
        "proof confusion",
        "performance/slow",
        "docs mismatch",
    ]:
        assert classification in intake


def test_tracker_template_warns_not_to_commit_personal_info() -> None:
    tracker = _read(LAUNCH / "PILOT_TRACKER_TEMPLATE.md")

    assert "template only" in tracker
    assert "Do not commit real participant names" in tracker
    assert "private project details" in tracker
    assert "Create a private copy" in tracker
    assert "| P10 |" in tracker


def test_pilot_success_criteria_are_defined() -> None:
    kit = _read(LAUNCH / "PILOT_OUTREACH_KIT.md")

    for heading in [
        "### Minimum success",
        "### Strong signal",
        "### Kill / pivot signal",
    ]:
        assert heading in kit

    for phrase in [
        "5-10 people",
        "Auth Bug Core only",
        "prepared AI reply first run",
        "validation handoff",
    ]:
        assert phrase in kit


def test_readme_and_public_demo_kit_link_to_pilot_kit() -> None:
    readme = _read(ROOT / "README.md")
    public_kit = _read(LAUNCH / "PUBLIC_DEMO_KIT.md")

    assert "docs/launch/PILOT_OUTREACH_KIT.md" in readme
    assert "PILOT_OUTREACH_KIT.md" in public_kit
    assert "Private pilot" in readme
    assert "Private Pilot Outreach Kit" in public_kit


def test_pilot_docs_have_no_overclaim_or_fake_proof_terms() -> None:
    combined = "\n".join(
        [
            _pilot_text(),
            _read(ROOT / "README.md"),
            _read(LAUNCH / "PUBLIC_DEMO_KIT.md"),
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


def test_advanced_feature_terms_do_not_dominate_pilot_pitch() -> None:
    invites = _read(LAUNCH / "PILOT_INVITE_MESSAGES.md").lower()
    kit = _read(LAUNCH / "PILOT_OUTREACH_KIT.md")
    pitch = kit.split("## Out of Scope", 1)[0].lower()
    combined_pitch = "\n".join([invites, pitch])

    for advanced in [
        "marketplace",
        "remote registry",
        "payment",
        "vnext",
        "rollout",
        "canary",
        "challenger",
        "cloud execution",
    ]:
        assert advanced not in combined_pitch

    assert "auth bug core" in combined_pitch
    assert "ai worker pack" in combined_pitch
