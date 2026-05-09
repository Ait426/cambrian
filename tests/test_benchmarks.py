from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _run_cli


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add_case(project_root: Path, name: str, request: str = "fix login bug") -> dict:
    proc = _run_cli(
        [
            "benchmark",
            "case-add",
            request,
            "--name",
            name,
            "--class",
            "bug_fix",
            "--tag",
            "auth",
            "--focus",
            "regression_test",
            "--json",
        ],
        cwd=project_root,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["case"]


def _seed_session(project_root: Path, session_id: str = "do-good") -> None:
    _write_yaml(
        project_root / ".cambrian" / "sessions" / f"do_session_{session_id}.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": session_id,
            "created_at": "2026-04-21T00:01:00+00:00",
            "user_request": "fix login bug",
            "status": "adopted",
            "current_stage": "adopted",
            "agent_context": {"lead_agent_id": "bug-fix-agent"},
            "continuations": [{"action": "patch_proposal_validated"}],
            "metrics_context": {
                "lead_agent_id": "bug-fix-agent",
                "final_lead_agent_id": "bug-fix-agent",
                "validation_path": "continue",
                "human_interventions": {
                    "source_selected_manually": False,
                    "test_selected_manually": False,
                    "old_text_overridden": False,
                    "new_text_overridden": False,
                    "explicit_agent_override": False,
                    "explicit_team_override": False,
                    "explicit_template_choice": False,
                },
                "milestones": {
                    "request_started_at": "2026-04-21T00:00:00+00:00",
                    "proposal_validated_at": "2026-04-21T00:05:00+00:00",
                    "applied_at": "2026-04-21T00:10:00+00:00",
                },
                "results": {
                    "validated_proposal": True,
                    "adoption_succeeded": True,
                    "apply_tests_passed": True,
                },
            },
        },
    )


def _seed_bridge_reply(project_root: Path) -> Path:
    reply_path = project_root / ".cambrian" / "bridge" / "replies" / "reply_bridge.yaml"
    _write_yaml(
        reply_path,
        {
            "schema_version": "1.0.0",
            "reply_id": "reply_bridge",
            "created_at": "2026-04-21T00:00:00+00:00",
            "packet_id": "packet-1",
            "project_name": "demo",
            "request": "fix login bug",
            "response_kind": "analysis",
            "content": {
                "response_kind": "analysis",
                "summary": "inspect auth login path first",
            },
            "raw_text": None,
            "source_reply_path": None,
            "linked_session_id": None,
            "linked_request_ref": None,
            "warnings": [],
            "errors": [],
        },
    )
    return reply_path


def test_benchmark_case_add_and_list(tmp_path: Path) -> None:
    case = _add_case(tmp_path, "login-bug")

    assert case["case_id"] == "login-bug"
    assert (tmp_path / ".cambrian" / "benchmarks" / "cases" / "case_login-bug.yaml").exists()

    proc = _run_cli(["benchmark", "cases", "--class", "bug_fix", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert [item["name"] for item in payload["cases"]] == ["login-bug"]


def test_benchmark_workset_save_and_list(tmp_path: Path) -> None:
    _add_case(tmp_path, "login-bug")
    _add_case(tmp_path, "auth-edge-case", "fix auth edge case")

    proc = _run_cli(
        [
            "benchmark",
            "workset-save",
            "auth-bug-workset",
            "--case",
            "login-bug",
            "--case",
            "auth-edge-case",
            "--json",
        ],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    workset = json.loads(proc.stdout)["workset"]
    assert workset["case_ids"] == ["login-bug", "auth-edge-case"]

    list_proc = _run_cli(["benchmark", "worksets", "--json"], cwd=tmp_path)
    assert list_proc.returncode == 0, list_proc.stderr
    assert json.loads(list_proc.stdout)["worksets"][0]["name"] == "auth-bug-workset"


def test_benchmark_attach_result_from_session(tmp_path: Path) -> None:
    _add_case(tmp_path, "login-bug")
    _seed_session(tmp_path)

    proc = _run_cli(
        ["benchmark", "attach", "login-bug", "--mode", "cambrian_full", "--session", "do-good", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["metrics_snapshot"]["validated_proposal"] is True
    assert result["metrics_snapshot"]["adoption_succeeded"] is True
    assert result["metrics_snapshot"]["human_intervention"] is False
    assert result["metrics_snapshot"]["duration_seconds"] == 300.0


def test_benchmark_attach_result_from_bridge_reply(tmp_path: Path) -> None:
    _add_case(tmp_path, "login-bug")
    _seed_bridge_reply(tmp_path)

    proc = _run_cli(
        ["benchmark", "attach", "login-bug", "--mode", "bridge_only", "--reply", "reply_bridge", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["metrics_snapshot"]["response_kind"] == "analysis"
    assert result["metrics_snapshot"]["validated_proposal"] is None
    assert result["warnings"]


def test_benchmark_attach_result_from_manual_file(tmp_path: Path) -> None:
    _add_case(tmp_path, "login-bug")
    manual_path = tmp_path / "raw_result.yaml"
    _write_yaml(
        manual_path,
        {
            "validated_proposal": False,
            "adoption_succeeded": False,
            "apply_tests_passed": None,
            "human_intervention": True,
            "validation_autonomy": False,
            "duration_seconds": 420,
            "summary": "raw AI required manual rewrite",
        },
    )

    proc = _run_cli(
        ["benchmark", "attach", "login-bug", "--mode", "raw_ai", "--manual-result", str(manual_path), "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)["result"]
    assert result["metrics_snapshot"]["human_intervention"] is True
    assert result["summary"] == "raw AI required manual rewrite"


def test_benchmark_report_aggregation_best_mode_and_save(tmp_path: Path) -> None:
    _add_case(tmp_path, "login-bug")
    _add_case(tmp_path, "auth-edge-case", "fix auth edge case")
    assert _run_cli(
        [
            "benchmark",
            "workset-save",
            "auth-bug-workset",
            "--case",
            "login-bug",
            "--case",
            "auth-edge-case",
        ],
        cwd=tmp_path,
    ).returncode == 0
    for case_id in ("login-bug", "auth-edge-case"):
        raw_path = tmp_path / f"{case_id}_raw.yaml"
        full_path = tmp_path / f"{case_id}_full.yaml"
        _write_yaml(
            raw_path,
            {
                "validated_proposal": False,
                "adoption_succeeded": False,
                "apply_tests_passed": None,
                "human_intervention": True,
                "validation_autonomy": False,
                "duration_seconds": 420,
            },
        )
        _write_yaml(
            full_path,
            {
                "validated_proposal": True,
                "adoption_succeeded": True,
                "apply_tests_passed": True,
                "human_intervention": False,
                "validation_autonomy": True,
                "duration_seconds": 180,
            },
        )
        assert _run_cli(["benchmark", "attach", case_id, "--mode", "raw_ai", "--manual-result", str(raw_path)], cwd=tmp_path).returncode == 0
        assert _run_cli(["benchmark", "attach", case_id, "--mode", "cambrian_full", "--manual-result", str(full_path)], cwd=tmp_path).returncode == 0

    proc = _run_cli(["benchmark", "report", "auth-bug-workset", "--save", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["best_mode"] == "cambrian_full"
    assert report["by_mode"]["cambrian_full"]["validated_proposal_rate"] == 1.0
    assert report["by_mode"]["raw_ai"]["human_intervention_rate"] == 1.0
    assert Path(report["saved_path"]).exists()
    assert (tmp_path / ".cambrian" / "benchmarks" / "reports" / "latest.yaml").exists()


def test_benchmark_status_summary_and_source_immutability(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def login():\n    return True\n", encoding="utf-8")
    before = _sha256(source_path)
    _add_case(tmp_path, "login-bug")
    assert _run_cli(["benchmark", "workset-save", "auth-bug-workset", "--case", "login-bug"], cwd=tmp_path).returncode == 0
    manual_path = tmp_path / "full.yaml"
    _write_json(
        manual_path,
        {
            "validated_proposal": True,
            "adoption_succeeded": True,
            "apply_tests_passed": True,
            "human_intervention": False,
            "validation_autonomy": True,
            "duration_seconds": 100,
        },
    )
    assert _run_cli(["benchmark", "attach", "login-bug", "--mode", "cambrian_full", "--manual-result", str(manual_path)], cwd=tmp_path).returncode == 0
    assert _run_cli(["benchmark", "report", "auth-bug-workset", "--save"], cwd=tmp_path).returncode == 0

    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Benchmark:" in status_proc.stdout
    assert "cambrian_full" in status_proc.stdout
    assert _sha256(source_path) == before
