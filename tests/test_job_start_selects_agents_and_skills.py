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


def _prepare(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")
    assert _run_cli(root, "project", "scan", "--json").returncode == 0
    assert _run_cli(root, "harness", "interview", "start", "--json").returncode == 0
    answers = root / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
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
    assert _run_cli(root, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert _run_cli(root, "harness", "design", "--json").returncode == 0
    assert _run_cli(root, "workforce", "generate", "--json").returncode == 0
    assert _run_cli(root, "skill", "generate", "--json").returncode == 0
    assert _run_cli(root, "harness", "engineer", "design", "--json").returncode == 0
    assert _run_cli(root, "harness", "engineer", "review", "--json").returncode == 0
    assert _run_cli(root, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json").returncode == 0
    assert _run_cli(root, "harness", "install", "--confirm", "--json").returncode == 0


def test_job_start_selects_agents_and_skills(tmp_path: Path) -> None:
    _prepare(tmp_path)
    source_path = tmp_path / "backend" / "src" / "middleware" / "authMiddleware.ts"
    source_before = source_path.read_text(encoding="utf-8")

    result = _run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["status"] == "created"
    assert payload["job_status"] == "waiting_for_ai_reply"
    assert payload["harness_id"].startswith("custom-")
    assert payload["workforce_id"].startswith("workforce-")
    assert "auth-flow-investigator" in payload["selected_agents"]
    assert "jest-regression-guardian" in payload["selected_agents"]
    assert "risk-reviewer" in payload["selected_agents"]
    assert "trace-auth-token-flow" in payload["selected_skills"]
    assert "inspect-jest-auth-test" in payload["selected_skills"]
    assert "review-regression-risk" in payload["selected_skills"]
    assert "propose-safe-patch" in payload["selected_skills"]
    assert payload["dispatch_reason"]
    assert payload["change_policy"] == "proposal_only"
    assert "npm test" in payload["validation_commands"]
    assert payload["request_packet_ref"].startswith(".cambrian/bridge/packets/")
    assert payload["request_packet"] == payload["request_packet_ref"]
    assert payload["job_ref"].startswith(".cambrian/packs/jobs/")
    assert payload["ai_provider_called"] is False
    assert payload["source_code_modified"] is False
    assert payload["next_commands"] == [
        "cambrian job ingest latest ai_reply_patch_candidate.yaml",
        "cambrian job validate latest",
    ]
    assert payload["pack_job"]["packet_ref"] == payload["request_packet_ref"]
    assert payload["pack_job"]["job_ref"] == payload["job_ref"]
    assert (tmp_path / payload["request_packet_ref"]).exists()
    assert (tmp_path / payload["job_ref"]).exists()
    latest = yaml.safe_load((tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml").read_text(encoding="utf-8"))
    assert latest["status"] == "waiting_for_ai_reply"
    assert latest["outcome_snapshot"]["selected_agents"] == payload["selected_agents"]
    assert latest["outcome_snapshot"]["selected_skills"] == payload["selected_skills"]
    assert source_path.read_text(encoding="utf-8") == source_before
