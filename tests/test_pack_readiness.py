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


def test_doctor_active_pack_ready(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    _install_seed_pack(tmp_path)
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr

    result = _cli(tmp_path, "pack", "doctor", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["pack_id"] == "auth-bug-core"
    assert payload["active"] is True
    assert payload["readiness_status"] == "ready"
    assert payload["fit_status"] == "strong"


def test_doctor_installed_pack_partial_when_pytest_unknown(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["installed"] is True
    assert payload["readiness_status"] == "partial"
    assert any("pytest" in warning.lower() for warning in payload["warnings"])


def test_doctor_uninstalled_pack_blocked(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["installed"] is False
    assert payload["readiness_status"] == "blocked"
    assert "cambrian install pack auth-bug-core" in "\n".join(payload["next_actions"])


def test_doctor_unsupported_non_python_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")

    result = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["readiness_status"] == "unsupported"
    assert payload["fit_status"] == "weak"
    assert any("stack" in error.lower() for error in payload["errors"])


def test_missing_installed_artifact_blocks_readiness(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    (tmp_path / ".cambrian" / "templates" / "templates.yaml").unlink()

    result = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["readiness_status"] == "blocked"
    assert any("missing template ref" in error for error in payload["errors"])


def test_digest_failure_blocks_readiness(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    installed = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    manifest_ref = installed["packs"][0]["manifest_ref"]
    manifest_path = tmp_path / manifest_ref
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    result = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["readiness_status"] == "blocked"
    assert any("digest mismatch" in error for error in payload["errors"])


def test_pack_show_surfaces_readiness(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    doctor = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--save")
    assert doctor.returncode == 0, doctor.stderr

    result = _cli(tmp_path, "pack", "show", "auth-bug-core")

    assert result.returncode == 0, result.stderr
    assert "Readiness:" in result.stdout
    assert "partial" in result.stdout


def test_pack_activate_blocks_failed_readiness(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    (tmp_path / ".cambrian" / "templates" / "templates.yaml").unlink()

    result = _cli(tmp_path, "pack", "activate", "auth-bug-core")

    assert result.returncode != 0
    assert "Readiness:" in result.stderr
    assert not (tmp_path / ".cambrian" / "install" / "active_pack.yaml").exists()


def test_pack_next_shows_readiness_warning(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr

    result = _cli(tmp_path, "pack", "next")

    assert result.returncode == 0, result.stderr
    assert "Readiness:" in result.stdout
    assert "partial" in result.stdout
    assert "Pack Next" in result.stdout


def test_status_shows_active_pack_readiness(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    _install_seed_pack(tmp_path)
    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, activate.stderr

    result = _cli(tmp_path, "status")

    assert result.returncode == 0, result.stderr
    assert "Active pack:" in result.stdout
    assert "Readiness:" in result.stdout
    assert "ready" in result.stdout


def test_pack_readiness_does_not_mutate_project_source(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")
    _install_seed_pack(tmp_path)

    doctor = _cli(tmp_path, "pack", "doctor", "auth-bug-core", "--save")
    readiness = _cli(tmp_path, "pack", "readiness", "auth-bug-core")
    show = _cli(tmp_path, "pack", "show", "auth-bug-core")
    status = _cli(tmp_path, "status")

    assert doctor.returncode == 0, doctor.stderr
    assert readiness.returncode == 0, readiness.stderr
    assert show.returncode == 0, show.stderr
    assert status.returncode == 0, status.stderr
    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
    assert (tmp_path / ".cambrian" / "packs" / "readiness" / "latest.yaml").exists()


def test_docs_mention_pack_doctor_flow() -> None:
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "product" / "06_PACKS_AND_INSTALL.md",
        ROOT / "docs" / "product" / "07_EXECUTION_LOOPS.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)

    assert "cambrian pack doctor auth-bug-core" in text
    assert "readiness" in text.lower()
    assert "does not apply" in text.lower() or "not apply" in text.lower()
