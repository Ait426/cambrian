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

    # AST Attribute/Name에서 차단할 위험한 dunder 이름
    BANNED_ATTRIBUTES: set[str] = {
        "__builtins__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "__class__",
        "__globals__",
        "__code__",
    }

    # ast.Name 노드에서도 차단할 이름 (전역 변수로 접근 시)
    BANNED_NAMES: set[str] = {
        "__builtins__",
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
                self._check_call(node, violations)

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

            elif isinstance(node, ast.Attribute):
                # 위험한 dunder 속성 접근 차단 (__builtins__, __subclasses__ 등)
                if node.attr in self.BANNED_ATTRIBUTES:
                    violations.append(f"Banned attribute access: {node.attr}")

            elif isinstance(node, ast.Name):
                # __builtins__ 등 위험한 전역 이름 접근 차단
                if node.id in self.BANNED_NAMES:
                    violations.append(f"Banned name access: {node.id}")

            elif isinstance(node, ast.Assign):
                # __import__ 함수를 변수에 할당하는 간접 호출 패턴 탐지
                self._check_import_alias(node, violations)

        return violations

    def _check_call(self, node: ast.Call, violations: list[str]) -> None:
        """함수 호출 노드에서 금지된 패턴을 탐지한다.

        Args:
            node: AST Call 노드
            violations: 위반 목록 (in-place 추가)
        """
        # 직접 호출: eval(), exec() 등
        if isinstance(node.func, ast.Name) and node.func.id in self.BANNED_CALLS:
            violations.append(f"Banned call: {node.func.id}()")

        # Attribute 체인 호출: obj.nested.eval() — 재귀 검사
        elif isinstance(node.func, ast.Attribute):
            banned_attr = self._find_banned_in_chain(node.func)
            if banned_attr is not None:
                violations.append(f"Banned call: {banned_attr}()")

        # type('', (), {...}) 메타클래스 패턴 탐지
        if isinstance(node.func, ast.Name) and node.func.id == "type":
            if len(node.args) == 3:
                violations.append(
                    "Banned call: type() with 3 arguments (dynamic class creation)"
                )

    def _find_banned_in_chain(self, node: ast.Attribute) -> str | None:
        """Attribute 체인을 재귀 탐색하여 금지된 호출을 찾는다.

        Args:
            node: AST Attribute 노드

        Returns:
            금지된 속성명 또는 None
        """
        if node.attr in self.BANNED_CALLS:
            return node.attr

        # 체인의 중간 노드도 검사 (예: obj.__builtins__.__dict__['eval'])
        if node.attr in self.BANNED_ATTRIBUTES:
            return node.attr

        if isinstance(node.value, ast.Attribute):
            return self._find_banned_in_chain(node.value)

        return None

    def _check_import_alias(self, node: ast.Assign, violations: list[str]) -> None:
        """__import__를 변수에 할당하는 패턴을 탐지한다.

        예: x = __import__; x('os')

        Args:
            node: AST Assign 노드
            violations: 위반 목록 (in-place 추가)
        """
        if isinstance(node.value, ast.Name) and node.value.id == "__import__":
            violations.append("Banned pattern: __import__ assigned to variable")

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
