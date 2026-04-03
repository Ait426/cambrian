"""SecurityScanner 테스트."""

from pathlib import Path

from engine.security import SecurityScanner


def test_safe_code_passes() -> None:
    """safe_skill의 코드는 위반 0건."""
    scanner = SecurityScanner()

    violations = scanner.scan_skill(Path("test_skills/safe_skill"))

    assert violations == []


def test_detect_eval() -> None:
    """eval() 호출이 포함된 코드는 위반으로 탐지된다."""
    scanner = SecurityScanner()

    violations = scanner.scan_skill(Path("test_skills/malicious_eval"))

    assert len(violations) > 0
    assert any("eval" in violation for violation in violations)


def test_detect_subprocess() -> None:
    """subprocess import가 있으면 위반으로 탐지된다."""
    scanner = SecurityScanner()

    violations = scanner.scan_skill(Path("test_skills/malicious_subprocess"))

    assert len(violations) > 0
    assert any("subprocess" in violation for violation in violations)


def test_detect_network_import() -> None:
    """needs_network=False인데 requests를 import하면 위반."""
    scanner = SecurityScanner()

    violations = scanner.scan_skill(
        Path("test_skills/network_liar"),
        needs_network=False,
    )

    assert len(violations) > 0
    assert any("requests" in violation for violation in violations)


def test_allow_network_import() -> None:
    """needs_network=True이면 requests import가 허용된다."""
    scanner = SecurityScanner()

    violations = scanner.scan_skill(
        Path("test_skills/network_liar"),
        needs_network=True,
    )
    network_violations = [
        violation for violation in violations if "Network import" in violation
    ]

    assert network_violations == []


def test_broken_python(tmp_path: Path) -> None:
    """파싱 불가능한 .py 파일은 위반으로 보고된다."""
    scanner = SecurityScanner()
    bad_py = tmp_path / "broken.py"
    bad_py.write_text("def {{invalid python", encoding="utf-8")

    violations = scanner.scan_file(bad_py)

    assert len(violations) > 0
    assert any("parse" in violation.lower() for violation in violations)


def test_detect_os_submodule(tmp_path: Path) -> None:
    """from os.path import join도 os 계열이므로 차단된다."""
    scanner = SecurityScanner()
    code_file = tmp_path / "sneaky.py"
    code_file.write_text(
        "from os.path import join\n\ndef run(d):\n    return d\n",
        encoding="utf-8",
    )

    violations = scanner.scan_file(code_file)

    assert len(violations) > 0
    assert any("os" in violation for violation in violations)
