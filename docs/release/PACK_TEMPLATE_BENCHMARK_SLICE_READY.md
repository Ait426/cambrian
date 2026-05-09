# Pack Template Benchmark Slice Readiness

## Purpose

This document records the readiness of the fourth recommended commit slice from `COMMIT_SLICING_PLAN.md`.

Slice 4 covers Cambrian's advanced pack, template, and benchmark surfaces: pack lifecycle, proof, release, registry, rollout, trust, template bootstrap, canary, challenge, qualification, rollback, library policy, benchmark replay, comparison, and proof behavior.

## Slice

Suggested commit:

```text
feat(pack): pack template qualification surfaces
```

## Include

- `engine/project_pack_*` advanced pack lifecycle, proof, release, registry, rollout, trust, usage, and vNext modules
- `engine/project_template_*` bootstrap, canary, challenge, qualification, rollback, recommendation, transfer, and library policy modules
- `engine/project_benchmark*` comparison, proof, replay, workset replay, and benchmark modules
- related `tests/test_pack_*.py`
- related `tests/test_template_*.py`
- related `tests/test_benchmark*.py`

## Do Not Include

- installed wheel pack catalog fixes
- authority and auto runtime source files
- conversational harness/workforce/skill builder source files
- launch or pilot copy unrelated to pack/template/benchmark surfaces
- `.cambrian/` runtime evidence unless intentionally committing evidence
- private local project files
- `.env` or secret files

## Validation

The broad Slice 4 gate is long in this local environment, so it is validated with split-run evidence instead of one opaque timeout-prone command.

### Pack Test Gate

Initial all-pack command:

```bash
python -m pytest -q tests/test_pack_*.py
```

Result:

```text
Timeout before completion; split-run validation used.
```

Split results:

```text
Pack chunk 1: 74 passed in 49.69s
Pack chunk 2a: 21 passed in 63.32s
Pack chunk 2b: 21 passed in 41.26s
Pack chunk 2c: 21 passed in 39.26s
Pack chunk 2d: 22 passed in 30.07s
Pack chunk 3: 92 passed in 79.86s
```

Pack total:

```text
251 passed
```

### Template Test Gate

Split results:

```text
Template chunk 1: 62 passed in 202.98s
Template chunk 2 all-at-once: Timeout before completion; smaller split-run validation used.
Template chunk 2a: 24 passed in 69.60s
Template chunk 2b: 17 passed in 54.34s
Template chunk 2c: 17 passed in 65.86s
Template chunk 2d: 9 passed in 100.97s
Template chunk 3: 56 passed in 192.37s
```

Template total:

```text
185 passed
```

### Benchmark Test Gate

```bash
python -m pytest -q tests/test_benchmark*.py
```

Result:

```text
47 passed in 41.65s
```

### Slice Total

```text
483 passed
```

## Review Notes

- Pack/template/benchmark features are advanced surfaces and should not become the default launch path.
- Compatibility, qualification, rollout, registry, and canary behavior are scoped to this slice.
- Benchmark proof and replay features are local validation/evidence surfaces, not fake public proof claims.
- This slice does not call provider APIs, deploy, access secrets, or apply source patches by itself.
- Broad timeout risk is handled through split-run validation evidence.

## Slice Verdict

GO for review/staging as Slice 4, provided the staged diff matches only the intended pack, template, benchmark, and related test files.
