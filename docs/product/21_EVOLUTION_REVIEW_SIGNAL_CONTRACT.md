# Evolution Review Signal Contract

## Purpose

`cambrian evolve review` turns job outcome evidence into evolution signals.
It does not modify source code, does not apply evolution, and does not edit preset files.

The command reads:

```text
.cambrian/evidence/outcomes.yaml
```

When available, each outcome links back to:

```text
.cambrian/evidence/validation/<job-id>.yaml
```

## Command

```bash
cambrian evolve review --recent 5 --json
```

## Signal Contract

The JSON payload includes:

```json
{
  "ok": true,
  "reviewed_jobs": 1,
  "signals": {
    "repeated_missing_paths": [],
    "wrong_test_commands": [],
    "validation_commands_needing_manual_run": ["npm test"],
    "validation_evidence_refs": [".cambrian/evidence/validation/job-....yaml"],
    "trust_gate_status_counts": {
      "manual_required": 1
    },
    "validation_contract_statuses": ["manual_validation_required"],
    "manual_validation_required_jobs": ["job-..."],
    "unchecked_items": [
      "Patch proposal was not applied to source code"
    ],
    "outcome_counts": {
      "partial": 1
    },
    "evidence_gaps": [],
    "underused_agents": [],
    "skills_to_improve": ["trace-auth-token-flow"],
    "failure_terms": []
  },
  "next_command": "cambrian evolve propose --json"
}
```

## Meaning

- `validation_commands_needing_manual_run`: commands a human still had to run.
- `validation_evidence_refs`: validation trust gate evidence that supports the outcome.
- `trust_gate_status_counts`: how many jobs passed, blocked, or required manual validation.
- `manual_validation_required_jobs`: jobs that need better validation support or clearer workflow.
- `unchecked_items`: trust gaps that should become success criteria, skill checks, or harness rules.
- `evidence_gaps`: jobs completed without validation evidence.
- `skills_to_improve`: generated skills that should be refined by `evolve propose`.

## Proposal Handoff

`cambrian evolve propose` uses these signals to create local metadata changes such as:

- harness success criteria
- validation command updates
- agent responsibility updates
- skill procedure updates
- skill validation requirements
- known failure patterns

## Safety Boundary

`evolve review` and `evolve propose` are advisory.

They must not:

- modify project source code
- apply patches
- auto-approve evolution
- edit preset source files
- call an AI provider

Only `cambrian evolve apply <proposal-id> --confirm` may update local `.cambrian/` metadata.
