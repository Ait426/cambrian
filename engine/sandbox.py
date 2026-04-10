"""Cambrian 컨테이너 격리 실행기.

Mode B 스킬을 Docker 컨테이너 내에서 실행하여
파일시스템/네트워크/프로세스 격리를 제공한다.
"""

import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from engine.models import ExecutionResult, SandboxConfig, Skill

logger = logging.getLogger(__name__)


class ContainerRunner:
    """Docker 기반 컨테이너 격리 실행기.

    SandboxConfig를 받아 Docker 명령을 구성하고,
    스킬을 격리된 환경에서 실행한다.
    """

    def __init__(self, config: SandboxConfig) -> None:
        """초기화.

        Args:
            config: 컨테이너 격리 설정
        """
        self._config = config
        self._docker_path: str | None = None

    def is_available(self) -> bool:
        """Docker CLI가 사용 가능한지 확인한다.

        Returns:
            True면 docker 명령이 실행 가능
        """
        if self._docker_path is not None:
            return True

        docker = shutil.which("docker")
        if docker is None:
            logger.warning("Docker CLI not found in PATH")
            return False

        try:
            result = subprocess.run(
                [docker, "info"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.warning(
                    "Docker daemon not responding: %s",
                    result.stderr.decode("utf-8", errors="replace")[:200],
                )
                return False
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Docker availability check failed: %s", exc)
            return False

        self._docker_path = docker
        return True

    def _build_docker_command(
        self,
        skill: Skill,
        container_name: str | None = None,
    ) -> list[str]:
        """Docker run 명령을 구성한다.

        Args:
            skill: 실행할 스킬
            container_name: 컨테이너 식별 이름 (timeout 시 kill 대상)

        Returns:
            docker run 명령 인자 리스트
        """
        docker = self._docker_path or "docker"
        cfg = self._config

        cmd = [
            docker, "run", "--rm", "-i",
        ]

        # 컨테이너 이름 (timeout cleanup 경로에서 kill 대상으로 사용)
        if container_name:
            cmd.extend(["--name", container_name])

        # 네트워크 제어
        if not cfg.network_enabled and not skill.runtime.needs_network:
            cmd.extend(["--network", "none"])

        # 자원 제한
        cmd.extend(["--memory", f"{cfg.memory_limit_mb}m"])
        cmd.extend(["--cpus", str(cfg.cpu_limit)])
        cmd.extend(["--pids-limit", str(cfg.pids_limit)])
        cmd.extend(["--ulimit", "nofile=256:256"])

        # bytecode 쓰기 방지 (--read-only 환경 호환, python -B와 이중 보장)
        cmd.extend(["-e", "PYTHONDONTWRITEBYTECODE=1"])

        # 파일시스템 격리
        if cfg.read_only_root:
            cmd.append("--read-only")
            cmd.extend(["--tmpfs", "/tmp:size=64m"])

        # 스킬 디렉토리 마운트 (읽기 전용)
        skill_path = str(skill.skill_path.resolve())
        cmd.extend(["-v", f"{skill_path}:/skill:ro"])
        cmd.extend(["-w", "/skill"])

        # 이미지 + 실행 명령
        # -B: __pycache__ 쓰기 방지 (--read-only 환경 필수)
        cmd.append(cfg.image)
        cmd.extend(["python", "-B", "/skill/execute/main.py"])

        return cmd

    def _cleanup_container(self, container_name: str) -> None:
        """timeout 등으로 남은 컨테이너를 정리한다.

        docker kill → docker rm -f 순서. 실패해도 로그만 남기고 계속한다.

        Args:
            container_name: 정리할 컨테이너 이름
        """
        docker = self._docker_path or "docker"
        for action in (["kill"], ["rm", "-f"]):
            try:
                subprocess.run(
                    [docker] + action + [container_name],
                    capture_output=True,
                    timeout=5,
                )
            except Exception as exc:
                logger.warning(
                    "Container cleanup '%s %s' failed: %s",
                    action[0], container_name, exc,
                )

    def execute(self, skill: Skill, input_data: dict) -> ExecutionResult:
        """컨테이너 내에서 스킬을 실행한다.

        Args:
            skill: 실행할 Skill 객체
            input_data: 스킬에 전달할 입력 데이터

        Returns:
            ExecutionResult 객체
        """
        if not self.is_available():
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error="Sandbox unavailable: Docker not found or not running",
                stderr="",
                exit_code=-1,
                execution_time_ms=0,
                mode="b",
                failure_type="sandbox_unavailable",
            )

        main_py = skill.skill_path / "execute" / "main.py"
        if not main_py.exists():
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error="execute/main.py not found",
                stderr="",
                exit_code=-1,
                execution_time_ms=0,
                mode="b",
                failure_type="execution_error",
            )

        # 컨테이너 이름 (timeout cleanup 시 kill 대상으로 사용)
        container_name = f"cambrian-{skill.id}-{uuid.uuid4().hex[:8]}"
        cmd = self._build_docker_command(skill, container_name=container_name)
        json_input = json.dumps(input_data, ensure_ascii=False)
        timeout = self._config.timeout_sec
        started_at = time.perf_counter()

        try:
            completed = subprocess.run(
                cmd,
                input=json_input.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
            )
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            stdout_text = completed.stdout.decode("utf-8", errors="replace")
            stderr_text = completed.stderr.decode("utf-8", errors="replace")

            # OOM killed 등 시그널 감지
            if completed.returncode == 137:
                return ExecutionResult(
                    skill_id=skill.id,
                    success=False,
                    output=None,
                    error="Container killed (OOM or resource limit exceeded)",
                    stderr=stderr_text,
                    exit_code=137,
                    execution_time_ms=execution_time_ms,
                    mode="b",
                    failure_type="sandbox_violation",
                )

            # Docker image not found / startup 실패
            if completed.returncode == 125:
                return ExecutionResult(
                    skill_id=skill.id,
                    success=False,
                    output=None,
                    error=f"Docker error (image missing or config issue): {stderr_text[:200]}",
                    stderr=stderr_text,
                    exit_code=125,
                    execution_time_ms=execution_time_ms,
                    mode="b",
                    failure_type="sandbox_unavailable",
                )

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
                        failure_type="output_invalid",
                    )

                return ExecutionResult(
                    skill_id=skill.id,
                    success=True,
                    output=output,
                    error="",
                    stderr=stderr_text,
                    exit_code=0,
                    execution_time_ms=execution_time_ms,
                    mode="b",
                    failure_type=None,
                )

            error_message = stderr_text.strip() or f"Container exited with code {completed.returncode}"
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=error_message,
                stderr=stderr_text,
                exit_code=completed.returncode,
                execution_time_ms=execution_time_ms,
                mode="b",
                failure_type="execution_error",
            )

        except subprocess.TimeoutExpired:
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            # timeout 시 컨테이너 정리 (kill → rm -f)
            self._cleanup_container(container_name)
            logger.warning(
                "Container timeout for skill '%s' after %ds",
                skill.id, timeout,
            )
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=f"Sandbox timeout after {timeout}s",
                stderr="",
                exit_code=-1,
                execution_time_ms=execution_time_ms,
                mode="b",
                failure_type="sandbox_timeout",
            )

        except Exception as exc:
            ended_at = time.perf_counter()
            execution_time_ms = int((ended_at - started_at) * 1000)
            logger.exception(
                "Container execution error for skill '%s': %s",
                skill.id, exc,
            )
            return ExecutionResult(
                skill_id=skill.id,
                success=False,
                output=None,
                error=str(exc),
                stderr="",
                exit_code=-1,
                execution_time_ms=execution_time_ms,
                mode="b",
                failure_type="execution_error",
            )
