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


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def make_typescript_auth_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "routes" / "auth.ts", "export function authRoute() {}\n")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def write_complete_answers(root: Path) -> None:
    answers = root / ".cambrian" / "interview" / "answers.yaml"
    answers.parent.mkdir(parents=True, exist_ok=True)
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Investigate auth and reservation bugs safely.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["no automatic patch apply", "no DB schema changes"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": "Relevant Jest tests pass and regression risk is explained.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def prepare_engineering_project(root: Path) -> None:
    make_typescript_auth_project(root)
    assert run_cli(root, "project", "scan", "--json").returncode == 0
    assert run_cli(root, "harness", "interview", "start", "--json").returncode == 0
    write_complete_answers(root)
    assert run_cli(root, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0


def pass_engineering_gate(root: Path) -> tuple[dict, dict, dict]:
    design = run_cli(root, "harness", "engineer", "design", "--json")
    assert design.returncode == 0, design.stderr
    review = run_cli(root, "harness", "engineer", "review", "--json")
    assert review.returncode == 0, review.stderr
    dry_run = run_cli(root, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json")
    assert dry_run.returncode == 0, dry_run.stderr
    return json.loads(design.stdout), json.loads(review.stdout), json.loads(dry_run.stdout)


def test_harness_engineer_design_creates_candidate(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)

    result = run_cli(tmp_path, "harness", "engineer", "design", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "candidate"
    assert payload["harness_id"].startswith("custom-")
    assert payload["quality_score"] >= 70
    assert ".cambrian/harness.yaml" in payload["generated_files_preview"]
    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    assert candidate["harness"]["type"] == "custom"
    assert 3 <= len(candidate["workforce"]["agents"]) <= 5
    assert candidate["skills"]
