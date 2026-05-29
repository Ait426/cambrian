# MCP External Client Connect

## Purpose

This is the first-user MCP connection path for Cambrian.

Use it after Cambrian is installed in a project environment and the user wants Claude, Codex, Cursor, or another MCP client to operate Cambrian through tools instead of raw shell commands.

MCP is the connection layer. One Good Harness remains the product core.

## Installed Entry Points

Installed CLI:

```bash
cambrian
```

Installed MCP server:

```bash
cambrian-mcp
```

Installed MCP verifier:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

The verifier starts the MCP server, performs a JSON-RPC initialize, lists tools, checks explicit `cwd` enforcement, confirms `cambrian_project_scan` works with an explicit project directory, confirms `cambrian_harness_install` is blocked without `confirm=true`, and records the no-arbitrary-shell safety boundary.

For external-user proof, the receipt must show that the server was started from the installed `cambrian-mcp` entry point, not from the source-tree module fallback.

## Client Config Shape

Most stdio MCP clients use a config shaped like this:

```json
{
  "mcpServers": {
    "cambrian": {
      "command": "cambrian-mcp",
      "args": []
    }
  }
}
```

If the client cannot resolve `cambrian-mcp` from `PATH`, point `command` to the installed environment's executable, for example:

```json
{
  "mcpServers": {
    "cambrian": {
      "command": "C:\\path\\to\\venv\\Scripts\\cambrian-mcp.exe",
      "args": []
    }
  }
}
```

On macOS/Linux, the same idea usually looks like:

```json
{
  "mcpServers": {
    "cambrian": {
      "command": "/path/to/venv/bin/cambrian-mcp",
      "args": []
    }
  }
}
```

Client-specific config file locations differ. The Cambrian contract does not: the client starts `cambrian-mcp` over stdio and every Cambrian tool call supplies an explicit `cwd`.

### Codex Desktop / CLI

Codex uses TOML under the user Codex config. A working local entry looks like this:

```toml
[mcp_servers.cambrian]
command = 'cambrian-mcp'
args = []
startup_timeout_sec = 120
```

If Codex cannot resolve the entry point from `PATH`, use the same installed-environment executable shape shown above, for example `C:\path\to\venv\Scripts\cambrian-mcp.exe`.

After editing the config, verify that Codex sees the server:

```bash
codex mcp list
codex mcp get cambrian
```

Expected status:

```text
cambrian ... enabled
```

In a fresh Codex session, the first live tool proof is:

```text
MCP_TOOL_VISIBLE=yes
CALL_SUCCEEDED=yes
PROJECT_SCAN_STATUS=passed
```

On Windows, if the target project path contains non-ASCII characters and Codex CLI fails before the model turn with websocket metadata encoding errors, create an ASCII junction or use an ASCII workspace alias for the Codex session. Cambrian still receives the explicit `cwd` and resolves it to the real target path. Tool results include both `requested_cwd` and `resolved_cwd` so the caller can distinguish the alias path from the actual execution path.

## First Tool Calls

After the client connects:

1. Run MCP `tools/list`.
2. Call `cambrian_doctor` with the target project directory.
3. Call `cambrian_project_scan` with the same target project directory.
4. Call `cambrian_harness_interview_infer`.
5. Review the inferred answers before any install.
6. Call harness design/review/dry-run.
7. Call `cambrian_harness_install` only after user approval and with `confirm=true`.

Example tool arguments:

```json
{
  "cwd": "C:\\path\\to\\target-project"
}
```

`cwd` is required per tool call even if the MCP client config also has a process working directory.

## Verification Commands

For an installed Cambrian environment:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

For source-tree development:

```bash
python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json
```

For the full release proof:

```bash
python scripts/smoke_ai_company_gold_path.py
```

The golden path builds a fresh wheel, installs it into a fresh virtual environment, runs `cambrian mcp verify` against the installed `cambrian-mcp` entry point, and writes `.launch_runs/ai_company_gold_path_latest/mcp_operability_receipt.json`.

## Required Receipt Signals

The receipt must show:

```text
verdict: GO
initialize: true
tools_list: true
missing_cwd_blocked: true
project_scan_with_explicit_cwd: true
harness_install_requires_confirm: true
allowlisted_cli_only: true
no_arbitrary_shell: true
explicit_cwd_required: true
source_code_modified_by_cambrian: false
provider_api_called_by_cambrian: false
server_command_mode: installed_entrypoint
installed_entrypoint_command: true
```

## Safety Boundary

The local MCP adapter does not expose:

- arbitrary shell execution
- git push
- deploy
- package publish
- secret reading
- source patching by default
- database migration
- external spend

`cambrian_harness_install` is blocked unless the tool call includes:

```json
{
  "confirm": true
}
```

Even then, the action installs Cambrian metadata and must not silently mutate project source code.

## Current Release Judgment

The local MCP path is ready to be part of external-user release proof when:

- `cambrian mcp verify` returns `verdict: GO`.
- The AI Company Golden Path records `installed cambrian-mcp entry point is operable: PASS`.
- The user can identify the target project `cwd`.
- The MCP client can start `cambrian-mcp` from the installed environment.

Remote MCP, OAuth, hosted MCP, registry-backed install, and marketplace distribution are later lanes.
