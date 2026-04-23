from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_required_docs_exist() -> None:
    required = [
        "CAMBRIAN_FOUNDATION.md",
        "CAMBRIAN_PRODUCT_DEFINITION.md",
        "docs/PROJECT_MODE_QUICKSTART.md",
        "docs/COMMANDS.md",
        "docs/ARTIFACTS.md",
    ]

    for relative_path in required:
        assert (ROOT / relative_path).exists(), f"문서 누락: {relative_path}"


def test_quickstart_and_commands_match_existing_cli_groups() -> None:
    quickstart = _read("docs/PROJECT_MODE_QUICKSTART.md")
    commands_doc = _read("docs/COMMANDS.md")
    cli_text = _read("engine/cli.py")

    for command_text in [
        "cambrian init",
        "cambrian run",
        "cambrian status",
        "cambrian summary",
        "cambrian notes",
        "cambrian clarify",
        "cambrian patch intent",
        "cambrian patch intent-fill",
        "cambrian patch propose",
        "cambrian patch apply",
    ]:
        assert command_text in quickstart or command_text in commands_doc

    for parser_name in [
        "init",
        "run",
        "status",
        "summary",
        "context",
        "clarify",
        "patch",
        "brain",
        "evolution",
    ]:
        assert re.search(r'add_parser\(\s*"' + re.escape(parser_name) + r'"', cli_text)

    assert "cambrian context scan" in commands_doc
    assert "cambrian notes add" in commands_doc


def test_no_forbidden_overclaim_in_foundation_docs() -> None:
    combined = "\n".join(
        [
            _read("CAMBRIAN_FOUNDATION.md"),
            _read("CAMBRIAN_PRODUCT_DEFINITION.md"),
            _read("docs/PROJECT_MODE_QUICKSTART.md"),
        ]
    ).lower()

    forbidden_phrases = [
        "fully autonomous product manager",
        "automatic adoption by default",
        "replaces jira",
        "replaces amplitude",
        "automatic source changes without approval",
    ]

    for phrase in forbidden_phrases:
        assert phrase not in combined


def test_safety_principles_present() -> None:
    foundation = _read("CAMBRIAN_FOUNDATION.md").lower()
    quickstart = _read("docs/PROJECT_MODE_QUICKSTART.md").lower()

    assert "no automatic adoption" in foundation
    assert "explicit apply/adoption" in foundation
    assert "file-first" in foundation
    assert "project memory" in foundation

    assert "automatic adoption" in quickstart
    assert "source 수정" in _read("docs/PROJECT_MODE_QUICKSTART.md")
    assert "file-first" in quickstart


def test_readme_top_contains_updated_tagline() -> None:
    readme_top = "\n".join(_read("README.md").splitlines()[:25]).lower()

    signals = [
        "evolutionary trust harness",
        "project memory",
        "explicit apply",
        "explicit adoption",
    ]

    assert sum(signal in readme_top for signal in signals) >= 2


def test_summary_docs_remain_local_only() -> None:
    commands = _read("docs/COMMANDS.md").lower()
    demo = _read("docs/FIRST_RUN_DEMO.md").lower()

    assert "cambrian summary" in commands
    assert "외부 telemetry 전송: 아니오" in _read("docs/COMMANDS.md")
    assert "cambrian summary" in demo
    assert "외부 telemetry는 보내지 않습니다." in _read("docs/FIRST_RUN_DEMO.md")


def test_generated_demo_template_uses_do_centered_flow() -> None:
    template = _read("engine/demo_project.py")

    assert "cambrian do \\\"로그인 정규화 버그 수정해\\\"" in template
    assert "cambrian do --continue --use-suggestion 1 --execute" in template
    assert (
        "cambrian do --continue --old-choice old-1 --new-text "
        "\\\"return username.strip().lower()\\\" --validate"
    ) in template
    assert "cambrian do --continue --apply --reason \\\"normalize username before login\\\"" in template
    assert "## Advanced / manual path" in template
