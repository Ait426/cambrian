from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "docs" / "launch"
WEB = ROOT / "web"

KIT_FILES = [
    "PUBLIC_DEMO_KIT.md",
    "ONE_MINUTE_PITCH.md",
    "FIVE_MINUTE_DEMO_SCRIPT.md",
    "SCREENSHOT_AND_RECORDING_CHECKLIST.md",
    "LAUNCH_COPY.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _kit_text() -> str:
    return "\n".join(_read(LAUNCH / name) for name in KIT_FILES)


def _hero_text() -> str:
    text = _read(WEB / "index.html")
    start = text.index('<section class="hero"')
    end = text.index("</section>", start)
    return text[start:end].lower()


def test_public_demo_kit_files_exist() -> None:
    for name in KIT_FILES:
        assert (LAUNCH / name).exists()


def test_one_liner_and_auth_bug_core_appear_in_launch_docs() -> None:
    text = _kit_text()

    assert "Cambrian installs AI worker packs into the AI you already use." in text
    assert "이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요." in text
    assert "Auth Bug Core" in text
    assert "Python + pytest + narrow auth/login bug fixes" in text


def test_golden_path_commands_are_in_public_kit() -> None:
    text = _kit_text()

    for command in [
        "cambrian pack show auth-bug-core",
        "cambrian install pack auth-bug-core",
        "cambrian install doctor",
        "cambrian pack activate auth-bug-core",
        "cambrian pack doctor auth-bug-core",
        'cambrian pack start "로그인 에러 수정해"',
        "cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml",
        "cambrian pack job-validate <job-id>",
        "cambrian pack proof auth-bug-core",
    ]:
        assert command in text


def test_web_local_runtime_boundary_appears() -> None:
    text = _kit_text()

    assert "The web page is the hiring desk." in text
    assert "Your local Cambrian runtime does the install, job handoff, validation, and proof." in text
    assert "웹은 작업반을 고르는 hiring desk입니다." in text


def test_pitch_and_demo_script_cover_required_story() -> None:
    pitch = _read(LAUNCH / "ONE_MINUTE_PITCH.md")
    script = _read(LAUNCH / "FIVE_MINUTE_DEMO_SCRIPT.md")

    for phrase in [
        "사용자가 직접 에이전트를 설계하지 않아도",
        "canned AI reply fixture",
        "실제 AI 호출 없이",
    ]:
        assert phrase in pitch

    for heading in [
        "0:00 -- Problem",
        "0:30 -- Product",
        "1:00 -- Show Auth Bug Core",
        "1:45 -- Install",
        "2:15 -- Activate",
        "2:45 -- Start Job",
        "3:30 -- Paste Canned AI Reply",
        "4:15 -- Validate",
        "4:45 -- Proof / Outcome",
        "5:00 -- Closing",
    ]:
        assert heading in script


def test_screenshot_checklist_covers_required_captures() -> None:
    checklist = _read(LAUNCH / "SCREENSHOT_AND_RECORDING_CHECKLIST.md")

    for phrase in [
        "Web landing hero",
        "Auth Bug Core pack page",
        "README quickstart",
        "pack show auth-bug-core",
        "install pack auth-bug-core",
        "pack activate auth-bug-core",
        'pack start "로그인 에러 수정해"',
        "job-ingest canned AI reply",
        "job-validate result",
        "proof/outcome summary",
        "raw private path 노출 금지",
        "API key 노출 금지",
    ]:
        assert phrase in checklist


def test_launch_copy_has_public_assets() -> None:
    copy = _read(LAUNCH / "LAUNCH_COPY.md")

    for heading in [
        "Product one-liners",
        "Website hero copy",
        "README intro copy",
        "Short social post",
        "Longer social post",
        "Cold email style intro",
        "Walkthrough invite message",
        "Korean version",
        "English version",
    ]:
        assert heading in copy


def test_public_demo_kit_has_no_fake_proof_claims() -> None:
    docs_only = "\n".join(
        [
            _kit_text(),
            _read(ROOT / "README.md"),
        ]
    ).lower()
    combined = "\n".join(
        [
            _kit_text(),
            _read(ROOT / "README.md"),
            _read(WEB / "index.html"),
            _read(WEB / "packs" / "auth-bug-core.html"),
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "proven best",
        "72%",
        "100%",
        "replaces developers",
        "production-ready without caveat",
    ]:
        target = docs_only if forbidden in {"72%", "100%"} else combined
        assert forbidden not in target

    assert "local proof" in combined
    assert "canned ai reply fixture" in combined


def test_readme_points_to_public_demo_kit_and_launch_demo_docs() -> None:
    readme = _read(ROOT / "README.md")

    assert "docs/launch/DEMO_RUNBOOK.md" in readme
    assert "docs/launch/PUBLIC_DEMO_KIT.md" in readme
    assert "python tools/run_launch_demo.py" in readme


def test_advanced_terms_do_not_dominate_launch_hero() -> None:
    hero = _hero_text()

    for excluded in [
        "remote registry",
        "rollout",
        "vnext",
        "marketplace",
        "canary",
        "cloud execution",
    ]:
        assert excluded not in hero
