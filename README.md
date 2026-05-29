# Cambrian

Cambrian is an installable AI company runtime.
Every project becomes an AI company.

It installs a project-specific operating layer that helps Claude, Codex, Cursor, or another AI execution engine plan, build, validate, and improve work inside a local project without pretending that the AI can run unsupervised.

The current public release path is GitHub Release assets first: download the install kit bundle, install Cambrian into a target project, run the local gold path, and share only the generated share-safe receipts.

## Current Release Lane

Use the GitHub Release asset `cambrian-install-kit-release-bundle.zip` for real external users.

The release bundle contains the install kit ZIP, standalone verifier, standalone installer, gold-path runner, MCP connection guide, handoff JSON/Markdown, and send-ready receipt. The bundle is designed so another PC can install Cambrian without PyPI.

Do not treat `pip install cambrian` as available until the PyPI verification gate passes after an actual TestPyPI upload, TestPyPI install verification, final PyPI upload, and fresh `pip install cambrian` verification.

PyPI remains a deferred distribution lane. Its scripts and receipts are kept ready, but upload is not the default next task.

## Install From GitHub Release

1. Download `cambrian-install-kit-release-bundle.zip` from the GitHub Release assets.
2. Extract the ZIP.
3. Run the standalone installer from the extracted folder:

```bash
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project /path/to/project
```

On Windows:

```powershell
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project C:\path\to\project
```

Then run the gold path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project /path/to/project
```

Successful local validation writes share-safe receipts such as `cambrian_install_share_receipt.json`, `cambrian_gold_path_share_receipt.json`, and `mcp_operability_receipt.json`.

## Install From Local Wheel

Before PyPI release, developers can install a locally built wheel:

```bash
python -m pip install build
python -m build
python -m pip install dist/*.whl
```

After PyPI release, the intended one-line install is:

```bash
python -m pip install cambrian
```

## Quickstart

Core AI company flow:

```bash
cambrian doctor
cambrian project scan
cambrian harness interview start
cambrian harness interview answer --answers .cambrian/interview/answers.yaml
cambrian harness engineer design
cambrian harness engineer review
cambrian harness engineer dry-run "review the login failure"
cambrian workforce generate
cambrian skill generate
cambrian harness install --confirm
cambrian authority grant --mode full-authority
cambrian auto init --goal "Build this product"
cambrian auto boardroom
cambrian auto plan
cambrian auto run --max-steps 5
```

Compatibility launch-path commands remain available:

```bash
cambrian harness plan
cambrian agent dispatch "fix the login error"
```

`project scan` and `harness interview` collect the project goal, structure, forbidden actions, and validation standard. `harness engineer design/review/dry-run` checks whether the proposed harness is fit for the project. `authority` defines the execution boundary. `auto` records boardroom decisions, bounded plans, task directives, execution logs, and evidence.

V1 auto mode is supervised by default. It writes plans and evidence; it does not automatically patch source code, read secrets, deploy, charge payments, or bypass operator approval.

AI company bootstrap details are documented in [AI Company Bootstrap](docs/product/15_AI_COMPANY_BOOTSTRAP.md).

## Manual Job Mode

```bash
cambrian job start "investigate the login session expiry" --json
```

`job start` reads `.cambrian/workforce.yaml` and `.cambrian/skills/*.yaml`, selects relevant agents and skills, and writes a request packet for an AI execution engine. It does not call an AI provider or mutate source code by itself. AI replies are later ingested and validated through `job ingest` and `job validate`.

Job-mode contracts:

- [Job Start Runtime Contract](docs/product/16_JOB_START_RUNTIME_CONTRACT.md)
- [Codex / Claude Request Packet Contract](docs/product/17_CODEX_CLAUDE_REQUEST_PACKET.md)
- [AI Reply Ingest Contract](docs/product/18_AI_REPLY_INGEST_CONTRACT.md)
- [Job Validate Trust Gate](docs/product/19_JOB_VALIDATE_TRUST_GATE.md)
- [Job Complete Outcome Contract](docs/product/20_JOB_COMPLETE_OUTCOME_CONTRACT.md)
- [Evolution Review Signal Contract](docs/product/21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md)
- [Evolution Proposal Preview Contract](docs/product/22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md)
- [Evolution Apply Audit Contract](docs/product/23_EVOLUTION_APPLY_AUDIT_CONTRACT.md)
- [Evolution Rollback Contract](docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md)

## AI Company Pieces

- AI Company: the project-local operating organization Cambrian installs.
- Harness: the rules, architecture, validation, authority, and evidence layer.
- Workforce: generated roles for the current project.
- Agent: an AI worker role with a defined scope.
- Skill: a repeatable capability an agent can use.
- Boardroom: CEO/CTO/COO/PM style decision records.
- Authority Mode: the operator-defined permission boundary.
- Auto Mode: supervised planning and evidence loops.
- Claude / Codex: execution engines Cambrian can hand work to.
- Preset: an optional seed, not the default product.

## Validate A Canned AI Reply

```bash
cambrian demo create login-bug --out ./auth-bug-demo
cd ./auth-bug-demo
cambrian job ingest latest fixtures/ai_reply_patch_candidate.yaml
cambrian job validate latest
```

This validation path uses a prepared fixture and does not call an AI provider. `job validate` checks the handoff and evidence without automatically applying source changes.

## Evidence-Based Evolution

Cambrian treats human-recorded outcomes as the input to evolution. It can propose harness, workforce, and skill improvements from evidence; applying those proposals is explicit and local to `.cambrian/` metadata.

```bash
cambrian job complete latest --outcome partial --notes "test command is slow and refresh-token coverage is missing"
cambrian evolve review --recent 5
cambrian evolve propose
cambrian evolve apply <proposal-id> --confirm
```

`evolve apply` does not edit application source code, preset originals, or provider APIs.

## Authority And Auto Mode

Cambrian defaults to `proposal_only`. Auto mode records state, decisions, plans, execution proposals, and evidence only inside explicit authority boundaries.

```bash
cambrian authority status
cambrian authority grant --mode full-authority
cambrian auto init --goal "finish the installable RC"
cambrian auto boardroom
cambrian auto plan
cambrian auto run --max-steps 5
```

Auto-mode contracts:

- [Auto Task Directive Bridge](docs/product/25_AUTO_TASK_DIRECTIVE_BRIDGE.md)
- [Auto Step Result Intake](docs/product/26_AUTO_STEP_RESULT_INTAKE.md)
- [Auto Result Report Handoff](docs/product/27_AUTO_RESULT_REPORT_HANDOFF.md)
- [Auto Boardroom Report Review](docs/product/28_AUTO_BOARDROOM_REPORT_REVIEW.md)
- [Auto Plan From Handoff](docs/product/29_AUTO_PLAN_FROM_HANDOFF.md)
- [Auto Cycle Command](docs/product/30_AUTO_CYCLE_COMMAND.md)
- [Codex Result Contract Hardening](docs/product/31_CODEX_RESULT_CONTRACT_HARDENING.md)
- [Auto Loop Done Gate](docs/product/32_AUTO_LOOP_DONE_GATE.md)
- [Auto Next Iteration Gate](docs/product/33_AUTO_NEXT_ITERATION_GATE.md)
- [Role-Specific Auto Directives](docs/product/34_ROLE_SPECIFIC_AUTO_DIRECTIVES.md)
- [Role-Specific Result Compliance](docs/product/35_ROLE_SPECIFIC_RESULT_COMPLIANCE.md)
- [Auto Result Quality Scoring](docs/product/36_AUTO_RESULT_QUALITY_SCORING.md)
- [Quality-Aware Auto Plan Selection](docs/product/37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md)
- [Release Gate Evidence Package](docs/product/38_RELEASE_GATE_EVIDENCE_PACKAGE.md)
- [Release Gate Decision Loop](docs/product/39_RELEASE_GATE_DECISION_LOOP.md)
- [Auto Iteration Archive Fresh Start Contract](docs/product/40_AUTO_ITERATION_ARCHIVE_FRESH_START.md)
- [Explicit Next Goal Contract](docs/product/41_EXPLICIT_NEXT_GOAL_CONTRACT.md)

## Fresh Install RC Verification

```bash
python scripts/smoke_installed_wheel.py
```

This smoke test creates a fresh virtual environment, installs the wheel, and verifies the built-in harness preset path. Details are in [RC Install Guide](docs/release/RC_INSTALL_GUIDE.md).

## Portable Install Kit

```bash
python scripts/build_cambrian_install_kit.py
python scripts/prepare_cambrian_install_kit_release.py
python scripts/verify_cambrian_install_kit.py --install-check
python scripts/verify_cambrian_install_kit.py --install-check --offline --receipt dist/cambrian-install-kit-verification-receipt.json
python scripts/prepare_cambrian_install_kit_handoff.py
python scripts/check_cambrian_install_kit_send_ready.py
```

The kit lets another PC, Claude, or Codex install Cambrian from a ZIP into a project virtual environment and verify `cambrian --help`, `cambrian doctor --json`, and `cambrian company snapshot --help`. Verification receipts and handoffs omit absolute paths, secrets, and raw private project data. The standard is fixed in [Cambrian Install Kit](docs/release/CAMBRIAN_INSTALL_KIT.md).

## PyPI Release

This is a guarded future distribution lane, not the current external-user release path.
The current release path remains the portable install kit until TestPyPI upload, TestPyPI install verification, final PyPI upload, and fresh `pip install cambrian` verification all pass.

```bash
python scripts/prepare_pypi_release.py
python scripts/prepare_pypi_release.py --verify-receipt dist/pypi_release_receipt.json
python scripts/verify_pypi_install.py --wheel dist/pypi/cambrian-0.3.0-py3-none-any.whl --repository pypi --version 0.3.0 --receipt dist/pypi_local_wheel_install_receipt.json
python scripts/verify_pypi_install.py --verify-receipt dist/pypi_local_wheel_install_receipt.json
python scripts/prepare_pypi_release.py --preflight-upload testpypi
python scripts/prepare_pypi_release.py --preflight-upload testpypi --require-token-env
python scripts/prepare_pypi_release.py --verify-preflight-receipt dist/pypi_publish_preflight_receipt.json
python scripts/check_pypi_publish_ready.py --repository testpypi
python scripts/check_pypi_publish_ready.py --verify-ready dist/pypi-publish-ready-testpypi.json
python scripts/verify_pypi_install.py --repository testpypi --version 0.3.0 --receipt dist/pypi_testpypi_install_receipt.json
python scripts/verify_pypi_install.py --verify-receipt dist/pypi_testpypi_install_receipt.json
python scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json
python scripts/prepare_pypi_release.py --preflight-upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --require-token-env
python scripts/check_pypi_publish_ready.py --repository pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --require-token-env
```

After TestPyPI or PyPI upload, verify a clean install:

```bash
python scripts/verify_pypi_install.py --repository pypi --version 0.3.0
```

Upload safety: actual `--upload testpypi` and `--upload pypi` commands require `TWINE_USERNAME=__token__`, a local `TWINE_PASSWORD`, and a matching `pypi-publish-ready-*.json` receipt with verdict `GO`. Final PyPI also requires the same-version `dist/pypi_testpypi_install_receipt.json`. Details are in [PyPI Release](docs/release/PYPI_RELEASE.md).

## Local MCP Adapter

Cambrian includes a thin local MCP adapter so Claude, Codex, Cursor, or another MCP client can operate the local runtime through allowlisted tools instead of arbitrary shell commands.

```bash
cambrian-mcp
```

Equivalent module form:

```bash
python -m engine.project_mcp_server
```

The adapter exposes project scan, docs-to-interview inference, harness engineering, workforce/skill generation, job start/ingest/validate/complete, doctor, and company snapshot tools. Every tool requires an explicit `cwd`, returns command/evidence output, and does not allow git push, deploy, secret reading, arbitrary shell execution, or source patching by default.

MCP client config shape:

```json
{
  "mcpServers": {
    "cambrian": {
      "command": "cambrian-mcp",
      "args": []
    }
  }
}
```

Local operability receipt:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

Source-tree verifier:

```bash
python scripts/verify_mcp_operability.py --receipt dist/mcp_operability_receipt.json
```

The receipt checks initialize, tools/list, explicit `cwd`, safe project scan, install confirmation blocking, and the no-arbitrary-shell safety boundary.
External-user proof must use the installed `cambrian-mcp` entry point; source-tree module receipts are for development checks only.
The external-client connection guide is [MCP External Client Connect](docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md).

## AI Company Golden Path

```bash
python scripts/smoke_ai_company_gold_path.py
```

The smoke test verifies fresh wheel install, AI agent generation, skill generation/validation, harness-engineer evidence-based evolution propose/preview/apply, private-safe `company snapshot`, and the installed `cambrian-mcp` entry point. The standard is fixed in [AI Company Golden Path](docs/release/AI_COMPANY_GOLDEN_PATH.md).

The same golden path also verifies the freshly installed `cambrian-mcp` entry point and writes an MCP operability receipt, so MCP readiness is part of the official local release proof rather than a separate claim.

## Built-in preset seeds

Cambrian starts with custom harness first, preset optional seed.

`auth-bug-core` is a seed pack. local proof required.
The launch surface does not claim public outcome metrics.

## Built-in preset compatibility

Cambrian shows compatible preset options during the interview, but it does not install a preset automatically.
For Python + pytest auth projects, `auth-bug-core` can be used as a seed.
For TypeScript + Jest auth/API projects, `typescript-jest-auth-core` can be used as a seed.

Compatibility commands:

```bash
cambrian pack list
cambrian pack show auth-bug-core
cambrian install pack auth-bug-core
cambrian pack activate auth-bug-core
cambrian pack start "fix the login error"
```

This path is the compatibility/distribution surface. The product spine remains `AI company runtime, custom harness first, preset optional seed`.

## Product Run Docs

- First run runbook: [docs/launch/DEMO_RUNBOOK.md](docs/launch/DEMO_RUNBOOK.md)
- Public demo kit: [docs/launch/PUBLIC_DEMO_KIT.md](docs/launch/PUBLIC_DEMO_KIT.md)
- Public product assets: [docs/launch/DEMO_ASSETS.md](docs/launch/DEMO_ASSETS.md)
- RC checklist: [docs/release/RC_CHECKLIST.md](docs/release/RC_CHECKLIST.md)
- RC verification: [docs/release/RC_VERIFICATION.md](docs/release/RC_VERIFICATION.md)
- Dogfood runbook: [docs/release/DOGFOOD_RUNBOOK.md](docs/release/DOGFOOD_RUNBOOK.md)
- Pilot outreach kit: [docs/launch/PILOT_OUTREACH_KIT.md](docs/launch/PILOT_OUTREACH_KIT.md)
- Pilot learning board: [docs/launch/PILOT_LEARNING_BOARD.md](docs/launch/PILOT_LEARNING_BOARD.md)
- Launch golden path: [docs/launch/LAUNCH_GOLDEN_PATH.md](docs/launch/LAUNCH_GOLDEN_PATH.md)

Reproducible product run:

```bash
python tools/run_launch_demo.py
```

### Private pilot

For invite messages, interview guide, and feedback templates, see [Pilot Outreach Kit](docs/launch/PILOT_OUTREACH_KIT.md).

## What The Product Run Shows

- `project scan`: analyze the current project for AI company installation.
- `harness interview start`: create AI-mediated project questions.
- `harness engineer design`: draft project-specific harness, workforce, and skill architecture.
- `harness engineer review`: review the first harness design.
- `harness engineer dry-run`: simulate routing before a real job.
- `workforce generate`: create project-specific AI worker roles.
- `skill generate`: create project-specific skills.
- `authority grant`: define the AI company's execution boundary.
- `auto boardroom`: record CEO/CTO/COO/PM decision context.
- `auto plan`: convert decisions into bounded execution steps.
- `auto run`: write task directives and evidence inside a maximum step count.

Compatibility/history terms:

- `harness plan`: create a custom harness draft from answers.
- `harness install --confirm`: install the approved custom harness into `.cambrian/`.
- `agent dispatch`: recommend agents and work packets from the installed harness.
- `auth-bug-core`: a seed for Python + pytest + auth/login narrow bug fixes.
- Included workers: `bug-fix-agent`, `regression-test-agent`, `review-agent`.
- Included team/template/workset: `auth-bug-team`, `auth-bug-template`, `auth-bug-workset`.

## Safety Boundary

- Cambrian does not call AI provider APIs by itself in the local validation flows.
- Cambrian does not automatically patch source code, deploy cloud services, read secrets, or charge payments.
- `pack start` and `pack job-paste` do not mutate source code.
- Source changes require explicit apply/adoption flows.
- `cambrian pack job-apply <job-id>` previews by default.
- Real apply requires `cambrian pack job-apply <job-id> --confirm`.
- Adoption is recorded explicitly with `cambrian pack job-adopt <job-id> --accepted|--rejected|--skipped`.

## Web Pack Catalog MVP

The static web catalog is Cambrian's first control plane.

- `web/`
- `web/assets/catalog.json`
- `web/assets/auth-bug-core.cambrian-pack.yaml`
- `python tools/generate_web_catalog.py`
- `packs/catalog.yaml`

The web catalog is the hiring desk. Your local Cambrian runtime does the actual install, job handoff, validation, and proof. This page does not execute code or mutate `.cambrian/` state.

## Product Docs

Long-form product definitions and lifecycle references live outside the launch surface.

- [Alpha install](docs/ALPHA_INSTALL.md)
- [Product index](docs/product/00_INDEX.md)
- [AI company runtime](docs/product/13_AI_COMPANY_RUNTIME.md)
- [Packs and install](docs/product/06_PACKS_AND_INSTALL.md)
- [Execution loops](docs/product/07_EXECUTION_LOOPS.md)
- [Metrics and proof](docs/product/08_METRICS_AND_PROOF.md)
- [Harness engineering system](docs/product/12_HARNESS_ENGINEERING_SYSTEM.md)
- [Launch golden path](docs/launch/LAUNCH_GOLDEN_PATH.md)
- [Product walkthrough script](docs/launch/DEMO_SCRIPT.md)
- [First run runbook](docs/launch/DEMO_RUNBOOK.md)
- [Launch checklist](docs/launch/LAUNCH_CHECKLIST.md)

## Current Strongest Lane

Current strongest lane:

```text
Python + pytest + auth/login narrow bug fix
```

- Default team: `auth-bug-team`
- Default template: `auth-bug-template`
- Default workset: `auth-bug-workset`
- Outside this lane, Cambrian should warn instead of pretending confidence.

## Compatibility Reference

Cambrian is also described in the product docs as an AI workforce runtime, harness engineering runtime, and evidence-based evolution engine. The launch surface keeps those terms below the fold because the first message is simpler: install AI workers into the AI you already use.

The Web control plane is the hiring desk. The Local Cambrian runtime performs local install, job handoff, validation, and proof. Broader lifecycle commands stay below the launch path.

Security note: Mode B skill execution can use an optional Docker container sandbox. The container sandbox disables network access by default, mounts the skill read-only, applies memory/CPU/PID limits, and uses a read-only root filesystem when enabled. The launch run does not require the sandbox path, but the safety boundary remains documented for local execution.

## Implemented Reference Commands Outside The Launch Path

These commands are implemented references, not the first public install path.

```bash
cambrian pack next
cambrian install diff auth-bug-core
cambrian install update auth-bug-core
cambrian uninstall pack auth-bug-core
cambrian pack verify auth-bug-core
cambrian install verify
cambrian install verify auth-bug-core
cambrian pack draft auth-bug-core-local
cambrian pack build
cambrian pack publish-local
cambrian pack release-check --require-proof
cambrian pack web-sync
cambrian registry add local-web web/assets/catalog.json
cambrian registry sync local-web
cambrian pack search auth --registry local-web
cambrian install pack auth-bug-core --registry local-web
cambrian install plan cambrian/auth-bug-core@0.2.0 --registry official
cambrian install pack cambrian/auth-bug-core@0.2.0 --registry official --confirm-deps
```

Remote/web registry update is still planned for broader distribution. Static pull, manifest digest checks, no login, no payment, no cloud execution, and no source upload are the current boundary. Namespace, version, dependencies, `.cambrian/install/pack_lock.yaml`, `.cambrian/install/graphs/`, complex npm-style semver, dependency auto-update cascade, SHA-256, `--require-trusted`, and cryptographic signing are tracked in product docs.
