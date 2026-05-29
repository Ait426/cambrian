from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "cambrian-local-mcp"
SERVER_VERSION = "0.1.0"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


def _cwd_schema(extra: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "cwd": {
            "type": "string",
            "description": "Absolute or relative project directory where Cambrian should run. Required for safety.",
        },
        "timeout_seconds": {
            "type": "integer",
            "minimum": 1,
            "maximum": 600,
            "description": "Command timeout. Defaults to 120 seconds.",
        },
    }
    if extra:
        properties.update(extra)
    return {
        "type": "object",
        "properties": properties,
        "required": ["cwd", *(required or [])],
        "additionalProperties": False,
    }


TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="cambrian_doctor",
        description="Run local Cambrian readiness checks for a project. Does not mutate source files.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_project_scan",
        description="Scan the project and save a project harness profile under .cambrian/project/profile.yaml.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_harness_interview_infer",
        description="Infer harness interview answers from project Markdown docs and scanner evidence.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_harness_engineer_design",
        description="Create the project-specific harness design candidate from scan and interview answers.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_harness_engineer_review",
        description="Review the current harness design candidate before installation.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_harness_engineer_dry_run",
        description="Dry-run selected agents, skills, validation, and risk boundaries for a request.",
        input_schema=_cwd_schema(
            {
                "request": {
                    "type": "string",
                    "description": "Work request to simulate without starting a real job.",
                }
            },
            required=["request"],
        ),
    ),
    ToolDefinition(
        name="cambrian_workforce_generate",
        description="Generate project-specific AI workforce draft files.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_skill_generate",
        description="Generate project-specific skill draft files.",
        input_schema=_cwd_schema(),
    ),
    ToolDefinition(
        name="cambrian_harness_install",
        description="Install the reviewed harness into .cambrian metadata. Requires confirm=true.",
        input_schema=_cwd_schema(
            {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true. This only installs Cambrian metadata and must not auto-patch source code.",
                }
            },
            required=["confirm"],
        ),
    ),
    ToolDefinition(
        name="cambrian_job_start",
        description="Create a Cambrian job packet using the active harness. Does not call providers or patch source code.",
        input_schema=_cwd_schema(
            {
                "request": {
                    "type": "string",
                    "description": "The job request to hand to the external AI.",
                }
            },
            required=["request"],
        ),
    ),
    ToolDefinition(
        name="cambrian_job_ingest",
        description="Ingest an AI reply file into the latest or named Cambrian job.",
        input_schema=_cwd_schema(
            {
                "job_ref": {
                    "type": "string",
                    "description": "Job reference. Use 'latest' when appropriate.",
                    "default": "latest",
                },
                "reply_file": {
                    "type": "string",
                    "description": "Path to the AI reply YAML/JSON/text file.",
                },
            },
            required=["reply_file"],
        ),
    ),
    ToolDefinition(
        name="cambrian_job_validate",
        description="Validate the latest or named Cambrian job. run_commands defaults to false.",
        input_schema=_cwd_schema(
            {
                "job_ref": {
                    "type": "string",
                    "description": "Job reference. Use 'latest' when appropriate.",
                    "default": "latest",
                },
                "run_commands": {
                    "type": "boolean",
                    "description": "Whether to execute validation commands. Defaults to false.",
                    "default": False,
                },
            }
        ),
    ),
    ToolDefinition(
        name="cambrian_job_complete",
        description="Record a manual job outcome after validation evidence is available.",
        input_schema=_cwd_schema(
            {
                "job_ref": {
                    "type": "string",
                    "description": "Job reference. Use 'latest' when appropriate.",
                    "default": "latest",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": "Manual outcome to record.",
                },
                "notes": {
                    "type": "string",
                    "description": "Short outcome note.",
                    "default": "",
                },
            },
            required=["outcome"],
        ),
    ),
    ToolDefinition(
        name="cambrian_company_snapshot",
        description="Create a private-safe company snapshot summary. Excludes raw private project data.",
        input_schema=_cwd_schema(),
    ),
]


def main() -> None:
    serve_stdio()


def serve_stdio(stdin: Any | None = None, stdout: Any | None = None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for raw_line in stdin:
        line = str(raw_line).strip()
        if not line:
            continue
        response = handle_jsonrpc_line(line)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
        stdout.flush()


def handle_jsonrpc_line(line: str) -> dict[str, Any] | None:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        return _error(None, -32700, f"Parse error: {exc}")
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")
    request_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params", {})
    if method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _result(request_id, _initialize_result(params if isinstance(params, dict) else {}))
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [_tool_payload(tool) for tool in TOOLS]})
    if method == "tools/call":
        try:
            payload = _handle_tool_call(params if isinstance(params, dict) else {})
        except ValueError as exc:
            return _result(request_id, _tool_result(_blocked_payload(str(exc)), is_error=True))
        return _result(request_id, _tool_result(payload, is_error=not bool(payload.get("ok"))))
    if method == "shutdown":
        return _result(request_id, None)
    return _error(request_id, -32601, f"Method not found: {method}")


def _initialize_result(params: dict[str, Any]) -> dict[str, Any]:
    requested = str(params.get("protocolVersion") or PROTOCOL_VERSION)
    return {
        "protocolVersion": requested or PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
    }


def _handle_tool_call(params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("tools/call arguments must be an object")
    known_names = {tool.name for tool in TOOLS}
    if name not in known_names:
        raise ValueError(f"Unknown Cambrian MCP tool: {name}")
    command = _command_for_tool(name, arguments)
    requested_cwd = str(arguments.get("cwd") or "").strip()
    cwd = _resolve_cwd(arguments)
    timeout = _timeout(arguments)
    return _run_cambrian_cli(command, cwd=cwd, timeout_seconds=timeout, requested_cwd=requested_cwd)


def _command_for_tool(name: str, args: dict[str, Any]) -> list[str]:
    if name == "cambrian_doctor":
        cwd = str(_resolve_cwd(args))
        return ["doctor", "--workspace", cwd, "--json"]
    if name == "cambrian_project_scan":
        return ["project", "scan", "--json"]
    if name == "cambrian_harness_interview_infer":
        return ["harness", "interview", "infer", "--json"]
    if name == "cambrian_harness_engineer_design":
        return ["harness", "engineer", "design", "--json"]
    if name == "cambrian_harness_engineer_review":
        return ["harness", "engineer", "review", "--json"]
    if name == "cambrian_harness_engineer_dry_run":
        return ["harness", "engineer", "dry-run", _required_text(args, "request"), "--json"]
    if name == "cambrian_workforce_generate":
        return ["workforce", "generate", "--json"]
    if name == "cambrian_skill_generate":
        return ["skill", "generate", "--json"]
    if name == "cambrian_harness_install":
        if args.get("confirm") is not True:
            raise ValueError("cambrian_harness_install is blocked unless confirm=true")
        return ["harness", "install", "--confirm", "--json"]
    if name == "cambrian_job_start":
        return ["job", "start", _required_text(args, "request"), "--json"]
    if name == "cambrian_job_ingest":
        return ["job", "ingest", str(args.get("job_ref") or "latest"), _required_text(args, "reply_file"), "--json"]
    if name == "cambrian_job_validate":
        command = ["job", "validate", str(args.get("job_ref") or "latest"), "--json"]
        if args.get("run_commands") is True:
            command.insert(3, "--run")
        return command
    if name == "cambrian_job_complete":
        command = ["job", "complete", str(args.get("job_ref") or "latest"), "--outcome", _required_text(args, "outcome"), "--json"]
        notes = str(args.get("notes") or "").strip()
        if notes:
            command.extend(["--notes", notes])
        return command
    if name == "cambrian_company_snapshot":
        return ["company", "snapshot", "--json"]
    raise ValueError(f"Unknown Cambrian MCP tool: {name}")


def _resolve_cwd(args: dict[str, Any]) -> Path:
    raw = str(args.get("cwd") or "").strip()
    if not raw:
        raise ValueError("cwd is required for every Cambrian MCP tool")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"cwd does not exist or is not a directory: {path}")
    return path


def _required_text(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _timeout(args: dict[str, Any]) -> int:
    raw = args.get("timeout_seconds", 120)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("timeout_seconds must be an integer") from None
    return max(1, min(value, 600))


def _run_cambrian_cli(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    requested_cwd: str | None = None,
) -> dict[str, Any]:
    full_command = [sys.executable, "-m", "engine.cli", *command]
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        completed = subprocess.run(
            full_command,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "timeout",
            "command": ["cambrian", *command],
            "cwd": str(cwd),
            "requested_cwd": requested_cwd or str(cwd),
            "resolved_cwd": str(cwd),
            "timeout_seconds": timeout_seconds,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "next_recommended_command": None,
        }
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    stdout_json = _parse_json_or_none(stdout)
    return {
        "ok": completed.returncode == 0,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": ["cambrian", *command],
        "cwd": str(cwd),
        "requested_cwd": requested_cwd or str(cwd),
        "resolved_cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_json": stdout_json,
        "next_recommended_command": _extract_next_command(stdout_json),
        "safety_boundary": {
            "shell": False,
            "allowlisted_cambrian_cli_only": True,
            "requires_explicit_cwd": True,
            "source_code_patch_apply_default": False,
            "git_push_allowed": False,
            "secret_reading_allowed": False,
        },
    }


def _parse_json_or_none(text: str) -> Any | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _extract_next_command(payload: Any) -> str | list[str] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("next_command", "next"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    value = payload.get("next_commands")
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return None


def _tool_result(payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=True, indent=2)}],
        "structuredContent": payload,
        "isError": bool(is_error),
    }


def _blocked_payload(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "error": message,
        "safety_boundary": {
            "allowlisted_cambrian_cli_only": True,
            "requires_explicit_cwd": True,
            "source_code_patch_apply_default": False,
            "git_push_allowed": False,
            "secret_reading_allowed": False,
        },
    }


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
