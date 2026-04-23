"""Cambrian 알파 packaging/doctor 회귀 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import engine.project_doctor as project_doctor_module
from engine.demo_project import DemoProjectCreator
from engine.project_doctor import ProjectDoctor
from engine.project_mode import ProjectInitializer


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
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
        check=False,
    )


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = ['.']\naddopts = '-q'\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pyproject_packaging_sanity() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "cambrian"
    assert pyproject["project"]["scripts"]["cambrian"] == "engine.cli:main"
    assert "build>=1.2" in pyproject["project"]["optional-dependencies"]["dev"]
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["include"] == ["engine*"]


def test_build_wheel_includes_project_mode_packages(tmp_path: Path) -> None:
    build_root = tmp_path / "build_repo"
    shutil.copytree(
        ROOT,
        build_root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".pytest_tmp",
            "build",
            "dist",
            "__pycache__",
            "*.pyc",
        ),
    )
    out_dir = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(out_dir)],
        cwd=str(build_root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(out_dir)],
            cwd=str(build_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    assert proc.returncode == 0, proc.stderr
    wheel_paths = sorted(out_dir.glob("cambrian-*.whl"))
    assert wheel_paths
    with zipfile.ZipFile(wheel_paths[-1]) as archive:
        names = set(archive.namelist())
    assert "engine/project_doctor.py" in names
    assert "engine/brain/__init__.py" in names
    assert "engine/brain/adapters/__init__.py" in names


def test_doctor_basic_for_non_initialized_workspace(tmp_path: Path) -> None:
    report = ProjectDoctor().run(tmp_path)

    assert report.summary["fail"] == 0
    assert any(check.name == "Python" for check in report.checks)
    assert any(check.name == "CLI import" for check in report.checks)
    init_check = next(check for check in report.checks if check.name == "Project mode")
    assert init_check.status == "warn"
    assert "cambrian init --wizard" in report.next_actions
    assert "cambrian demo create login-bug --out ./demo" in report.next_actions


def test_doctor_generic_project_pyproject_does_not_fail_package_metadata(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample-app'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )

    report = ProjectDoctor().run(tmp_path)

    package_check = next(check for check in report.checks if check.name == "Package metadata")
    assert package_check.status in {"ok", "warn"}
    assert report.summary["fail"] == 0


def test_doctor_initialized_workspace_reports_ok(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    report = ProjectDoctor().run(tmp_path)

    init_check = next(check for check in report.checks if check.name == "Project mode")
    demo_check = next(check for check in report.checks if check.name == "Demo assets")
    assert init_check.status == "ok"
    assert demo_check.status == "ok"
    assert "cambrian status" in report.next_actions


def test_doctor_demo_workspace_does_not_false_fail_package_metadata(tmp_path: Path) -> None:
    demo_root = tmp_path / "demo"
    result = DemoProjectCreator().create("login-bug", demo_root)

    assert result.status == "created"
    report = ProjectDoctor().run(demo_root)

    package_check = next(check for check in report.checks if check.name == "Package metadata")
    assert package_check.status in {"ok", "warn"}
    assert report.summary["fail"] == 0


def test_doctor_package_metadata_fails_when_cli_import_breaks(tmp_path: Path, monkeypatch) -> None:
    original_import_module = project_doctor_module.importlib.import_module

    def _broken_import(name: str, package: str | None = None):
        if name == "engine.cli":
            raise ImportError("boom")
        return original_import_module(name, package)

    monkeypatch.setattr(project_doctor_module.importlib, "import_module", _broken_import)

    report = ProjectDoctor().run(tmp_path)

    package_check = next(check for check in report.checks if check.name == "Package metadata")
    assert package_check.status == "fail"
    assert "could not be imported" in package_check.summary


def test_doctor_json_cli_output(tmp_path: Path) -> None:
    proc = _run_cli(["doctor", "--workspace", str(tmp_path), "--json"], cwd=ROOT)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["workspace"] == str(tmp_path.resolve())
    assert any(check["name"] == "Python" for check in payload["checks"])
    assert "next_actions" in payload


def test_demo_create_cli_smoke(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo"

    proc = _run_cli(["demo", "create", "login-bug", "--out", str(demo_dir)], cwd=ROOT)

    assert proc.returncode == 0, proc.stderr
    assert (demo_dir / "src" / "auth.py").exists()
    assert (demo_dir / "tests" / "test_auth.py").exists()
    assert (demo_dir / "demo_answers.yaml").exists()
    assert (demo_dir / "README_DEMO.md").exists()


def test_alpha_install_docs_exist_and_reference_doctor_flow() -> None:
    install_doc = (ROOT / "docs" / "ALPHA_INSTALL.md").read_text(encoding="utf-8")
    first_run_doc = (ROOT / "docs" / "FIRST_RUN_DEMO.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "pip install -e .[dev]" in install_doc
    assert "cambrian doctor" in install_doc
    assert "cambrian demo create login-bug" in install_doc
    assert "cambrian do " in install_doc
    assert "local-only" in install_doc
    assert "cambrian doctor" in first_run_doc
    assert "docs/ALPHA_INSTALL.md" in readme


def test_doctor_does_not_mutate_workspace_files(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    source_path = tmp_path / "app.py"
    source_path.write_text("print('safe')\n", encoding="utf-8")
    before = _sha256(source_path)

    proc = _run_cli(["doctor", "--workspace", str(tmp_path)], cwd=ROOT)

    assert proc.returncode == 0, proc.stderr
    assert _sha256(source_path) == before
