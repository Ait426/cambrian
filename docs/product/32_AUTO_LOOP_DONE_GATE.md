# Auto Loop Done Gate

## Purpose

Auto mode must stop when an external Codex/Claude result explicitly says the current bounded loop is complete.

Without this gate, a validated release-gate result can keep producing another release-gate task forever.

## Done Result Contract

Use the normal hardened result contract, with `status: done`:

```yaml
status: done
summary: "The current bounded loop is complete."
changed_files: []
tests:
  - command: "python -m pytest"
    status: passed
blockers: []
next_action: done
evidence:
  notes:
    - "completion evidence"
  artifacts: []
```

## Behavior

When `cambrian auto step ingest <task-ref> --result <file> --json` receives a done result:

- the task status becomes `done`
- `auto report` returns `decision_handoff.status=auto_done`
- `auto boardroom` recommends no next action
- `auto plan` creates `plan_kind=done` with no steps
- `auto cycle` creates no new task directive
- auto state becomes `DONE`

## Safety

- no source code is modified by the done gate
- no provider API is called
- no new task is created after done unless the user starts a new goal
- the evidence trail remains in `.cambrian/auto/results/` and `.cambrian/auto/execution_log.yaml`
