# Job Validate Trust Gate

## Purpose

`cambrian job validate` is the trust gate after an AI reply has been ingested.
It does not apply patches, does not call an AI provider, and does not mutate source code.

The command answers four questions:

- what Cambrian checked
- what remains unchecked
- whether manual validation is required
- where the validation evidence was recorded

## Command

```bash
cambrian job validate latest --json
```

Compatibility command:

```bash
cambrian pack job-validate latest --json
```

## JSON Contract

The JSON payload includes:

```json
{
  "ok": false,
  "validation_status": "not_ready",
  "validation_contract_status": "manual_validation_required",
  "trust_gate_status": "manual_required",
  "manual_validation_required": true,
  "validation_commands": ["npm test"],
  "checked_artifacts": [
    ".cambrian/packs/jobs/job-...",
    ".cambrian/bridge/packets/packet-...",
    ".cambrian/bridge/replies/reply-...",
    ".cambrian/bridge/patch_intents/patch-..."
  ],
  "unchecked_items": [
    "Cambrian did not execute validation commands automatically",
    "Human must run validation commands and record the outcome",
    "Patch proposal was not applied to source code"
  ],
  "evidence_ref": ".cambrian/evidence/validation/job-....yaml",
  "patch_applied": false,
  "source_code_modified": false,
  "ai_provider_called": false,
  "next_commands": [
    "npm test",
    "cambrian job complete <job-id> --outcome partial --notes \"manual validation result\""
  ]
}
```

## Statuses

- `validated`: Cambrian has a validated proposal and the trust gate passed.
- `manual_validation_required`: Cambrian has enough handoff artifacts, but the user must run the validation command and record the outcome.
- `blocked`: Required reply, patch intent, session, or validation data is missing.
- `not_ready`: The job cannot be trusted as complete yet.

## Evidence

Every validation attempt writes an evidence file under:

```text
.cambrian/evidence/validation/
```

The evidence file records the job id, checked artifacts, unchecked items, validation commands, trust gate status, warnings, errors, and safety flags.

## Safety Boundary

`job validate` must keep these flags false unless a later explicitly approved feature changes the contract:

```json
{
  "patch_applied": false,
  "source_code_modified": false,
  "ai_provider_called": false
}
```

If the project uses a custom harness or TypeScript/Jest lane, Cambrian may return `manual_validation_required`.
That is not a fake pass. It means Cambrian produced the validation handoff and evidence, and the human must run the listed command before recording the outcome.
