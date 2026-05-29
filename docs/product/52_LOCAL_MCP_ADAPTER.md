# Local MCP Adapter

## Purpose

Cambrian needs a way for Claude, Codex, Cursor, and other MCP clients to operate the local Cambrian runtime without asking the user to copy every CLI command by hand.

The local MCP adapter is that thin connection layer.

It is not a cloud service.
It is not a remote registry.
It is not a marketplace.
It does not make Cambrian autonomous by itself.

It exposes Cambrian's local control plane to an AI tool through allowlisted commands.

## Product Boundary

The MCP adapter is a distribution and control surface.
It is not the product core.

The product core remains:

```text
project-local AI company runtime
-> harness
-> workforce
-> skills
-> authority
-> validation
-> evidence
-> outcome learning
```

MCP exists so an external AI can call that core safely.

## Entry Point

Installed package entry point:

```bash
cambrian-mcp
```

Equivalent module form:

```bash
python -m engine.project_mcp_server
```

The server uses stdio JSON-RPC and exposes MCP `tools/list` and `tools/call`.

## MCP Client Config Shape

Most MCP clients accept a server config shaped like this:

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

For source-tree verification before packaging, use the module form:

```json
{
  "mcpServers": {
    "cambrian": {
      "command": "python",
      "args": ["-m", "engine.project_mcp_server"],
      "cwd": "C:\\path\\to\\cambrian"
    }
  }
}
```

The exact config file location depends on the client.
The required Cambrian behavior does not: the client must start a stdio MCP server and call allowlisted tools with an explicit `cwd`.

## Operability Receipt

Run the installed verifier:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

For source-tree development, run the script wrapper:

```bash
python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json
```

The verifier proves the external AI-tool surface by checking:

```text
initialize works
tools/list exposes allowlisted Cambrian tools
tools/call blocks missing cwd
cambrian_project_scan works with explicit cwd
cambrian_harness_install is blocked unless confirm=true
tool safety boundary reports no arbitrary shell
```

The receipt is the first local proof that another AI workbench can operate Cambrian through MCP without gaining a raw shell.

For external-user release proof, the receipt must also show `server_command_mode: installed_entrypoint` and `installed_entrypoint_command: true`. A source-tree `python -m engine.project_mcp_server` receipt is useful for development, but it is not accepted as the returned first-recipient installed-wheel MCP proof.

This installed-entrypoint receipt is an official external-user release proof.
It is part of the AI Company Golden Path and release gate, while ordinary mission ticks may keep using the lighter mission/job trust gate unless the mission is MCP or release-readiness specific.

The concrete first-user connection path is fixed in `docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md`.

## Exposed Tools

Current tools:

```text
cambrian_doctor
cambrian_project_scan
cambrian_harness_interview_infer
cambrian_harness_engineer_design
cambrian_harness_engineer_review
cambrian_harness_engineer_dry_run
cambrian_workforce_generate
cambrian_skill_generate
cambrian_harness_install
cambrian_job_start
cambrian_job_ingest
cambrian_job_validate
cambrian_job_complete
cambrian_company_snapshot
```

These are intentionally close to Cambrian CLI commands.
The adapter does not expose arbitrary shell execution.

## Safety Contract

Every tool requires:

```text
cwd
```

The adapter returns:

```text
ok
status
command
cwd
requested_cwd
resolved_cwd
exit_code
stdout
stderr
stdout_json
next_recommended_command
safety_boundary
```

`cwd` and `resolved_cwd` are the actual execution directory after path resolution. `requested_cwd` preserves the caller's original tool argument, which matters when Codex or another client uses an ASCII junction/alias for a non-ASCII Windows project path.

The safety boundary records:

```text
shell: false
allowlisted_cambrian_cli_only: true
requires_explicit_cwd: true
source_code_patch_apply_default: false
git_push_allowed: false
secret_reading_allowed: false
```

`cambrian_harness_install` is blocked unless the caller passes:

```json
{"confirm": true}
```

This still installs only Cambrian metadata and must not auto-patch source code.

## External User Path

The external-user path becomes:

```text
1. User installs Cambrian.
2. User connects cambrian-mcp to Claude/Codex/Cursor.
3. AI calls cambrian_doctor.
4. AI calls cambrian_project_scan.
5. AI calls cambrian_harness_interview_infer.
6. AI reviews or asks for missing answers.
7. AI runs harness engineer design/review/dry-run.
8. User explicitly approves install when needed.
9. AI starts jobs through Cambrian job packets.
10. Validation and completion flow through evidence tools.
```

## Non-Goals

The local MCP adapter does not:

- read secrets intentionally
- run arbitrary shell commands
- git push
- deploy
- publish packages
- mutate source code by default
- call an AI provider by itself
- replace the local Cambrian runtime

## Current Product Judgment

MCP is now a practical requirement for making Cambrian usable by other people's AI tools.

But the correct first version is a thin local adapter, not a broad MCP platform.

The adapter should help prove:

```text
Can an external user's AI operate Cambrian's One Good Harness path safely?
```

If yes, MCP becomes part of the first-recipient proof surface.
