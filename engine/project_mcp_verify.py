from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CODE_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _jsonrpc(request_id: int, method: str, params: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        ensure_ascii=True,
    )


def _read_tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("result", {}).get("content", [])
    if not content:
        return {}
    text = str(content[0].get("text") or "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_text": text}


def _rpc(
    proc: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(_jsonrpc(request_id, method, params) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"MCP server returned no response for {method}: {stderr}")
    return json.loads(line)


def _sample_project(root: Path) -> None:
    _write(root / "pyproject.toml", '[project]\nname = "mcp-sample"\nversion = "0.1.0"\n')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(root / "src" / "pipeline.py", "def run_stage_pipeline():\n    return 'ok'\n")
    _write(root / "tests" / "test_pipeline.py", "def test_pipeline():\n    assert True\n")


def default_server_command() -> list[str]:
    entrypoint = shutil.which("cambrian-mcp")
    if entrypoint:
        return [entrypoint]
    return [sys.executable, "-m", "engine.project_mcp_server"]


def _is_installed_entrypoint_command(command: list[str]) -> bool:
    if not command:
        return False
    executable_name = Path(command[0]).name.lower()
    return executable_name in {"cambrian-mcp", "cambrian-mcp.exe"}


def _server_command_mode(command: list[str]) -> str:
    if _is_installed_entrypoint_command(command):
        return "installed_entrypoint"
    if len(command) >= 3 and command[1:3] == ["-m", "engine.project_mcp_server"]:
        return "source_module"
    return "custom"


def verify(
    *,
    server_command: list[str] | None = None,
    python_executable: str | Path | None = None,
    server_cwd: str | Path | None = None,
    source_pythonpath: bool = False,
    require_installed_entrypoint: bool = False,
    verifier: str = "engine.project_mcp_verify",
) -> dict[str, Any]:
    env = dict(os.environ)
    if source_pythonpath:
        env["PYTHONPATH"] = str(CODE_ROOT)
    else:
        env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"

    if server_command:
        command = [str(item) for item in server_command]
    else:
        command = default_server_command()
        if command == [sys.executable, "-m", "engine.project_mcp_server"] and python_executable:
            command = [str(python_executable), "-m", "engine.project_mcp_server"]

    cwd = Path(server_cwd).resolve() if server_cwd else Path.cwd().resolve()
    with tempfile.TemporaryDirectory(prefix="cambrian-mcp-proof-") as temp:
        sample = Path(temp)
        _sample_project(sample)
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            initialize = _rpc(
                proc,
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "cambrian-mcp-operability-verifier", "version": "1.0.0"},
                },
            )
            tools = _rpc(proc, 2, "tools/list")
            missing_cwd = _rpc(
                proc,
                3,
                "tools/call",
                {"name": "cambrian_project_scan", "arguments": {}},
            )
            project_scan = _rpc(
                proc,
                4,
                "tools/call",
                {"name": "cambrian_project_scan", "arguments": {"cwd": str(sample), "timeout_seconds": 20}},
            )
            install_block = _rpc(
                proc,
                5,
                "tools/call",
                {"name": "cambrian_harness_install", "arguments": {"cwd": str(sample)}},
            )
            _rpc(proc, 6, "shutdown")
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            proc.wait(timeout=10)

    tool_names = [
        str(tool.get("name"))
        for tool in tools.get("result", {}).get("tools", [])
        if isinstance(tool, dict) and tool.get("name")
    ]
    missing_cwd_payload = _read_tool_payload(missing_cwd)
    project_scan_payload = _read_tool_payload(project_scan)
    install_block_payload = _read_tool_payload(install_block)
    checks = {
        "initialize": initialize.get("result", {}).get("serverInfo", {}).get("name") == "cambrian-local-mcp",
        "tools_list": "cambrian_project_scan" in tool_names and "cambrian_harness_install" in tool_names,
        "missing_cwd_blocked": bool(missing_cwd.get("result", {}).get("isError"))
        and missing_cwd_payload.get("status") == "blocked",
        "project_scan_with_explicit_cwd": bool(project_scan_payload.get("ok"))
        and project_scan_payload.get("stdout_json", {}).get("ok") is True,
        "harness_install_requires_confirm": bool(install_block.get("result", {}).get("isError"))
        and install_block_payload.get("status") == "blocked"
        and "confirm=true" in str(install_block_payload.get("error") or ""),
    }
    safety = project_scan_payload.get("safety_boundary", {}) if isinstance(project_scan_payload, dict) else {}
    checks["allowlisted_cli_only"] = safety.get("allowlisted_cambrian_cli_only") is True
    checks["no_arbitrary_shell"] = safety.get("shell") is False
    checks["explicit_cwd_required"] = safety.get("requires_explicit_cwd") is True
    command_mode = _server_command_mode(command)
    installed_entrypoint_command = command_mode == "installed_entrypoint"
    installed_entrypoint_required_satisfied = (
        installed_entrypoint_command if require_installed_entrypoint else True
    )
    verdict = "GO" if all(checks.values()) and installed_entrypoint_required_satisfied else "NO_GO"
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verifier": verifier,
        "server_command": command,
        "server_command_mode": command_mode,
        "installed_entrypoint_command": installed_entrypoint_command,
        "installed_entrypoint_required": require_installed_entrypoint,
        "installed_entrypoint_required_satisfied": installed_entrypoint_required_satisfied,
        "server_cwd": str(cwd),
        "source_pythonpath_injected": source_pythonpath,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "checks": checks,
        "project_scan_command": project_scan_payload.get("command"),
        "project_scan_status": project_scan_payload.get("status"),
        "blocked_without_cwd": missing_cwd_payload.get("error"),
        "blocked_install_without_confirm": install_block_payload.get("error"),
        "safety_boundary": safety,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "verdict": verdict,
    }


def write_receipt(receipt: dict[str, Any], receipt_path: str | Path, *, base: Path | None = None) -> Path:
    path = Path(receipt_path)
    if not path.is_absolute():
        path = (base or Path.cwd()).resolve() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_server_command_json(value: str) -> list[str] | None:
    if not value:
        return None
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) and item for item in loaded):
        raise ValueError("--server-command-json must be a JSON array of non-empty strings")
    return list(loaded)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Cambrian local MCP operability and write a receipt.")
    parser.add_argument(
        "--receipt",
        default="dist/mcp_operability_receipt.json",
        help="Path to write the JSON receipt.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for module-form server startup.",
    )
    parser.add_argument(
        "--server-cwd",
        default=str(Path.cwd()),
        help="Working directory used to start the MCP server.",
    )
    parser.add_argument(
        "--source-tree-mode",
        action="store_true",
        help="Inject the source tree into PYTHONPATH for source checkout verification.",
    )
    parser.add_argument(
        "--installed-wheel-mode",
        action="store_true",
        help="Require an installed cambrian-mcp entry point and keep source-tree PYTHONPATH disabled.",
    )
    parser.add_argument(
        "--server-command-json",
        default="",
        help="JSON array for an exact MCP server command, for example an installed cambrian-mcp entry point.",
    )
    return parser


def main(argv: list[str] | None = None, *, receipt_base: Path | None = None, print_json: bool = True) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        server_command = parse_server_command_json(args.server_command_json)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if server_command is None and args.source_tree_mode:
        server_command = [str(args.python), "-m", "engine.project_mcp_server"]
    receipt = verify(
        server_command=server_command,
        python_executable=args.python,
        server_cwd=args.server_cwd,
        source_pythonpath=bool(args.source_tree_mode),
        require_installed_entrypoint=bool(args.installed_wheel_mode),
    )
    receipt_path = write_receipt(receipt, args.receipt, base=receipt_base)
    if print_json:
        print(json.dumps({**receipt, "receipt_ref": str(receipt_path)}, ensure_ascii=False, indent=2))
    return 0 if receipt["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
