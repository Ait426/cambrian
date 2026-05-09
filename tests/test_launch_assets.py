from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "docs" / "launch"
WEB = ROOT / "web"

ASSET_DOCS = [
    "DEMO_ASSETS.md",
    "RECORDING_SHOT_LIST.md",
    "SANITIZED_TERMINAL_TRANSCRIPT.md",
    "ASSET_PRIVACY_CHECKLIST.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _asset_text() -> str:
    return "\n".join(_read(LAUNCH / name) for name in ASSET_DOCS)


def _hero_text() -> str:
    text = _read(WEB / "index.html")
    start = text.index('<section class="hero"')
    end = text.index("</section>", start)
    return text[start:end].lower()


def test_launch_asset_docs_exist() -> None:
    for name in ASSET_DOCS:
        assert (LAUNCH / name).exists()


def test_product_one_liner_and_auth_bug_core_are_present() -> None:
    text = _asset_text()

    assert "Cambrian installs AI worker packs into the AI you already use." in text
    assert "이미 쓰는 AI에 검증된 AI 일꾼을 설치하세요." in text
    assert "Auth Bug Core" in text
    assert "Python + pytest + narrow auth/login bug fixes" in text


def test_golden_path_commands_are_in_assets() -> None:
    text = _asset_text()

    for command in [
        "cambrian pack show auth-bug-core",
        "cambrian install pack auth-bug-core",
        "cambrian pack activate auth-bug-core",
        'cambrian pack start "로그인 에러 수정해"',
        "cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml",
        "cambrian pack job-validate <job-id>",
        "cambrian pack proof auth-bug-core",
    ]:
        assert command in text


def test_canned_ai_reply_notice_and_runtime_boundary_are_present() -> None:
    text = _asset_text()

    assert "canned AI reply fixture" in text
    assert "No provider API call is shown or required." in text
    assert "The web page is the hiring desk" in text or "web is the hiring desk" in text
    assert "install, job handoff, validation, and proof" in text


def test_sanitized_transcript_has_public_excerpts_not_raw_paths() -> None:
    transcript = _read(LAUNCH / "SANITIZED_TERMINAL_TRANSCRIPT.md")

    assert "Source: `.launch_runs/latest`" in transcript
    assert "[demo-workdir]" in transcript
    assert "C:\\Users\\" not in transcript
    assert "validation_status: validated" in transcript
    assert "No provider API call is shown or required." in transcript


def test_privacy_checklist_covers_required_safety_items() -> None:
    checklist = _read(LAUNCH / "ASSET_PRIVACY_CHECKLIST.md")

    for phrase in [
        "No API keys",
        "No private absolute paths",
        "No personal username path",
        "No raw private project source",
        "No fake proof numbers",
        "Web/local runtime boundary shown",
        "Canned AI reply clearly marked",
        "No real provider call required",
    ]:
        assert phrase in checklist


def test_asset_placeholder_directory_exists() -> None:
    readme = LAUNCH / "assets" / "README.md"
    text = _read(readme)

    assert readme.exists()
    for filename in [
        "01_landing_hero.png",
        "02_auth_bug_core_pack_page.png",
        "03_readme_quickstart.png",
        "04_pack_show_terminal.png",
        "05_install_pack_terminal.png",
        "06_pack_activate_terminal.png",
        "07_pack_start_terminal.png",
        "08_job_ingest_terminal.png",
        "09_job_validate_terminal.png",
        "10_pack_proof_terminal.png",
        "launch_demo_v1.mp4",
    ]:
        assert filename in text


def test_readme_and_public_demo_kit_link_to_demo_assets() -> None:
    readme = _read(ROOT / "README.md")
    kit = _read(LAUNCH / "PUBLIC_DEMO_KIT.md")

    assert "docs/launch/DEMO_ASSETS.md" in readme
    assert "DEMO_ASSETS.md" in kit
    assert "RECORDING_SHOT_LIST.md" in kit
    assert "SANITIZED_TERMINAL_TRANSCRIPT.md" in kit
    assert "ASSET_PRIVACY_CHECKLIST.md" in kit


def test_launch_asset_docs_have_no_fake_proof_claims() -> None:
    combined = "\n".join(
        [
            _asset_text(),
            _read(ROOT / "README.md"),
            _read(LAUNCH / "PUBLIC_DEMO_KIT.md"),
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "proven best",
        "replaces developers",
        "marketplace launch",
        "payment ready",
    ]:
        assert forbidden not in combined

    for numeric_claim in ["72%", "100%"]:
        assert numeric_claim not in _asset_text().lower()


def test_advanced_launch_terms_do_not_dominate_hero_copy() -> None:
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
