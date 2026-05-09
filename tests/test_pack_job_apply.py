from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

import engine.project_pack_job_apply as pack_job_apply


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


def _install_activate_validate(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    install = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert install.returncode == 0, install.stderr
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr
    start = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    assert start.returncode == 0, start.stderr
    paste = _cli(tmp_path, "pack", "job-paste", "latest", "--json", input_text=_patch_reply())
    assert paste.returncode == 0, paste.stderr
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    assert validate.returncode == 0, validate.stderr


def test_apply_preview_for_validated_job_no_source_mutation(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)
    source = tmp_path / "src" / "auth.py"
    before = source.read_text(encoding="utf-8")

    result = _cli(tmp_path, "pack", "job-apply", "latest", "--json")
    payload = json.loads(result.stdout)
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")
    next_result = _cli(tmp_path, "pack", "job-next", "latest")

    assert result.returncode == 0, result.stderr
    assert payload["safe_to_apply"] is True
    assert payload["requires_confirm"] is True
    assert "src/auth.py" in payload["target_paths"]
    assert source.read_text(encoding="utf-8") == before
    assert job["apply_status"] == "previewed"
    assert "--confirm" in next_result.stdout


def test_apply_confirm_uses_existing_apply_path(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)

    result = _cli(tmp_path, "pack", "job-apply", "latest", "--confirm", "--json")
    payload = json.loads(result.stdout)
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")

    assert result.returncode == 0, result.stderr
    assert payload["status"] == "applied"
    assert payload["tests_passed"] is True
    assert payload["regression_free_apply"] is True
    assert "src/auth.py" in payload["changed_paths"]
    assert "return username.strip().lower()" in (tmp_path / "src" / "auth.py").read_text(encoding="utf-8")
    assert (tmp_path / ".cambrian" / "adoptions" / "_latest.json").exists()
    assert job["apply_status"] == "applied"
    assert job["linked_apply_record_ref"]
    assert job["final_outcome_snapshot"]["applied"] is True


def test_apply_blocked_if_not_validated(tmp_path: Path) -> None:
    _validating_auth_project(tmp_path)
    install = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert install.returncode == 0, install.stderr
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr
    start = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    assert start.returncode == 0, start.stderr

    result = _cli(tmp_path, "pack", "job-apply", "latest", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode != 0
    assert payload["safe_to_apply"] is False
    assert "no validated proposal is linked" in "\n".join(payload["errors"])


def test_no_new_patch_engine_behavior() -> None:
    source = inspect.getsource(pack_job_apply.PackJobApplyHandler.apply)

    assert "PatchApplier().apply" in source
    assert "old_text.replace" not in source
    assert "_atomic_write" not in source


def test_adopt_accepted_updates_final_outcome(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)
    apply_result = _cli(tmp_path, "pack", "job-apply", "latest", "--confirm", "--json")
    assert apply_result.returncode == 0, apply_result.stderr

    result = _cli(
        tmp_path,
        "pack",
        "job-adopt",
        "latest",
        "--accepted",
        "--reason",
        "validated and applied cleanly",
        "--json",
    )
    payload = json.loads(result.stdout)
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")
    next_result = _cli(tmp_path, "pack", "job-next", "latest")

    assert result.returncode == 0, result.stderr
    assert payload["decision"] == "accepted"
    assert payload["adoption_succeeded"] is True
    assert job["adoption_status"] == "accepted"
    assert job["final_status"] == "adopted"
    assert job["final_outcome_snapshot"]["adoption_succeeded"] is True
    assert "pack proof auth-bug-core" in next_result.stdout


def test_adopt_rejected_stores_reason(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)

    result = _cli(
        tmp_path,
        "pack",
        "job-adopt",
        "latest",
        "--rejected",
        "--reason",
        "patch too broad",
        "--json",
    )
    payload = json.loads(result.stdout)
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")

    assert result.returncode == 0, result.stderr
    assert payload["decision"] == "rejected"
    assert payload["adoption_succeeded"] is False
    assert payload["reason"] == "patch too broad"
    assert job["adoption_status"] == "rejected"
    assert job["final_outcome_snapshot"]["rejection_reason"] == "patch too broad"


def test_adopt_skipped(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)

    result = _cli(tmp_path, "pack", "job-adopt", "latest", "--skipped", "--reason", "not needed", "--json")
    payload = json.loads(result.stdout)
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")

    assert result.returncode == 0, result.stderr
    assert payload["decision"] == "skipped"
    assert payload["adoption_succeeded"] is None
    assert job["adoption_status"] == "skipped"
    assert job["final_status"] == "closed"


def test_job_show_and_next_apply_adoption_states(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)

    validated_next = _cli(tmp_path, "pack", "job-next", "latest")
    assert "pack job-apply" in validated_next.stdout
    preview = _cli(tmp_path, "pack", "job-apply", "latest")
    assert preview.returncode == 0, preview.stderr
    preview_next = _cli(tmp_path, "pack", "job-next", "latest")
    assert "--confirm" in preview_next.stdout
    applied = _cli(tmp_path, "pack", "job-apply", "latest", "--confirm")
    assert applied.returncode == 0, applied.stderr
    applied_next = _cli(tmp_path, "pack", "job-next", "latest")
    assert "pack job-adopt" in applied_next.stdout
    accepted = _cli(tmp_path, "pack", "job-adopt", "latest", "--accepted", "--reason", "ok")
    assert accepted.returncode == 0, accepted.stderr
    shown = _cli(tmp_path, "pack", "job-show", "latest")
    assert "Apply:" in shown.stdout
    assert "Adoption:" in shown.stdout
    assert "Final outcome snapshot:" in shown.stdout


def test_pack_outcomes_include_adoption_apply(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)
    apply_result = _cli(tmp_path, "pack", "job-apply", "latest", "--confirm", "--json")
    assert apply_result.returncode == 0, apply_result.stderr
    adopt = _cli(tmp_path, "pack", "job-adopt", "latest", "--accepted", "--reason", "ok", "--json")
    assert adopt.returncode == 0, adopt.stderr

    result = _cli(tmp_path, "pack", "usage", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["counts"]["applied_count"] >= 1
    assert payload["counts"]["accepted_count"] >= 1
    assert payload["counts"]["adopted_count"] >= 1
    assert payload["counts"]["regression_free_apply_count"] >= 1


def test_no_auto_apply_or_adoption(tmp_path: Path) -> None:
    _install_activate_validate(tmp_path)
    source = tmp_path / "src" / "auth.py"
    before = source.read_text(encoding="utf-8")

    preview = _cli(tmp_path, "pack", "job-apply", "latest", "--json")
    job = _read_yaml(tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml")

    assert preview.returncode == 0, preview.stderr
    assert source.read_text(encoding="utf-8") == before
    assert job.get("adoption_status") in {None, "undecided"}
    assert not (tmp_path / ".cambrian" / "packs" / "jobs" / "adoptions").exists()
