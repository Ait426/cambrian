# Auto Next Iteration Gate

## Purpose

`cambrian auto next --goal "..."` starts a new bounded auto loop after the previous loop reached `DONE` or after a release gate returned `GO`.

The command preserves previous evidence, then clears the active auto task/result surface so the old `done` result does not block the new goal.

## Command

```bash
cambrian auto next --goal "Build the next bounded product step" --json
```

## Behavior

- requires an existing `.cambrian/auto/state.yaml`
- requires the previous handoff to be `auto_done` or `release_gate_go`
- archives the active auto files under `.cambrian/auto/iterations/<iteration-id>/`
- preserves previous evidence, report, tasks, results, cycles, external result files, and release gate packages
- writes a fresh `PRODUCT_CHARTER` state for the new goal
- clears active release gate evidence so the new loop does not reuse the old GO package
- leaves source code unchanged
- does not call a provider API
- next command is `cambrian auto boardroom --json`

## Why It Exists

After a `status: done` result, `auto report` returns `auto_done`.

After a release gate returns `GO`, `auto report` returns `release_gate_go`.

That is correct for the finished loop, but a new product goal needs a clean active auto surface.

The old evidence must remain available, while the new loop should start from:

```text
PRODUCT_CHARTER -> BOARDROOM_PLANNING -> EXECUTION_PLAN -> IMPLEMENTATION
```

## Safety

- no source code is modified
- no old evidence is deleted
- archived files can be inspected in `.cambrian/auto/iterations/`
- release gate packages are archived with the completed iteration
- the new active loop starts without `.cambrian/auto/release_gate/`
- the command does not create a new task by itself
