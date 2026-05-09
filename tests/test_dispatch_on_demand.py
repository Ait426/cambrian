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


def _make_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _write_answers(root: Path) -> None:
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "인증 세션 만료 문제를 안정적으로 점검한다.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": "Jest 테스트 통과",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_install_does_not_dispatch_and_job_start_dispatches_on_demand(tmp_path: Path) -> None:
    _make_project(tmp_path)

    assert _run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert _run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    _write_answers(tmp_path)
    assert _run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    design = _run_cli(tmp_path, "harness", "design", "--json")
    assert design.returncode == 0, design.stderr
    assert json.loads(design.stdout)["plan_type"] == "custom"
    workforce = _run_cli(tmp_path, "workforce", "generate", "--json")
    assert workforce.returncode == 0, workforce.stderr
    assert any(agent["id"] == "auth-flow-investigator" for agent in json.loads(workforce.stdout)["agents"])
    assert _run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    assert _run_cli(tmp_path, "harness", "engineer", "review", "--json").returncode == 0
    assert _run_cli(tmp_path, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json").returncode == 0
    install = _run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    install_payload = json.loads(install.stdout)
    assert install_payload["no_agent_dispatched"] is True
    assert install_payload["workforce_id"].startswith("workforce-")
    assert not (tmp_path / ".cambrian" / "packs" / "jobs").exists()

    start = _run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")
    assert start.returncode == 0, start.stderr
    payload = json.loads(start.stdout)
    assert payload["ok"] is True
    assert payload["job_id"].startswith("job-custom-")
    assert "auth-flow-investigator" in payload["selected_agents"]
    assert "risk-reviewer" in payload["selected_agents"]
    assert "trace-auth-token-flow" in payload["selected_skills"]
    assert "propose-safe-patch" in payload["selected_skills"]
    assert payload["dispatch_reason"]
    assert (tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml").exists()


def test_agent_run_uses_explicit_generated_agent(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _run_cli(tmp_path, "project", "scan", "--json")
    _run_cli(tmp_path, "harness", "interview", "start", "--json")
    _write_answers(tmp_path)
    _run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json")
    _run_cli(tmp_path, "harness", "engineer", "design", "--json")
    _run_cli(tmp_path, "harness", "engineer", "review", "--json")
    _run_cli(tmp_path, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json")
    _run_cli(tmp_path, "harness", "install", "--confirm", "--json")

    result = _run_cli(tmp_path, "agent", "run", "auth-flow-investigator", "Bearer 토큰 검증 흐름 점검해", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["selected_agents"] == ["auth-flow-investigator"]
    assert "trace-auth-token-flow" in payload["selected_skills"]
    assert payload["job_id"].startswith("job-custom-")
