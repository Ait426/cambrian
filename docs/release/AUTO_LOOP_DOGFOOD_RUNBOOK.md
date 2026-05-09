# Auto Loop Dogfood Runbook

## Purpose

Cambrian auto loop dogfood verifies that a real project can move through:

```text
auto cycle -> external Codex/Claude task -> result file -> auto step ingest -> next auto cycle
```

This is not a demo gate. It must not use `examples/auth_bug_demo` as a successful target.

## Preconditions

- A real project target is available.
- The target is not `examples/auth_bug_demo`.
- Cambrian auto mode commands are available.
- The target can safely receive `.cambrian/` metadata.

## Target

Set the target with one of these:

```bash
set CAMBRIAN_AUTO_LOOP_TARGET=C:\path\to\real-project
python scripts/auto_loop_dogfood.py --target C:\path\to\real-project
```

If no target is provided, the script must return `BLOCKED`.

## First Cycle

Run:

```bash
python scripts/auto_loop_dogfood.py --target C:\path\to\real-project
```

Expected result without a result file:

```text
Result: WAITING_FOR_RESULT
```

This is acceptable. It means Cambrian created a Codex/Claude task directive and is waiting for the external execution result.

## Result Contract

The external result file must include the hardened contract:

```yaml
status: success
summary: "작업 결과 요약"
changed_files: []
tests:
  - command: "python -m pytest"
    status: "passed"
blockers: []
next_action: "cambrian auto cycle --max-steps 1 --json"
evidence:
  notes:
    - "검증 메모"
  artifacts: []
```

## Ingest And Continue

After Codex or Claude completes the directive, save the result and run:

```bash
python scripts/auto_loop_dogfood.py ^
  --target C:\path\to\real-project ^
  --task-ref .cambrian/auto/tasks/<task>.yaml ^
  --result C:\path\to\step_result.yaml
```

Expected result:

```text
Result: PASS
```

The script performs:

```bash
cambrian auto step ingest <task-ref> --result <result-file> --json
cambrian auto cycle --max-steps 1 --json
```

## Safety

- The script does not apply source patches.
- The script does not call an AI provider API.
- The script does not accept the demo project as a real project.
- The script records a sanitized report in `docs/release/AUTO_LOOP_DOGFOOD_REPORT.md`.
- The script may create or update `.cambrian/` metadata inside the target project.

## Verdicts

- `PASS`: result file was ingested and the next auto cycle ran.
- `WAITING_FOR_RESULT`: first cycle created an external task and no result file was provided.
- `BLOCKED`: no real target was provided or a demo target was used.
- `FAIL`: an auto command failed, no task reference was created, or result ingest failed.

## Report

The report is written to:

```text
docs/release/AUTO_LOOP_DOGFOOD_REPORT.md
```

Do not store private source excerpts, secrets, or raw local user paths in the report.
