from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _hero_text() -> str:
    text = _read(WEB / "index.html")
    start = text.index('<section class="hero"')
    end = text.index("</section>", start)
    return text[start:end]


def test_launch_landing_page_exists_and_explains_product() -> None:
    landing = _read(WEB / "index.html")

    assert "Install AI workers into the AI you already use." in landing
    assert "AI Worker Installer" in landing
    assert "Cambrian lets you install worker packs into your local project" in landing
    assert "Start with Auth Bug Core" in landing


def test_auth_bug_core_showcase_page_has_launch_commands() -> None:
    detail = _read(WEB / "packs" / "auth-bug-core.html")

    for phrase in [
        "Auth Bug Core",
        "Lane Pack",
        "Python + pytest + narrow auth/login bug fixes",
        "cambrian install pack auth-bug-core",
        "cambrian pack activate auth-bug-core",
        "cambrian pack start",
        "This page does not install anything by itself.",
        "Generate local proof after real usage.",
    ]:
        assert phrase in detail


def test_web_runtime_boundary_copy_exists() -> None:
    combined = "\n".join(
        [
            _read(WEB / "index.html"),
            _read(WEB / "packs" / "auth-bug-core.html"),
        ]
    )

    assert "The web page is the hiring desk." in combined
    assert "The web catalog is the hiring desk." in combined
    assert "Your local Cambrian runtime does the actual install, job handoff, validation, and proof." in combined
    assert "This page does not execute code or mutate `.cambrian/` state." in combined


def test_launch_surface_makes_no_fake_proof_claims() -> None:
    combined = "\n".join(
        [
            _read(WEB / "index.html"),
            _read(WEB / "packs" / "auth-bug-core.html"),
            _read(ROOT / "README.md"),
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "proven best",
        "72% validated proposal rate",
        "validated_proposal_rate: 1",
        "100% success",
    ]:
        assert forbidden not in combined

    assert "seed pack. local proof required." in combined
    assert "does not claim public outcome metrics" in combined


def test_readme_quickstart_matches_launch_surface() -> None:
    readme = _read(ROOT / "README.md")
    first_block = readme[: readme.index("## Built-in preset seeds")]

    for command in [
        "python -m build",
        "cambrian doctor",
        "cambrian project scan",
        "cambrian harness interview start",
        "cambrian harness interview answer --answers .cambrian/interview/answers.yaml",
        "cambrian harness plan",
        "cambrian harness install --confirm",
        'cambrian agent dispatch "fix the login error"',
        "cambrian job ingest latest fixtures/ai_reply_patch_candidate.yaml",
        "cambrian job validate latest",
    ]:
        assert command in first_block

    assert "docs/release/RC_INSTALL_GUIDE.md" in readme
    assert "docs/launch/LAUNCH_GOLDEN_PATH.md" in readme
    assert "custom harness first, preset optional seed" in readme


def test_landing_links_launch_docs_and_pack_detail() -> None:
    landing = _read(WEB / "index.html")

    assert "packs/auth-bug-core.html" in landing
    assert "../docs/launch/LAUNCH_GOLDEN_PATH.md" in landing
    assert "../docs/launch/DEMO_SCRIPT.md" in landing
    assert "View product walkthrough" in landing
    assert "Run reproducible product run" in landing


def test_expansion_terms_do_not_dominate_launch_hero() -> None:
    hero = _hero_text().lower()

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
