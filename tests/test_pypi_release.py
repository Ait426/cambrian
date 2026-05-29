import hashlib
import json
from pathlib import Path

import pytest

from scripts.check_pypi_publish_ready import check_pypi_publish_ready, verify_pypi_publish_ready_file
from scripts.prepare_pypi_release import (
    _release_receipt,
    _verify_publish_ready_gate,
    _verify_testpypi_install_gate,
    preflight_publish,
    prepare_release,
    verify_pypi_publish_preflight_receipt_file,
    verify_pypi_release_receipt_file,
)
from scripts.verify_pypi_install import _install_receipt, verify_pypi_install_receipt_file


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pyproject_has_pypi_metadata() -> None:
    text = _read("pyproject.toml")

    for phrase in [
        'name = "cambrian"',
        'version = "0.3.0"',
        'description = "Installable AI company runtime',
        'readme = "README.md"',
        'license = "MIT"',
        '[project.urls]',
        'cambrian = "engine.cli:main"',
    ]:
        assert phrase in text

    assert "License :: OSI Approved :: MIT License" not in text


def test_pypi_release_doc_records_safe_publish_flow() -> None:
    text = _read("docs/release/PYPI_RELEASE.md")

    for phrase in [
        "python scripts/prepare_pypi_release.py",
        "dist/pypi/",
        "twine check",
        "--upload testpypi",
        "--upload pypi",
        "--verify-receipt dist/pypi_release_receipt.json",
        "dist/pypi_local_wheel_install_receipt.json",
        "dist/pypi_testpypi_install_receipt.json",
        "--testpypi-install-receipt",
        "--preflight-upload testpypi",
        "--verify-preflight-receipt",
        "check_pypi_publish_ready.py",
        "pypi-publish-ready-testpypi.json",
        "--publish-ready-receipt dist/pypi-publish-ready-testpypi.json",
        "--publish-ready-receipt dist/pypi-publish-ready-pypi.json",
        "receipt body hash",
        "TWINE_PASSWORD",
        "TWINE_USERNAME=__token__",
        "python -m pip install cambrian",
        "토큰을 채팅에 붙여넣지 않는다",
    ]:
        assert phrase in text


def test_pypi_release_script_uses_isolated_dist_and_token_env() -> None:
    text = _read("scripts/prepare_pypi_release.py")

    for phrase in [
        'DEFAULT_DIST_SUBDIR = "pypi"',
        "twine",
        "TWINE_PASSWORD",
        "TESTPYPI_UPLOAD_URL",
        "PYPI_UPLOAD_URL",
        "pypi_release_receipt.json",
        "pypi_testpypi_install_receipt.json",
        "dist_dir_isolated",
        "testpypi_install_receipt_verified",
        "upload_environment_verified",
        "publish_ready_receipt_verified",
        "--publish-ready-receipt",
        "dist/pypi-publish-ready-testpypi.json",
        "dist/pypi-publish-ready-pypi.json",
        "twine_password_recorded",
        "missing_testpypi_install_receipt",
        "ready_to_upload_testpypi",
        "ready_to_upload_pypi",
        "PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION",
        "pypi_publish_preflight_receipt.json",
        "preflight_publish",
        "--preflight-upload",
        "--verify-preflight-receipt",
        "--testpypi-install-receipt",
        "verify_pypi_release_receipt_file",
        "--verify-receipt",
        "pypi_release_receipt_body_sha256",
        "absolute_paths_omitted",
        "command_steps",
    ]:
        assert phrase in text


def test_pypi_release_receipt_verifies_artifacts_without_private_paths(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist" / "pypi"
    dist_dir.mkdir(parents=True)
    wheel = dist_dir / "cambrian-0.3.0-py3-none-any.whl"
    sdist = dist_dir / "cambrian-0.3.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    root = tmp_path / "repo"
    root.mkdir()
    tool_venv = tmp_path / "tools"
    tool_venv.mkdir()
    receipt = _release_receipt(
        metadata={
            "name": "cambrian",
            "version": "0.3.0",
            "description": "Installable AI company runtime",
            "readme": "README.md",
            "requires_python": ">=3.11",
            "license": "MIT",
        },
        files=[
            {"file": wheel.name, "bytes": wheel.stat().st_size, "sha256": "0" * 64},
            {"file": sdist.name, "bytes": sdist.stat().st_size, "sha256": "0" * 64},
        ],
        name_status={"status": "available"},
        checks={
            "metadata_name_present": True,
            "metadata_version_present": True,
            "metadata_description_present": True,
            "metadata_readme_present": True,
            "metadata_license_present": True,
            "wheel_built": True,
            "sdist_built": True,
            "twine_check_passed": True,
            "wheel_metadata_has_no_local_paths": True,
            "pypi_name_not_known_taken": True,
            "dist_dir_isolated": True,
        },
        upload=None,
        upload_result=None,
        testpypi_install_gate=None,
        commands=[
            {
                "command": [tool_venv / "python.exe", "-m", "build", str(root), "--outdir", dist_dir],
                "cwd": str(root),
                "exit_code": 0,
                "status": "passed",
                "stdout": str(root),
                "stderr": "",
            }
        ],
        root=root,
        tool_venv=tool_venv,
        dist_dir=dist_dir,
    )
    receipt["files"][0]["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    receipt["files"][1]["sha256"] = hashlib.sha256(sdist.read_bytes()).hexdigest()
    receipt = _release_receipt(
        metadata=receipt["metadata"],
        files=receipt["files"],
        name_status=receipt["name_status"],
        checks=receipt["checks"],
        upload=None,
        upload_result=None,
        testpypi_install_gate=None,
        commands=[],
        root=root,
        tool_venv=tool_venv,
        dist_dir=dist_dir,
    )
    receipt_path = tmp_path / "dist" / "pypi_release_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verified = verify_pypi_release_receipt_file(receipt_path)
    text = receipt_path.read_text(encoding="utf-8")

    assert verified["status"] == "ready"
    assert verified["receipt_checks"]["body_hash_matched"] is True
    assert verified["receipt_checks"]["absolute_paths_omitted"] is True
    assert verified["artifact_verification_checks"][f"artifact_hash_matched:{wheel.name}"] is True
    assert str(root) not in text


def test_final_pypi_upload_requires_verified_testpypi_install_receipt(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    temp_dir = tmp_path / "venv"
    temp_dir.mkdir()
    commands = [
        {
            "command": [temp_dir / "Scripts" / "cambrian.exe", "--help"],
            "cwd": str(root),
            "exit_code": 0,
            "status": "passed",
            "stdout": "",
            "stderr": "",
        }
    ]
    checks = {
        "venv_created": True,
        "pip_upgrade_passed": True,
        "install_passed": True,
        "cli_help_passed": True,
        "doctor_passed": True,
        "no_token_required": True,
    }
    receipt = _install_receipt(
        repository="testpypi",
        package="cambrian",
        version="0.3.0",
        wheel=None,
        checks=checks,
        failed=[],
        commands=commands,
        root=root,
        temp_dir=temp_dir,
    )
    receipt_path = tmp_path / "dist" / "pypi_testpypi_install_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    gate = _verify_testpypi_install_gate(
        receipt_path,
        expected_package="cambrian",
        expected_version="0.3.0",
    )

    assert gate["status"] == "verified"
    assert gate["checks"]["repository_testpypi"] is True
    assert gate["receipt"] == "pypi_testpypi_install_receipt.json"

    bad_receipt = _install_receipt(
        repository="pypi",
        package="cambrian",
        version="0.3.0",
        wheel=None,
        checks=checks,
        failed=[],
        commands=commands,
        root=root,
        temp_dir=temp_dir,
    )
    bad_path = tmp_path / "dist" / "pypi_install_verification_receipt.json"
    bad_path.write_text(json.dumps(bad_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="repository_testpypi"):
        _verify_testpypi_install_gate(
            bad_path,
            expected_package="cambrian",
            expected_version="0.3.0",
        )


def test_final_pypi_upload_fails_fast_without_testpypi_install_receipt(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="TestPyPI install receipt"):
        prepare_release(
            upload="pypi",
            skip_name_check=True,
            testpypi_install_receipt=tmp_path / "missing.json",
        )


def test_upload_fails_fast_without_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="TWINE_PASSWORD"):
        prepare_release(
            dist_dir=tmp_path / "dist" / "pypi",
            upload="testpypi",
            skip_name_check=True,
        )

    assert not (tmp_path / "dist").exists()


def test_upload_requires_api_token_username(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TWINE_USERNAME", "not-token")
    monkeypatch.setenv("TWINE_PASSWORD", "secret-value-not-written")

    with pytest.raises(RuntimeError, match="TWINE_USERNAME"):
        prepare_release(
            dist_dir=tmp_path / "dist" / "pypi",
            upload="testpypi",
            skip_name_check=True,
        )

    assert not (tmp_path / "dist").exists()


def test_upload_requires_publish_ready_receipt_after_token_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TWINE_USERNAME", "__token__")
    monkeypatch.setenv("TWINE_PASSWORD", "secret-value-not-written")

    with pytest.raises(FileNotFoundError, match="publish-ready"):
        prepare_release(
            dist_dir=tmp_path / "dist" / "pypi",
            upload="testpypi",
            skip_name_check=True,
            publish_ready_receipt=tmp_path / "missing-publish-ready.json",
        )

    assert not (tmp_path / "dist").exists()


def _write_preflight_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    dist_dir = tmp_path / "dist" / "pypi"
    dist_dir.mkdir(parents=True)
    wheel = dist_dir / "cambrian-0.3.0-py3-none-any.whl"
    sdist = dist_dir / "cambrian-0.3.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    root = tmp_path / "repo"
    root.mkdir()
    tool_venv = tmp_path / "tools"
    tool_venv.mkdir()
    release = _release_receipt(
        metadata={
            "name": "cambrian",
            "version": "0.3.0",
            "description": "Installable AI company runtime",
            "readme": "README.md",
            "requires_python": ">=3.11",
            "license": "MIT",
        },
        files=[
            {"file": wheel.name, "bytes": wheel.stat().st_size, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()},
            {"file": sdist.name, "bytes": sdist.stat().st_size, "sha256": hashlib.sha256(sdist.read_bytes()).hexdigest()},
        ],
        name_status={"status": "available"},
        checks={
            "metadata_name_present": True,
            "metadata_version_present": True,
            "metadata_description_present": True,
            "metadata_readme_present": True,
            "metadata_license_present": True,
            "wheel_built": True,
            "sdist_built": True,
            "twine_check_passed": True,
            "wheel_metadata_has_no_local_paths": True,
            "pypi_name_not_known_taken": True,
            "dist_dir_isolated": True,
        },
        upload=None,
        upload_result=None,
        testpypi_install_gate=None,
        commands=[],
        root=root,
        tool_venv=tool_venv,
        dist_dir=dist_dir,
    )
    release_path = tmp_path / "dist" / "pypi_release_receipt.json"
    release_path.write_text(json.dumps(release, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checks = {
        "venv_created": True,
        "pip_upgrade_passed": True,
        "install_passed": True,
        "cli_help_passed": True,
        "doctor_passed": True,
        "no_token_required": True,
    }
    commands = [
        {
            "command": [tmp_path / "venv" / "Scripts" / "cambrian.exe", "--help"],
            "cwd": str(root),
            "exit_code": 0,
            "status": "passed",
            "stdout": "",
            "stderr": "",
        }
    ]
    temp_dir = tmp_path / "venv"
    temp_dir.mkdir()
    local_install = _install_receipt(
        repository="pypi",
        package="cambrian",
        version="0.3.0",
        wheel=wheel,
        checks=checks,
        failed=[],
        commands=commands,
        root=root,
        temp_dir=temp_dir,
    )
    local_path = tmp_path / "dist" / "pypi_local_wheel_install_receipt.json"
    local_path.write_text(json.dumps(local_install, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    testpypi_install = _install_receipt(
        repository="testpypi",
        package="cambrian",
        version="0.3.0",
        wheel=None,
        checks=checks,
        failed=[],
        commands=commands,
        root=root,
        temp_dir=temp_dir,
    )
    testpypi_path = tmp_path / "dist" / "pypi_testpypi_install_receipt.json"
    testpypi_path.write_text(json.dumps(testpypi_install, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return release_path, local_path, testpypi_path


def test_testpypi_publish_preflight_receipt_is_token_free(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)
    preflight_path = tmp_path / "dist" / "pypi_publish_preflight_receipt.json"

    receipt = preflight_publish(
        repository="testpypi",
        release_receipt=release_path,
        local_install_receipt=local_path,
        receipt_path=preflight_path,
    )
    verified = verify_pypi_publish_preflight_receipt_file(preflight_path)
    text = preflight_path.read_text(encoding="utf-8")

    assert receipt["status"] == "ready_for_testpypi_token"
    assert verified["receipt_checks"]["body_hash_matched"] is True
    assert receipt["checks"]["token_env_ready"] is False
    assert receipt["blocking_checks"] == []
    assert str(tmp_path) not in text
    assert "TWINE_PASSWORD=<testpypi-token>" in text


def test_testpypi_publish_preflight_with_token_is_ready_without_recording_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TWINE_USERNAME", "__token__")
    monkeypatch.setenv("TWINE_PASSWORD", "secret-value-not-written")
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)
    preflight_path = tmp_path / "dist" / "pypi_publish_preflight_token_receipt.json"

    receipt = preflight_publish(
        repository="testpypi",
        release_receipt=release_path,
        local_install_receipt=local_path,
        receipt_path=preflight_path,
        require_token_env=True,
    )
    verified = verify_pypi_publish_preflight_receipt_file(preflight_path)
    text = preflight_path.read_text(encoding="utf-8")

    assert receipt["status"] == "ready_to_upload_testpypi"
    assert verified["checks"]["token_env_ready"] is True
    assert verified["upload_env_gate"]["twine_password_present"] is True
    assert verified["upload_env_gate"]["twine_password_recorded"] is False
    assert "secret-value-not-written" not in text
    assert str(tmp_path) not in text


def test_pypi_publish_preflight_requires_testpypi_install_receipt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    release_path, local_path, testpypi_path = _write_preflight_inputs(tmp_path)

    receipt = preflight_publish(
        repository="pypi",
        release_receipt=release_path,
        local_install_receipt=local_path,
        testpypi_install_receipt=testpypi_path,
        receipt_path=tmp_path / "dist" / "pypi_publish_preflight_receipt.json",
    )

    assert receipt["status"] == "ready_for_pypi_token"
    assert receipt["checks"]["testpypi_install_receipt_verified"] is True
    assert receipt["testpypi_install_gate"]["checks"]["repository_testpypi"] is True


def test_pypi_publish_preflight_with_token_is_ready_without_recording_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TWINE_USERNAME", "__token__")
    monkeypatch.setenv("TWINE_PASSWORD", "secret-value-not-written")
    release_path, local_path, testpypi_path = _write_preflight_inputs(tmp_path)
    preflight_path = tmp_path / "dist" / "pypi_publish_preflight_pypi_token_receipt.json"

    receipt = preflight_publish(
        repository="pypi",
        release_receipt=release_path,
        local_install_receipt=local_path,
        testpypi_install_receipt=testpypi_path,
        receipt_path=preflight_path,
        require_token_env=True,
    )
    verified = verify_pypi_publish_preflight_receipt_file(preflight_path)
    text = preflight_path.read_text(encoding="utf-8")

    assert receipt["status"] == "ready_to_upload_pypi"
    assert verified["checks"]["token_env_ready"] is True
    assert verified["checks"]["testpypi_install_receipt_verified"] is True
    assert verified["upload_env_gate"]["twine_password_present"] is True
    assert verified["upload_env_gate"]["twine_password_recorded"] is False
    assert "TWINE_PASSWORD=<pypi-token>" in text
    assert "secret-value-not-written" not in text
    assert str(tmp_path) not in text


def test_pypi_publish_preflight_writes_blocked_receipt_when_testpypi_receipt_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)
    preflight_path = tmp_path / "dist" / "pypi_publish_preflight_receipt.json"

    with pytest.raises(SystemExit):
        preflight_publish(
            repository="pypi",
            release_receipt=release_path,
            local_install_receipt=local_path,
            testpypi_install_receipt=tmp_path / "dist" / "missing-testpypi-install.json",
            receipt_path=preflight_path,
        )
    verified = verify_pypi_publish_preflight_receipt_file(preflight_path)
    text = preflight_path.read_text(encoding="utf-8")

    assert verified["status"] == "blocked"
    assert verified["blocking_checks"] == ["testpypi_install_receipt_verified"]
    assert verified["testpypi_install_gate"]["reason"] == "missing_testpypi_install_receipt"
    assert str(tmp_path) not in text


def test_testpypi_publish_preflight_writes_blocked_receipt_when_required_receipts_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    preflight_path = tmp_path / "dist" / "pypi_publish_preflight_receipt.json"

    with pytest.raises(SystemExit):
        preflight_publish(
            repository="testpypi",
            release_receipt=tmp_path / "dist" / "missing-release.json",
            local_install_receipt=tmp_path / "dist" / "missing-local-install.json",
            receipt_path=preflight_path,
        )
    verified = verify_pypi_publish_preflight_receipt_file(preflight_path)
    text = preflight_path.read_text(encoding="utf-8")

    assert verified["status"] == "blocked"
    assert verified["blocking_checks"] == [
        "release_receipt_ready",
        "release_receipt_artifacts_verified",
        "local_install_receipt_verified",
        "local_install_package_matched",
        "local_install_version_matched",
        "local_install_wheel_hash_matched",
    ]
    assert verified["release_receipt_gate"]["reason"] == "missing_release_receipt"
    assert verified["local_install_gate"]["reason"] == "missing_local_install_receipt"
    assert str(tmp_path) not in text


def test_pypi_publish_ready_handoff_waits_for_testpypi_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)

    result = check_pypi_publish_ready(
        repository="testpypi",
        output_dir=tmp_path / "dist",
        release_receipt=release_path,
        local_install_receipt=local_path,
    )
    ready = verify_pypi_publish_ready_file(Path(result["publish_ready_json"]))
    json_text = Path(result["publish_ready_json"]).read_text(encoding="utf-8")
    md_text = Path(result["publish_ready_md"]).read_text(encoding="utf-8")

    assert result["verdict"] == "WAITING_FOR_TOKEN"
    assert ready["preflight"]["status"] == "ready_for_testpypi_token"
    assert ready["checks"]["local_install_matches_release"] is True
    assert ready["checks"]["token_value_not_recorded"] is True
    assert "TWINE_PASSWORD=<testpypi-token>" in json_text
    assert "--upload testpypi --publish-ready-receipt dist/pypi-publish-ready-testpypi.json" in md_text
    assert str(tmp_path) not in json_text
    assert str(tmp_path) not in md_text


def test_pypi_publish_ready_handoff_go_with_token_without_recording_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TWINE_USERNAME", "__token__")
    monkeypatch.setenv("TWINE_PASSWORD", "secret-value-not-written")
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)

    result = check_pypi_publish_ready(
        repository="testpypi",
        output_dir=tmp_path / "dist",
        release_receipt=release_path,
        local_install_receipt=local_path,
        require_token_env=True,
    )
    ready = verify_pypi_publish_ready_file(Path(result["publish_ready_json"]))
    json_text = Path(result["publish_ready_json"]).read_text(encoding="utf-8")
    md_text = Path(result["publish_ready_md"]).read_text(encoding="utf-8")

    assert result["verdict"] == "GO"
    assert ready["preflight"]["status"] == "ready_to_upload_testpypi"
    assert ready["preflight"]["upload_env_gate"]["twine_password_present"] is True
    assert ready["preflight"]["upload_env_gate"]["twine_password_recorded"] is False
    assert "secret-value-not-written" not in json_text
    assert "secret-value-not-written" not in md_text


def test_publish_ready_gate_accepts_go_receipt_and_rejects_waiting_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    waiting = check_pypi_publish_ready(
        repository="testpypi",
        output_dir=tmp_path / "waiting",
        release_receipt=release_path,
        local_install_receipt=local_path,
    )

    with pytest.raises(ValueError, match="verdict_go"):
        _verify_publish_ready_gate(
            Path(waiting["publish_ready_json"]),
            repository="testpypi",
            expected_package="cambrian",
            expected_version="0.3.0",
            root=tmp_path,
        )

    monkeypatch.setenv("TWINE_USERNAME", "__token__")
    monkeypatch.setenv("TWINE_PASSWORD", "secret-value-not-written")
    ready = check_pypi_publish_ready(
        repository="testpypi",
        output_dir=tmp_path / "ready",
        release_receipt=release_path,
        local_install_receipt=local_path,
        require_token_env=True,
    )
    gate = _verify_publish_ready_gate(
        Path(ready["publish_ready_json"]),
        repository="testpypi",
        expected_package="cambrian",
        expected_version="0.3.0",
        root=tmp_path,
    )
    text = Path(ready["publish_ready_json"]).read_text(encoding="utf-8")

    assert gate["status"] == "verified"
    assert gate["repository"] == "testpypi"
    assert gate["verdict"] == "GO"
    assert gate["checks"]["publish_ready_checks_all_true"] is True
    assert "secret-value-not-written" not in text


def test_pypi_publish_ready_handoff_blocks_without_testpypi_install_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)
    release_path, local_path, _ = _write_preflight_inputs(tmp_path)

    result = check_pypi_publish_ready(
        repository="pypi",
        output_dir=tmp_path / "dist",
        release_receipt=release_path,
        local_install_receipt=local_path,
        testpypi_install_receipt=tmp_path / "dist" / "missing-testpypi-install.json",
    )
    ready = verify_pypi_publish_ready_file(Path(result["publish_ready_json"]))
    json_text = Path(result["publish_ready_json"]).read_text(encoding="utf-8")

    assert result["verdict"] == "BLOCKED"
    assert ready["preflight"]["status"] == "blocked"
    assert ready["preflight"]["blocking_checks"] == ["testpypi_install_receipt_verified"]
    assert ready["checks"]["testpypi_gate_satisfied_or_not_required"] is False
    assert str(tmp_path) not in json_text


def test_pypi_publish_ready_handoff_blocks_without_required_release_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TWINE_USERNAME", raising=False)
    monkeypatch.delenv("TWINE_PASSWORD", raising=False)

    result = check_pypi_publish_ready(
        repository="testpypi",
        output_dir=tmp_path / "dist",
        release_receipt=tmp_path / "dist" / "missing-release.json",
        local_install_receipt=tmp_path / "dist" / "missing-local-install.json",
    )
    ready = verify_pypi_publish_ready_file(Path(result["publish_ready_json"]))
    json_text = Path(result["publish_ready_json"]).read_text(encoding="utf-8")
    md_text = Path(result["publish_ready_md"]).read_text(encoding="utf-8")

    assert result["verdict"] == "BLOCKED"
    assert ready["preflight"]["status"] == "blocked"
    assert "release_receipt_ready" in ready["preflight"]["blocking_checks"]
    assert "local_install_receipt_verified" in ready["preflight"]["blocking_checks"]
    assert ready["preflight"]["release_receipt_gate"]["reason"] == "missing_release_receipt"
    assert ready["preflight"]["local_install_gate"]["reason"] == "missing_local_install_receipt"
    assert str(tmp_path) not in json_text
    assert str(tmp_path) not in md_text


def test_pypi_install_verifier_records_fresh_environment_receipt() -> None:
    text = _read("scripts/verify_pypi_install.py")

    for phrase in [
        "PYPI_INSTALL_RECEIPT_SCHEMA_VERSION",
        "pypi_install_verification_receipt.json",
        "https://test.pypi.org/simple/",
        "https://pypi.org/simple/",
        "venv.EnvBuilder",
        '"cambrian"',
        '"doctor"',
        "TWINE_PASSWORD",
        "no_token_required",
        "safe_to_share",
        "verify_pypi_install_receipt_file",
        "--verify-receipt",
        "pypi_install_receipt_body_sha256",
        "command_output_text_omitted",
    ]:
        assert phrase in text


def test_pypi_install_receipt_verifies_without_private_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    temp_dir = tmp_path / "venv"
    temp_dir.mkdir()
    wheel = tmp_path / "dist" / "pypi" / "cambrian-0.3.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"wheel")
    receipt = _install_receipt(
        repository="pypi",
        package="cambrian",
        version="0.3.0",
        wheel=wheel,
        checks={
            "venv_created": True,
            "pip_upgrade_passed": True,
            "install_passed": True,
            "cli_help_passed": True,
            "doctor_passed": True,
            "no_token_required": True,
        },
        failed=[],
        commands=[
            {
                "command": [temp_dir / "Scripts" / "python.exe", "-m", "pip", "install", str(wheel)],
                "cwd": str(root),
                "exit_code": 0,
                "status": "passed",
                "stdout": str(root),
                "stderr": str(temp_dir),
            }
        ],
        root=root,
        temp_dir=temp_dir,
    )
    receipt_path = tmp_path / "dist" / "pypi_install_verification_receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verified = verify_pypi_install_receipt_file(receipt_path)
    text = receipt_path.read_text(encoding="utf-8")

    assert verified["status"] == "verified"
    assert verified["receipt_checks"]["body_hash_matched"] is True
    assert verified["receipt_checks"]["absolute_paths_omitted"] is True
    assert verified["receipt_checks"]["command_output_text_omitted"] is True
    assert str(root) not in text
    assert str(temp_dir) not in text


def test_pypi_release_is_linked_from_readme_and_checklist() -> None:
    readme = _read("README.md")
    checklist = _read("docs/release/RC_CHECKLIST.md")

    assert "scripts/prepare_pypi_release.py" in readme
    assert "scripts/prepare_pypi_release.py --verify-receipt dist/pypi_release_receipt.json" in readme
    assert "scripts/verify_pypi_install.py --wheel dist/pypi/cambrian-0.3.0-py3-none-any.whl" in readme
    assert "scripts/verify_pypi_install.py --verify-receipt dist/pypi_local_wheel_install_receipt.json" in readme
    assert "scripts/prepare_pypi_release.py --preflight-upload testpypi" in readme
    assert "scripts/prepare_pypi_release.py --preflight-upload testpypi --require-token-env" in readme
    assert "scripts/check_pypi_publish_ready.py --repository testpypi" in readme
    assert "scripts/check_pypi_publish_ready.py --verify-ready dist/pypi-publish-ready-testpypi.json" in readme
    assert "scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json" in readme
    assert "scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --require-token-env" in readme
    assert "scripts/check_pypi_publish_ready.py --repository pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json" in readme
    assert "pypi-publish-ready-*.json" in readme
    assert "scripts/prepare_pypi_release.py --verify-preflight-receipt dist/pypi_publish_preflight_receipt.json" in readme
    assert "scripts/verify_pypi_install.py --repository testpypi --version 0.3.0 --receipt dist/pypi_testpypi_install_receipt.json" in readme
    assert "--testpypi-install-receipt" in readme
    assert "TWINE_USERNAME=__token__" in readme
    assert "scripts/verify_pypi_install.py" in readme
    assert "docs/release/PYPI_RELEASE.md" in readme
    assert "PyPI Release Gate" in checklist
    assert "scripts/prepare_pypi_release.py --verify-receipt dist/pypi_release_receipt.json" in checklist
    assert "local wheel fresh install smoke passes" in checklist
    assert "scripts/verify_pypi_install.py --verify-receipt dist/pypi_local_wheel_install_receipt.json" in checklist
    assert "ready_for_testpypi_token" in checklist
    assert "ready_to_upload_testpypi" in checklist
    assert "ready_to_upload_pypi" in checklist
    assert "pypi-publish-ready-testpypi.json" in checklist
    assert "WAITING_FOR_TOKEN" in checklist
    assert "pypi-publish-ready-*.json" in checklist
    assert "scripts/prepare_pypi_release.py --verify-preflight-receipt dist/pypi_publish_preflight_receipt.json" in checklist
    assert "upload commands fail fast before build" in checklist
    assert "--testpypi-install-receipt dist/pypi_testpypi_install_receipt.json" in checklist
    assert "scripts/verify_pypi_install.py --repository pypi --version 0.3.0" in checklist
    assert "`pip install cambrian` works from a fresh environment" in checklist
