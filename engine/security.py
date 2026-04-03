"""Cambrian 스킬 보안 스캐너."""

import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SecurityScanner:
    """스킬의 실행 코드를 AST 기반으로 정적 분석하여 악성 패턴을 탐지한다."""

    BANNED_CALLS: set[str] = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
    }

    BANNED_IMPORTS: set[str] = {
        "subprocess",
        "os",
        "shutil",
        "socket",
        "ctypes",
        "importlib",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
        "compileall",
    }

    NETWORK_IMPORTS: set[str] = {
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "aiohttp",
        "http",
        "socket",
        "ftplib",
        "smtplib",
        "xmlrpc",
    }

    def scan_file(self, file_path: str | Path, needs_network: bool = False) -> list[str]:
        """단일 Python 파일을 스캔한다.

        Args:
            file_path: 스캔할 .py 파일 경로
            needs_network: True면 네트워크 관련 import를 허용한다.

        Returns:
            위반 사항 목록. 빈 리스트면 안전하다.
        """
        path = Path(file_path)

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return ["Failed to parse Python file"]

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return ["Failed to parse Python file"]

        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.BANNED_CALLS:
                    violations.append(f"Banned call: {node.func.id}()")
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.BANNED_CALLS
                ):
                    violations.append(f"Banned call: {node.func.attr}()")

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.BANNED_IMPORTS:
                        violations.append(f"Banned import: {alias.name}")
                    elif not needs_network and alias.name in self.NETWORK_IMPORTS:
                        violations.append(
                            "Network import not allowed: "
                            f"{alias.name} (needs_network is false)"
                        )

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module and any(
                    module == banned or module.startswith(f"{banned}.")
                    for banned in self.BANNED_IMPORTS
                ):
                    violations.append(f"Banned import: {module}")
                elif module and not needs_network and any(
                    module == network or module.startswith(f"{network}.")
                    for network in self.NETWORK_IMPORTS
                ):
                    violations.append(
                        "Network import not allowed: "
                        f"{module} (needs_network is false)"
                    )

        return violations

    def scan_skill(self, skill_dir: str | Path, needs_network: bool = False) -> list[str]:
        """스킬 디렉토리 내 모든 .py 파일을 스캔한다.

        Args:
            skill_dir: 스킬 루트 디렉토리
            needs_network: True면 네트워크 관련 import를 허용한다.

        Returns:
            전체 파일의 위반 사항 목록. 빈 리스트면 안전하다.
        """
        root = Path(skill_dir)
        violations: list[str] = []

        for file_path in root.rglob("*.py"):
            relative_path = file_path.relative_to(root)
            file_violations = self.scan_file(file_path, needs_network=needs_network)
            for violation in file_violations:
                violations.append(f"[{relative_path.as_posix()}] {violation}")

        return violations
