from __future__ import annotations

from pathlib import Path

from engine.project_harness_profile import ProjectHarnessScanner


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_recommends_auth_bug_core_for_python_pytest_auth_project(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample-auth"\nversion = "0.1.0"\n')
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "src" / "auth.py", "def login(user):\n    return user\n")
    _write(tmp_path / "tests" / "test_auth.py", "def test_login():\n    assert True\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert profile.language == "python"
    assert profile.test_framework == "pytest"
    assert "auth" in profile.domains
    assert "tests" in profile.domains
    assert profile.recommended_harnesses == ["auth-bug-core"]


def test_scan_does_not_force_python_preset_on_typescript_auth_project(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(tmp_path / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(tmp_path / "backend" / "src" / "api" / "authRoutes.ts", 'export const route = "/api/auth/login";\n')
    _write(tmp_path / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(tmp_path / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")

    profile = ProjectHarnessScanner().scan(tmp_path)

    assert "typescript" in profile.languages
    assert "jest" in profile.test_frameworks
    assert profile.language == "typescript"
    assert profile.test_framework == "jest"
    assert "api" in profile.domains
    assert profile.recommended_harnesses == ["typescript-jest-auth-core"]
