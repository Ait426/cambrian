from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _write_yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_template_store(project_root: Path, *, candidate_has_context: bool = True) -> None:
    parent = {
        "schema_version": "1.0.0",
        "template_id": "imported-auth-bug-template",
        "name": "imported-auth-bug-template",
        "created_at": "2026-04-29T00:00:00+00:00",
        "updated_at": None,
        "description": "parent auth template",
        "source_project_name": "upstream",
        "source_harness_id": "harness-upstream",
        "template_kind": "team_based",
        "tags": ["auth"],
        "project_defaults": {
            "project_type": "python",
            "stack": ["python", "pytest"],
            "test_command": "pytest -q",
            "mode": "balanced",
            "primary_use_cases": ["bug_fix"],
        },
        "safety_defaults": {},
        "agent_defaults": {
            "active_agents": ["bug-fix-agent"],
            "preferred_lead_agents": ["bug-fix-agent"],
            "preferred_support_agents": [],
        },
        "team_defaults": {
            "active_team_id": "auth-bug-team",
            "active_team_name": "auth-bug-team",
            "backup_teams": [],
            "watched_teams": [],
        },
        "policy_defaults": {
            "test_first_practice": False,
            "narrow_change_scope": False,
            "increase_review_support": False,
        },
        "fit_hints": ["auth bug parent"],
        "warnings": [],
        "errors": [],
        "source_kind": "imported",
        "source_origin": {"source_project_name": "upstream"},
    }
    candidate = copy.deepcopy(parent)
    candidate["template_id"] = "auth-bug-template-local"
    candidate["name"] = "auth-bug-template-local"
    candidate["description"] = "local derivative auth template"
    candidate["source_kind"] = "local"
    candidate["source_origin"] = {
        "parent_template_name": "imported-auth-bug-template",
        "root_template_name": "imported-auth-bug-template",
    }
    candidate["policy_defaults"] = {
        "test_first_practice": True,
        "narrow_change_scope": True,
        "increase_review_support": True,
    }
    candidate["fit_hints"] = ["local derivative for auth/login bug work"]
    if candidate_has_context:
        candidate["context_defaults"] = {
            "preferred_context_paths": ["src/auth.py"],
            "preferred_test_paths": ["tests/test_auth.py"],
        }
    _write_yaml(
        project_root / ".cambrian" / "templates" / "templates.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-29T00:00:00+00:00",
            "active_template_name": None,
            "templates": [parent, candidate],
            "warnings": [],
            "errors": [],
        },
    )


def _seed_workset(project_root: Path) -> Path:
    _prepare_target_project(project_root)
    source = project_root / "src" / "auth.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def login(name):\n    return name\n", encoding="utf-8")
    other = project_root / "src" / "login.py"
    other.write_text("def auth_login(name):\n    return name\n", encoding="utf-8")
    test_path = project_root / "tests" / "test_auth.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_login():\n    assert True\n", encoding="utf-8")
    _write_yaml(
        project_root / ".cambrian" / "bridge" / "replies" / "reply_auth.yaml",
        {
            "schema_version": "1.0.0",
            "reply_id": "reply_auth",
            "created_at": "2026-04-29T00:00:00+00:00",
            "packet_id": None,
            "project_name": "demo",
            "request": "",
            "response_kind": "patch_candidate",
            "content": {
                "response_kind": "patch_candidate",
                "summary": "strip auth login input",
                "target_path": "src/auth.py",
                "old_text": "return name",
                "new_text": "return name.strip()",
                "reason": "narrow auth login fix",
                "related_tests": ["tests/test_auth.py"],
                "warnings": [],
            },
            "raw_text": None,
            "source_reply_path": None,
            "linked_session_id": None,
            "linked_request_ref": None,
            "warnings": [],
            "errors": [],
        },
    )
    for case_id, request in [
        ("login-bug", "fix auth login"),
        ("login-edge", "fix auth login edge"),
    ]:
        _write_yaml(
            project_root / ".cambrian" / "benchmarks" / "cases" / f"case_{case_id}.yaml",
            {
                "schema_version": "1.0.0",
                "case_id": case_id,
                "created_at": "2026-04-29T00:00:00+00:00",
                "name": case_id,
                "request": request,
                "request_class": "bug_fix",
                "description": None,
                "tags": ["auth", "login"],
                "expected_focus": ["auth", "login"],
                "replay_hints": {},
                "notes": [],
                "warnings": [],
                "errors": [],
            },
        )
    _write_yaml(
        project_root / ".cambrian" / "benchmarks" / "worksets" / "workset_auth-bug-workset.yaml",
        {
            "schema_version": "1.0.0",
            "workset_id": "auth-bug-workset",
            "created_at": "2026-04-29T00:00:00+00:00",
            "name": "auth-bug-workset",
            "description": None,
            "case_ids": ["login-bug", "login-edge"],
            "tags": ["auth"],
            "warnings": [],
            "errors": [],
        },
    )
    return source


def _prepare_project(project_root: Path, *, candidate_has_context: bool = True) -> Path:
    source = _seed_workset(project_root)
    _seed_template_store(project_root, candidate_has_context=candidate_has_context)
    return source


def test_qualify_uses_lineage_parent_and_candidate_stronger(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)

    proc = _run_cli(
        [
            "template",
            "qualify",
            "auth-bug-template-local",
            "--workset",
            "auth-bug-workset",
            "--save",
            "--json",
        ],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["reference_template_name"] == "imported-auth-bug-template"
    assert payload["verdict"] == "candidate_stronger"
    assert set(payload["modes"]) == {"cambrian_guided", "cambrian_full"}
    assert Path(project_root / payload["saved_path"]).exists()


def test_qualify_show_template_show_and_lineage_surface_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualify = _run_cli(
        [
            "template",
            "qualify",
            "auth-bug-template-local",
            "--workset",
            "auth-bug-workset",
            "--save",
            "--json",
        ],
        cwd=project_root,
    )
    assert qualify.returncode == 0, qualify.stderr
    saved_path = json.loads(qualify.stdout)["saved_path"]

    show = _run_cli(["template", "qualify-show", saved_path], cwd=project_root)
    template_show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    lineage = _run_cli(["template", "lineage", "auth-bug-template-local"], cwd=project_root)

    assert show.returncode == 0, show.stderr
    assert "Template Qualification" in show.stdout
    assert "candidate_stronger" in show.stdout
    assert template_show.returncode == 0, template_show.stderr
    assert "Qualification:" in template_show.stdout
    assert "candidate_stronger" in template_show.stdout
    assert lineage.returncode == 0, lineage.stderr
    assert "Template Lineage" in lineage.stdout
    assert "imported-auth-bug-template" in lineage.stdout


def test_qualification_inconclusive_when_reference_missing_and_against_required(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    store_path = project_root / ".cambrian" / "templates" / "templates.yaml"
    store = _read_yaml(store_path)
    candidate = next(item for item in store["templates"] if item["name"] == "auth-bug-template-local")
    candidate["source_origin"] = {}
    _write_yaml(store_path, store)

    proc = _run_cli(
        ["template", "qualify", "auth-bug-template-local", "--workset", "auth-bug-workset"],
        cwd=project_root,
    )

    assert proc.returncode != 0
    assert "--against" in proc.stderr


def test_explicit_against_and_single_mode(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)

    proc = _run_cli(
        [
            "template",
            "qualify",
            "auth-bug-template-local",
            "--workset",
            "auth-bug-workset",
            "--against",
            "imported-auth-bug-template",
            "--mode",
            "full",
            "--json",
        ],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["modes"] == ["cambrian_full"]
    assert payload["candidate_runs"][0]["metrics_snapshot"]["validated_proposal_rate"] == 1.0


def test_template_board_and_status_use_qualification_weakly(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    assert _run_cli(
        [
            "template",
            "qualify",
            "auth-bug-template-local",
            "--workset",
            "auth-bug-workset",
            "--save",
        ],
        cwd=project_root,
    ).returncode == 0

    board = _run_cli(["template", "board", "--json"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)

    assert board.returncode == 0, board.stderr
    candidates = {item["template_name"]: item for item in json.loads(board.stdout)["entries"]}
    assert "qualified above parent on auth-bug-workset" in candidates["auth-bug-template-local"]["reasons"]
    assert status.returncode == 0, status.stderr
    assert "Template qualification:" in status.stdout
    assert "auth-bug-template-local" in status.stdout


def test_qualification_does_not_mutate_source_or_current_template(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    before = _sha256(source)
    current_path = project_root / ".cambrian" / "templates" / "current_template.yaml"
    current_before = current_path.read_text(encoding="utf-8") if current_path.exists() else None

    proc = _run_cli(
        [
            "template",
            "qualify",
            "auth-bug-template-local",
            "--workset",
            "auth-bug-workset",
            "--save",
        ],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    assert _sha256(source) == before
    current_after = current_path.read_text(encoding="utf-8") if current_path.exists() else None
    assert current_after == current_before
    assert list((project_root / ".cambrian" / "templates" / "qualifications").glob("qualify_*.yaml"))
    assert list((project_root / ".cambrian" / "benchmarks" / "workset_replays").glob("replay_*.yaml"))
