# Web Tools Slice Readiness

## Purpose

This document records the readiness of the sixth recommended commit slice from `COMMIT_SLICING_PLAN.md`.

Slice 6 covers Cambrian's optional static web hiring desk and local launch tooling. This slice is intentionally small and should only be included in the RC if the static web catalog and tooling are intentionally part of the local release surface.

## Slice

Suggested commit:

```text
feat(web): launch surface and local tooling
```

## Include

- `web/`
- `tools/generate_web_catalog.py`
- `tools/run_launch_demo.py`
- `tests/test_web_catalog.py`
- related web/tool slice readiness tests

## Do Not Include

- runtime source changes outside web/tool support
- installed wheel pack catalog fixes
- authority and auto runtime source files
- harness/workforce/skill builder source files
- pack/template/benchmark advanced source files
- launch or pilot docs unrelated to web/tool validation
- `.cambrian/` runtime evidence unless intentionally committing evidence
- private local project files
- `.env` or secret files

## Validation

### Web Catalog Generation

```bash
python tools/generate_web_catalog.py
```

Result:

```text
web catalog generated: C:\Users\user\Desktop\cambrain\cambrian\web
```

### Web Catalog Test Gate

```bash
python -m pytest -q tests/test_web_catalog.py
```

Initial result:

```text
2 failed, 4 passed
```

Root cause:

```text
Generated web copy omitted the expected job handoff/proof boundary phrase and used the benchmark proof command instead of the pack proof command.
```

Fix:

```text
Updated `tools/generate_web_catalog.py` so generated pages say the local runtime handles install, job handoff, validation, and proof, and the pack detail page shows `cambrian pack proof auth-bug-core`.
```

Final result:

```text
6 passed in 0.24s
```

## Review Notes

- The web catalog is the hiring desk, not the runtime.
- Local Cambrian performs install, job handoff, validation, and proof.
- Static web pages do not mutate `.cambrian/` runtime state.
- The web catalog makes no fake proof claims.
- The pack proof command is shown as local proof generation, not as public proof.
- This slice does not call provider APIs, deploy, access secrets, or apply source patches by itself.

## Slice Verdict

GO for review/staging as Slice 6, provided the staged diff matches only the intended web, tools, and related test files.
