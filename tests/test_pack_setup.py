from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _install_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _python_pytest_auth_project(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def login():\n    return True\n", encoding="utf-8")
    test_file.write_text("def test_login():\n    assert True\n", encoding="utf-8")


def test_setup_for_active_ready_pack(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    _install_seed_pack(tmp_path)
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr

    result = _cli(tmp_path, "pack", "setup", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["pack_id"] == "auth-bug-core"
    assert payload["readiness_status"] == "ready"
    assert any(step["step_id"] == "start_first_job" for step in payload["steps"])
    assert any("pack next" in action for action in payload["next_actions"])
    assert (tmp_path / ".cambrian" / "packs" / "setup_plans" / "latest.yaml").exists()


def test_setup_for_uninstalled_pack_does_not_install(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "setup", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)
    apply_result = _cli(tmp_path, "pack", "setup-apply", "latest", "--json")
    run = json.loads(apply_result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["readiness_status"] == "blocked"
    assert any(step["step_id"] == "install_pack" for step in payload["steps"])
    assert apply_result.returncode == 0, apply_result.stderr
    assert "install_pack" in run["skipped_steps"]
    assert not (tmp_path / ".cambrian" / "install" / "installed_packs.yaml").exists()
    assert not (tmp_path / ".cambrian" / "install" / "active_pack.yaml").exists()


def test_setup_applies_activation_when_safe(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    setup = _cli(tmp_path, "pack", "setup", "auth-bug-core")
    assert setup.returncode == 0, setup.stderr

    result = _cli(tmp_path, "pack", "setup-apply", "latest", "--json")
    payload = json.loads(result.stdout)
    active = _read_yaml(tmp_path / ".cambrian" / "install" / "active_pack.yaml")

    assert result.returncode == 0, result.stderr
    assert "activate_pack_context" in payload["applied_steps"]
    assert active["pack_id"] == "auth-bug-core"
    assert active["status"] == "active"


def test_setup_skips_user_action_required(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    setup = _cli(tmp_path, "pack", "setup", "auth-bug-core", "--json")
    plan = json.loads(setup.stdout)

    result = _cli(tmp_path, "pack", "setup-apply", "latest", "--json")
    run = json.loads(result.stdout)

    assert setup.returncode == 0, setup.stderr
    assert any(step["step_id"] == "configure_test_framework" for step in plan["steps"])
    assert result.returncode == 0, result.stderr
    assert "configure_test_framework" in run["skipped_steps"]
    assert any("pytest" in warning.lower() for warning in run["warnings"])


def test_setup_blocked_for_unsupported(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    _install_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "setup", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["readiness_status"] == "unsupported"
    assert payload["blocked"] is True
    assert any(step["action_kind"] == "unsupported" for step in payload["steps"])
    assert any((step["command"] or "") == "cambrian pack recommend" for step in payload["steps"])


def test_setup_show_works(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    setup = _cli(tmp_path, "pack", "setup", "auth-bug-core")
    assert setup.returncode == 0, setup.stderr

    result = _cli(tmp_path, "pack", "setup-show", "latest")

    assert result.returncode == 0, result.stderr
    assert "Pack Setup Plan" in result.stdout
    assert "Safe Cambrian fixes" in result.stdout


def test_status_and_pack_next_show_unresolved_setup(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr
    setup = _cli(tmp_path, "pack", "setup", "auth-bug-core")
    assert setup.returncode == 0, setup.stderr

    status = _cli(tmp_path, "status")
    next_result = _cli(tmp_path, "pack", "next")

    assert status.returncode == 0, status.stderr
    assert "Pack setup:" in status.stdout
    assert "unresolved user actions" in status.stdout
    assert next_result.returncode == 0, next_result.stderr
    assert "Pack setup:" in next_result.stdout


def test_no_auto_apply_bootstrap_or_source_mutation(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")
    _install_seed_pack(tmp_path)

    setup = _cli(tmp_path, "pack", "setup", "auth-bug-core")
    apply_result = _cli(tmp_path, "pack", "setup-apply", "latest")

    assert setup.returncode == 0, setup.stderr
    assert apply_result.returncode == 0, apply_result.stderr
    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
    assert not (tmp_path / ".cambrian" / "bootstrap").exists()
    assert (tmp_path / ".cambrian" / "packs" / "setup_runs" / "latest.yaml").exists()
    assert (tmp_path / ".cambrian" / "install" / "active_pack.yaml").exists()


def test_docs_mention_pack_setup_flow() -> None:
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "product" / "06_PACKS_AND_INSTALL.md",
        ROOT / "docs" / "product" / "07_EXECUTION_LOOPS.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)

    assert "cambrian pack setup auth-bug-core" in text
    assert "cambrian pack setup-apply" in text
    assert "does not install" in text.lower() or "will not install" in text.lower()
    assert "mutate source code" in text.lower()
