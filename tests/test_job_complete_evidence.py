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


def prepare_custom_harness_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "routes" / "auth.ts", "export function route() {}\n")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")
    assert run_cli(root, "project", "scan", "--json").returncode == 0
    assert run_cli(root, "harness", "interview", "start", "--json").returncode == 0
    answers = root / ".cambrian" / "interview" / "answers.yaml"
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
                    "validation_standard": "Relevant Jest tests pass.",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(root, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert run_cli(root, "harness", "design", "--json").returncode == 0
    assert run_cli(root, "workforce", "generate", "--json").returncode == 0
    assert run_cli(root, "skill", "generate", "--json").returncode == 0
    assert run_cli(root, "harness", "engineer", "design", "--json").returncode == 0
    assert run_cli(root, "harness", "engineer", "review", "--json").returncode == 0
    assert run_cli(root, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json").returncode == 0
    assert run_cli(root, "harness", "install", "--confirm", "--json").returncode == 0
    started = run_cli(root, "job", "start", "check refresh token login failure", "--json")
    assert started.returncode == 0, started.stderr
    payload = json.loads(started.stdout)
    assert payload["job_id"]


def complete_latest_job(root: Path) -> dict:
    result = run_cli(
        root,
        "job",
        "complete",
        "latest",
        "--outcome",
        "partial",
        "--notes",
        "test command was wrong and refresh token path was missed",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def ingest_and_validate_patch_candidate(root: Path) -> dict:
    reply = root / "ai_reply_patch_candidate.yaml"
    reply.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "reason": "Authorization header must strip Bearer before verification.",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(root, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")
    assert ingest.returncode == 0, ingest.stderr
    validate = run_cli(root, "job", "validate", "latest", "--json")
    assert validate.returncode != 0
    return json.loads(validate.stdout)


def test_job_complete_records_outcome_and_evidence(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)

    payload = complete_latest_job(tmp_path)

    assert payload["ok"] is True
    assert payload["status"] == "recorded"
    assert payload["outcome"] == "partial"
    assert payload["outcome_ref"]
    assert payload["evidence_ref"] == ".cambrian/evidence/outcomes.yaml"
    assert (tmp_path / payload["outcome_ref"]).exists()
    evidence = yaml.safe_load((tmp_path / ".cambrian" / "evidence" / "outcomes.yaml").read_text(encoding="utf-8"))
    assert evidence["outcomes"][0]["outcome"] == "partial"
    assert "trace-auth-token-flow" in evidence["outcomes"][0]["selected_skills"]



def test_job_complete_links_validation_evidence_for_evolution(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)

    payload = complete_latest_job(tmp_path)

    assert payload["ok"] is True
    assert payload["validation_evidence_ref"] == validation["evidence_ref"]
    assert payload["validation_contract_status"] == "manual_validation_required"
    assert payload["trust_gate_status"] == "manual_required"
    assert payload["ready_for_evolution"] is True
    assert payload["source_code_modified_by_cambrian"] is False
    assert "npm test" in payload["validation_commands"]
    assert payload["checked_artifacts"]
    assert "Patch proposal was not applied to source code" in payload["unchecked_items"]
    outcome = yaml.safe_load((tmp_path / payload["outcome_ref"]).read_text(encoding="utf-8"))
    assert outcome["validation_evidence_ref"] == validation["evidence_ref"]
    assert outcome["ready_for_evolution"] is True
    assert outcome["source_code_modified_by_cambrian"] is False
    ledger = yaml.safe_load((tmp_path / ".cambrian" / "evidence" / "outcomes.yaml").read_text(encoding="utf-8"))
    assert ledger["outcomes"][0]["validation_evidence_ref"] == validation["evidence_ref"]
