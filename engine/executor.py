"""Cambrian 스킬 실행기."""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from jsonschema import Draft7Validator

from engine.exceptions import SkillExecutionError
from engine.llm import LLMProvider, create_provider
from engine.models import ExecutionResult, Skill

logger = logging.getLogger(__name__)


class SkillExecutor:
    """스킬을 실행하고 결과를 반환한다."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        """초기화.

        Args:
            provider: LLM 프로바이더. None이면 Mode A 실행 시 자동 생성.
        """
        self._provider = provider

    def execute(self, skill: Skill, input_data: dict) -> ExecutionResult:
        """스킬을 실행한다.

        Args:
            skill: 실행할 Skill 객체
            input_data: 스킬에 전달할 입력 데이터

        Returns:
            ExecutionResult 객체

        Raises:
            SkillExecutionError: mode가 "b"인데 execute/main.py가 없을 때
            ValueError: 알 수 없는 mode일 때
        """
        if skill.mode == "b":
            return self._execute_mode_b(skill, input_data)
        elif skill.mode == "a":
            return self._execute_mode_a(skill, input_data)
        else:
            raise ValueError(f"Unknown mode: {skill.mode}")

    def _execute_mode_b(self, skill: Skill, input_data: dict) -> ExecutionResult:
        """Mode B: execute/main.py를 subprocess로 실행한다.

        Args:
            skill: 실행할 Skill 객체
            input_data: 스킬에 전달할 입력 데이터

        Returns:
            ExecutionResult 객체

        Raises:
            SkillExecutionError: mode가 "b"인데 execute/main.py가 없을 때
        """
        main_py = skill.skill_path / "execute" / "main.py"
        if not main_py.exists():
            raise SkillExecutionError(skill.id, "execute/main.py not found")

        json_input = json.dumps(input_data, ensure_ascii=False)
        started_at = time.perf_counter()

        try:
            completed = subprocess.run(
                [sys.executable, str(main_py)],
                input=json_input.encode("utf-8"),
                capture_output=True,
                timeout=skill.runtime.timeout_seconds,
                cwd=str(skill.skill_path),
            )
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            stdout_text = completed.stdout.decode("utf-8", errors="replace")
            stderr_text = completed.stderr.decode("utf-8", errors="replace")

            if completed.returncode == 0:
                try:
                    output = json.loads(stdout_text)
                except json.JSONDecodeError:
                    return ExecutionResult(
                        skill_id=skill.id,
                        success=False,
                        output=None,
                        error=f"Invalid JSON output: {stdout_text[:200]}",
                        stderr=stderr_text,
                        exit_code=completed.returncode,
                        execution_time_ms=execution_time_ms,
                        mode="b",
                    )

                return ExecutionResult(
                    skill_id=skill.id,
                    success=True,
                    output=output,
                    error="",
                    stderr=stderr_text,
                    exit_code=completed.returncode,
                    execution_time_ms=execution_time_ms,
                    mode="b",
                )

            error_message = stderr_text.strip()
            if not error_message:
                error_message = f"Process exited with code {completed.returncode}"

            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=error_message,
                stderr=stderr_text,
                exit_code=completed.returncode,
                execution_time_ms=execution_time_ms,
                mode="b",
            )

        except subprocess.TimeoutExpired as exc:
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            stderr_text = ""
            if exc.stderr:
                if isinstance(exc.stderr, bytes):
                    stderr_text = exc.stderr.decode("utf-8", errors="replace")
                else:
                    stderr_text = str(exc.stderr)

            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=f"Timeout after {skill.runtime.timeout_seconds}s",
                stderr=stderr_text,
                exit_code=-1,
                execution_time_ms=execution_time_ms,
                mode="b",
            )
        except Exception as exc:
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            logger.exception("Unexpected error during skill execution: %s", skill.id)
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=str(exc),
                stderr="",
                exit_code=-1,
                execution_time_ms=execution_time_ms,
                mode="b",
            )

    def _execute_mode_a(self, skill: Skill, input_data: dict) -> ExecutionResult:
        """Mode A: LLM이 SKILL.md를 읽고 결과물을 생성한다.

        Args:
            skill: Skill 객체
            input_data: 스킬에 전달할 입력 데이터

        Returns:
            ExecutionResult 객체
        """
        if skill.skill_md_content is None:
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error="SKILL.md content is empty",
                stderr="",
                exit_code=1,
                execution_time_ms=0,
                mode="a",
            )

        started_at = time.perf_counter()

        try:
            provider = self._provider or create_provider()
            response_text = provider.complete(
                system=skill.skill_md_content,
                user=json.dumps(input_data, ensure_ascii=False),
                max_tokens=16000,
            )

            parsed_json = self._extract_json(response_text)
            if parsed_json is None:
                parsed_json = {"raw_output": response_text}

            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)

            return ExecutionResult(
                skill_id=skill.id,
                success=True,
                output=parsed_json,
                error="",
                stderr="",
                exit_code=0,
                execution_time_ms=execution_time_ms,
                mode="a",
            )

        except Exception as exc:
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            logger.exception("Mode A execution failed: %s", skill.id)

            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=str(exc),
                stderr="",
                exit_code=1,
                execution_time_ms=execution_time_ms,
                mode="a",
            )

    def _extract_json(self, text: str) -> dict | None:
        """LLM 응답 텍스트에서 JSON을 추출한다.

        Args:
            text: LLM 응답 전문

        Returns:
            파싱된 dict 또는 None
        """
        stripped = text.strip()

        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        code_block_match = re.search(
            r"```json\s*(\{.*?\})\s*```",
            stripped,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if code_block_match:
            try:
                parsed = json.loads(code_block_match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and start < end:
            try:
                parsed = json.loads(stripped[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    def validate_input(self, skill: Skill, input_data: dict) -> list[str]:
        """입력 데이터가 skill의 interface_input 스키마에 맞는지 검증한다.

        Args:
            skill: 스킬 객체
            input_data: 검증할 입력 데이터

        Returns:
            에러 메시지 리스트. 빈 리스트 = 통과.
        """
        validator = Draft7Validator(skill.interface_input)
        return [error.message for error in validator.iter_errors(input_data)]

    def validate_output(self, skill: Skill, output_data: dict) -> list[str]:
        """출력 데이터가 skill의 interface_output 스키마에 맞는지 검증한다.

        Args:
            skill: 스킬 객체
            output_data: 검증할 출력 데이터

        Returns:
            에러 메시지 리스트. 빈 리스트 = 통과.
        """
        validator = Draft7Validator(skill.interface_output)
        return [error.message for error in validator.iter_errors(output_data)]
