from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TS_FIXTURE = ROOT / "tests" / "fixtures" / "typescript_jest_auth_project"


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _copy_ts_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "ts-project"
    shutil.copytree(TS_FIXTURE, target)
    return target


def _write_answers(project: Path) -> None:
    payload = {
        "session_id": "harness-interview-test",
        "answers": {
            "primary_goal": "인증/API 버그를 안정적으로 수정하고 검증한다.",
            "test_command": "npm test",
            "build_command": "npm run build",
            "change_policy": "proposal_only",
            "forbidden_scope": ["자동 patch apply 금지"],
            "validation_standard": "관련 테스트 통과",
        },
    }
    path = project / ".cambrian" / "interview" / "answers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _prepare_custom_harness(project: Path) -> None:
    for args in [
        ("project", "scan", "--json"),
        ("harness", "interview", "start", "--json"),
    ]:
        result = _run_cli(project, *args)
        assert result.returncode == 0, f"{args}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    _write_answers(project)
    for args in [
        ("harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json"),
        ("harness", "plan", "--json"),
        ("harness", "engineer", "design", "--json"),
        ("harness", "engineer", "review", "--json"),
        ("harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json"),
        ("harness", "install", "--confirm", "--json"),
    ]:
        result = _run_cli(project, *args)
        assert result.returncode == 0, f"{args}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_typescript_jest_harness_custom_first_flow(tmp_path: Path) -> None:
    project = _copy_ts_fixture(tmp_path)

    scan = _run_cli(project, "project", "scan", "--json")
    assert scan.returncode == 0, scan.stderr
    scan_payload = json.loads(scan.stdout)
    assert scan_payload["profile"]["language"] == "typescript"
    assert scan_payload["profile"]["test_framework"] == "jest"
    assert "typescript-jest-auth-core" in scan_payload["profile"]["recommended_harnesses"]

    start = _run_cli(project, "harness", "interview", "start", "--json")
    assert start.returncode == 0, start.stderr
    start_payload = json.loads(start.stdout)
    assert start_payload["mode"] == "custom_harness_first"
    assert any(option["id"] == "typescript-jest-auth-core" for option in start_payload["preset_options"])

    _write_answers(project)
    answer = _run_cli(project, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json")
    assert answer.returncode == 0, answer.stderr

    plan = _run_cli(project, "harness", "plan", "--json")
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_type"] == "custom"
    assert plan_payload["harness_id"].startswith("custom-")
    assert _run_cli(project, "harness", "engineer", "design", "--json").returncode == 0
    assert _run_cli(project, "harness", "engineer", "review", "--json").returncode == 0
    assert _run_cli(project, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json").returncode == 0

    install_without_confirm = _run_cli(project, "harness", "install", "--json")
    assert install_without_confirm.returncode == 1
    assert json.loads(install_without_confirm.stdout)["error"] == "confirmation_required"

    install = _run_cli(project, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    install_payload = json.loads(install.stdout)
    assert install_payload["plan_type"] == "custom"
    assert ".cambrian/project.yaml" in install_payload["installed_files"]

    status = _run_cli(project, "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["initialized"] is True
    assert status_payload["harness"]["fitted"] is True
    assert status_payload["harness"]["type"] == "custom_harness"

    harness_show = _run_cli(project, "harness", "show", "--json")
    assert harness_show.returncode == 0, harness_show.stderr
    harness_show_payload = json.loads(harness_show.stdout)
    assert harness_show_payload["type"] == "custom_harness"
    assert harness_show_payload["fitted"] is True

    dispatch = _run_cli(project, "agent", "dispatch", "로그인 에러 수정해", "--json")
    assert dispatch.returncode == 0, dispatch.stderr
    dispatch_payload = json.loads(dispatch.stdout)
    assert dispatch_payload["harness_id"].startswith("custom-")
    assert dispatch_payload["change_policy"] == "proposal_only"
    assert dispatch_payload["job_id"].startswith("job-custom-")


def test_custom_harness_job_validate_does_not_invoke_pytest_lane(tmp_path: Path) -> None:
    project = _copy_ts_fixture(tmp_path)
    _prepare_custom_harness(project)
    dispatch = _run_cli(project, "agent", "dispatch", "로그인 에러 수정해", "--json")
    assert dispatch.returncode == 0, dispatch.stderr

    reply = project / "ai_reply_patch_candidate.yaml"
    reply.write_text(
        """
response_kind: patch_candidate
summary: Add Bearer token handling.
target_path: backend/src/middleware/authMiddleware.ts
reason: Auth middleware should parse Bearer tokens.
old_text: |
  export function authenticate(header: string | undefined): boolean {
    return Boolean(header);
  }
new_text: |
  export function authenticate(header: string | undefined): boolean {
    if (!header) {
      return false;
    }
    const token = header.startsWith("Bearer ") ? header.slice(7).trim() : header.trim();
    return Boolean(token);
  }
""".lstrip(),
        encoding="utf-8",
    )
    ingest = _run_cli(project, "job", "ingest", "latest", str(reply), "--json")
    assert ingest.returncode == 0, f"STDOUT:\n{ingest.stdout}\nSTDERR:\n{ingest.stderr}"

    validate = _run_cli(project, "job", "validate", "latest", "--json")

    assert validate.returncode != 0
    payload = json.loads(validate.stdout)
    assert payload["pack_id"].startswith("custom-")
    assert payload["outcome_snapshot"].get("validation_lane") == "custom harness"
    assert payload["outcome_snapshot"].get("auto_apply") is False
    assert "npm test" in payload["outcome_snapshot"].get("test_commands", [])
    assert payload["verdict"] == "hold"
    assert payload["latest_verdict_ref"] == ".cambrian/reports/latest_verdict.json"
    assert payload["evaluator_verdict"]["verdict_reason"] == "manual_validation_required"
    latest_verdict = json.loads((project / ".cambrian" / "reports" / "latest_verdict.json").read_text(encoding="utf-8"))
    assert latest_verdict["report_kind"] == "evaluator_verdict"
    assert latest_verdict["verdict_contract"] == ["pass", "hold", "rollback"]
    assert latest_verdict["verdict"] == "hold"
    assert latest_verdict["promotion_readiness"] == "blocked"
    assert latest_verdict["domain_spec"]["validation_commands"] == ["npm test", "npm run build"]
    assert "pytest -q" not in json.dumps(payload, ensure_ascii=False).lower()

    complete = _run_cli(
        project,
        "job",
        "complete",
        "latest",
        "--outcome",
        "success",
        "--notes",
        "manual validation passed",
        "--json",
    )
    assert complete.returncode == 0, complete.stderr
    complete_payload = json.loads(complete.stdout)
    assert complete_payload["verdict"] == "hold"
    assert complete_payload["latest_verdict_ref"] == ".cambrian/reports/latest_verdict.json"
    assert complete_payload["evaluator_verdict"]["verdict_reason"] == "manual_outcome_success_without_passed_validation_not_ready"
    assert complete_payload["evaluator_verdict"]["promotion_readiness"] == "blocked"
    latest_after_complete = json.loads((project / ".cambrian" / "reports" / "latest_verdict.json").read_text(encoding="utf-8"))
    assert latest_after_complete["verdict"] == "hold"
    assert latest_after_complete["outcome_ref"] == complete_payload["outcome_ref"]
    assert latest_after_complete["manual_outcome"] == "success"
    assert latest_after_complete["metrics"]["validation_evidence_present"] is True

    failed_complete = _run_cli(
        project,
        "job",
        "complete",
        "latest",
        "--outcome",
        "failed",
        "--notes",
        "manual validation failed",
        "--json",
    )
    assert failed_complete.returncode == 0, failed_complete.stderr
    failed_payload = json.loads(failed_complete.stdout)
    assert failed_payload["verdict"] == "rollback"
    assert failed_payload["evaluator_verdict"]["rollback_reason"] == "manual outcome recorded as failed"
    latest_after_failed = json.loads((project / ".cambrian" / "reports" / "latest_verdict.json").read_text(encoding="utf-8"))
    assert latest_after_failed["verdict"] == "rollback"
    assert latest_after_failed["manual_outcome"] == "failed"


def test_custom_harness_stays_active_when_legacy_profile_exists(tmp_path: Path) -> None:
    project = _copy_ts_fixture(tmp_path)
    _prepare_custom_harness(project)

    legacy_fit = _run_cli(project, "harness", "fit", "--json")
    assert legacy_fit.returncode == 0, legacy_fit.stderr
    assert (project / ".cambrian" / "harness" / "profile.yaml").exists()

    harness_show = _run_cli(project, "harness", "show", "--json")
    assert harness_show.returncode == 0, harness_show.stderr
    harness_payload = json.loads(harness_show.stdout)
    assert harness_payload["type"] == "custom_harness"
    assert harness_payload["harness_id"].startswith("custom-")
    assert harness_payload["legacy_harness"]["harness_id"].startswith("harness-")

    start = _run_cli(project, "job", "start", "custom harness split-brain smoke", "--json")
    assert start.returncode == 0, start.stderr
    payload = json.loads(start.stdout)
    packet = yaml.safe_load((project / payload["request_packet_ref"]).read_text(encoding="utf-8"))
    assert packet["harness_summary"]["harness_id"] == payload["harness_id"]
    assert packet["harness_summary"]["project_type"] == "custom_harness"
    assert packet["agent_summary"]["active_agents"] == payload["selected_agents"]
    assert "bug-fix-agent" not in packet["agent_summary"]["active_agents"]
    assert "bug-fix-agent" not in payload["pack_job"]["packet_preview"]
