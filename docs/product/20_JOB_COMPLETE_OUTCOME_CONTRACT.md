# Job Complete Outcome Contract

## Purpose

`cambrian job complete` records the human result after validation.
It closes the loop between validation evidence and evolution input.

Cambrian does not infer that a job succeeded by itself.
The human records the outcome explicitly.

## Command

```bash
cambrian job complete latest --outcome partial --notes "manual validation result" --json
```

Allowed outcomes:

- `success`
- `partial`
- `failed`
- `rejected`
- `needs_more_info`

## JSON Contract

The JSON payload includes:

```json
{
  "ok": true,
  "status": "recorded",
  "job_id": "job-...",
  "outcome": "partial",
  "outcome_ref": ".cambrian/jobs/job-.../outcome.yaml",
  "evidence_ref": ".cambrian/evidence/outcomes.yaml",
  "validation_evidence_ref": ".cambrian/evidence/validation/job-....yaml",
  "validation_contract_status": "manual_validation_required",
  "trust_gate_status": "manual_required",
  "validation_commands": ["npm test"],
  "checked_artifacts": [],
  "unchecked_items": [],
  "ready_for_evolution": true,
  "source_code_modified_by_cambrian": false
}
```

## Files

`job complete` writes:

```text
.cambrian/jobs/<job-id>/outcome.yaml
.cambrian/evidence/outcomes.yaml
```

If `job validate` already ran, the outcome links back to:

```text
.cambrian/evidence/validation/<job-id>.yaml
```

## Evolution Input

`cambrian evolve review` reads `.cambrian/evidence/outcomes.yaml`.
For that reason, the outcome record includes:

- job id
- human outcome
- notes
- validation evidence ref
- validation commands
- selected agents
- selected skills
- trust gate status
- unchecked items

## Safety Boundary

`job complete` records human judgement only.

It must not:

- apply patches
- modify project source code
- call an AI provider
- mark validation as passed without a human outcome
- edit preset files

The safety flag is:

```json
{
  "source_code_modified_by_cambrian": false
}
```

## Canonical Loop

```bash
cambrian job start "로그인 문제 봐줘" --json
cambrian job ingest latest ai_reply_patch_candidate.yaml --json
cambrian job validate latest --json
cambrian job complete latest --outcome partial --notes "manual validation result" --json
cambrian evolve review --recent 5 --json
```
