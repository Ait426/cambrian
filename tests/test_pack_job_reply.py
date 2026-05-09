from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _cli(tmp_path: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        input=input_text,
        capture_output=True,
        check=False,
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _install_and_activate(tmp_path: Path) -> None:
    install = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert install.returncode == 0, install.stderr
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr


def _validating_auth_project(tmp_path: Path) -> None:
    _write_text(
        tmp_path / "src" / "auth.py",
        "\n".join(
            [
                "def normalize_username(username):",
                "    return username",
                "",
            ]
        ),
    )
    _write_text(
        tmp_path / "tests" / "test_auth.py",
        "\n".join(
            [
                "from src.auth import normalize_username",
                "",
                "",
                "def test_normalize_username():",
                "    assert normalize_username(' Alice ') == 'alice'",
                "",
            ]
        ),
    )


def _start_job(tmp_path: Path) -> dict:
    start = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    assert start.returncode == 0, start.stderr
    return json.loads(start.stdout)["job"]


def _patch_reply() -> str:
    return "\n".join(
        [
            "response_kind: patch_candidate",
            "summary: normalize username before login",
            "target_path: src/auth.py",
            "old_text: return username",
            "new_text: return username.strip().lower()",
            "reason: narrow auth login fix with pytest validation",
            "related_tests:",
            "  - tests/test_auth.py",
        ]
    )


def test_job_paste_patch_candidate_routes_to_validation_ready(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    _install_and_activate(tmp_path)
    _start_job(tmp_path)

    result = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=_patch_reply())
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["reply_kind"] == "patch_candidate"
    assert payload["status"] == "validation_ready"
    assert payload["patch_intent_ref"]
    assert payload["session_ref"]
    assert payload["next_command"].startswith("cambrian pack job-validate")
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")
    assert job["linked_bridge_reply_ref"]
    assert job["linked_patch_intent_ref"]
    assert job["validation_status"] == "ready"


def test_job_ingest_file_works(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    _install_and_activate(tmp_path)
    _start_job(tmp_path)
    reply_path = tmp_path / "reply.yaml"
    _write_text(reply_path, _patch_reply())

    result = _cli(tmp_path, "pack", "job-ingest", "latest", str(reply_path), "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["reply_kind"] == "patch_candidate"
    assert payload["status"] == "validation_ready"
    assert payload["bridge_reply_ref"]


def test_job_paste_analysis_materializes(tmp_path: Path) -> None:
    _install_and_activate(tmp_path)
    _start_job(tmp_path)
    reply = "response_kind: analysis\nsummary: inspect auth flow first\nrecommended_files:\n  - src/auth.py\n"

    result = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=reply)
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["reply_kind"] == "analysis"
    assert payload["status"] == "materialized"
    assert payload["materialization_ref"]
    assert payload["context_hint_ref"]


def test_job_paste_plan_creates_checklist(tmp_path: Path) -> None:
    _install_and_activate(tmp_path)
    _start_job(tmp_path)
    reply = "response_kind: plan\nsummary: plan the fix\nsteps:\n  - inspect auth\n  - validate pytest\n"

    result = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=reply)
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["reply_kind"] == "plan"
    assert payload["status"] == "checklist_ready"
    assert payload["checklist_ref"]
    next_result = _cli(tmp_path, "pack", "job-next", "latest")
    assert "bridge checklist-show" in next_result.stdout


def test_job_paste_invalid_blocks_safely(tmp_path: Path) -> None:
    _install_and_activate(tmp_path)
    _start_job(tmp_path)

    result = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text="not: [valid")
    payload = json.loads(result.stdout)

    assert result.returncode != 0
    assert payload["status"] == "blocked"
    assert payload["errors"]
    assert not list((tmp_path / ".cambrian" / "patches").glob("*.yaml"))


def test_job_validate_validates_ready_job(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    before_source = source.read_text(encoding="utf-8")
    _install_and_activate(tmp_path)
    _start_job(tmp_path)
    paste = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=_patch_reply())
    assert paste.returncode == 0, paste.stderr

    result = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["validation_status"] == "validated"
    assert payload["validation_contract_status"] == "validated"
    assert payload["trust_gate_status"] == "passed"
    assert payload["proposal_ref"]
    assert payload["evidence_ref"]
    assert (tmp_path / payload["evidence_ref"]).exists()
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert payload["ai_provider_called"] is False
    assert payload["outcome_snapshot"]["validated_proposal"] is True
    assert payload["outcome_snapshot"]["validation_autonomy"] is True
    assert source.read_text(encoding="utf-8") == before_source
    assert not (tmp_path / ".cambrian" / "adoptions").exists()


def test_job_validate_blocked_when_not_ready(tmp_path: Path) -> None:
    _install_and_activate(tmp_path)
    _start_job(tmp_path)

    result = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode != 0
    assert payload["validation_status"] == "not_ready"
    assert "no patch candidate reply" in "\n".join(payload["errors"])


def test_job_show_and_next_stage_aware(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    _install_and_activate(tmp_path)
    _start_job(tmp_path)
    waiting = _cli(tmp_path, "pack", "job-next", "latest")
    assert "pack job-paste" in waiting.stdout
    paste = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=_patch_reply())
    assert paste.returncode == 0, paste.stderr
    ready = _cli(tmp_path, "pack", "job-next", "latest")
    assert "pack job-validate" in ready.stdout
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    assert validate.returncode == 0, validate.stderr
    shown = _cli(tmp_path, "pack", "job-show", "latest")
    assert "Reply kind:" in shown.stdout
    assert "Validation:" in shown.stdout
    validated_next = _cli(tmp_path, "pack", "job-next", "latest")
    assert "pack job-apply" in validated_next.stdout


def test_usage_event_linkage(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    _install_and_activate(tmp_path)
    _start_job(tmp_path)
    paste = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=_patch_reply())
    assert paste.returncode == 0, paste.stderr
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    assert validate.returncode == 0, validate.stderr

    events = [_read_yaml(path) for path in (tmp_path / ".cambrian" / "packs" / "usage" / "events").glob("event_*.yaml")]
    surfaces = {event.get("surface_kind") for event in events}

    assert "pack_job_paste" in surfaces
    assert "pack_job_validate" in surfaces
    assert any(str(event.get("linked_request_ref", "")).startswith(".cambrian/packs/jobs/") for event in events)


def test_job_reply_flow_does_not_mutate_source_or_apply(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    before_source = source.read_text(encoding="utf-8")
    _install_and_activate(tmp_path)
    _start_job(tmp_path)

    paste = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=_patch_reply())
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")

    assert paste.returncode == 0, paste.stderr
    assert validate.returncode == 0, validate.stderr
    assert source.read_text(encoding="utf-8") == before_source
    assert not (tmp_path / ".cambrian" / "adoptions").exists()
    assert not (tmp_path / ".cambrian" / "templates" / "bootstrap_record.yaml").exists()
