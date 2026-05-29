from __future__ import annotations

import json
import io
import subprocess
import sys
import tomllib
from pathlib import Path

from engine.project_mcp_server import TOOLS, handle_jsonrpc_line, serve_stdio


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _message(request_id: int, method: str, params: dict | None = None) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})


def _tool_text(response: dict) -> dict:
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def test_mcp_initialize_and_tools_list() -> None:
    init = handle_jsonrpc_line(
        _message(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        )
    )
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "cambrian-local-mcp"
    assert init["result"]["capabilities"] == {"tools": {}}

    listed = handle_jsonrpc_line(_message(2, "tools/list"))
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {tool.name for tool in TOOLS}
    assert "cambrian_project_scan" in names
    assert "cambrian_job_validate" in names
    assert all(tool["inputSchema"]["required"][0] == "cwd" for tool in listed["result"]["tools"])


def test_mcp_tool_call_blocks_missing_cwd() -> None:
    response = handle_jsonrpc_line(
        _message(
            1,
            "tools/call",
            {"name": "cambrian_project_scan", "arguments": {}},
        )
    )

    assert response is not None
    assert response["result"]["isError"] is True
    payload = _tool_text(response)
    assert payload["status"] == "blocked"
    assert "cwd is required" in payload["error"]
    assert payload["safety_boundary"]["requires_explicit_cwd"] is True


def test_mcp_harness_install_requires_explicit_confirm(tmp_path: Path) -> None:
    response = handle_jsonrpc_line(
        _message(
            1,
            "tools/call",
            {"name": "cambrian_harness_install", "arguments": {"cwd": str(tmp_path)}},
        )
    )

    assert response is not None
    assert response["result"]["isError"] is True
    payload = _tool_text(response)
    assert payload["status"] == "blocked"
    assert "confirm=true" in payload["error"]


def test_mcp_project_scan_runs_allowlisted_cambrian_cli(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample"\nversion = "0.1.0"\n')
    _write(tmp_path / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(tmp_path / "src" / "pipeline.py", "def run_stage_pipeline():\n    return 'ok'\n")
    _write(tmp_path / "tests" / "test_pipeline.py", "def test_pipeline():\n    assert True\n")

    response = handle_jsonrpc_line(
        _message(
            1,
            "tools/call",
            {"name": "cambrian_project_scan", "arguments": {"cwd": str(tmp_path), "timeout_seconds": 20}},
        )
    )

    assert response is not None
    assert response["result"]["isError"] is False
    payload = _tool_text(response)
    assert payload["ok"] is True
    assert payload["command"] == ["cambrian", "project", "scan", "--json"]
    assert payload["requested_cwd"] == str(tmp_path)
    assert payload["resolved_cwd"] == str(tmp_path.resolve())
    assert payload["safety_boundary"]["allowlisted_cambrian_cli_only"] is True
    assert payload["safety_boundary"]["git_push_allowed"] is False
    assert payload["stdout_json"]["ok"] is True
    assert payload["stdout_json"]["profile"]["language"] == "python"


def test_mcp_stdio_server_roundtrip_lists_tools() -> None:
    request = _message(1, "tools/list") + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "engine.project_mcp_server"],
        cwd=ROOT,
        input=request,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=10,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["id"] == 1
    assert any(tool["name"] == "cambrian_project_scan" for tool in payload["result"]["tools"])


def test_mcp_stdio_emits_ascii_safe_json_for_unicode_tool_payload(monkeypatch, tmp_path: Path) -> None:
    def fake_run(command, *, cwd, timeout_seconds, requested_cwd=None):  # type: ignore[no-untyped-def]
        return {
            "ok": True,
            "status": "passed",
            "command": ["cambrian", *command],
            "cwd": str(cwd),
            "requested_cwd": requested_cwd or str(cwd),
            "resolved_cwd": str(cwd),
            "stdout": '{"ok": true, "message": "한글 경로"}',
            "stderr": "",
            "stdout_json": {"ok": True, "message": "한글 경로"},
            "safety_boundary": {"allowlisted_cambrian_cli_only": True},
        }

    monkeypatch.setattr("engine.project_mcp_server._run_cambrian_cli", fake_run)
    request = _message(
        1,
        "tools/call",
        {"name": "cambrian_project_scan", "arguments": {"cwd": str(tmp_path)}},
    )
    output = io.StringIO()

    serve_stdio(io.StringIO(request + "\n"), output)

    wire_payload = output.getvalue()
    wire_payload.encode("ascii")
    response = json.loads(wire_payload)
    payload = _tool_text(response)
    assert payload["stdout_json"]["message"] == "한글 경로"


def test_mcp_entry_point_and_docs_are_registered() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["scripts"]["cambrian-mcp"] == "engine.project_mcp_server:main"

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    adapter_doc = (ROOT / "docs" / "product" / "52_LOCAL_MCP_ADAPTER.md").read_text(encoding="utf-8")
    connect_doc = (ROOT / "docs" / "release" / "MCP_EXTERNAL_CLIENT_CONNECT.md").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "product" / "46_TRUE_HARNESS_CONTRACT.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert "cambrian-mcp" in readme
    assert "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in readme
    assert "MCP_EXTERNAL_CLIENT_CONNECT.md" in readme
    assert "cambrian_project_scan" in adapter_doc
    assert "mcpServers" in adapter_doc
    assert "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in adapter_doc
    assert "scripts/verify_mcp_operability.py" in adapter_doc
    assert "First Tool Calls" in connect_doc
    assert "cambrian_harness_install" in connect_doc
    assert "confirm=true" in connect_doc
    assert "server_command_mode: installed_entrypoint" in connect_doc
    assert "installed_entrypoint_command: true" in connect_doc
    assert "verify_mcp_operability.py" in readme
    assert "source-tree module receipts are for development checks only" in readme
    assert "allowlisted local Cambrian CLI tools" in contract
    assert "52_LOCAL_MCP_ADAPTER.md" in index


def test_mcp_cli_verify_writes_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / "mcp_cli_receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "mcp",
            "verify",
            "--receipt",
            str(receipt),
            "--server-command-json",
            json.dumps([sys.executable, "-m", "engine.project_mcp_server"]),
            "--server-cwd",
            str(ROOT),
            "--source-tree-mode",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert receipt.exists()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["verdict"] == "GO"
    assert payload["verifier"] == "cambrian mcp verify"
    assert payload["source_pythonpath_injected"] is True
    assert payload["server_command_mode"] == "source_module"
    assert payload["installed_entrypoint_command"] is False
    assert payload["installed_entrypoint_required"] is False
    assert payload["checks"]["no_arbitrary_shell"] is True


def test_mcp_external_operability_verifier_writes_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / "mcp_operability_receipt.json"
    completed = subprocess.run(
        [sys.executable, "scripts/verify_mcp_operability.py", "--receipt", str(receipt)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert receipt.exists()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["verdict"] == "GO"
    assert payload["source_pythonpath_injected"] is True
    assert payload["server_command_mode"] == "source_module"
    assert payload["installed_entrypoint_command"] is False
    assert payload["checks"]["initialize"] is True
    assert payload["checks"]["tools_list"] is True
    assert payload["checks"]["missing_cwd_blocked"] is True
    assert payload["checks"]["project_scan_with_explicit_cwd"] is True
    assert payload["checks"]["harness_install_requires_confirm"] is True
    assert payload["checks"]["allowlisted_cli_only"] is True
    assert payload["checks"]["no_arbitrary_shell"] is True
    assert payload["source_code_modified_by_cambrian"] is False


def test_mcp_cli_verify_requires_installed_entrypoint_unless_source_tree_mode(tmp_path: Path) -> None:
    receipt = tmp_path / "mcp_cli_receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "engine.cli",
            "mcp",
            "verify",
            "--receipt",
            str(receipt),
            "--server-command-json",
            json.dumps([sys.executable, "-m", "engine.project_mcp_server"]),
            "--server-cwd",
            str(ROOT),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 1
    assert receipt.exists()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["verdict"] == "NO_GO"
    assert payload["source_pythonpath_injected"] is False
    assert payload["server_command_mode"] == "source_module"
    assert payload["installed_entrypoint_command"] is False
    assert payload["installed_entrypoint_required"] is True
    assert payload["installed_entrypoint_required_satisfied"] is False
    assert all(payload["checks"].values())
