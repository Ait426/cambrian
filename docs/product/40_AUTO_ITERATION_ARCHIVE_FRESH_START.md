# Auto Iteration Archive Fresh Start Contract

## Purpose

`cambrian auto next --goal "..."` is the boundary between one completed auto-company iteration and the next product goal.

The command must archive the previous iteration evidence and start a clean active loop. A previous `GO` release gate is preserved as historical evidence, not reused as active evidence for the next goal.

## Start Conditions

`auto next` is allowed only when `auto report` returns one of these handoff states:

- `auto_done`
- `release_gate_go`

All other states are blocked. This prevents a waiting, failed, conditional, or NO-GO loop from being silently treated as complete.

## Archived Evidence

The iteration archive is written under:

```text
.cambrian/auto/iterations/<iteration-id>/
```

The archive can include:

- `plan.yaml`
- `report.yaml`
- `execution_log.yaml`
- `boardroom/`
- `decisions/`
- `tasks/`
- `results/`
- `cycles/`
- `external_results/`
- `release_gate/`
- `iteration.yaml`

`iteration.yaml` records the archive manifest, previous handoff status, previous release gate verdict, and fresh-start contract.

## Fresh Start Contract

After a successful `auto next`:

- active state is reset to `PRODUCT_CHARTER`
- active goal is the new goal
- active release gate evidence is cleared
- active tasks and results are cleared
- source code is not modified
- provider APIs are not called
- next command is `cambrian auto boardroom --json`

## Explicit Goal Requirement

The next loop must begin with a concrete product goal. Placeholder goals such as `Next product iteration` are blocked before any archive or fresh-start mutation happens.

The detailed rule is fixed in `41_EXPLICIT_NEXT_GOAL_CONTRACT.md`.

## Release Gate Rule

A `GO` release gate closes the previous iteration. It does not make the next iteration automatically releasable.

The previous release gate package is archived and referenced by the new iteration record. The new active loop must produce its own boardroom, plan, run evidence, quality result, and release gate package.

## Safety

- no old evidence is deleted
- no source files are changed
- no automatic release is performed
- `CONDITIONAL GO` and `NO-GO` cannot start a fresh iteration
- stale release gate packages cannot drive the new loop
