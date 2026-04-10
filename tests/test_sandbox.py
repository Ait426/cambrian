"""ContainerRunner 유닛 테스트."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.models import ExecutionResult, SandboxConfig, Skill, SkillRuntime, SkillLifecycle
from engine.sandbox import ContainerRunner


def _make_skill(
    skill_path: Path,
    needs_network: bool = False,
) -> Skill:
    """테스트용 Mode B Skill 객체."""
    return Skill(
        id="test_skill",
        version="1.0.0",
        name="Test",
        description="test",
        domain="testing",
        tags=["test"],
        mode="b",
        runtime=SkillRuntime(
            language="python",
            needs_network=needs_network,
        ),
        lifecycle=SkillLifecycle(),
        skill_path=skill_path,
    )


def test_container_runner_disables_network_by_default(tmp_path: Path) -> None:
    """네트워크가 기본적으로 비활성화되는지 검증."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path, needs_network=False)
    cmd = runner._build_docker_command(skill)

    assert "--network" in cmd
    net_idx = cmd.index("--network")
    assert cmd[net_idx + 1] == "none"


def test_container_runner_enables_network_for_needs_network_skill(
    tmp_path: Path,
) -> None:
    """needs_network=True 스킬에는 네트워크 차단을 적용하지 않는다."""
    config = SandboxConfig(enabled=True, network_enabled=False)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path, needs_network=True)
    cmd = runner._build_docker_command(skill)

    # --network none이 없어야 함
    if "--network" in cmd:
        net_idx = cmd.index("--network")
        assert cmd[net_idx + 1] != "none"


def test_container_runner_applies_resource_limits(tmp_path: Path) -> None:
    """메모리/CPU/PID 제한이 명령에 포함되는지 검증."""
    config = SandboxConfig(
        enabled=True,
        memory_limit_mb=512,
        cpu_limit=2.0,
        pids_limit=32,
    )
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    cmd = runner._build_docker_command(skill)

    assert "512m" in cmd
    assert "2.0" in cmd
    assert "32" in cmd


def test_container_runner_mounts_skill_readonly(tmp_path: Path) -> None:
    """스킬 디렉토리가 읽기 전용으로 마운트되는지 검증."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    cmd = runner._build_docker_command(skill)

    # -v {path}:/skill:ro 패턴 확인
    found_mount = False
    for i, arg in enumerate(cmd):
        if arg == "-v" and i + 1 < len(cmd):
            mount = cmd[i + 1]
            if mount.endswith(":/skill:ro"):
                found_mount = True
                break
    assert found_mount, f"skill ro 마운트 미발견: {cmd}"


def test_container_runner_read_only_root(tmp_path: Path) -> None:
    """read_only_root=True 시 --read-only + tmpfs 적용."""
    config = SandboxConfig(enabled=True, read_only_root=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    cmd = runner._build_docker_command(skill)

    assert "--read-only" in cmd
    assert "--tmpfs" in cmd


def test_container_runner_is_available_no_docker() -> None:
    """Docker CLI가 없으면 is_available()이 False."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)

    with patch("shutil.which", return_value=None):
        assert runner.is_available() is False


def test_sandbox_config_defaults() -> None:
    """SandboxConfig 기본값 검증."""
    config = SandboxConfig()
    assert config.enabled is False
    assert config.provider == "docker"
    assert config.network_enabled is False
    assert config.memory_limit_mb == 256
    assert config.read_only_root is True


def test_policy_loads_sandbox_section(tmp_path: Path) -> None:
    """policy JSON에 sandbox 섹션이 있으면 정상 파싱된다."""
    import json
    from engine.policy import CambrianPolicy

    policy_data = {
        "sandbox": {
            "enabled": True,
            "image": "python:3.12-slim",
            "memory_limit_mb": 512,
        },
    }
    policy_path = tmp_path / "test_policy.json"
    policy_path.write_text(json.dumps(policy_data), encoding="utf-8")

    policy = CambrianPolicy(str(policy_path))

    assert policy.sandbox.enabled is True
    assert policy.sandbox.image == "python:3.12-slim"
    assert policy.sandbox.memory_limit_mb == 512
    # 미지정 필드는 기본값
    assert policy.sandbox.network_enabled is False
    assert policy.sandbox.pids_limit == 64


def test_mode_b_uses_container_runner_when_sandbox_enabled(
    tmp_path: Path,
) -> None:
    """sandbox enabled 시 executor가 container runner를 사용한다."""
    from engine.executor import SkillExecutor

    config = SandboxConfig(enabled=True)
    executor = SkillExecutor(sandbox_config=config)

    assert executor._container_runner is not None


def test_mode_b_falls_back_or_fails_cleanly_when_docker_unavailable(
    tmp_path: Path,
) -> None:
    """Docker 미사용 환경에서 sandbox_unavailable을 반환한다."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)

    skill = _make_skill(tmp_path, needs_network=False)
    # execute/main.py 생성
    (tmp_path / "execute").mkdir()
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    with patch("shutil.which", return_value=None):
        runner._docker_path = None
        result = runner.execute(skill, {"x": "test"})

    assert result.success is False
    assert "unavailable" in result.error.lower()


def test_container_runner_applies_timeout_limit(tmp_path: Path) -> None:
    """timeout 제한이 적용되어 TimeoutExpired 시 적절한 결과를 반환한다."""
    config = SandboxConfig(enabled=True, timeout_sec=1)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=1),
    ):
        result = runner.execute(skill, {"x": "test"})

    assert result.success is False
    assert "timeout" in result.error.lower()


def test_container_runner_returns_execution_result_contract(
    tmp_path: Path,
) -> None:
    """컨테이너 실행 결과가 ExecutionResult 계약을 만족한다."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b'{"result": "ok"}'
    mock_result.stderr = b""

    with patch("subprocess.run", return_value=mock_result):
        result = runner.execute(skill, {"x": "test"})

    assert isinstance(result, ExecutionResult)
    assert result.success is True
    assert result.output == {"result": "ok"}
    assert result.skill_id == "test_skill"
    assert result.mode == "b"
    assert result.execution_time_ms >= 0


def test_container_runner_oom_killed(tmp_path: Path) -> None:
    """OOM killed (exit code 137) 시 적절한 에러 메시지를 반환한다."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    mock_result = MagicMock()
    mock_result.returncode = 137
    mock_result.stdout = b""
    mock_result.stderr = b"Killed"

    with patch("subprocess.run", return_value=mock_result):
        result = runner.execute(skill, {"x": "test"})

    assert result.success is False
    assert result.exit_code == 137
    assert "killed" in result.error.lower() or "oom" in result.error.lower()


def test_security_docs_reflect_container_isolation_availability() -> None:
    """README에 컨테이너 격리 관련 내용이 포함되어 있다."""
    from pathlib import Path

    # README.md 또는 README_EN.md에서 찾기
    project_root = Path(__file__).parent.parent
    readme_paths = [
        project_root / "README.md",
        project_root / "README_EN.md",
    ]

    found_content = False
    for readme_path in readme_paths:
        if not readme_path.exists():
            continue
        content = readme_path.read_text(encoding="utf-8")
        if "container" in content.lower() and "sandbox" in content.lower():
            found_content = True
            break

    assert found_content, (
        "README에 container/sandbox 격리 관련 내용이 없음"
    )


def test_container_runner_uses_python_no_bytecode_flag(tmp_path: Path) -> None:
    """A: docker 명령에 python -B 플래그가 포함된다."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    cmd = runner._build_docker_command(skill)

    # python 다음에 -B가 와야 함
    assert "python" in cmd
    python_idx = cmd.index("python")
    assert cmd[python_idx + 1] == "-B", f"python -B 미적용: {cmd[python_idx:]}"


def test_container_runner_bytecode_env_set(tmp_path: Path) -> None:
    """A: PYTHONDONTWRITEBYTECODE=1 env가 설정된다."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    cmd = runner._build_docker_command(skill)

    assert "PYTHONDONTWRITEBYTECODE=1" in cmd


def test_container_runner_kills_container_on_timeout(tmp_path: Path) -> None:
    """B: timeout 시 docker kill + docker rm -f가 호출된다."""
    config = SandboxConfig(enabled=True, timeout_sec=1)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    cleanup_calls = []

    def mock_run(cmd, **kwargs):
        cmd_str = " ".join(cmd)
        if "docker run" in cmd_str or cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        # kill/rm 호출 기록
        cleanup_calls.append(cmd[1])  # "kill" or "rm"
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = runner.execute(skill, {"x": "test"})

    assert "kill" in cleanup_calls, f"docker kill 미호출: {cleanup_calls}"
    assert result.failure_type == "sandbox_timeout"


def test_container_runner_returns_sandbox_timeout_failure_type(
    tmp_path: Path,
) -> None:
    """C: timeout 결과에 failure_type='sandbox_timeout'이 설정된다."""
    config = SandboxConfig(enabled=True, timeout_sec=1)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=1),
    ):
        result = runner.execute(skill, {"x": "test"})

    assert result.success is False
    assert result.failure_type == "sandbox_timeout"
    assert "timeout" in result.error.lower()


def test_container_runner_returns_sandbox_unavailable_failure_type(
    tmp_path: Path,
) -> None:
    """C: Docker 없을 때 failure_type='sandbox_unavailable'이 설정된다."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    with patch("shutil.which", return_value=None):
        runner._docker_path = None
        result = runner.execute(skill, {"x": "test"})

    assert result.success is False
    assert result.failure_type == "sandbox_unavailable"


def test_container_runner_maps_oom_to_sandbox_violation(
    tmp_path: Path,
) -> None:
    """C: OOM killed (exit 137)에 failure_type='sandbox_violation'."""
    config = SandboxConfig(enabled=True)
    runner = ContainerRunner(config)
    runner._docker_path = "/usr/bin/docker"

    skill = _make_skill(tmp_path)
    (tmp_path / "execute").mkdir(exist_ok=True)
    (tmp_path / "execute" / "main.py").write_text("pass\n")

    mock_result = MagicMock()
    mock_result.returncode = 137
    mock_result.stdout = b""
    mock_result.stderr = b"Killed"

    with patch("subprocess.run", return_value=mock_result):
        result = runner.execute(skill, {"x": "test"})

    assert result.success is False
    assert result.failure_type == "sandbox_violation"
    assert result.exit_code == 137


def test_sandbox_off_path_remains_unchanged(tmp_path: Path) -> None:
    """sandbox off 시 기존 subprocess 경로가 그대로 동작한다."""
    from engine.executor import SkillExecutor

    # sandbox_config=None → container_runner 없음
    executor = SkillExecutor(sandbox_config=None)
    assert executor._container_runner is None

    # sandbox disabled
    config = SandboxConfig(enabled=False)
    executor2 = SkillExecutor(sandbox_config=config)
    assert executor2._container_runner is None
