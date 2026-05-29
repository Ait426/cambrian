# Harness-First Reality Check

Decision date: 2026-05-21

## Problem Redefined

The conversation started from a fear:

```text
Is Cambrian becoming a Meta-Harness clone?
```

It moved through a wider question:

```text
What comes after prompt engineering, context engineering, and harness engineering?
```

But the final product reality is simpler:

```text
Cambrian does not yet deserve the next abstraction until it can make one real harness work.
```

The current problem is not evolution, marketplace, MCP, landing page, or research breadth.

The current problem is:

```text
Can Cambrian install one correct project-local harness and make the runtime actually obey it?
```

## Conversation Summary

### 1. Meta-Harness Anxiety Was Valid

Meta-Harness overlaps with Cambrian in this zone:

```text
harness candidates -> traces -> scores -> selection -> improvement
```

This overlap is real.
Cambrian should not deny it.

But Meta-Harness is mainly an optimizer for task-specific harness code.
Cambrian's intended product category is broader:

```text
project-local AI company runtime
```

The distinction must remain:

```text
Meta-Harness searches for better harnesses.
Cambrian governs whether a proposed improvement is allowed to become part of a real project's AI company.
```

### 2. Harness Is One Axis, Not The Whole Product

The discussion clarified that Cambrian should not collapse into a harness-only product.

AI quality is built from multiple axes:

```text
Prompt  -> instruction axis
Context -> information axis
Skill   -> capability axis
Harness -> execution-control axis
Eval    -> verification axis
Memory  -> experience axis
Policy  -> authority/legal/safety axis
Trace   -> evidence axis
Evolution -> improvement loop across all axes
```

Meta-Harness mainly touches:

```text
Harness + Trace + Eval + Optimization
```

Cambrian should eventually coordinate:

```text
Prompt + Context + Skill + Harness + Eval + Memory + Policy + Trace + Evolution
```

But that larger ambition is not an excuse to skip the first working loop.

### 3. Reliability And Assurance Are Real, But Not Enough

The alternative view was:

```text
After Harness Engineering comes Agent Reliability Engineering or AI Assurance Engineering.
```

This is directionally correct.

Once AI can act, the next market question becomes:

```text
Can we trust, audit, validate, and operate what it did?
```

However, for Cambrian, reliability and assurance are not separate decorations after the harness.
They are maturity levels of the harness itself.

A real harness must already include:

- trace
- validation
- proof
- authority
- rollback
- human approval where needed
- honest status

Therefore the strongest long-term framing is:

```text
Reliability is the door.
Assurance is the trust contract.
Evolution is the moat.
```

But near-term Cambrian must not jump to the moat before it has the door.

### 4. Research Was Useful Mainly Because It Removed Bad Paths

The research did not prove that Cambrian should copy any one paper or product.

It proved what Cambrian should not do:

- do not become a Meta-Harness clone
- do not call YAML generation a harness
- do not call prompt edits evolution
- do not build marketplace before runtime truth
- do not build MCP before the local control loop is real
- do not claim learning without evidence
- do not claim completion without validation

Research is still useful, but only when it sharpens the product boundary.
Research must not become a way to avoid implementing the core loop.

## Current Product Judgment

The current Cambrian priority is:

```text
One Good Harness
```

This means one real, narrow, closed loop:

```text
scan
-> design/review
-> install
-> status truth
-> job start
-> validate
-> complete
```

If this loop is not true, every higher-level phrase is premature.

## What Must Work Before Bigger Claims

Cambrian can discuss evidence ledger, learning, evolution, MCP, marketplace, or AI Company OS only after the following are true in a real project.

### Scan

- noisy folders such as archive, logs, temp, errors, dropzones do not distort identity.
- Korean partial substrings do not trigger wrong domains.
- codebase evidence is separated from documentation noise.
- important paths are checked as actual paths, not broken multiline strings.
- project domain is not guessed from weak keyword vibes.

### Interview / Answers

- answers.yaml parses both expected and user-natural forms.
- Korean change policy is normalized into enforceable policy.
- agent count and role structure are validated before install.
- custom roles are not overwritten by generic domain presets.

### Install

- install creates a coherent `.cambrian/` state.
- `project.yaml`, `profile.yaml`, `skills.yaml`, `agents.yaml`, harness files, validation files, and status readers agree.
- partial installs are detected and repaired or blocked.
- install cannot leave the project in a fake fitted state.

### Status Truth

- `cambrian status` tells the real installed state.
- custom harnesses appear as fitted only when required runtime surfaces exist.
- broken partial state is visible.
- active harness, agents, skills, authority, validation, and evidence gaps are shown.

### Job Start

- a job packet uses the active harness.
- selected agents, skills, authority, validation command, and proof requirements are injected.
- external AI receives a real work contract, not a generic prompt.

### Validate

- missing validation command blocks or marks partial.
- missing proof blocks success claims.
- test/log/diff evidence is attached to the job outcome.
- weak evidence does not pass as complete.

## Temporary Feature Freeze

Until One Good Harness works, these are postponed:

```text
full evolution engine
automatic harness mutation
skill marketplace
public agent marketplace
MCP expansion beyond core control-plane design
landing-page polish
generic AI research expansion
large observability platform
model training or RL
```

These ideas are not rejected.
They are sequenced after harness truth.

## The First Strong Technology

The later strong technology may become:

```text
Claim-Based Evidence Ledger
```

But not yet as a giant platform.

The first version should appear only as the minimum proof surface required by One Good Harness:

```text
job result claim
-> required evidence
-> validation verdict
-> status truth
```

Do not build a general evidence OS before the harness can enforce one job.

## Next Implementation Rule

The next engineering work should target the weakest link in this loop:

```text
scan -> design/review -> install -> status -> job start -> validate
```

For each change, ask:

```text
Does this make One Good Harness more real?
```

If no, defer it.

## Success Definition

Cambrian earns the right to talk about evolution only when a real external-style project can pass this gold path:

```text
1. Cambrian scans the project without domain hallucination.
2. Cambrian designs the correct custom harness.
3. Cambrian installs it without split-brain config.
4. `cambrian status` shows fitted truth.
5. `cambrian job start` emits the active harness contract.
6. An external AI can follow that contract.
7. `cambrian validate` rejects unproven completion.
8. `cambrian complete` records outcome evidence.
```

Until then, the honest product status is:

```text
Cambrian is building toward a real harness.
It is not yet a self-improving AI company OS.
```

## Final Decision

The big vision remains:

```text
AI Company OS
```

But the current execution target is smaller:

```text
One Good Harness.
```

This is not a downgrade.
It is the first non-fake step.

## 2026-05-21 One Good Harness AVF Proof

Target project:

```text
<private AVF project path redacted>
```

Result:

```text
One Good Harness is now partially proven on a real external-style project.
It is not yet promotable as a fully closed harness because reply-evidence compliance is still incomplete.
```

What was proven:

```text
scan -> design/review -> install -> status truth -> job start -> validate -> complete
```

Evidence:

```text
harness_id: custom-ave-ddmq-stage_pipeline
status: fitted custom_harness
policy: proposal_only
codebase_evidence_status: grounded
job_id: job-custom-ave-ddmq-stage_pipeline-20260520_165818_529089
validation_status: passed
validation_contract_status: commands_executed
trust_gate_status: verified_with_unchecked_risk
manual_outcome: partial
verdict: hold
```

Active agents installed for the AVF target:

```text
anthropic-api-error-analyst
ddmq-debugger
pytest-regression-guardian
risk-boundary-reviewer
stage-schema-validator
```

Validation evidence:

```text
python -m pytest tests/ -v -> 27 passed
python -m py_compile avf.py core/orchestrator.py core/ddmq.py core/schema_registry.py core/validators/schema_validator.py -> passed
```

The first validation attempt correctly failed because `aiohttp` was hidden inside a broken comment in the AVF `requirements.txt`, so pip had not installed it. The target requirements file was corrected to make `aiohttp>=3.9.0` a real dependency, requirements were installed, and the same validation commands then passed.

What improved in Cambrian:

```text
- Korean/natural-language change_policy now normalizes to proposal_only where appropriate.
- Supabase and hotel-style false positives were reduced.
- Weak domains stay as references instead of becoming harness identity.
- AVF custom roles now produce specific agents instead of generic or wrong-domain agents.
- Skill generation filters out orphan skills whose owner agent is not installed.
- harness show, status, and job start now prefer the active custom harness over legacy profile noise.
```

Remaining gap:

```text
validation commands passed, but promotion stayed blocked because:
- patch proposal was not applied to source code
- AI reply evidence compliance is incomplete:
  codebase_evidence_path_citation
  risk_boundary_check
  validation_command_selection
```

Product judgment:

```text
Cambrian now behaved like a real harness at the validation boundary.
It still needs a stricter AI reply evidence envelope before it can claim a fully closed One Good Harness.
```

Next implementation target:

```text
Make job replies carry a required evidence envelope:
1. cited code paths
2. risk boundary check
3. selected validation commands
4. patch-applied state
5. resulting verdict

Then make validate/complete promote only when that envelope is present and commands pass.
```

## 2026-05-21 One Good Harness AVF Closure

The AVF proof was rerun after the required evidence envelope became a product contract.

Closed job:

```text
job_id: job-custom-ave-ddmq-stage_pipeline-20260521_093725_283486
harness_id: custom-ave-ddmq-stage_pipeline
target: <private AVF project path redacted>
```

Required AI reply evidence envelope:

```text
codebase_evidence_path_citation -> satisfied
risk_boundary_check -> satisfied
validation_command_selection -> satisfied
patch_application_state -> satisfied
verdict_rationale -> satisfied
context_intent_resolution -> satisfied
project_discussion_role_check -> satisfied
```

Validation:

```text
python -m pytest tests/ -v -> 27 passed
python -m py_compile avf.py core/orchestrator.py core/ddmq.py core/schema_registry.py core/validators/schema_validator.py -> passed
```

Final verdict:

```text
validation_status: passed
validation_contract_status: commands_executed
trust_gate_status: verified
unchecked_items: []
manual_outcome: success
verdict: pass
verdict_reason: manual_outcome_success_with_verified_evidence
promotion_readiness: review_ready
```

Important distinction:

```text
patch_application_state records what the reply claims happened in the target work.
source_code_modified_by_cambrian remains false because Cambrian did not auto-apply code.
```

Product judgment:

```text
One Good Harness is now proven once on AVF.
This does not mean Cambrian is generally complete.
It means the first non-fake harness loop has one closed pass:
scan -> install -> status -> job packet -> reply envelope -> validate -> complete -> verdict.
```
