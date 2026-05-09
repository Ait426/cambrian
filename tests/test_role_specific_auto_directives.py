from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


GARBLED_TEXT_PATTERNS = ["\ufffd", "\u6028", "\uf9cf", "?꾨", "?앺", "?묒", "寃", "由대"]


def _run_default_auto_steps(tmp_path: Path, max_steps: int = 5) -> dict:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    result = run_cli(tmp_path, "auto", "run", "--max-steps", str(max_steps), "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_pm_directive_contains_role_specific_result_contract(tmp_path: Path) -> None:
    payload = _run_default_auto_steps(tmp_path, max_steps=1)
    task_path = tmp_path / payload["task_refs"][0]
    directive_path = tmp_path / payload["directive_refs"][0]

    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    directive = directive_path.read_text(encoding="utf-8")

    assert task["directive_type"] == "role_specific_auto_task"
    assert task["owner"] == "pm-agent"
    assert task["role_profile"]["role_id"] == "pm-agent"
    assert task["result_contract"]["required_fields"] == [
        "status",
        "summary",
        "changed_files",
        "tests",
        "blockers",
        "next_action",
        "evidence",
    ]
    assert "Cambrian Auto Task Directive" in directive
    assert "역할별 작업 지시" in directive
    assert "작업 범위" in directive
    assert "결과 계약" in directive
    assert "evidence:" in directive
    for pattern in GARBLED_TEXT_PATTERNS:
        assert pattern not in directive


def test_default_plan_directives_are_different_by_role(tmp_path: Path) -> None:
    payload = _run_default_auto_steps(tmp_path, max_steps=5)
    directives = {
        yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))["owner"]: (
            tmp_path / directive_ref
        ).read_text(encoding="utf-8")
        for task_ref, directive_ref in zip(payload["task_refs"], payload["directive_refs"], strict=True)
    }

    assert "구현 후보" in directives["engineering-agent"]
    assert "변경 파일" in directives["engineering-agent"]
    assert "검증 명령" in directives["qa-agent"]
    assert "실패 분류" in directives["qa-agent"]
    assert "릴리즈 게이트" in directives["release-manager-agent"]
    assert "체크리스트" in directives["release-manager-agent"]
    for directive in directives.values():
        for pattern in GARBLED_TEXT_PATTERNS:
            assert pattern not in directive


def test_role_specific_profile_is_written_to_each_task_yaml(tmp_path: Path) -> None:
    payload = _run_default_auto_steps(tmp_path, max_steps=5)
    profiles = [
        yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))["role_profile"]
        for task_ref in payload["task_refs"]
    ]

    assert {profile["role_id"] for profile in profiles} == {
        "pm-agent",
        "cto-agent",
        "engineering-agent",
        "qa-agent",
        "release-manager-agent",
    }
    for profile in profiles:
        assert profile["mission"]
        assert profile["focus"]
        assert profile["instructions"]
        assert profile["outputs"]


def test_role_specific_auto_directive_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "role_specific_auto_task",
        "pm-agent",
        "engineering-agent",
        "qa-agent",
        "result_contract",
    ]:
        assert phrase in text
    assert "docs/product/34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md" in readme
    assert "34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md" in index
