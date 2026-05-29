# Current Project Direction Audit - 2026-05-15

## Problem Redefined

The current problem is not "make `pip install cambrian` work."

The current problem is:

```text
Can an external user receive Cambrian, install it into another project, and use it to create an AI company workflow that can make agents, make/search/fuse skills, engineer a harness, evolve from evidence, and produce a private-safe company snapshot?
```

That is the gold path. Distribution channel is secondary until this path works for a real recipient.

## Fixed Direction

Cambrian is an installable AI Company OS:

```text
Every project becomes an AI company.
The company has roles, skills, harnesses, authority boundaries, proof, and evolution.
```

The long-term marketplace/platform direction is valid, but it is downstream of runtime and proof maturity. The current external release is not a public marketplace and not a sale-ready proof network.

## Current Release Lane

Current lane:

```text
portable install kit + external alpha bundle
```

Current artifacts:

- `dist/cambrian-install-kit-release-bundle.zip`
- `dist/cambrian-agent-platform-external-alpha.zip`
- install kit verification receipt
- external alpha verification receipt
- handoff, send-ready, pilot-ready, pilot dispatch, pilot review, pilot evidence, pilot decision, and pilot iteration artifacts

Current decision:

```text
Continue with install kit / external alpha delivery unless the operator explicitly reopens the PyPI lane.
PyPI upload is not the default next task.
```

## PyPI Boundary

PyPI is a prepared but deferred distribution lane.

Do not claim that `pip install cambrian` works until all of these pass after an actual upload:

1. TestPyPI upload
2. TestPyPI fresh install verification
3. final PyPI upload
4. fresh `pip install cambrian` verification

Until then, the real external-user delivery path is the install kit bundle.

## Capability Status

Cambrian can already demonstrate the four requested capabilities in the local installed-wheel gold path:

1. AI agent creation
2. skill creation, search, and fusion
3. harness engineering
4. evidence-based evolution

The verified command is:

```bash
python scripts/smoke_ai_company_gold_path.py
```

This is a local runtime proof, not a public marketplace proof.

## What Is Still Not Proven

The following are not proven and must not be claimed:

- public marketplace
- payment
- cloud execution
- public proof badge
- sale-ready agent listing
- multi-user success rate
- automatic source patching without explicit authority
- external recipient completion evidence

## Main Risk

The biggest risk is not missing backend code.

The biggest risk is recipient friction:

```text
Can someone who is not the builder receive one ZIP, run the correct command, understand the next step, avoid sharing private data, and produce a clean install/diagnostics receipt?
```

If the first recipient fails, the issue is likely packaging, instructions, or expectation-setting, not the AI Company OS core.

## PM Judgment

The current direction is correct if the next work stays narrow:

```text
one external recipient
one install bundle
one private-safe receipt
one pilot decision
```

The direction becomes weak if work jumps back to PyPI, public marketplace, payment, broad platform UI, or proof claims before the first recipient evidence exists.

## Next Work

The next execution priority is:

```text
Run the recipient path exactly as an external user would experience it.
```

Order:

1. Verify the latest install kit release bundle and external alpha bundle.
2. Run a fresh recipient-style install into a clean temporary project.
3. Confirm the generated share receipt has no absolute private paths, secrets, raw project data, or private user text.
4. Confirm the installed CLI exposes `cambrian --help`, `cambrian doctor --json`, and `cambrian company snapshot --help`.
5. Confirm the next action after install is clear: initialize or run the AI Company gold path depending on project state.
6. Record first-recipient dispatch with `READY_TO_SEND_ONE` before sending and `SENT_ONE_RECORDED` after sending, using only private hashes.
7. Tighten `START_HERE`, handoff, and install prompt only if the dry-run exposes friction.
8. Keep pilot-review at `WAITING_FOR_EVIDENCE` until a real recipient returns private-safe receipt/diagnostics/feedback hashes.

## Sharp Questions

Before doing anything else, only three questions matter:

1. Can the first external user install it without us explaining over chat?
2. Does the receipt prove installation without leaking private data?
3. Does the first user understand what Cambrian is supposed to do next?

## Conclusion

Cambrian is no longer in the "can this exist?" phase.

It is in the "can a real external user receive and successfully start it?" phase.

Therefore the next work must optimize first-recipient success, not add another future-facing layer.
