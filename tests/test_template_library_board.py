from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from test_agent_transfer import _read_yaml, _run_cli
from test_harness_templates import _approve_template_for_apply, _prepare_template_source, _write_yaml
from test_template_transfer import _export_template


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duplicate_template(project_root: Path, source_name: str, target_name: str, **updates: object) -> None:
    store_path = project_root / ".cambrian" / "templates" / "templates.yaml"
    payload = _read_yaml(store_path)
    source = next(item for item in payload["templates"] if item["name"] == source_name)
    duplicate = copy.deepcopy(source)
    duplicate["name"] = target_name
    duplicate["template_id"] = target_name
    duplicate["description"] = str(updates.pop("description", target_name))
    for key, value in updates.items():
        duplicate[key] = value
    payload["templates"].append(duplicate)
    _write_yaml(store_path, payload)


def _prepare_board_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", "auth-bug-template", "--tag", "auth"], cwd=project_root).returncode == 0
    _duplicate_template(
        project_root,
        "auth-bug-template",
        "safe-patch-template",
        tags=["safe", "patch"],
        fit_hints=["safe patch discipline with review support"],
    )
    _duplicate_template(project_root, "auth-bug-template", "watch-template")
    _duplicate_template(
        project_root,
        "auth-bug-template",
        "docs-review-template",
        tags=["docs"],
        project_defaults={
            "project_type": "docs",
            "stack": ["markdown"],
            "test_command": None,
            "mode": "balanced",
            "primary_use_cases": ["docs_update"],
        },
        agent_defaults={
            "active_agents": ["docs-update-agent"],
            "preferred_lead_agents": ["docs-update-agent"],
            "preferred_support_agents": ["review-agent"],
        },
        team_defaults={
            "active_team_id": "docs-review-team",
            "active_team_name": "docs-review-team",
            "active_team": None,
            "backup_teams": [],
            "watched_teams": [],
            "saved_teams": [],
        },
        policy_defaults={
            "test_first_practice": False,
            "narrow_change_scope": False,
            "increase_review_support": True,
            "promote_request_focus": ["docs_update"],
        },
        fit_hints=["docs_update bootstrap"],
    )
    _source_root, export_path = _export_template(tmp_path / "transfer")
    import_proc = _run_cli(
        ["template", "import", str(export_path), "--as", "imported-auth-bug-template"],
        cwd=project_root,
    )
    assert import_proc.returncode == 0, import_proc.stderr
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template",
            "Strong fit for auth bug work.",
            "--rating",
            "strong",
            "--kind",
            "fit",
        ],
        cwd=project_root,
    ).returncode == 0
    assert _run_cli(
        [
            "template",
            "retrospective",
            "watch-template",
            "Useful sometimes, but risky for this project focus.",
            "--rating",
            "mixed",
            "--kind",
            "fit",
        ],
        cwd=project_root,
    ).returncode == 0
    for text in ["Poor fit for auth bug work.", "Repeatedly too weak for this stack."]:
        assert _run_cli(
            [
                "template",
                "retrospective",
                "docs-review-template",
                text,
                "--rating",
                "weak",
                "--kind",
                "fit",
            ],
            cwd=project_root,
        ).returncode == 0
    return project_root


def _board_payload(project_root: Path, *args: str) -> dict:
    proc = _run_cli(["template", "board", *args, "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_template_board_selects_preferred_template(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    payload = _board_payload(project_root)

    assert "auth-bug-template" in payload["preferred_templates"]
    assert payload["entries"][0]["template_name"] == "auth-bug-template"


def test_template_board_marks_strong_alternative(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    payload = _board_payload(project_root)

    assert "safe-patch-template" in payload["strong_alternatives"]


def test_template_board_marks_promising_imported(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    payload = _board_payload(project_root)

    assert "imported-auth-bug-template" in payload["promising_imported"]


def test_template_board_marks_watch_template(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    payload = _board_payload(project_root)

    assert "watch-template" in payload["watch_templates"]


def test_template_board_marks_retire_candidate(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    payload = _board_payload(project_root)

    assert "docs-review-template" in payload["retire_candidates"]


def test_template_board_request_mode(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    payload = _board_payload(project_root, "--request", "로그인 에러 수정해")

    assert payload["mode"] == "request"
    assert payload["request"] == "로그인 에러 수정해"
    assert "auth-bug-template" in payload["preferred_templates"]


def test_template_board_save_report(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    proc = _run_cli(["template", "board", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert (project_root / payload["saved_path"]).exists()
    report = _read_yaml(project_root / ".cambrian" / "templates" / "library_board.yaml")
    assert "auth-bug-template" in report["preferred_templates"]


def test_template_board_status_and_show_surface_standing(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["template", "show", "safe-patch-template"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template library:" in status_proc.stdout
    assert "auth-bug-template" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Library standing:" in show_proc.stdout
    assert "strong_alternative" in show_proc.stdout


def test_template_board_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = _prepare_board_project(tmp_path)
    source_path = project_root / "src" / "auth.py"
    before = _sha256(source_path)

    assert _run_cli(["template", "board"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
