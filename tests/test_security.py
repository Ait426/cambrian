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


# --- C-3 우회 벡터 테스트 ---


def test_detect_builtins_access(tmp_path: Path) -> None:
    """__builtins__ 접근이 차단된다."""
    scanner = SecurityScanner()
    code_file = tmp_path / "builtins_hack.py"
    code_file.write_text(
        "x = __builtins__.__dict__['eval']\nx('print(1)')\n",
        encoding="utf-8",
    )

    violations = scanner.scan_file(code_file)

    assert len(violations) > 0
    assert any("__builtins__" in v for v in violations)


def test_detect_type_metaclass(tmp_path: Path) -> None:
    """type('', (), {...}) 동적 클래스 생성이 차단된다."""
    scanner = SecurityScanner()
    code_file = tmp_path / "type_hack.py"
    code_file.write_text(
        "Evil = type('Evil', (), {'__init__': lambda s: None})\n",
        encoding="utf-8",
    )

    violations = scanner.scan_file(code_file)

    assert len(violations) > 0
    assert any("type()" in v for v in violations)


def test_detect_import_alias(tmp_path: Path) -> None:
    """x = __import__; x('os') 간접 호출이 차단된다."""
    scanner = SecurityScanner()
    code_file = tmp_path / "import_alias.py"
    code_file.write_text(
        "x = __import__\nx('os')\n",
        encoding="utf-8",
    )

    violations = scanner.scan_file(code_file)

    assert len(violations) > 0
    assert any("__import__" in v for v in violations)


def test_detect_nested_attribute_chain(tmp_path: Path) -> None:
    """obj.nested.eval() 깊은 체인도 탐지된다."""
    scanner = SecurityScanner()
    code_file = tmp_path / "chain_hack.py"
    code_file.write_text(
        "class A: pass\na = A()\na.b.c.eval('1+1')\n",
        encoding="utf-8",
    )

    violations = scanner.scan_file(code_file)

    assert len(violations) > 0
    assert any("eval" in v for v in violations)


def test_detect_subclasses_access(tmp_path: Path) -> None:
    """__subclasses__ 접근이 차단된다."""
    scanner = SecurityScanner()
    code_file = tmp_path / "subclass_hack.py"
    code_file.write_text(
        "x = ().__class__.__bases__[0].__subclasses__()\n",
        encoding="utf-8",
    )

    violations = scanner.scan_file(code_file)

    assert len(violations) > 0
    assert any("__class__" in v or "__bases__" in v or "__subclasses__" in v for v in violations)
