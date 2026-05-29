from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def _make_typescript_jest_auth_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(root / "backend" / "src" / "api" / "authRoutes.ts", 'export const route = "/api/auth/login";\n')
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _write_answers(root: Path) -> None:
    payload = {
        "session_id": "harness-interview-test",
        "answers": {
            "primary_goal": "인증/예약 관련 버그를 안정적으로 수정하고 검증한다.",
            "test_command": "npm test",
            "build_command": "npm run build",
            "change_policy": "proposal_only",
            "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
            "validation_standard": "관련 테스트 통과",
        },
    }
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_project_first_cli_flow_creates_custom_agent_dispatch_job(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)

    scan = _run_cli(tmp_path, "project", "scan", "--json")
    assert scan.returncode == 0, scan.stderr
    start = _run_cli(tmp_path, "harness", "interview", "start", "--json")
    assert start.returncode == 0, start.stderr
    _write_answers(tmp_path)
    answer = _run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json")
    assert answer.returncode == 0, answer.stderr
    plan = _run_cli(tmp_path, "harness", "plan", "--json")
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_type"] == "custom"
    assert _run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    assert _run_cli(tmp_path, "harness", "engineer", "review", "--json").returncode == 0
    assert _run_cli(tmp_path, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json").returncode == 0

    install_without_confirm = _run_cli(tmp_path, "harness", "install", "--json")
    assert install_without_confirm.returncode == 1
    assert json.loads(install_without_confirm.stdout)["error"] == "confirmation_required"

    install = _run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    dispatch = _run_cli(tmp_path, "agent", "dispatch", "로그인 에러 수정해", "--json")
    assert dispatch.returncode == 0, dispatch.stderr
    payload = json.loads(dispatch.stdout)

    assert payload["ok"] is True
    assert payload["harness_id"].startswith("custom-")
    assert payload["harness_status"] == "active"
    assert payload["change_policy"] == "proposal_only"
    assert payload["job_id"].startswith("job-custom-")
    assert any(command.startswith("cambrian job ingest ") for command in payload["next_commands"])
    assert (tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml").exists()


def test_job_alias_help_exists(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "job", "--help")

    assert result.returncode == 0
    assert "ingest" in result.stdout
    assert "validate" in result.stdout
