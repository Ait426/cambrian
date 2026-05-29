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
.cambrian/reports/latest_verdict.json
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
  "promotion_review_decision_ref": ".cambrian/evolution/review_decisions/latest_promotion_review.yaml",
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
    "evaluator_verdict_counts": {
      "hold": 1
    },
    "evaluator_verdict_refs": [".cambrian/reports/latest_verdict.json"],
    "promotion_review_gate": {
      "status": "blocked_by_hold",
      "auto_promote": false,
      "review_required": false,
      "pass_jobs": [],
      "hold_jobs": ["job-..."],
      "rollback_jobs": [],
      "reasons": ["manual_outcome_partial"]
    },
    "evidence_gaps": [],
    "underused_agents": [],
    "skills_to_improve": ["trace-auth-token-flow"],
    "failure_terms": [],
    "maturity_gate": {
      "status": "insufficient_data",
      "sample_size": 1,
      "apply_allowed": false,
      "next_step": "collect_more_job_evidence"
    }
  },
  "next_command": "cambrian evolve propose --json"
}
```

## Maturity Gate

Cambrian must not treat a small number of jobs as a stable pattern.

Evolution review records a `maturity_gate`:

```text
insufficient_data: fewer than 3 jobs. Evolution apply is blocked.
signal_candidate: 3 to 9 jobs. Signals may be recorded, but metadata evolution is blocked.
review_required: 10 to 19 jobs. Human-reviewed apply may proceed.
trusted_pattern: 20 or more jobs. Pattern is stronger, but auto apply is still forbidden.
```

`repeated_missing_paths` may only include paths that exist inside the project.
Cambrian process noise such as unchecked validation warnings must stay in `process_noise_items`; it must not become success criteria or known failure patterns.

## Decision Artifact

`evolve review` also records a local decision artifact:

```text
.cambrian/evolution/review_decisions/latest_promotion_review.yaml
```

The artifact records:

- latest `promotion_review_gate`
- reviewed job ids and evaluator verdict summaries
- `auto_promote: false`
- `proof_boundary.auto_apply: false`
- next human review step

If the evaluator verdict is `pass`, the decision is `needs_human_review`.
If the evaluator verdict is `hold`, the decision is `hold`.
If the evaluator verdict is `rollback`, the decision is `blocked`.

## Meaning

- `validation_commands_needing_manual_run`: commands a human still had to run.
- `validation_evidence_refs`: validation trust gate evidence that supports the outcome.
- `trust_gate_status_counts`: how many jobs passed, blocked, or required manual validation.
- `manual_validation_required_jobs`: jobs that need better validation support or clearer workflow.
- `unchecked_items`: trust gaps that should become success criteria, skill checks, or harness rules.
- `evaluator_verdict_counts`: latest evaluator verdict distribution from completed jobs.
- `evaluator_verdict_refs`: generated verdict reports that support the review.
- `promotion_review_gate`: promotion readiness signal. `pass` means review is required, not automatic promotion.
- `evidence_gaps`: jobs completed without validation evidence.
- `skills_to_improve`: generated skills that should be refined by `evolve propose`.
- `maturity_gate`: whether there is enough job evidence to apply metadata evolution.

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

Even if `promotion_review_gate.status` is `review_required`, Cambrian must not promote automatically.
The gate only says a human review can begin.

They must not:

- modify project source code
- apply patches
- auto-approve evolution
- auto-promote a passing evaluator verdict
- edit preset source files
- call an AI provider

Only `cambrian evolve apply <proposal-id> --confirm` may update local `.cambrian/` metadata.
The promotion review decision artifact by itself must never update `.cambrian/` defaults.
