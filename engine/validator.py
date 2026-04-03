"""Cambrian skill validator."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator


@dataclass
class ValidationResult:
    """Result of skill validation."""

    valid: bool
    skill_id: str | None
    errors: list[str]
    warnings: list[str]


class SkillValidator:
    """스킬 디렉토리의 구조와 내용을 검증한다."""

    def __init__(self, schemas_dir: str | Path):
        """Load validators from the given schema directory.

        Args:
            schemas_dir: meta.schema.json과 interface.schema.json이 있는 디렉토리 경로
        """
        self.schemas_dir = Path(schemas_dir)
        meta_schema_path = self.schemas_dir / "meta.schema.json"
        interface_schema_path = self.schemas_dir / "interface.schema.json"

        self._meta_schema = json.loads(meta_schema_path.read_text(encoding="utf-8"))
        self._interface_schema = json.loads(interface_schema_path.read_text(encoding="utf-8"))

        self._meta_validator = Draft7Validator(self._meta_schema)
        self._interface_validator = Draft7Validator(self._interface_schema)

    def validate(self, skill_dir: str | Path) -> ValidationResult:
        """스킬 디렉토리 전체를 검증한다.

        Args:
            skill_dir: 스킬 루트 디렉토리 경로 (meta.yaml이 있는 곳)

        Returns:
            ValidationResult 객체
        """
        skill_root = Path(skill_dir)
        errors: list[str] = []
        warnings: list[str] = []
        skill_id: str | None = None

        meta_path = skill_root / "meta.yaml"
        interface_path = skill_root / "interface.yaml"
        skill_doc_path = skill_root / "SKILL.md"
        execute_path = skill_root / "execute" / "main.py"

        for required_path in (meta_path, interface_path, skill_doc_path):
            if not required_path.exists():
                errors.append(f"[{required_path.name}] 필수 파일이 존재하지 않음")

        meta_data: dict[str, Any] | None = None
        interface_data: dict[str, Any] | None = None

        if meta_path.exists():
            meta_data, meta_errors = self._load_yaml(meta_path)
            errors.extend(meta_errors)
            if meta_data is not None:
                raw_skill_id = meta_data.get("id")
                skill_id = raw_skill_id if isinstance(raw_skill_id, str) else None
                errors.extend(self._schema_errors(meta_data, self._meta_validator, "meta.yaml"))
                warnings.extend(self._meta_warnings(meta_data))

        if interface_path.exists():
            interface_data, interface_errors = self._load_yaml(interface_path)
            errors.extend(interface_errors)
            if interface_data is not None:
                errors.extend(
                    self._schema_errors(
                        interface_data,
                        self._interface_validator,
                        "interface.yaml",
                    )
                )

        mode = meta_data.get("mode") if isinstance(meta_data, dict) else None
        if mode == "b":
            if not execute_path.exists():
                errors.append("[structure] mode가 'b'이지만 execute/main.py가 존재하지 않음")
            else:
                errors.extend(self._validate_execute_file(execute_path))
        elif execute_path.exists():
            errors.extend(self._validate_execute_file(execute_path))

        return ValidationResult(
            valid=not errors,
            skill_id=skill_id,
            errors=errors,
            warnings=warnings,
        )

    def validate_meta(self, meta_path: str | Path) -> list[str]:
        """meta.yaml만 단독 검증. 에러 메시지 목록 반환. 빈 목록 = 통과."""
        path = Path(meta_path)
        data, parse_errors = self._load_yaml(path)
        if parse_errors:
            return parse_errors
        assert data is not None
        return self._schema_errors(data, self._meta_validator, path.name)

    def validate_interface(self, interface_path: str | Path) -> list[str]:
        """interface.yaml만 단독 검증. 에러 메시지 목록 반환. 빈 목록 = 통과."""
        path = Path(interface_path)
        data, parse_errors = self._load_yaml(path)
        if parse_errors:
            return parse_errors
        assert data is not None
        return self._schema_errors(data, self._interface_validator, path.name)

    def _load_yaml(self, path: Path) -> tuple[dict[str, Any] | None, list[str]]:
        """Load YAML as a dict and return parse errors if any."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return None, [f"[{path.name}] YAML 파싱 오류. 실제값: {exc}"]

        if raw is None:
            raw = {}

        if not isinstance(raw, dict):
            return None, [
                f"[{path.name}] 최상위 형식 오류. 기대값: object, 실제값: {type(raw).__name__}"
            ]
        return raw, []

    def _schema_errors(
        self,
        data: dict[str, Any],
        validator: Draft7Validator,
        filename: str,
    ) -> list[str]:
        """Format JSON Schema validation errors into user-facing messages."""
        errors: list[str] = []
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
            errors.append(self._format_schema_error(error, filename))
        return errors

    def _format_schema_error(self, error: Any, filename: str) -> str:
        """Convert a jsonschema validation error into the required message format."""
        validator_name = error.validator
        path_parts = [str(part) for part in error.path]
        path_str = ".".join(path_parts)

        if validator_name == "required":
            missing_field = error.message.split("'")[1]
            if path_str:
                return f"[{filename}] {path_str}에 '{missing_field}' 필드 누락"
            return f"[{filename}] 필수 필드 누락: '{missing_field}'"

        if validator_name == "pattern":
            actual_value = error.instance
            field_name = path_parts[-1] if path_parts else "value"
            return (
                f"[{filename}] {field_name} 형식 오류. 기대값: {error.schema.get('pattern')}, "
                f"실제값: {actual_value!r}"
            )

        if validator_name == "enum":
            field_name = path_parts[-1] if path_parts else "value"
            return (
                f"[{filename}] {field_name} 값 오류. 기대값: {error.validator_value}, "
                f"실제값: {error.instance!r}"
            )

        if validator_name == "const":
            field_name = path_parts[-1] if path_parts else "value"
            return (
                f"[{filename}] {field_name} 값 오류. 기대값: {error.validator_value!r}, "
                f"실제값: {error.instance!r}"
            )

        if validator_name == "type":
            target = path_str or "root"
            return (
                f"[{filename}] {target} 타입 오류. 기대값: {error.validator_value}, "
                f"실제값: {type(error.instance).__name__}"
            )

        if validator_name == "minProperties":
            target = path_str or "root"
            return (
                f"[{filename}] {target} 속성 수 부족. 기대값: >= {error.validator_value}, "
                f"실제값: {len(error.instance)}"
            )

        if validator_name == "additionalProperties":
            target = path_str or "root"
            extra_field = error.message.split("'")[1]
            return f"[{filename}] {target}에 허용되지 않은 필드: '{extra_field}'"

        return f"[{filename}] {error.message}"

    def _meta_warnings(self, meta_data: dict[str, Any]) -> list[str]:
        """Collect non-blocking warnings from metadata."""
        warnings: list[str] = []
        if not meta_data.get("author"):
            warnings.append("[meta.yaml] 권장 필드 누락: 'author'")
        if not meta_data.get("license"):
            warnings.append("[meta.yaml] 권장 필드 누락: 'license'")
        return warnings

    def _validate_execute_file(self, execute_path: Path) -> list[str]:
        """Validate execute/main.py existence and run() definition."""
        try:
            source = execute_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [f"[{execute_path.as_posix()}] 파일 읽기 오류. 실제값: {exc}"]

        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return [f"[{execute_path.as_posix()}] Python 파싱 오류. 실제값: {exc}"]

        has_run = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run"
            for node in tree.body
        )
        if not has_run:
            return [f"[{execute_path.as_posix()}] run() 함수가 정의되지 않음"]
        return []
