# Comprehensive Release Test Report - 2026-05-15

## Verdict

Cambrian is ready for external-user delivery through the install kit and external alpha bundle.

PyPI/TestPyPI publication is not complete because no upload token was available in the local environment. The package artifacts, local wheel install, publish-ready handoffs, and guardrails are verified.

Release direction lock: continue with install kit / external alpha delivery unless the operator explicitly reopens the PyPI lane. PyPI upload is not the default next task.

## Code And Runtime Gates

- `python -m compileall -q engine scripts tools`: PASS
- Focus gate 1: `60 passed`
- Focus gate 2: `93 passed`
- Focus gate 3: `106 passed`
- Launch and pilot surface: `80 passed`
- Release readiness meta gates: `63 passed`
- External alpha focused tests: `134 passed`
- PyPI release tests: `21 passed`

## Installable Product Gates

- `python scripts/smoke_installed_wheel.py`: PASS
- `python scripts/smoke_ai_company_gold_path.py`: PASS
- Fresh installed wheel can create agents, generate/search/fuse skills, run harness engineer design/review/dry-run, start/complete a job, run evolution propose/preview/apply, and generate a private-safe company snapshot.

## PyPI Gate

- Release receipt: `dist/pypi_release_receipt.json` verified.
- Local wheel install receipt: `dist/pypi_local_wheel_install_receipt.json` verified.
- Package: `cambrian==0.3.0`
- Wheel sha256: `f4be459c7184989c41c0ba1cc01faf7a0d3ed13882285790a141df5d0dc537c2`
- sdist sha256: `60bb3e6c9d52ecef1f414b32396d24414b41d2461c427ada37a61683dc81f46d`
- TestPyPI publish-ready verdict: `WAITING_FOR_TOKEN`
- PyPI publish-ready verdict: `BLOCKED`

PyPI remains blocked until a same-version TestPyPI install receipt exists and the local PyPI token environment is provided. No token was recorded in any receipt.

## Install Kit Gate

- `python scripts/prepare_cambrian_install_kit_release.py`: GO
- Install kit ZIP: `dist/cambrian-install-kit-0.3.0.zip`
- Install kit sha256: `92816f834f181912f710918e2821e47154739c3cb88b8660ad33c0242add37c4`
- Release bundle: `dist/cambrian-install-kit-release-bundle.zip`
- Release bundle sha256: `2292c17b235db55a127cd58892f918846820df1d4f63bc0b9f1c171ec75e14dd`
- Verified: release receipt, release bundle, offline install receipt, handoff, send-ready, dispatch-record, recipient-checkpoint.
- Handoff/send-ready/dispatch copy-paste now requires the bundle gold path runner and `cambrian_gold_path_share_receipt.json`; external completion no longer stops at install-only proof.
- `START_HERE_CAMBRIAN_INSTALL_KIT.md` now marks the AI Company Gold Path as required, not optional, so the first recipient path is aligned with the architecture-level 1/2/3/4 capability promise.
- `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md` is now included at the release bundle root, so Claude/Codex can be handed the extracted bundle without first digging into the inner install kit ZIP.
- Recipient-style extracted bundle required gold path smoke: PASS. A freshly extracted release bundle installed Cambrian into a clean project and generated both share-safe install and gold path receipts.
- `scripts/smoke_cambrian_install_kit_release_bundle.py`: PASS. This repeatable gate writes `dist/cambrian-install-kit-release-bundle-smoke-receipt.json` and verifies it standalone.
- `scripts/check_cambrian_install_kit_dispatch_record.py` now requires the release bundle smoke receipt before `READY_TO_SEND_ONE`, so manual dispatch cannot bypass the required gold path gate.
- Dispatch-record now consumes an existing verified send-ready when present instead of regenerating it, keeping the release bundle chain and dispatch evidence on the same prepared artifact set.
- Recipient-style bundle install dry run: PASS.
- Bundle gold path e2e: PASS. The extracted release bundle installed Cambrian offline and verified AI agent creation, skill generation/search/fusion, harness engineering, evolution propose/preview/apply, and private-safe company snapshot generation through `cambrian_gold_path_share_receipt.json`.
- Local install receipt is marked `safe_to_share: false`; share-safe install receipt `cambrian_install_share_receipt.json` is generated with `safe_to_share: true` and `absolute_paths_included: false`.
- Install kit dispatch-record gate: `READY_TO_SEND_ONE`; standalone verification PASS.
- Install kit recipient-checkpoint gate: `WAITING_FOR_RECIPIENT`; standalone verification PASS.
- Install kit recipient-checkpoint can close `RECIPIENT_GOLD_PATH_CONFIRMED` from `cambrian_install_share_receipt.json` plus `cambrian_gold_path_share_receipt.json` without storing raw acknowledgement text, local receipt paths, private project data, proof claims, or sale-ready claims. Windows UTF-8 BOM receipts are accepted.
- Install kit focused tests after release bundle prompt and smoke gate addition: `33 passed`.

## External Alpha Gate

- `python scripts/verify_platform_alpha.py`: PASS
- `python scripts/build_external_alpha_release.py`: PASS
- `python scripts/verify_external_alpha_release.py --receipt dist/external_alpha_release_verification_receipt.json`: PASS
- `python scripts/check_external_alpha_pilot_iteration.py`: PASS
- External alpha ZIP sha256 after send-ready receipt hash chain, browser smoke wrapper verifier gate, stable receipt hash, receipt verifier browser-wrapper rejection, recipient-style release bundle smoke gate, dispatch-record smoke gate, final send-chain audit inclusion, private pilot workspace scaffold, private workspace rehearsal receipt, first-recipient send workspace, first-recipient pre-send preflight gate, private-note channel/release-hash hardening, shared operator note template helper, operator note auto-seeding, unresolved `<private-send-channel>` placeholder rejection, source-to-release manifest freshness gate, first-recipient manual send GO/NO-GO gate, first-recipient full pre-send sequence, first-recipient operator status, controlled final-audit failed-check surfacing, share-safe operator safe checklist packaged into the ZIP, first-recipient post-send sequence, post-send rerun after SENT_ONE_RECORDED, receipt-only post-send verification, manual send GO rehearsal, manual-send rehearsal operator-status-ready proof, strict manual-send rehearsal required-check regression gate, final send-chain audit enforcement of current manual-send GO rehearsal, required-preflight dispatch-record gate, required-preflight recipient-checkpoint chain gate, operator send bypass audit, cycle-free post-send preflight rehearsal contract, operator packet enforcement of post-send real-preflight/template evidence, final send-chain audit recalculation of operator packet self-checks, stale self-check rejection, private-workspace-dir full pilot learning shortcut, rehearsal shortcut evidence, readable ASCII first-recipient send message, ASCII/mojibake regression gate, operator dispatch packet inclusion, post-send checkpoint rehearsal, pilot learning loop rehearsal, safe pre-send blocking summary, safe post-send ack summary, private README/status refresh without overwriting raw private files, operator status final-chain-depth summary, operator status CLI open-gates/runbook/send-state summary, operator launch snapshot, stale first-recipient workspace/runbook guard, stale pre-send/manual-send GO receipt guard, missing-final-rehearsal operator next-action guard, direct-user Quickstart at the ZIP root, Quickstart-first copy-paste/send gate enforcement, two-edit private runbook, pre-send sequence manual-send rehearsal refresh, one-recipient non-empty-line preflight guard, CONFIRMED-only post-send ACK guard, and refreshed pilot chain: `6a2914c8adf5f6f6f35ebc0c4728c8ff82dc1f80d2497f660fc678c244decc90`
- External alpha ZIP file count: `87`.
- `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md` is now included at the external alpha ZIP root, so Codex/Claude can be handed the extracted bundle without relying on a chat explanation.
- External alpha prompt surface focused tests: `21 passed`.
- External alpha prompt policy focused tests: `37 passed`.
- External alpha controlled pilot learning focused tests: `19 passed`.
- External alpha learning/release focused tests: `40 passed`.
- External alpha Builder Golden Path recipient receipt focused tests: `35 passed`.
- External alpha Builder Golden Path + release docs focused tests: `53 passed`.
- Platform gold path receipt surface + external alpha release docs focused tests: `41 passed`.
- Platform gold path receipt runtime contract: `3 passed`. This executes the actual receipt functions extracted from `web/platform/index.html` in Node and verifies pass/block behavior, recipient-checkpoint acceptance, and controlled pilot iteration without browser automation.
- Platform-generated receipt -> recipient checkpoint/pilot-review/evidence/decision/iteration focused tests: `38 passed`.
- Platform gold path receipt runtime + external alpha release docs focused tests: `46 passed`.
- Send-ready receipt hash chain + platform/external alpha focused tests: `50 passed`.
- External alpha final send-chain audit tests: `3 passed`.
- External alpha release bundle smoke tests: `4 passed`.
- Send-chain audit focused tests: `20 passed`.
- Final send-chain audit + platform/release docs focused tests: `52 passed`.
- Dispatch-record smoke gate + final smoke/audit/platform focused tests: `68 passed`.
- Operator dispatch packet + final release/platform focused tests: `71 passed`.
- Post-send checkpoint rehearsal + final release/platform focused tests: `74 passed`.
- Private pilot workspace + pilot learning loop rehearsal + final release/platform focused tests: `80 passed`.
- Private workspace rehearsal + final external alpha focused tests: `84 passed`.
- First-recipient send workspace + final external alpha focused tests: `88 passed`.
- First-recipient operator note seed/placeholder focused tests: send workspace `6 passed`, preflight `7 passed`, operator status `10 passed`.
- First-recipient pre-send preflight gate + connected release/operator workspace tests: `30 passed`.
- Dispatch-record required-preflight + release/operator workspace focused tests: `41 passed`.
- Operator send bypass audit + final send-chain focused tests: `10 passed`.
- First-recipient manual send GO/NO-GO + operator/release focused tests: `26 passed`.
- First-recipient full pre-send sequence + operator/release/install/diagnostics focused tests: `29 passed`.
- Manual send GO rehearsal + release/install/diagnostics focused tests: `26 passed`.
- First-recipient private-note channel/release-hash hardening and safe blocked-output focused tests: `62 passed`.
- Private-workspace-dir full pilot learning shortcut + rehearsal shortcut evidence + final external alpha focused tests: `134 passed`.
- Readable ASCII first-recipient send message focused tests: `28 passed`.
- ASCII/mojibake regression gate focused tests: `8 passed`.
- Current shared-template/preflight/post-send focused tests: `14 passed`.
- Current send-chain audit + operator packet focused tests after final audit self-check recalculation: `9 passed`.
- Current operator packet + post-send checkpoint focused tests after operator packet evidence enforcement: `6 passed`.
- Current operator packet + first-recipient pre-send sequence focused tests after final rehearsal gate/no-stale-next-action hardening: `10 passed`.
- Direct-user quickstart/install surface/diagnostics focused tests: `8 passed`.
- External alpha release bundle focused tests after quickstart inclusion: `14 passed`.
- Current release bundle/install surface/diagnostics focused tests: `22 passed`.
- Quickstart-first send message/gate focused tests: `36 passed`.
- First-recipient private runbook/pre-send sequence focused tests: `38 passed`.
- One-recipient private-line and ACK guard focused tests: preflight `6 passed`, pre-send sequence `8 passed`, post-send sequence `8 passed`, operator status `12 passed`.
- `python scripts/smoke_external_alpha_release_bundle.py`: PASS, recipient-style extracted bundle smoke receipt body sha256 `326735713171f827a0c84a97b6c76d5a4e74459ce1efa519504c3466783d9b24`.
- `python scripts/audit_external_alpha_send_chain.py`: PASS, `READY_TO_SEND_ONE`, 12 artifact links, release receipt body sha256 `8de81a1fd6bf9e9d38be508f0efc3f57cd5f37b0ecd120609b077f49ec1f72be`, bundle smoke receipt body sha256 `326735713171f827a0c84a97b6c76d5a4e74459ce1efa519504c3466783d9b24`, operator bypass audit body sha256 `cd7749771a2f80709dbd999c6b5b7d4666b9f3cb625541dfe1993b785c2f2782`, manual-send GO rehearsal body sha256 `8924ad2e8437ea041146e0d2f10c8a8e68c3b8e43285dae0e68ba80b6dad29bc`, and source-to-release manifest freshness plus recalculated operator packet self-check/post-send evidence checks all true.
- `python scripts/audit_external_alpha_operator_send_bypass.py`: PASS, `NO_OPERATOR_PREFLIGHT_BYPASS`, operator send bypass audit body sha256 `cd7749771a2f80709dbd999c6b5b7d4666b9f3cb625541dfe1993b785c2f2782`.
- `python scripts/smoke_external_alpha_private_pilot_workspace.py`: PASS, `REHEARSAL_PASS`, current ZIP hash matched, `real_private_workspace=false`, `real_private_data_entered=false`, receipt body sha256 `527b7dfdf1e43a64eaddcba53b0eb0a267737716a00b7c132c908108f1b5d14f`.
- `python scripts/smoke_external_alpha_manual_send_go_rehearsal.py`: PASS, `REHEARSAL_PASS`, current ZIP hash matched, `real_manual_send=false`, `synthetic_private_values_used=true`, `operator_status_verdict=READY_TO_MANUALLY_SEND_ONE`, receipt body sha256 `8924ad2e8437ea041146e0d2f10c8a8e68c3b8e43285dae0e68ba80b6dad29bc`.
- `python scripts/prepare_external_alpha_first_recipient_send_workspace.py`: PASS, `FIRST_RECIPIENT_SEND_WORKSPACE_READY`, private runbook created under ignored `.cambrian` workspace, operator status command included, generated README refreshed without overwriting raw private files, operator note private file auto-seeded when still scaffold/template text, required-preflight dispatch-record command included, two private edits/no CLI-argument warning included, one non-empty recipient line required, ACK storage narrowed to exactly one `CONFIRMED` line, `--private-workspace-dir` shortcut locked through pilot learning, share-safe receipt body sha256 `fdce43031140249ffc315a5113e33e5c2fd5d599c169353feab7c21e7b09e217`.
- `python scripts/check_external_alpha_first_recipient_send_preflight.py`: expected BLOCKED on the default workspace until `recipient-private.txt` is real, contains exactly one non-empty recipient line, and `operator-dispatch-note-private.md` replaces `<private-send-channel>` with the real private send channel plus the exact release ZIP sha256, share-safe blocked receipt body sha256 `61eda89168a21b63c326f4f8fce841826848980380c773f3eeb29f65f3a13f35`.
- `python scripts/check_external_alpha_first_recipient_manual_send_go.py`: expected BLOCKED on the default workspace until the private preflight receipt is ready, share-safe blocked receipt body sha256 `6e4ced002579ebf9b7156a23f9be0a80d527cb9f96f677d3bc9b374da9f8601d`.
- `python scripts/check_external_alpha_first_recipient_pre_send_sequence.py`: expected BLOCKED on the default workspace until the real private recipient is exactly one non-empty line and the private operator note replaces `<private-send-channel>` with the send channel plus exact release ZIP sha256, safely refreshes the synthetic manual-send GO rehearsal before final audit, names only safe private file statuses in output including `exactly_one_recipient=false`, share-safe blocked receipt body sha256 `e0e86a8fa60b3a1015449f83ec4fa1b949344f82f6913efa9e0b1ec0baf8f321`.
- `python scripts/check_external_alpha_first_recipient_operator_status.py`: PASS, `FILL_PRIVATE_FIELDS`, prints `send   : BLOCKED`, safe private status, open gates, and the local private runbook path directly in the CLI, reports final send-chain depth `12`, includes `operator_launch_snapshot` with `manual_send_allowed=false` and the three open private gates, blocks stale first-recipient workspace receipts as `PREPARE_PRIVATE_WORKSPACE` before private-field entry, blocks stale pre-send/manual-send GO receipts from opening `READY_TO_MANUALLY_SEND_ONE`, treats non-`CONFIRMED` ACK text as `unconfirmed`, and safely prints controlled final audit failed check ids during `CHECK_RELEASE_CHAIN`, share-safe receipt body sha256 `d8bcfcf119915477b4c60ba0fa128fa3a01c6129d2a1c68f7a107e2f062951f7`.
- `python scripts/prepare_external_alpha_operator_dispatch_packet.py`: PASS, `READY_TO_SEND_ONE`, operator dispatch packet body sha256 `e9bd3d473f3c2d73d75ac7783e92397f04a9504aae55ceebb5411ec852c98e72`, and now requires post-send rehearsal evidence for `preflight_generated_by_real_gate=true`, `operator_note_template_preflight_contract=true`, Quickstart-first copy-paste text, and the two-edit private runbook path.
- `python scripts/smoke_external_alpha_post_send_checkpoint.py`: PASS, `REHEARSAL_PASS`, current ZIP hash matched, real preflight engine exercised through a cycle-free send contract, standard private workspace filenames and standard post-send sequence verified, post-send reruns after `SENT_ONE_RECORDED` only record ACK/gold-path confirmation after exactly one `CONFIRMED` line, receipt-only verification no longer requires `--sent-at-utc`, receipt body sha256 `f0755e01919b2e399bf124ef0f0b9c63d3abdc1fa2019840101a68bf4e42595d`.
- `python scripts/smoke_external_alpha_pilot_learning_loop.py`: PASS, `REHEARSAL_PASS`, current ZIP hash matched, `real_pilot_evidence=false`, `PATCH_BEFORE_NEXT`, standard private workspace filenames and `--private-workspace-dir` shortcut verified, receipt body sha256 `9b1fd11cf3ad8b3b54a9d4f64596ac8934391b9b4c3b6167f265e2e2936cb678`.
- Platform alpha verifier after gold path receipt surface: PASS.
- Browser smoke with temporary Playwright deps in `C:\tmp\cambrian-playwright-deps`: `28 passed`.
- Browser single golden path smoke: `1 passed`.
- Browser smoke wrapper `scripts/verify_agent_platform_browser_flow.py`: `28 passed`.
- Browser single golden path wrapper: `1 passed`.
- Release verifier browser wrapper help gate: PASS.
- Release receipt body hash stability across regenerated timestamps: PASS.
- Release receipt verifier rejects broken `browser_wrapper` evidence: PASS.
- Send-ready verifies the handoff receipt body hash matches the current receipt body hash: PASS.
- Final non-mutating send-chain audit verifies current `dist` without rewriting artifacts: PASS.
- Operator dispatch packet verifies current `dist` without sending anything and now names the pre-send private workspace gate: PASS.
- Private workspace rehearsal verifies current `dist` can scaffold a share-safe operator-only workspace receipt in a temporary directory without claiming real private data: PASS.
- First-recipient send workspace prepares the actual ignored private workspace and local-only send runbook while keeping the receipt share-safe and including the pre-send preflight command plus required-preflight dispatch-record command: PASS.
- First-recipient pre-send preflight blocks the default workspace while required private placeholders remain, and only writes a share-safe blocked receipt: PASS.
- Dispatch-record required-preflight gate blocks `SENT_ONE_RECORDED` on the standard private workspace when the ready preflight receipt is missing or blocked: PASS.
- Dispatch-record, recipient-checkpoint, pilot-review, pilot-evidence, pilot-decision, and pilot-iteration now accept `--private-workspace-dir <private-workspace-dir>` and reject scaffold placeholders before recording private hashes: PASS.
- Post-send checkpoint rehearsal verifies current `dist` can close private-hash dispatch and recipient checkpoint flow without claiming real recipient evidence: PASS.
- Pilot learning loop rehearsal verifies current `dist` can turn private feedback/intake hashes into controlled tags, `FIX_BEFORE_NEXT`, and `PATCH_BEFORE_NEXT` without claiming real pilot evidence: PASS.
- Send-ready verdict: `GO`
- Pilot-ready verdict: `GO`
- Pilot-review verdict: `WAITING_FOR_EVIDENCE`
- Pilot-evidence verdict: `NO_DECISION`
- Pilot-decision verdict: `NO_DECISION`
- Pilot-iteration verdict: `NO_ITERATION`

## Fixes Applied During This Test Run

- `web/index.html`: restored launch promise/install-worker copy expected by launch surface tests and kept the first viewport readable around AI Agent Marketplace + AI Worker Installer positioning.
- `engine/project_auto_mode.py`: fixed the auto-done loop so `auto plan` and stopped `auto cycle` preserve `DONE` state.
- `engine/project_evolution.py`: carried repeated `refresh token` evidence into skill `when_to_use` and validation requirements.
- `tests/test_skill_evolution.py`: aligned the successful apply case with the maturity gate by expanding outcome evidence before apply.
- `scripts/smoke_ai_company_gold_path.py`: made subprocess output decoding tolerant on Windows, forced UTF-8 where possible, and installed from the cached install-kit wheelhouse when available so smoke does not hang on dependency network lookup.
- `scripts/build_cambrian_install_kit.py`, `scripts/prepare_cambrian_install_kit_handoff.py`, and `scripts/check_cambrian_install_kit_send_ready.py`: added a share-safe recipient install receipt and tightened handoff/send-ready copy so local path-bearing receipts are not shared.
- `scripts/check_cambrian_install_kit_dispatch_record.py`: added first-recipient dispatch record evidence so actual sending is still manual, one-recipient only, and private-hash only.
- `scripts/check_cambrian_install_kit_recipient_checkpoint.py`: added the post-dispatch recipient install checkpoint so `cambrian_install_share_receipt.json` can confirm one install without raw acknowledgement text or local paths.
- `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat` and `COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat`: hardened Python discovery for external Windows users when `py -3` or PATH aliases are unreliable.
- `scripts/prepare_cambrian_install_kit_release.py`: added `RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py` so recipients can verify the AI Company Gold Path after install with a share-safe receipt.
- `engine/project_evolution.py`: shortened atomic-write temp file names so Windows backup paths in `evolve apply` do not fail near the legacy path-length boundary.
- `scripts/build_cambrian_install_kit.py`: made install kit wheel builds prefer local no-build-isolation wheel creation and reuse cached dependency wheels from the previous install kit ZIP before attempting network download.
- `scripts/check_cambrian_install_kit_recipient_checkpoint.py`: added gold path share receipt intake, Windows BOM-tolerant JSON receipt reads, and the `RECIPIENT_GOLD_PATH_CONFIRMED` verdict so external 1-recipient evidence can confirm all AI Company capabilities while keeping claim boundaries locked.
- `scripts/smoke_cambrian_install_kit_release_bundle.py`: added a repeatable recipient-style release bundle smoke gate so required gold path execution is verified by code, not by a manual one-off note.
- `scripts/check_cambrian_install_kit_dispatch_record.py`: added the release bundle smoke receipt to the dispatch artifact chain before first-recipient sending.
- `scripts/prepare_cambrian_install_kit_release.py`: added the top-level Claude/Codex release bundle prompt to the manifest, release receipt, standalone verifier checks, and payload checks.
- External alpha release bundle: added the top-level Codex/Claude prompt to the allowlist, local verifier required files, diagnostics required files, release manifest, and install guide.
- External alpha handoff/send-ready/pilot-ready/dispatch-record: locked the Codex/Claude prompt filename into copy-paste policy, recipient checklist, dispatch policy, Markdown output, and focused tests.
- `scripts/check_external_alpha_send_ready.py`: now blocks stale handoff/receipt pairings by requiring `handoff_receipt_body_matches_current_receipt`.
- `scripts/audit_external_alpha_send_chain.py`: added an operator-side final audit that reads the existing `dist` artifacts, validates standalone files, cross-checks release/receipt/body hashes, and confirms pre-send verdicts without rewriting files. It is now included in the external alpha ZIP allowlist and documented in START_HERE, the RC install guide, and the release manifest.
- External alpha pilot-evidence/decision/iteration: added controlled pilot learning tags (`outcome`, `friction`, `missing_skill`) so first-user learning can move through the decision chain without raw feedback, quotes, or free text in public artifacts.
- External alpha recipient-checkpoint/pilot-review/evidence/decision/iteration: added optional Builder Golden Path share receipt intake so a first user can be recorded as `RECIPIENT_GOLD_PATH_CONFIRMED` without storing browser localStorage, download paths, screenshots, or proof/sale claims.
- `web/platform/index.html`: added `gold path receipt 다운로드`, generating `external_alpha_builder_gold_path_share_receipt.json` only when Builder draft, manual runner/evolution handoff, candidate diff, promoted private version, verified promotion audit, and lineage verifier pass are all present; the receipt keeps proof/success/sale claims false and excludes raw browser storage and paths.
- `web/index.html`: restored readable marketplace/installer copy for the external user first viewport after detecting mojibake in the platform regression bundle.
- `tests/test_agent_platform_browser_flow.py`: tightened the Playwright availability check from `require.resolve('playwright')` to `require('playwright')` so an incomplete bundled Playwright install is treated as unavailable.

- `tests/test_agent_platform_gold_path_receipt_runtime.py`: added Node runtime contract coverage that extracts the platform receipt functions from the HTML, verifies share-safe receipt generation plus blocked download behavior when lineage verification fails, proves the platform-generated receipt closes external alpha recipient-checkpoint as `RECIPIENT_GOLD_PATH_CONFIRMED`, and carries the same receipt through controlled evidence, decision, and one-recipient-only pilot iteration.
- `scripts/verify_agent_platform_browser_flow.py`: added a repeatable optional browser smoke wrapper that uses temporary Playwright dependencies outside the repository and runs the existing platform browser flow suite.
- `scripts/verify_external_alpha_release.py`: now checks `scripts/verify_agent_platform_browser_flow.py --help` from the extracted ZIP and records `browser_smoke_wrapper_checked` in the share-safe release receipt.
- `scripts/verify_external_alpha_release.py`: excludes `generated_at` from `receipt_body_sha256`, so re-running receipt generation does not stale the handoff hash chain.
- `docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md`: records the browser wrapper help gate, stable `generated_at` hash boundary, and share-safe `browser_wrapper` receipt field.
- `scripts/smoke_external_alpha_release_bundle.py`: added a recipient-style external alpha ZIP smoke gate that verifies the extracted bundle, diagnostics privacy, browser wrapper help, Windows batch rehearsal, and manual-dispatch policy, then writes a share-safe smoke receipt.
- `scripts/audit_external_alpha_send_chain.py`: now requires the external alpha release bundle smoke receipt and verifies it matches the final ZIP hash before returning `READY_TO_SEND_ONE`.
- `scripts/check_external_alpha_dispatch_record.py`: now requires the external alpha release bundle smoke receipt before `READY_TO_SEND_ONE`, includes it in the artifact chain, and refreshes stale smoke receipts when their ZIP hash no longer matches the current release.
- `scripts/prepare_external_alpha_operator_dispatch_packet.py`: added a final one-recipient operator dispatch packet with exact ZIP, copy-paste message, final audit/smoke/dispatch hashes, post-send rehearsal evidence, pilot-learning rehearsal evidence, private workspace scaffold command, private-only post-send commands, and tamper-detecting self-checks.
- `scripts/check_external_alpha_first_recipient_send_preflight.py`: added a one-recipient pre-send gate that refuses to proceed until `recipient-private.txt` is real and `operator-dispatch-note-private.md` names the private send channel plus the exact release ZIP sha256; the receipt stores only file names, statuses, byte counts, controlled note booleans, sha256 hashes for ready files, and no local paths or raw private text.
- `scripts/prepare_external_alpha_operator_dispatch_packet.py`, `scripts/prepare_external_alpha_first_recipient_send_workspace.py`, and `scripts/prepare_external_alpha_private_pilot_workspace.py`: now instruct the operator to keep the private channel/hash confirmation in the local-only operator note before attempting the first manual send.
- `scripts/check_external_alpha_first_recipient_pre_send_sequence.py` and `scripts/check_external_alpha_first_recipient_operator_status.py`: now surface missing private-note requirements through controlled booleans such as `mentions_channel=false` and `contains_release_hash=false`, so partial private notes stay blocked without exposing raw recipient or operator text.
- `scripts/prepare_external_alpha_first_recipient_send_workspace.py`: now writes the local-only operator note template into `SEND_ONE_NOW_PRIVATE.md` and seeds `operator-dispatch-note-private.md` when it is missing, empty, or still scaffold text; existing real private notes are preserved, the share-safe workspace receipt records only a controlled seed status, and the focused tests prove unresolved `<private-send-channel>` remains blocked until replacement.
- `scripts/external_alpha_operator_note_template.py`: added the shared canonical first-recipient operator note template helper and included it in the external alpha ZIP allowlist so local development, generated runbooks, and extracted bundles use the same private-note contract.
- `scripts/smoke_external_alpha_manual_send_go_rehearsal.py`: now generates the normal first-recipient private send workspace, extracts the operator note template from `SEND_ONE_NOW_PRIVATE.md`, replaces the private channel placeholder, and proves the final manual-send GO rehearsal reaches `GO_TO_MANUALLY_SEND_ONE` through that template path.
- `scripts/prepare_external_alpha_operator_dispatch_packet.py` and `scripts/prepare_external_alpha_first_recipient_send_workspace.py`: now route the operator through the pre-send preflight before any manual send is allowed.
- `scripts/check_external_alpha_dispatch_record.py`: added `--require-preflight-receipt` so the standard private workspace send path cannot record `SENT_ONE_RECORDED` unless a ready pre-send preflight receipt exists and its private hashes and release hash match the dispatch record.
- `scripts/audit_external_alpha_operator_send_bypass.py`: added an operator-surface bypass audit that verifies the operator packet, release manifest, source private runbook templates, and generated private runbook all keep `--require-preflight-receipt` on private dispatch-record commands before the first manual send can be recorded.
- `scripts/check_external_alpha_recipient_checkpoint.py`: added `--preflight-receipt` and `--require-preflight-receipt`, carries the standard private workspace preflight receipt into the internal dispatch-record call, and records the preflight receipt in the recipient-checkpoint artifact chain so post-send checkpointing cannot silently bypass the pre-send gate.
- `scripts/audit_external_alpha_operator_send_bypass.py`: now audits both private dispatch-record commands and private recipient-checkpoint commands for `--require-preflight-receipt`.
- `scripts/audit_external_alpha_send_chain.py`: now requires the operator send bypass audit receipt in the final `READY_TO_SEND_ONE` gate, while `prepare_external_alpha_operator_dispatch_packet.py` uses an internal non-final audit mode to avoid a circular dependency during packet generation.
- `scripts/audit_external_alpha_send_chain.py`: now verifies the operator dispatch packet self-checks and requires the packet's post-send rehearsal evidence for `preflight_generated_by_real_gate=true` and `operator_note_template_preflight_contract=true` before final `READY_TO_SEND_ONE`.
- `scripts/audit_external_alpha_send_chain.py`: now recalculates critical operator packet self-checks and rejects stale or missing stored self-check entries, so the final audit cannot pass by trusting a tampered operator packet.
- `scripts/audit_external_alpha_send_chain.py`: now requires the manual-send GO rehearsal receipt in the final send-chain audit and rejects stale rehearsal receipts whose release hash does not match the current ZIP. Internal rehearsal generation uses an explicit non-final audit path to avoid circular dependency.
- `scripts/prepare_external_alpha_operator_dispatch_packet.py`: now names both `audit_external_alpha_operator_send_bypass.py` and the final `audit_external_alpha_send_chain.py` in the before-send section, with self-checks preventing the internal skip flag from appearing in the operator-facing command.
- `scripts/check_external_alpha_first_recipient_manual_send_go.py`: added the final private GO/NO-GO aggregator that combines the ready preflight receipt, operator bypass audit, and final send-chain audit before a human manually sends the ZIP to one recipient; the receipt is share-safe and defaults to BLOCKED until private recipient fields are filled.
- `scripts/smoke_external_alpha_manual_send_go_rehearsal.py`: added a synthetic private-input rehearsal proving the final manual-send GO gate reaches `GO_TO_MANUALLY_SEND_ONE` when required private files are filled, while recording `real_manual_send=false` and omitting raw private values and paths.
- `scripts/smoke_external_alpha_manual_send_go_rehearsal.py`: now treats `operator_status_ready_to_send`, `operator_status_verdict=READY_TO_MANUALLY_SEND_ONE`, and the operator-status receipt hash as explicit required evidence, so a recomputed but weakened rehearsal receipt cannot keep the final send chain green.
- `scripts/check_external_alpha_first_recipient_pre_send_sequence.py`: added the operator-facing one-command pre-send sequence that prepares the private runbook, runs preflight, operator bypass audit, final send-chain audit, and manual-send GO, then emits one share-safe `READY_TO_MANUALLY_SEND_ONE` or `BLOCKED_BEFORE_MANUAL_SEND` receipt without sending anything; blocked output now names only controlled private file statuses so the operator can fix placeholders without exposing raw private values, and names the current manual-send GO rehearsal/final send-chain audit when private files are ready but the release chain is stale.
- `scripts/check_external_alpha_first_recipient_post_send_sequence.py`: added the operator-facing one-command post-send sequence that records dispatch with the required preflight receipt, waits safely for recipient acknowledgement, then records recipient checkpoint or gold-path confirmation by hashes only without sending anything; waiting and blocked states now name only controlled ack status so the operator can distinguish sent-but-waiting from recipient-confirmed, and checkpoint closure now requires exactly one non-empty `CONFIRMED` acknowledgement line.
- `scripts/check_external_alpha_first_recipient_post_send_sequence.py`: fixed the real post-send rerun path so after the first pass records `SENT_ONE_RECORDED`, a later ACK/gold-path rerun can fall back to the already recorded dispatch/preflight chain instead of being blocked by the pre-send-only final audit.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: added a share-safe operator status command that reports the current first-recipient stage and next action without sending anything, raw private values, private hashes, or local paths.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: added `operator_safe_checklist`, a share-safe done/not-done checklist for setup, pre-send, and post-send steps so the first-recipient operator can see exactly which gate remains blocked without exposing private text or local paths.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: added `operator_launch_snapshot`, a share-safe single-decision object with `send_state`, `manual_send_allowed`, one-recipient/manual-dispatch policy, release hash, final-chain readiness, private-field readiness, pre-send readiness, open gate ids, and the next safe action; the CLI now prints `send   : BLOCKED` or `send   : MANUAL_SEND_ALLOWED_ONE`.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: now verifies the first-recipient workspace receipt against the current release hash and blocks stale runbooks as `PREPARE_PRIVATE_WORKSPACE` with only `first_recipient_workspace_ready` open, preventing operators from filling private fields against an old ZIP hash.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: now verifies pre-send sequence and manual-send GO receipts against the current release hash before allowing `READY_TO_MANUALLY_SEND_ONE`, preventing a valid old pre-send receipt from unlocking a newly rebuilt ZIP.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: now marks a non-`CONFIRMED` recipient acknowledgement as controlled `unconfirmed` status, surfaces `confirmed_reply_present` and `exactly_one_acknowledgement` booleans, and keeps the operator in `WAITING_FOR_RECIPIENT_ACK`.
- `scripts/check_external_alpha_first_recipient_operator_status.py`: now reads `final_chain_depth` from the final send-chain audit, so the safe status receipt reports the same 12-artifact chain depth as `audit_external_alpha_send_chain.py`.
- `.gitignore`: now ignores `external_alpha_diagnostics*.json` so locally generated support diagnostics do not become accidental commit candidates.
- External alpha handoff/send-ready/pilot-ready/dispatch-record/operator packet: replaced the first-recipient copy-paste message with readable ASCII text so the actual manual send does not expose mojibake to an external user.
- `scripts/prepare_external_alpha_operator_dispatch_packet.py` and `scripts/prepare_external_alpha_first_recipient_send_workspace.py`: added `copy_paste_message_ascii_only` and `mojibake_free` checks so broken first-recipient send text blocks the operator packet and private runbook receipts.
- `scripts/prepare_external_alpha_private_pilot_workspace.py`: added an operator-only scaffold for local private recipient, dispatch, acknowledgement, feedback, issue intake, and decision-note files, plus a share-safe scaffold receipt that omits local paths and raw private values.
- `scripts/smoke_external_alpha_private_pilot_workspace.py`: added an operator-only rehearsal receipt proving the private workspace scaffold can be generated in a temporary workspace, verified against the current ZIP hash, and shared without local paths, placeholders, or raw private values.
- `scripts/prepare_external_alpha_operator_dispatch_packet.py`: now includes the private workspace rehearsal receipt hash and self-checks before first-recipient sending.
- `.gitignore`: now ignores `.cambrian/` so the default private workspace cannot become an accidental commit candidate.
- `scripts/prepare_external_alpha_first_recipient_send_workspace.py`: added the local-only first-recipient send workspace builder, producing `SEND_ONE_NOW_PRIVATE.md` with exact local attachment/message/recording commands and a separate share-safe receipt that omits paths and raw private text.
- `scripts/check_external_alpha_dispatch_record.py`, `scripts/check_external_alpha_recipient_checkpoint.py`, `scripts/check_external_alpha_pilot_review.py`, `scripts/check_external_alpha_pilot_evidence.py`, `scripts/check_external_alpha_pilot_decision.py`, and `scripts/check_external_alpha_pilot_iteration.py`: added `--private-workspace-dir` shortcuts for the standard private workspace, with placeholder rejection so scaffold text cannot become fake dispatch, acknowledgement, feedback, issue, or decision evidence.
- `scripts/prepare_external_alpha_first_recipient_send_workspace.py` and `scripts/prepare_external_alpha_private_pilot_workspace.py`: updated generated runbooks to use the standard private workspace shortcut, include the safe operator status command, prefer the full pre-send/post-send sequences, require the acknowledgement file to contain exactly one `CONFIRMED` line, and refresh README/runbook receipts without overwriting existing private files.
- `scripts/smoke_external_alpha_post_send_checkpoint.py`: added an operator-only rehearsal that copies current `dist` artifacts into a temporary workspace, runs the real first-recipient preflight receipt engine through a cycle-free send contract, uses the standard private workspace filenames through the first-recipient post-send sequence, records fake private dispatch/ack inputs by hash only, proves the sequence can reach `RECIPIENT_GOLD_PATH_CONFIRMED`, and writes a receipt that explicitly keeps `real_recipient_evidence=false`.
- `scripts/smoke_external_alpha_pilot_learning_loop.py`: added an operator-only learning-loop rehearsal that uses the standard private workspace filenames through `--private-workspace-dir`, carries fake private feedback, issue intake, and decision-note files as hashes only through evidence, decision, and iteration, then blocks the next send with `PATCH_BEFORE_NEXT` while keeping `real_pilot_evidence=false`.

## Known Non-Blockers

- A single `python -m pytest -q` full-suite run was not used as the release gate. The project release policy defines split-run regression gates because the full suite can exceed local interactive timeouts.
- Browser automation requires optional Playwright deps. In this local run they were installed outside the repo under `C:\tmp\cambrian-playwright-deps`, then rerun through `scripts/verify_agent_platform_browser_flow.py`; the repository is still not converted into a Node package.
- Actual TestPyPI/PyPI upload was not attempted. This is intentionally gated on local `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=<token>` values.

## 2026-05-18 External Alpha Refresh

Verdict: external alpha remains release-chain ready for exactly one manual first-recipient send, but the real send is still blocked until the operator fills the two required local-only private fields. This is the intended launch boundary.

- User-facing root docs were made readable and ASCII/mojibake-gated: `START_HERE_EXTERNAL_ALPHA.md`, `QUICKSTART_EXTERNAL_ALPHA.md`, `EXTERNAL_ALPHA_SUPPORT_PACKET.md`, and `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md`.
- Send-ready was updated to enforce the current English support/privacy contract instead of stale mojibake guardrail text.
- Current external alpha ZIP sha256: `f101592eddb74c929a960204c622a0321b85ae61acd175eed07f68de230d7d40`.
- Current send-ready: `GO`, body sha256 `8bb7f0c39335e6e3656b8c9eb5bf5643c9e3172f92158c3c0adcc4d42bd6144d`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `6b68fdf5068a15038d46afc6d8b0453a223d211aadbb97c2602caa0436f5cd82`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `7368513adfa4e36f4fdee42d048c47d1046d544c409e82824c0ca013ea2436fd`.
- Expected blocked private gates: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification added in this refresh:

```text
python -m py_compile scripts\check_external_alpha_send_ready.py
python -m pytest -q tests\test_external_alpha_send_ready.py -> 4 passed
python -m pytest -q tests\test_external_alpha_install_surface.py tests\test_external_alpha_diagnostics.py tests\test_external_alpha_release_bundle.py -> 22 passed
python -m pytest -q tests\test_external_alpha_first_recipient_operator_status.py -> 12 passed
python scripts\verify_platform_alpha.py -> PASS
python scripts\verify_external_alpha_release.py -> PASS
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS
```

## 2026-05-20 Public Launch Chain Bundle Binding Refresh

Verdict: release packaging, public download packaging, deploy-candidate receipts, and Cloudflare launch gates are aligned. Public external sharing remains blocked only by missing Cloudflare credentials.

Key result:

- External alpha ZIP now includes the operator-only public launch scripts plus `docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md`.
- Public upload package is `cambrian-public-site.zip`.
- User-facing download inside the site remains `cambrian-alpha.zip`.
- Canonical deploy candidate receipt is `dist/cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json`.
- The guarded launch sequence now skips the public launch doctor until a launch-ready receipt exists, keeping the credentials-blocked path fast and deterministic.

Current chain:

- External alpha ZIP sha256: `b1d241d0426ddbc42e8c6168ffc167a4c3c0b7a8815f2d4dcea3bb8260fa2f7d`
- Release receipt body sha256: `9704c015e23015e1556a7fa9dbbabb06a0aabbe15b71119d1743a43e88d1b741`
- Send-ready: `GO`, body sha256 `ad91a7f48dccaa0fae6cb5f14c2ccd912d910b3723d8e30d1d46348258a6d95a`
- Public site upload ZIP sha256: `f232630e91815947ad973b8dccf5c6a3b293c1d6af1b4639d8d2902be0184cdc`
- Public deploy candidate: `PUBLIC_DEPLOY_CANDIDATE_READY`, body sha256 `8fa407f078566d0b26ef1e688be13c2960c49af87cffad8c4a326fe5cce15510`
- Cloudflare credentials: `BLOCKED_API_TOKEN_REQUIRED`, missing `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
- Cloudflare deploy-ready body sha256: `281665e7091b341f03610ee8026765d699433716f19e8193d84a67c97201bc69`
- Public launch sequence: `BLOCKED_CLOUDFLARE_CREDENTIALS`, body sha256 `cbb36fd3bf7db4b9a1d82e15072fcdf51e30a3ed7c947ef27ac781e7dec4c89b`
- Public launch doctor: `BLOCKED_CLOUDFLARE_CREDENTIALS`, body sha256 `9da43c8c250be40faa9a7d3b20c5abc0f928dfaa0c39faea222361c8d5297cab`

Verification:

```text
python scripts\build_external_alpha_release.py -> PASS
python scripts\verify_external_alpha_release.py --receipt dist\external_alpha_release_verification_receipt.json -> PASS
python scripts\prepare_external_alpha_handoff.py -> PASS
python scripts\check_external_alpha_send_ready.py -> PASS, GO
python scripts\package_external_alpha_public_download_site.py --output-dir dist -> PASS
python scripts\check_external_alpha_public_deploy_candidate.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json -> PASS
python scripts\check_external_alpha_cloudflare_credentials.py --verify-receipt dist\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json -> PASS
python scripts\check_external_alpha_cloudflare_pages_deploy_ready.py --verify-receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-deploy-ready.json -> PASS
python scripts\run_external_alpha_public_launch_sequence.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json -> PASS
python scripts\check_external_alpha_public_launch_doctor.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-launch-doctor.json -> PASS
python -m pytest -q tests\test_external_alpha_release_bundle.py tests\test_external_alpha_install_surface.py tests\test_external_alpha_public_launch_sequence.py -> 22 passed
python -m pytest -q tests\test_external_alpha_cloudflare_credentials.py tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py tests\test_external_alpha_public_launch_sequence.py -> 21 passed
python -m pytest -q tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_deploy_candidate.py tests\test_external_alpha_public_launch_url_gate.py tests\test_external_alpha_public_share_packet.py -> 22 passed
```

## 2026-05-20 Cloudflare Pages Deploy Preflight

Verdict: Cambrian's public download package is ready for static hosting, but the public launch is still blocked until the hosted HTTPS URL passes the final URL gate. In the Codex non-interactive shell, Cloudflare Pages deploy additionally requires both `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.

Changes:

- Added `scripts/check_external_alpha_cloudflare_pages_deploy_ready.py`.
- Added `tests/test_external_alpha_cloudflare_pages_deploy_ready.py`.
- Added `docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md`.
- The preflight verifies the current public deploy candidate, emits the exact Cloudflare Pages deploy command, emits the final public URL gate command, redacts Wrangler output, and distinguishes these states:
  - `READY_TO_DEPLOY_WITH_WRANGLER`
  - `BLOCKED_API_TOKEN_REQUIRED`
  - `BLOCKED_ACCOUNT_ID_REQUIRED`
  - `BLOCKED_AUTH_REQUIRED`
  - `BLOCKED_WRANGLER_UNAVAILABLE`

Credential contract:

- `CLOUDFLARE_API_TOKEN` is required for Codex/non-interactive deploy.
- `CLOUDFLARE_ACCOUNT_ID` is required for deterministic non-interactive direct upload.
- Token permission label: `Account / Cloudflare Pages / Edit` / `Pages Write`.

Current artifacts:

```text
public product ZIP sha256: 156dbc0e7e65ac99c3f824d4356c27811f9317a933a2f726ccdfabf797461855
public site package sha256: 08499f40bc2075bcd7b964467408e57641a8680491e4520d448140631404910f
public deploy candidate body sha256: 7398d0fccc52a1c26b65e085024dd67d85aefc1319e1deed962426e069a53a79
cloudflare pages preflight verdict: BLOCKED_API_TOKEN_REQUIRED
cloudflare pages preflight body sha256: 046fafc3d0e72eaa819a7da5627cfd7962d22cf4a668a6af60445eb5a1dc1d3b
cloudflare api token present: false
cloudflare account id present: false
external_sharing_allowed: false
```

Verification:

```text
python -m py_compile scripts\check_external_alpha_cloudflare_pages_deploy_ready.py scripts\launch_external_alpha_cloudflare_pages.py scripts\check_external_alpha_public_launch_doctor.py tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py -> PASS
python -m pytest -q tests\test_external_alpha_cloudflare_pages_deploy_ready.py -> 6 passed
python -m pytest -q tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py -> 14 passed
python scripts\check_external_alpha_public_deploy_candidate.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json -> PASS
python scripts\check_external_alpha_cloudflare_pages_deploy_ready.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-deploy-ready.json -> BLOCKED_API_TOKEN_REQUIRED
python scripts\check_external_alpha_cloudflare_pages_deploy_ready.py --verify-receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-deploy-ready.json -> PASS
npx wrangler pages deploy dist\cambrian-public-site --project-name cambrian-alpha --branch main -> expected BLOCKED in Codex shell until CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are set
```

Next gate:

```text
Set CLOUDFLARE_API_TOKEN outside the repo.
Set CLOUDFLARE_ACCOUNT_ID outside the repo.
Use docs\release\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md for the exact permission and cleanup steps.
Run python scripts\check_external_alpha_cloudflare_pages_deploy_ready.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-deploy-ready.json.
Run npx wrangler pages deploy dist\cambrian-public-site --project-name cambrian-alpha --branch main only after READY_TO_DEPLOY_WITH_WRANGLER.
Run python scripts\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> --expected-archive-sha256 156dbc0e7e65ac99c3f824d4356c27811f9317a933a2f726ccdfabf797461855 --receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json.
Share externally only after PUBLIC_LAUNCH_URL_READY.
```

## 2026-05-20 Cloudflare Credential Gate

Verdict: added a credential-only gate before the launch runner. It does not deploy, create a Pages project, or share a URL; it only verifies the required Cloudflare env vars and Wrangler auth state.

Changes:

- Added `scripts/check_external_alpha_cloudflare_credentials.py`.
- Added `tests/test_external_alpha_cloudflare_credentials.py`.
- Updated `docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md` to run the credential-only check before the guarded launch command.

Current state:

```text
credential verdict: BLOCKED_API_TOKEN_REQUIRED
missing credential env vars: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
credential receipt body sha256: d329bbcf3414861bb0f3e87ed8f80074775f36b4c88c9431c9923f4b343c57aa
does_not_deploy: true
```

Verification:

```text
python -m py_compile scripts\check_external_alpha_cloudflare_credentials.py tests\test_external_alpha_cloudflare_credentials.py -> PASS
python -m pytest -q tests\test_external_alpha_cloudflare_credentials.py -> 4 passed
python -m pytest -q tests\test_external_alpha_cloudflare_credentials.py tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py -> 18 passed
python scripts\check_external_alpha_cloudflare_credentials.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json -> BLOCKED_API_TOKEN_REQUIRED
python scripts\check_external_alpha_cloudflare_credentials.py --verify-receipt dist\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json -> PASS
```

## 2026-05-20 Public Launch Sequence Runner

Verdict: added a guarded one-command public launch sequence. It runs the credential gate first, skips deploy when credentials are missing, and only calls the Cloudflare launch runner after `CLOUDFLARE_CREDENTIALS_READY`.

Changes:

- Added `scripts/run_external_alpha_public_launch_sequence.py`.
- Added `tests/test_external_alpha_public_launch_sequence.py`.
- Updated `docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md` to prefer the guarded sequence command after credential setup.

Current state:

```text
sequence verdict: BLOCKED_CLOUDFLARE_CREDENTIALS
sequence body sha256: 0bdea0d64e0217f5de4c9649a31f4b558766ff6920f57a3c3dcc0ff8c4b1180e
launch attempted: false
external_sharing_allowed: false
```

Verification:

```text
python -m py_compile scripts\run_external_alpha_public_launch_sequence.py tests\test_external_alpha_public_launch_sequence.py -> PASS
python -m pytest -q tests\test_external_alpha_public_launch_sequence.py -> 3 passed
python -m pytest -q tests\test_external_alpha_cloudflare_credentials.py tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py tests\test_external_alpha_public_launch_sequence.py -> 21 passed
python scripts\run_external_alpha_public_launch_sequence.py --receipt dist\cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json -> BLOCKED_CLOUDFLARE_CREDENTIALS
python scripts\run_external_alpha_public_launch_sequence.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json -> PASS
```

## 2026-05-20 Cloudflare Pages Launch Runner

Verdict: the launch path is now a guarded one-command runner after the operator sets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in the shell. Without both credentials, the runner stops before deploy and writes a blocked receipt. With both credentials and a successful Pages deployment, it extracts the returned `https://*.pages.dev` URL and runs the final downloaded-ZIP URL gate.

Changes:

- Added `scripts/launch_external_alpha_cloudflare_pages.py`.
- Added `tests/test_external_alpha_cloudflare_pages_launch.py`.
- The runner writes `dist\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json`.
- The runner redacts raw Wrangler output and never records token values.
- The runner checks `wrangler pages project list --json` and creates the `cambrian-alpha` Pages project with `--production-branch main` before deploy when needed.
- The runner now prepares the public share packet automatically after the public URL gate passes. A launch receipt can return `CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY` only after deploy, URL gate, and share packet generation all succeed.
- A blocked launch receipt now includes `preflight_blocker` with required/missing credential env vars, credential runbook, and redacted preflight next action.

Current state:

```text
public product ZIP sha256: 156dbc0e7e65ac99c3f824d4356c27811f9317a933a2f726ccdfabf797461855
public site package sha256: 08499f40bc2075bcd7b964467408e57641a8680491e4520d448140631404910f
cloudflare pages preflight verdict: BLOCKED_API_TOKEN_REQUIRED
cloudflare pages launch verdict: BLOCKED_PREFLIGHT_NOT_READY
cloudflare pages launch body sha256: 33b1565fe872053569f9e770f4de75c15d53d360fd2fb028a1ba94716a5e1e7c
launch preflight blocker missing credential env vars: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
launch next action: Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in this shell, then rerun this launch runner.
deploy attempted: false
project ensure attempted: false, because preflight is still blocked by missing CLOUDFLARE_API_TOKEN
share packet attempted: false, because preflight is still blocked
external_sharing_allowed: false
```

Verification:

```text
python -m py_compile scripts\launch_external_alpha_cloudflare_pages.py tests\test_external_alpha_cloudflare_pages_launch.py -> PASS
python -m pytest -q tests\test_external_alpha_cloudflare_pages_launch.py -> 5 passed
python -m pytest -q tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py -> 11 passed
python -m pytest -q tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py -> 14 passed
python scripts\launch_external_alpha_cloudflare_pages.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json -> BLOCKED_PREFLIGHT_NOT_READY
python scripts\launch_external_alpha_cloudflare_pages.py --verify-receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json -> PASS
```

Next gate:

```text
Set CLOUDFLARE_API_TOKEN outside the repo.
Set CLOUDFLARE_ACCOUNT_ID outside the repo.
Run python scripts\launch_external_alpha_cloudflare_pages.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json.
Share externally only after the launch receipt returns CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY and external_sharing_allowed=true.
```

## 2026-05-20 Public Launch Doctor

Verdict: added a no-deploy public launch status doctor. It summarizes public deploy candidate, Cloudflare preflight, Cloudflare launch, public URL gate, and final share packet readiness into one share-safe receipt.

Changes:

- Added `scripts/check_external_alpha_public_launch_doctor.py`.
- Added `tests/test_external_alpha_public_launch_doctor.py`.
- The doctor writes `dist\cambrian-agent-platform-external-alpha-public-launch-doctor.json`.
- The doctor does not deploy or share anything; it only reports the current state and next action.
- The doctor now records `required_credential_env_vars` and `missing_credential_env_vars` in the preflight summary and mirrors the missing env vars into `next_action`.
- The doctor now includes the credential-only gate as `artifacts.cloudflare_credentials`, including the credential receipt body sha256 and `does_not_deploy=true`.

Current state:

```text
doctor verdict: BLOCKED_CLOUDFLARE_CREDENTIALS
doctor body sha256: 0582d70dc0c990a45a888dad7ae2141efbacc6da7386f0a3b1842640a511489c
cloudflare credential gate: BLOCKED_API_TOKEN_REQUIRED
cloudflare credential gate body sha256: d329bbcf3414861bb0f3e87ed8f80074775f36b4c88c9431c9923f4b343c57aa
public deploy candidate: PUBLIC_DEPLOY_CANDIDATE_READY
cloudflare pages preflight: BLOCKED_API_TOKEN_REQUIRED
missing credential env vars: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID
cloudflare pages launch: BLOCKED_PREFLIGHT_NOT_READY
public URL gate: PUBLIC_LAUNCH_URL_REHEARSAL_READY only
public share packet: missing until CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY
external_sharing_allowed: false
```

Verification:

```text
python -m py_compile scripts\check_external_alpha_public_launch_doctor.py tests\test_external_alpha_public_launch_doctor.py -> PASS
python -m pytest -q tests\test_external_alpha_public_launch_doctor.py -> 3 passed
python -m pytest -q tests\test_external_alpha_cloudflare_pages_deploy_ready.py tests\test_external_alpha_cloudflare_pages_launch.py tests\test_external_alpha_public_launch_doctor.py -> 14 passed
python scripts\check_external_alpha_public_launch_doctor.py --receipt dist\cambrian-agent-platform-external-alpha-public-launch-doctor.json -> BLOCKED_CLOUDFLARE_CREDENTIALS
python scripts\check_external_alpha_public_launch_doctor.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-launch-doctor.json -> PASS
```

Next gate:

```text
Run python scripts\check_external_alpha_public_launch_doctor.py --receipt dist\cambrian-agent-platform-external-alpha-public-launch-doctor.json to get the current next action.
Current next action is: read docs\release\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md; set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID; rerun python scripts\check_external_alpha_cloudflare_credentials.py --receipt dist\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json.
```

## 2026-05-19 Public ZIP Fresh-Venv Bootstrap Test

Verdict: the public download path is now installable enough for an external Windows recipient with Python 3.11+ to download the ZIP, extract it, and run verification from a clean `.venv` created by the bundle itself.

Initial finding before the fix:

- `cambrian-alpha.zip` downloaded and extracted successfully.
- Running `scripts/verify_platform_alpha.py` from a fresh venv failed with `No module named 'jsonschema'`.
- The failure was an installation surface problem, not a product workflow problem.

Fix:

- `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat` now creates/reuses `.venv`, installs local verification dependencies with `python -m pip install -e .` when needed, then runs the verifier.
- `COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat` now uses the same bootstrap.
- Recipient docs now point to the batch bootstrap as the normal path and show the manual `.venv` equivalent.
- The platform verifier now checks the updated Codex/Claude prompt wording.

Current artifacts:

- Release ZIP sha256: `9c16f02e16907ef5470e5e72520179f9bf057f3381fe0acf39b6bbfbe10eaf3b`
- Public product ZIP: `cambrian-alpha.zip`
- Public deploy package: `dist/cambrian-public-site.zip`
- Public deploy package sha256: `140afa6073c161ad9fc9f3131a838783c9821ba58762e001138157682589fd26`
- Public deploy candidate: `PUBLIC_DEPLOY_CANDIDATE_READY`
- Public deploy candidate body sha256: `2301d15318f83095f1707e0a5973a300363a08d6bc68d43bf53ace26223bf352`

Fresh recipient simulation:

```text
serve dist\cambrian-public-site over HTTP
download cambrian-alpha.zip
extract to a temporary folder
run VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat from the extracted root
result: PASS
.venv created: true
run COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat --output external_alpha_diagnostics.json
diagnostics: PASS, safe_to_share=true
```

Verification:

```text
python -m pytest -q tests\test_external_alpha_install_surface.py -> 5 passed
python scripts\build_external_alpha_release.py -> PASS
python scripts\check_external_alpha_send_ready.py -> PASS, GO
python scripts\prepare_external_alpha_public_download_site.py -> PASS
python scripts\package_external_alpha_public_download_site.py -> PASS
python scripts\prepare_external_alpha_public_launch_handoff.py -> PASS
python scripts\check_external_alpha_public_deploy_candidate.py -> PASS
python -m pytest -q tests\test_external_alpha_install_surface.py tests\test_external_alpha_diagnostics.py tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_deploy_candidate.py -> 29 passed
python -m pytest -q tests\test_external_alpha_public_download_site_url.py::test_external_alpha_public_download_site_url_verifies_live_download tests\test_external_alpha_public_launch_url_gate.py::test_external_alpha_public_launch_url_gate_local_rehearsal_passes tests\test_external_alpha_public_share_packet.py -> 7 passed
```

Launch boundary:

```text
External sharing remains blocked until a real non-local HTTPS URL passes:
python scripts\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> --expected-archive-sha256 9c16f02e16907ef5470e5e72520179f9bf057f3381fe0acf39b6bbfbe10eaf3b --receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json
```

## 2026-05-19 Comprehensive Launch Test Refresh

Verdict: the current launch-critical local build passes after hardening the packaging test harness and mission-control no-pending behavior.

Fixes discovered by the comprehensive run:

- Packaging wheel test copied stale `.pytest-basetemp-*` folders and failed on Windows missing-path copy errors. `tests/test_alpha_packaging.py` now ignores `.pytest-*`, `.pytest_cache`, `.venv`, `.env`, `.cambrian`, `.launch_runs`, `cambrian.egg-info`, and `node_modules`.
- Mission-control tests assumed at least one `status: pending` OS backlog item. The backlog currently has `current_next_task: none`, so `engine/project_auto_mode.py` now returns a clear `no_pending` completed next-task state instead of the generic fallback.

Final artifact state:

```text
cambrian-alpha.zip sha256: 156dbc0e7e65ac99c3f824d4356c27811f9317a933a2f726ccdfabf797461855
dist\cambrian-agent-platform-external-alpha.zip sha256: 156dbc0e7e65ac99c3f824d4356c27811f9317a933a2f726ccdfabf797461855
dist\cambrian-public-site.zip sha256: 17a7ce369acb28315c58ba9d6c26bb2c0c002f9514ec120bb2e3b762cabbf75c
public deploy candidate: PUBLIC_DEPLOY_CANDIDATE_READY
local launch URL rehearsal: PUBLIC_LAUNCH_URL_REHEARSAL_READY
external_sharing_allowed: false for local rehearsal
```

Script and smoke verification:

```text
python -m compileall -q engine scripts tools tests -> PASS
python -m pytest --collect-only -q -> 2522 tests collected
python scripts\verify_platform_alpha.py -> PASS
python scripts\verify_external_alpha_release.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\check_external_alpha_send_ready.py --skip-build -> PASS, GO
python scripts\check_external_alpha_pilot_ready.py -> PASS, GO
python scripts\check_external_alpha_dispatch_record.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_public_download_site.py -> PASS
python scripts\package_external_alpha_public_download_site.py -> PASS
python scripts\prepare_external_alpha_public_launch_handoff.py -> PASS
python scripts\check_external_alpha_public_deploy_candidate.py -> PASS
fresh recipient ZIP download, extract, VERIFY batch, diagnostics batch -> PASS
python scripts\finalize_external_alpha_public_launch_url.py <local-url> --allow-local-rehearsal -> PASS
```

Pytest verification:

```text
platform/validator/evolution/promotion suite -> 88 passed
browser smoke wrapper with existing Playwright node_modules -> 1 passed
external alpha core release group -> 33 passed
external alpha dispatch-record file -> 11 passed
AI Company/install/packaging group -> 88 passed
mission-control/backlog group -> 5 passed
agent/skill/harness/project/company/auto broad group -> 435 passed, 28 skipped
```

Known test-suite limitation:

```text
All-in-one external-alpha pytest run timed out after 60 minutes.
Operator-chain pytest grouping timed out because release-chain and fresh-venv recipient checks are repeatedly rebuilt.
The direct operator scripts for the same chain pass, so this is a test-runtime cost issue rather than a current launch-blocking product failure.
```

Current launch boundary:

```text
Do not share a public URL until a real non-local HTTPS URL passes:
python scripts\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> --expected-archive-sha256 156dbc0e7e65ac99c3f824d4356c27811f9317a933a2f726ccdfabf797461855 --receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json
```

## 2026-05-18 Operator Status Packet Binding Refresh

Verdict: external alpha remains release-chain ready for exactly one manual first-recipient alpha send after the operator fills the private recipient/channel files. The real send is still blocked by design.

What changed:

- `scripts/check_external_alpha_first_recipient_operator_status.py` now summarizes the manual-send GO receipt's operator packet binding with safe file/hash fields only.
- `READY_TO_MANUALLY_SEND_ONE` now requires the manual-send GO receipt's current operator packet body sha256 and preflight operator packet body sha256 to match the current operator dispatch packet body sha256.
- The operator checklist now includes `manual_send_go_operator_packet_bound`, preventing a validly rehashed but packet-drifted manual-send GO receipt from unlocking the final operator status.
- `tests/test_external_alpha_first_recipient_operator_status.py` now has a packet-body drift regression test.

Current chain:

- Current external alpha ZIP sha256: `b3b1315ef8982154cb73541c0e5e5ad1a623a42bd17165d42db234c5f85ad81e`.
- Current send-ready: `GO`, body sha256 `6fb2a543cde81a1d626b1c7dd8cc8eb47305071bdb451088294607351e98436b`.
- Current pilot-ready: `GO`, body sha256 `5ac4b106f0f33011e1f99947275d999d61e5ad4daf1db4911e70608014d3e1cf`.
- Current dispatch record: `READY_TO_SEND_ONE`, body sha256 `07f41c0198f19368234dae629f614136e6e49fc91402f20391d33d9e51e8c36e`.
- Current release verification receipt body sha256: `cab23d8ae9e60caaf283b8e8d510918161b9e46a4adc9d007548fe09b3560d61`.
- Current bundle smoke receipt body sha256: `f19fe43d147fc1700a660a412e1c5be9e5ce2986b58579b10953fa4edae88084`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `c246513199a775ba687b3e221a4c8da4b161be7a0a63daf18fbf2394ea685570`.
- Current operator send bypass audit body sha256: `02f903e00c7a4b71be9d7451dee7a8cec9eb7c43f10c2560cc03481af59fd9d5`.
- Current manual-send GO rehearsal body sha256: `b5170a93346bd655340d039fc0dd043921c954cbdbd5a10c303d3b1b2f342196`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `a5ab3f0a3b8290fd71f1634ebb69f84b92c7895bf8ef3e434886113bf2232f3d`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification:

```text
python -m py_compile scripts\check_external_alpha_first_recipient_operator_status.py tests\test_external_alpha_first_recipient_operator_status.py -> PASS
python -m pytest -q tests\test_external_alpha_first_recipient_operator_status.py -> 13 passed
python -m pytest -q tests\test_external_alpha_first_recipient_pre_send_sequence.py tests\test_external_alpha_first_recipient_manual_send_go.py tests\test_external_alpha_manual_send_go_rehearsal.py -> 17 passed
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\check_external_alpha_pilot_ready.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_operator_dispatch_packet.py --verify-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json -> PASS
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py --verify-receipt dist\cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE, 12 artifacts
python scripts\verify_external_alpha_release.py -> PASS
python scripts\verify_platform_alpha.py -> PASS
python scripts\prepare_external_alpha_first_recipient_send_workspace.py -> PASS
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS, send BLOCKED
python scripts\check_external_alpha_first_recipient_send_preflight.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_manual_send_go.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_pre_send_sequence.py -> expected FAIL/BLOCKED
```

## 2026-05-18 Public Download Landing Refresh

Verdict: the external alpha now has a public static download page that can be hosted beside the verified `dist` artifacts. This is the correct launch direction because it gives a non-operator user one obvious download path while preserving the private first-recipient send gate.

New artifacts:

- `dist/cambrian-agent-platform-external-alpha-download.html`
- `dist/cambrian-agent-platform-external-alpha-download-preview.png`
- `dist/cambrian-agent-platform-external-alpha-download-landing-receipt.json`

What changed:

- `scripts/prepare_external_alpha_download_landing.py` generates the download landing page after the ZIP/send-ready/release receipt already exist.
- The landing page is outside the release ZIP, avoiding self-referential ZIP hash drift while still showing the exact current ZIP sha256.
- The landing page links to the user-facing `cambrian-alpha.zip` alias, release verification receipt, manifest, and send-ready note.
- The landing page tells the recipient to unzip, read `QUICKSTART_EXTERNAL_ALPHA.md`, run `START_CAMBRIAN_AGENT_PLATFORM.bat`, and use `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md` when handing the bundle to Codex or Claude.
- The receipt asserts no email collection, no direct recipient send, no private values, no local paths, no API key requirement, and no proof/success claims.

Current landing state:

- Landing verdict: `DOWNLOAD_PAGE_READY`.
- User-facing download ZIP: `cambrian-alpha.zip`.
- Canonical internal release ZIP: `cambrian-agent-platform-external-alpha.zip`.
- Landing receipt body sha256: `c0f687ff534176c091c2f821d267a8a9f022d2a86f66260e0bd4b16655de1c92`.
- Landing HTML sha256: `9d3a7eae75279a9f50bfc80772389279aef12217993c5cdc30942c7443beda5d`.
- Current external alpha ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.
- Current release verification receipt body sha256: `362b4b225db488df4baf479afa3b0f43cfcb47dce5f4a6bebccf162eacbd5c4f`.
- Current send-ready body sha256: `52ecdf6d3c47656a23d801bcf26425303370676f107666f4d92d84bbdc851589`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_download_landing.py tests\test_external_alpha_download_landing.py -> PASS
python -m pytest -q tests\test_external_alpha_download_landing.py -> 3 passed
python scripts\prepare_external_alpha_download_landing.py -> PASS, DOWNLOAD_PAGE_READY
python scripts\prepare_external_alpha_download_landing.py --verify-receipt dist\cambrian-agent-platform-external-alpha-download-landing-receipt.json -> PASS
```

## 2026-05-18 Public Download Site Package Refresh

Verdict: the launch surface now has a self-contained static site directory that can be uploaded to static hosting as-is. This turns the prior download landing page into a practical public distribution unit.

New artifact:

- `dist/cambrian-agent-platform-external-alpha-public-download-site/`

Required site files:

- `index.html`
- `cambrian-agent-platform-external-alpha-download.html`
- `cambrian-agent-platform-external-alpha-download-preview.png`
- `cambrian-alpha.zip`
- `cambrian-agent-platform-external-alpha.manifest.json`
- `external_alpha_release_verification_receipt.json`
- `cambrian-agent-platform-external-alpha-send-ready.md`
- `cambrian-agent-platform-external-alpha-send-ready.json`
- `cambrian-agent-platform-external-alpha-download-landing-receipt.json`
- `README_HOSTING.md`
- `_headers`
- `.nojekyll`
- `robots.txt`
- `404.html`

What changed:

- `scripts/prepare_external_alpha_public_download_site.py` prepares the hostable directory and receipt.
- `index.html` is copied from the generated landing page so a static host can serve the download page from the root.
- The public site receipt verifies all required files, hash presence, index/landing hash equality, ZIP hash matching, same-directory static hosting, no email collection, no API key requirement, no local paths, no raw private values, and no proof/success claims.

Current public site state:

- Public site verdict: `PUBLIC_DOWNLOAD_SITE_READY`.
- Public site receipt body sha256: `3c2ff9fa5756e08594019f93bc4cbc0e3cb9415aebaadfb23783a6c5544cfad6`.
- Landing receipt body sha256: `c0f687ff534176c091c2f821d267a8a9f022d2a86f66260e0bd4b16655de1c92`.
- Landing/index HTML sha256: `9d3a7eae75279a9f50bfc80772389279aef12217993c5cdc30942c7443beda5d`.
- External alpha ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_download_landing.py scripts\prepare_external_alpha_public_download_site.py tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py -> PASS
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py -> 6 passed
python scripts\prepare_external_alpha_public_download_site.py -> PASS, PUBLIC_DOWNLOAD_SITE_READY
python scripts\prepare_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site\cambrian-agent-platform-external-alpha-public-download-site-receipt.json -> PASS
```

## 2026-05-18 Public Download Site ZIP Package Refresh

Verdict: the public download surface now has a single upload-ready ZIP package plus an external verification receipt. This is the practical launch artifact for static hosting because it keeps all required download files together and keeps the package hash outside the package.

New artifacts:

- `dist/cambrian-public-site.zip`
- `dist/cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json`

What changed:

- `scripts/package_external_alpha_public_download_site.py` packages the hostable static site directory into a root-level ZIP.
- The package receipt stays outside the ZIP to avoid self-referential hash drift.
- The package verifier checks ZIP hash, ZIP entries, required site files, root-level layout, public site receipt readiness, release ZIP hash matching, no local paths, no private values, no email collection, no API key requirement, and no proof/success claims.
- Tampered ZIP contents are rejected by receipt verification.

Current public package state:

- Package verdict: `PUBLIC_DOWNLOAD_SITE_PACKAGE_READY`.
- Package ZIP sha256: `481a7265ecc3123a614fc20322a3f48d094badd10dd1aa22054e9952e5c81e01`.
- Package receipt body sha256: `85444c7a415e6373cb06b6ebea9a6421bb713019410634244d3b212c7f6350b6`.
- Public site receipt body sha256: `3c2ff9fa5756e08594019f93bc4cbc0e3cb9415aebaadfb23783a6c5544cfad6`.
- External alpha ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.
- Package entries: `14`.
- Package bytes: `432498`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_download_landing.py scripts\prepare_external_alpha_public_download_site.py scripts\package_external_alpha_public_download_site.py tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py -> PASS
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py -> 10 passed
python scripts\package_external_alpha_public_download_site.py -> PASS, PUBLIC_DOWNLOAD_SITE_PACKAGE_READY
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
```

## 2026-05-18 Static Hosting Hardening and URL Verification Refresh

Verdict: the download site now has static-hosting hardening files and a URL-level verifier. This confirms the launch path through HTTP, not just local file existence.

New artifacts:

- `dist/cambrian-agent-platform-external-alpha-public-download-site/_headers`
- `dist/cambrian-agent-platform-external-alpha-public-download-site/.nojekyll`
- `dist/cambrian-agent-platform-external-alpha-public-download-site/robots.txt`
- `dist/cambrian-agent-platform-external-alpha-public-download-site/404.html`
- `dist/cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json`

What changed:

- `scripts/prepare_external_alpha_download_landing.py` now emits `noindex,nofollow` robots metadata.
- `scripts/prepare_external_alpha_public_download_site.py` now emits `_headers`, `.nojekyll`, `robots.txt`, and `404.html`.
- `scripts/verify_external_alpha_public_download_site_url.py` verifies a live public or local HTTP URL by fetching the landing page, download ZIP, manifest, release receipt, public site receipt, landing receipt, send-ready note, and robots policy.
- The verifier checks that every observed archive hash matches the expected external alpha ZIP hash.

Current URL verification state:

- URL verdict: `PUBLIC_DOWNLOAD_SITE_URL_READY`.
- URL receipt body sha256: `387bf9b7316e704f0cc95613df19556895e29c761f8b1d52461a60d1318adc67`.
- Observed ZIP sha256 over local HTTP: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_download_landing.py scripts\prepare_external_alpha_public_download_site.py scripts\package_external_alpha_public_download_site.py scripts\verify_external_alpha_public_download_site_url.py tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py -> PASS
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py -> 14 passed
python scripts\package_external_alpha_public_download_site.py -> PASS, PUBLIC_DOWNLOAD_SITE_PACKAGE_READY
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
local HTTP verification against dist/cambrian-agent-platform-external-alpha-public-download-site/ -> PASS, PUBLIC_DOWNLOAD_SITE_URL_READY
python scripts\verify_external_alpha_public_download_site_url.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
```

## 2026-05-18 Public Launch Handoff Refresh

Verdict: the release now has a public launch handoff that prevents false launch completion. The handoff is ready, while the public URL remains intentionally `PENDING_PUBLIC_URL` until hosted URL verification passes.

New artifacts:

- `dist/cambrian-agent-platform-external-alpha-public-launch-handoff.md`
- `dist/cambrian-agent-platform-external-alpha-public-launch-handoff.json`

What changed:

- `scripts/prepare_external_alpha_public_launch_handoff.py` produces the operator-facing publish handoff.
- The handoff references the current public download site package and pins the expected external alpha ZIP sha256 in the URL verification command.
- External sharing is blocked until `verify_external_alpha_public_download_site_url.py` returns `PUBLIC_DOWNLOAD_SITE_URL_READY`.
- Fake public URLs and premature share permission are rejected.

Current public launch handoff state:

- Handoff verdict: `PUBLIC_LAUNCH_HANDOFF_READY`.
- Public URL state: `PENDING_PUBLIC_URL`.
- Handoff body sha256: `4128835e071ab266f753b25e3db244e4bb0e16e8d256a20c9fd85d8fc328bda3`.
- Package ZIP sha256: `481a7265ecc3123a614fc20322a3f48d094badd10dd1aa22054e9952e5c81e01`.
- External alpha ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_launch_handoff.py -> PASS
python -m pytest -q tests\test_external_alpha_public_launch_handoff.py -> 4 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py -> 19 passed
python scripts\prepare_external_alpha_public_launch_handoff.py -> PASS, PUBLIC_LAUNCH_HANDOFF_READY, PENDING_PUBLIC_URL
python scripts\prepare_external_alpha_public_launch_handoff.py --verify-handoff dist\cambrian-agent-platform-external-alpha-public-launch-handoff.json -> PASS
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
python scripts\verify_external_alpha_public_download_site_url.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
```

## 2026-05-19 Public Deploy Candidate Gate

Verdict: the upload ZIP now has its own final pre-hosting gate. The candidate is ready to upload to a static HTTPS host, but external sharing remains blocked until the hosted URL passes the public launch URL gate.

What changed:

- Added `scripts/check_external_alpha_public_deploy_candidate.py`.
- Added `tests/test_external_alpha_public_deploy_candidate.py`.
- The deploy-candidate gate rebuilds the public download site package, opens the package ZIP, verifies root-only upload entries, confirms `PUBLIC_HOSTING_RUNBOOK.md` and `.nojekyll`, and checks that the runbook points to the final `<PUBLIC_HTTPS_URL>` gate.
- The receipt explicitly keeps `external_sharing_allowed=false` before the public URL gate.
- The upload root now includes `.nojekyll` so GitHub Pages can serve the static files without Jekyll processing changing underscore-prefixed helpers.
- The package step now also writes the short upload folder `dist/cambrian-public-site/` for hosts that prefer folder upload instead of ZIP upload.
- Deploy-candidate receipt verification now re-reads the current `dist/cambrian-public-site.zip`; stale candidate receipts fail if the ZIP hash or inspection no longer matches.
- Deploy-candidate receipt verification now also re-reads `dist/cambrian-public-site/` and fails if the folder contents drift from the ZIP.
- Public launch handoff reuses a verified package receipt/ZIP instead of repackaging and changing the candidate hash.

Current upload candidate evidence:

- Candidate verdict: `PUBLIC_DEPLOY_CANDIDATE_READY`.
- Candidate receipt: `dist/cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json`.
- Upload ZIP: `dist/cambrian-public-site.zip`.
- Upload folder: `dist/cambrian-public-site/`.
- Upload options: `zip_file`, `folder_contents`.
- Canonical internal package name: `cambrian-agent-platform-external-alpha-public-download-site.zip`.
- Upload ZIP sha256: `d2ef816283ca9a248e0df1c820a8f44bc802fdb2a9f11e8c5e70f811ab1629b9`.
- Candidate receipt body sha256: `e6458f3ce3fa07e7b05e2ab18a2d1b11ae550769d0e6d6ba9b06c1227279a0f5`.
- Package receipt body sha256: `33d9f9c8b02218cad71208451442a576267a11c5615ede2cd24161e21c0a04ed`.
- Public site receipt body sha256: `17257e738229eea83bc4474c0aa9d0c054f02141ad2e8bc24c1046d3a57488b8`.
- Public launch handoff body sha256: `bd461893fba4dd40b84710a4ddd7a3e5c1c7a39e6cd7de82d08dd1fb8237537d`.
- Runbook sha256: `8e660b1c20026c1d128da56a3ab5a3c4127636474104ee9a3f6735fae5baf846`.
- Package entry count: `16`.
- Upload folder/ZIP file list equality: `true`.

Verification:

```text
python -m py_compile scripts\check_external_alpha_public_deploy_candidate.py tests\test_external_alpha_public_deploy_candidate.py -> PASS
python -m pytest -q tests\test_external_alpha_public_deploy_candidate.py -> 5 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_launch_url_gate.py tests\test_external_alpha_public_deploy_candidate.py tests\test_external_alpha_public_share_packet.py -> 34 passed
python scripts\check_external_alpha_public_deploy_candidate.py --receipt dist\cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json -> PASS, PUBLIC_DEPLOY_CANDIDATE_READY
python scripts\prepare_external_alpha_public_launch_handoff.py -> PASS, PUBLIC_LAUNCH_HANDOFF_READY
python scripts\check_external_alpha_public_deploy_candidate.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json -> PASS
python scripts\prepare_external_alpha_public_launch_handoff.py --verify-handoff dist\cambrian-agent-platform-external-alpha-public-launch-handoff.json -> PASS
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
python scripts\prepare_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site\cambrian-agent-platform-external-alpha-public-download-site-receipt.json -> PASS
python scripts\prepare_external_alpha_public_share_packet.py -> expected FAIL, requires PUBLIC_LAUNCH_URL_READY
```

Next real launch action:

Upload `dist/cambrian-public-site.zip` or the contents of `dist/cambrian-public-site/` to a static HTTPS host, then run the public launch URL gate against the resulting URL.

## 2026-05-19 Public Hosting Runbook Packaging

Verdict: the upload-ready static site now includes a host-neutral operator runbook, so the deployment path is carried by the artifact itself rather than chat memory.

What changed:

- `scripts/prepare_external_alpha_public_download_site.py` now writes `PUBLIC_HOSTING_RUNBOOK.md` into the public site directory.
- `PUBLIC_HOSTING_RUNBOOK.md` names the required web-root files, acceptable static host classes, the final public HTTPS gate command, and the local rehearsal command.
- The public site receipt records `hosting_runbook_included=true` and checks `hosting_runbook_present`.
- The public launch handoff now lists `PUBLIC_HOSTING_RUNBOOK.md` as a required support file.
- Package tests assert the runbook is included in the upload ZIP.

Current runbook evidence:

- Site file count before writing the site receipt: `14`.
- Package entry count: `16`.
- Runbook sha256: `8e660b1c20026c1d128da56a3ab5a3c4127636474104ee9a3f6735fae5baf846`.
- Public site receipt body sha256: `3c2ff9fa5756e08594019f93bc4cbc0e3cb9415aebaadfb23783a6c5544cfad6`.
- Site package ZIP sha256: `481a7265ecc3123a614fc20322a3f48d094badd10dd1aa22054e9952e5c81e01`.
- Handoff body sha256: `4128835e071ab266f753b25e3db244e4bb0e16e8d256a20c9fd85d8fc328bda3`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_public_download_site.py scripts\prepare_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_launch_handoff.py -> PASS
python -m pytest -q tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_launch_handoff.py -> 12 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_launch_url_gate.py -> 23 passed
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
python scripts\prepare_external_alpha_public_launch_handoff.py --verify-handoff dist\cambrian-agent-platform-external-alpha-public-launch-handoff.json -> PASS
```

## 2026-05-19 Public Launch URL Gate

Verdict: the release now has a final public URL gate. Local URLs can pass only as rehearsals, while external sharing is allowed only after a non-local HTTPS URL passes the full landing/downloaded-ZIP verifier.

What changed:

- Added `scripts/finalize_external_alpha_public_launch_url.py`.
- Added `tests/test_external_alpha_public_launch_url_gate.py`.
- The gate calls the public launch handoff and hosted URL verifier, then writes `dist/cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json`.
- The gate rejects localhost/private URLs unless `--allow-local-rehearsal` is explicitly set.
- Local rehearsal verdict is `PUBLIC_LAUNCH_URL_REHEARSAL_READY` and keeps `external_sharing_allowed=false`.

Current local rehearsal evidence:

- Gate verdict: `PUBLIC_LAUNCH_URL_REHEARSAL_READY`.
- Gate share allowed: `false`.
- Gate receipt body sha256: `99ffe5f40e25a021ae531e35f8c5fa5fb3a31fd189206a7a0909a3f3c3bca680`.
- URL receipt body sha256: `387bf9b7316e704f0cc95613df19556895e29c761f8b1d52461a60d1318adc67`.
- Handoff body sha256: `4128835e071ab266f753b25e3db244e4bb0e16e8d256a20c9fd85d8fc328bda3`.
- Site package ZIP sha256: `481a7265ecc3123a614fc20322a3f48d094badd10dd1aa22054e9952e5c81e01`.

Verification:

```text
python -m py_compile scripts\finalize_external_alpha_public_launch_url.py tests\test_external_alpha_public_launch_url_gate.py -> PASS
python -m pytest -q tests\test_external_alpha_public_launch_url_gate.py -> 4 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_launch_url_gate.py -> 23 passed
python scripts\finalize_external_alpha_public_launch_url.py http://127.0.0.1:8787/ --expected-archive-sha256 42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881 --allow-local-rehearsal --receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json -> PASS, PUBLIC_LAUNCH_URL_REHEARSAL_READY, share=False
python scripts\finalize_external_alpha_public_launch_url.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json -> PASS
```

Next real launch action:

```text
python scripts\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> --expected-archive-sha256 42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881 --receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json
```

## 2026-05-19 Public Share Packet Gate

Verdict: the release now has a final share-message gate after the public URL gate. A human cannot generate the external copy-paste share packet from a local rehearsal receipt; the script requires `PUBLIC_LAUNCH_URL_READY`, `external_sharing_allowed=true`, and a non-local HTTPS URL.

What changed:

- Added `scripts/prepare_external_alpha_public_share_packet.py`.
- Added `tests/test_external_alpha_public_share_packet.py`.
- The share packet writes `cambrian-agent-platform-external-alpha-public-share-packet.json` and `.md` only after the public launch URL gate passes.
- The generated copy-paste message includes the verified public URL, `cambrian-alpha.zip`, and the release ZIP sha256 while preserving the external-alpha boundary.
- The packet rejects local rehearsal gates, missing URL gate receipts, stale packet checks, plain HTTP URLs, local paths, private material, production-ready claims, and success/proof claims.

Current state:

- Public share packet: blocked by design until the real HTTPS URL gate passes.
- Default command result before public URL exists: expected FAIL, `public share packet requires PUBLIC_LAUNCH_URL_READY`.
- Current upload ZIP remains `dist/cambrian-public-site.zip`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_public_share_packet.py tests\test_external_alpha_public_share_packet.py -> PASS
python -m pytest -q tests\test_external_alpha_public_share_packet.py -> 5 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py tests\test_external_alpha_public_launch_url_gate.py tests\test_external_alpha_public_deploy_candidate.py tests\test_external_alpha_public_share_packet.py -> 31 passed
python scripts\prepare_external_alpha_public_share_packet.py -> expected FAIL, requires PUBLIC_LAUNCH_URL_READY
```

After the real public URL gate passes:

```text
python scripts\prepare_external_alpha_public_share_packet.py --gate-receipt dist\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json
```

## 2026-05-19 Public Download User Path Smoke

Verdict: the public URL verifier now validates the actual external-user download path. It fetches `cambrian-alpha.zip`, opens the release ZIP, verifies the release root, checks the first-user entrypoint files, and confirms the Quickstart/Codex-Claude prompt points to the Builder Golden Path start.

What changed:

- `scripts/verify_external_alpha_public_download_site_url.py` now records `downloaded_release_zip` evidence.
- The verifier requires the downloaded ZIP to contain `QUICKSTART_EXTERNAL_ALPHA.md`, `START_CAMBRIAN_AGENT_PLATFORM.bat`, `RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md`, `START_HERE_EXTERNAL_ALPHA.md`, `EXTERNAL_ALPHA_SUPPORT_PACKET.md`, `VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat`, and `COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat`.
- `tests/test_external_alpha_public_download_site_url.py` now locks the downloaded ZIP root and first-user file contract.

Current downloaded ZIP evidence:

- Download URL file: `cambrian-alpha.zip`.
- Downloaded ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.
- Downloaded ZIP root: `cambrian-agent-platform-external-alpha`.
- Downloaded ZIP entry count observed by URL verifier: `88`.
- URL receipt body sha256: `387bf9b7316e704f0cc95613df19556895e29c761f8b1d52461a60d1318adc67`.

Verification:

```text
python -m py_compile scripts\verify_external_alpha_public_download_site_url.py tests\test_external_alpha_public_download_site_url.py -> PASS
python -m pytest -q tests\test_external_alpha_public_download_site_url.py -> 4 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py -> 19 passed
python scripts\verify_external_alpha_public_download_site_url.py http://127.0.0.1:8787/ --expected-archive-sha256 42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881 --receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
python scripts\verify_external_alpha_public_download_site_url.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
```

## 2026-05-19 Public Landing Capability Contract Refresh

Verdict: the public landing page now frames Cambrian around the four release-critical outcomes an external user needs to understand immediately: agents, skills, harness engineering, and evolution receipts.

What changed:

- `scripts/prepare_external_alpha_download_landing.py` adds a first-screen promise row for Agents, Skills, Harness, and Evolution.
- The generated landing and hosted index now include a `Capability Contract` section with `Build AI Agents`, `Create And Fuse Skills`, `Run Harness Engineering`, and `Evolve With Receipts`.
- Landing and public-site tests now assert those four outcomes so the release page cannot silently drift back into a generic file-download page.

Current public landing evidence:

- Public download file: `cambrian-alpha.zip`.
- Public download ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.
- Landing receipt body sha256: `c0f687ff534176c091c2f821d267a8a9f022d2a86f66260e0bd4b16655de1c92`.
- Landing/index HTML sha256: `9d3a7eae75279a9f50bfc80772389279aef12217993c5cdc30942c7443beda5d`.
- Public site receipt body sha256: `3c2ff9fa5756e08594019f93bc4cbc0e3cb9415aebaadfb23783a6c5544cfad6`.
- Site package ZIP sha256: `481a7265ecc3123a614fc20322a3f48d094badd10dd1aa22054e9952e5c81e01`.
- URL receipt body sha256: `387bf9b7316e704f0cc95613df19556895e29c761f8b1d52461a60d1318adc67`.
- Handoff body sha256: `4128835e071ab266f753b25e3db244e4bb0e16e8d256a20c9fd85d8fc328bda3`.

Verification:

```text
python -m py_compile scripts\prepare_external_alpha_download_landing.py tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py -> PASS
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py -> 7 passed
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py -> 19 passed
python scripts\prepare_external_alpha_public_launch_handoff.py -> PASS, PUBLIC_LAUNCH_HANDOFF_READY, PENDING_PUBLIC_URL
python scripts\package_external_alpha_public_download_site.py -> PASS, PUBLIC_DOWNLOAD_SITE_PACKAGE_READY
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
python scripts\verify_external_alpha_public_download_site_url.py http://127.0.0.1:8787/ --expected-archive-sha256 42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881 --receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
python scripts\verify_external_alpha_public_download_site_url.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
python scripts\prepare_external_alpha_public_launch_handoff.py --verify-handoff dist\cambrian-agent-platform-external-alpha-public-launch-handoff.json -> PASS
```

## 2026-05-19 Public Download Filename Refresh

Verdict: the user-facing download file is now `cambrian-alpha.zip`, while the canonical internal release artifact remains `cambrian-agent-platform-external-alpha.zip` for receipts and release evidence.

What changed:

- `scripts/prepare_external_alpha_download_landing.py` creates a public `cambrian-alpha.zip` alias with the same sha256 as the canonical release ZIP.
- `scripts/prepare_external_alpha_public_download_site.py` resets the public site directory before rebuilding, so stale long-name ZIP files cannot leak into the hosted site.
- The hosted site, package receipt, URL verifier, and public launch handoff now use `cambrian-alpha.zip` as the public download file.

Current filename state:

- Public download file: `cambrian-alpha.zip`.
- Canonical internal release file: `cambrian-agent-platform-external-alpha.zip`.
- Public download ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.
- Site package ZIP sha256: `481a7265ecc3123a614fc20322a3f48d094badd10dd1aa22054e9952e5c81e01`.
- URL receipt body sha256: `387bf9b7316e704f0cc95613df19556895e29c761f8b1d52461a60d1318adc67`.

Verification:

```text
python -m pytest -q tests\test_external_alpha_download_landing.py tests\test_external_alpha_public_download_site.py tests\test_external_alpha_public_download_site_package.py tests\test_external_alpha_public_download_site_url.py tests\test_external_alpha_public_launch_handoff.py -> 19 passed
python scripts\prepare_external_alpha_public_launch_handoff.py -> PASS, PUBLIC_LAUNCH_HANDOFF_READY, PENDING_PUBLIC_URL
python scripts\package_external_alpha_public_download_site.py --verify-receipt dist\cambrian-agent-platform-external-alpha-public-download-site-package-receipt.json -> PASS
python scripts\verify_external_alpha_public_download_site_url.py http://127.0.0.1:8787/ --expected-archive-sha256 42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881 --receipt dist\cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json -> PASS
```

## 2026-05-18 Manual-Send Rehearsal Packet Binding Evidence Refresh

Verdict: external alpha remains release-chain ready for exactly one manual first-recipient alpha send after the operator fills the private recipient/channel files. The real send is still blocked by design.

What changed:

- `scripts/smoke_external_alpha_manual_send_go_rehearsal.py` now requires `operator_status_manual_send_go_packet_bound`.
- The manual-send GO rehearsal receipt now records `rehearsed_flow.operator_status_manual_send_go_packet_bound=true`.
- `scripts/audit_external_alpha_send_chain.py` now requires `manual_send_go_rehearsal_operator_status_packet_bound`.
- Focus tests now reject rehearsal/final-audit paths that omit or falsify operator-status packet-binding evidence.

Current chain:

- Current external alpha ZIP sha256: `42008191a45c6819393de0443b36a867a142731530ab7d5e5f6facf7f1eb4881`.
- Current send-ready: `GO`, body sha256 `52ecdf6d3c47656a23d801bcf26425303370676f107666f4d92d84bbdc851589`.
- Current pilot-ready: `GO`, body sha256 `25fa2e1c2de84497c959147f0d3b03146969a4e52f362cd4923846e520228940`.
- Current dispatch record: `READY_TO_SEND_ONE`, body sha256 `fde217b78db227de46bbc4f35744b12b0540e0d9efc908a776d9ac7578d3392c`.
- Current release verification receipt body sha256: `362b4b225db488df4baf479afa3b0f43cfcb47dce5f4a6bebccf162eacbd5c4f`.
- Current bundle smoke receipt body sha256: `eb39044b84123f4eb03eee77aa4e48ac335b26778c5b1e8c9dbc547e9bef87b1`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `6c9e6d9c80977cff9599d6db2013136e8b2a9565249db78574898f55e069ce55`.
- Current operator send bypass audit body sha256: `f20fe91999f3835d23034e0541f4e800fe9bd59fc61ee04d50ac7678ef91ca0e`.
- Current manual-send GO rehearsal body sha256: `bda98c6efd2443c38980d983e603ae29f505f670ba335bd66cde4834a3a2a1f5`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `e9456a96ba024c81dd2ddcb9ea5828a16625b0773a529fb963e784860227b81e`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification:

```text
python -m py_compile scripts\smoke_external_alpha_manual_send_go_rehearsal.py scripts\audit_external_alpha_send_chain.py tests\test_external_alpha_manual_send_go_rehearsal.py tests\test_external_alpha_send_chain_audit.py -> PASS
python -m pytest -q tests\test_external_alpha_manual_send_go_rehearsal.py tests\test_external_alpha_send_chain_audit.py -> 18 passed
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\check_external_alpha_pilot_ready.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_operator_dispatch_packet.py --verify-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json -> PASS
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py --verify-receipt dist\cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE, 12 artifacts
python scripts\verify_external_alpha_release.py -> PASS
python scripts\verify_platform_alpha.py -> PASS
python scripts\prepare_external_alpha_first_recipient_send_workspace.py -> PASS
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS, send BLOCKED
python scripts\check_external_alpha_first_recipient_send_preflight.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_manual_send_go.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_pre_send_sequence.py -> expected FAIL/BLOCKED
```

## 2026-05-18 Manual-Send GO Packet Body Binding Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send, with the actual send still blocked until the operator fills the two local-only private fields.

- `scripts/check_external_alpha_first_recipient_manual_send_go.py` now loads the current operator dispatch packet directly.
- Manual-send GO now requires the ready preflight receipt's operator packet body sha256 to match the current operator dispatch packet body sha256.
- A recomputed preflight receipt with a stale packet body can no longer unlock `GO_TO_MANUALLY_SEND_ONE`.
- `tests/test_external_alpha_first_recipient_manual_send_go.py` covers the stale-preflight-packet-body case.
- Current external alpha ZIP sha256: `ed1101027d4f289f6f04742400089ebc0ce20d05a0a779785201694ed7093779`.
- Current send-ready: `GO`, body sha256 `c10a96ab6e02368ef1ec101a86236e01187941424b73a99cdec37be1f2eeb20e`.
- Current pilot-ready: `GO`, body sha256 `0eb3186c1cd8898c8eb535ff6f337be8d6c39940c9640a6ba13b758e4582b82b`.
- Current dispatch record: `READY_TO_SEND_ONE`, body sha256 `8c653ff9843b946e1238a85432f95d489e7f2e48ed2594672488e11ea8d4b27a`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `f31579073e43d8af73c72704176be637245d26251f961fcd397ee80c68dc513d`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `8e9da8c5efb362ae1aafc38a95bf701cf4bb440a82ea880b8c6a22b3c263eb78`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification added in this refresh:

```text
python -m py_compile scripts\check_external_alpha_first_recipient_manual_send_go.py tests\test_external_alpha_first_recipient_manual_send_go.py
python -m pytest -q tests\test_external_alpha_first_recipient_manual_send_go.py -> 3 passed
python -m pytest -q tests\test_external_alpha_first_recipient_pre_send_sequence.py tests\test_external_alpha_first_recipient_operator_status.py tests\test_external_alpha_manual_send_go_rehearsal.py -> 26 passed
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\check_external_alpha_pilot_ready.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_operator_dispatch_packet.py --verify-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json -> PASS
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py --verify-receipt dist\cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE, 12 artifacts
python scripts\verify_external_alpha_release.py -> PASS
python scripts\verify_platform_alpha.py -> PASS
python scripts\prepare_external_alpha_first_recipient_send_workspace.py -> PASS
python scripts\check_external_alpha_first_recipient_send_preflight.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_manual_send_go.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_pre_send_sequence.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS, send BLOCKED
```

## 2026-05-18 Operator Packet Exact-Arg Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send, with the actual send still blocked until the operator fills the two local-only private fields.

- `scripts/prepare_external_alpha_operator_dispatch_packet.py` now self-checks that both first-recipient workspace preparation and pre-send preflight commands include the exact `--operator-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json` argument.
- `scripts/audit_external_alpha_send_chain.py` mirrors that exact-operator-packet argument in its recalculated critical checks.
- `tests/test_external_alpha_operator_dispatch_packet.py` rejects recomputed command tampering that removes the operator packet argument.
- `tests/test_external_alpha_send_chain_audit.py` rejects a valid-body-hash operator packet whose preflight command no longer references the operator packet.
- Current external alpha ZIP sha256: `91106f11c29ceafd2e726121448e26fd146e167f387d4a7b1f9712ece05c0b11`.
- Current send-ready: `GO`, body sha256 `016b4140fce4adea0ff86f2d012a6846a2ef5c491a88c9b54b4c932053571af0`.
- Current pilot-ready: `GO`, body sha256 `6bef3c2c34b224d05c12bb42673247adac6c3a5a3966b1dd0bb4c25ee139c68d`.
- Current dispatch record: `READY_TO_SEND_ONE`, body sha256 `f684a4f67c11d152498b94ebfacbf92382214a2f1f16a6a78e1fd70747c4a7e7`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `c9b5c58520d67eec4eab3afdc22bc87b6c4bb970baeb8b8026e83231dbb69b56`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `7c4e10ee54543a14b87a4d70eebd998faeec76020220062cba7e5afd4eeeacbe`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification added in this refresh:

```text
python -m py_compile scripts\prepare_external_alpha_operator_dispatch_packet.py scripts\audit_external_alpha_send_chain.py tests\test_external_alpha_operator_dispatch_packet.py tests\test_external_alpha_send_chain_audit.py
python -m pytest -q tests\test_external_alpha_operator_dispatch_packet.py tests\test_external_alpha_send_chain_audit.py -> 14 passed
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\check_external_alpha_pilot_ready.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_operator_dispatch_packet.py --verify-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json -> PASS
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py --verify-receipt dist\cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE, 12 artifacts
python scripts\verify_external_alpha_release.py -> PASS
python scripts\verify_platform_alpha.py -> PASS
python scripts\prepare_external_alpha_first_recipient_send_workspace.py -> PASS
python scripts\check_external_alpha_first_recipient_send_preflight.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_manual_send_go.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_pre_send_sequence.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS, send BLOCKED
```

## 2026-05-18 First-Recipient Preflight Canonical Packet Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send, with the actual send still blocked until the operator fills the two local-only private fields.

- `scripts/check_external_alpha_first_recipient_send_preflight.py` now requires the real pre-send operator packet path to use the canonical `cambrian-agent-platform-external-alpha-operator-dispatch-packet.json` filename.
- The internal post-send rehearsal can still use its cycle-free `external_alpha_post_send_rehearsal_preflight_contract_v0_1` contract, preserving rehearsal coverage without a circular dependency.
- `tests/test_external_alpha_first_recipient_send_preflight.py` rejects a copied operator packet JSON with a noncanonical filename.
- Synthetic private-input GO paths still pass through preflight, manual-send GO, pre-send sequence, and operator status tests without leaking raw private values.
- Current external alpha ZIP sha256: `33bbe5d8144dae20d0e2fb47d32bf256bade11dd53816a8f34c3d409e76d2dfd`.
- Current send-ready: `GO`, body sha256 `c6e228b8265bd07081adcf142aa76bbc7a51afb7a17e64897fb78530d9605ee5`.
- Current pilot-ready: `GO`, body sha256 `37108a95dc330b77152fa45c4d9c4b40c699d208098806e293f84862bad1ba3c`.
- Current dispatch record: `READY_TO_SEND_ONE`, body sha256 `8c92dff8163e4d032601970eeb49d212486b3e69731a892c4afc406f3b0b78b9`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `53129530f9b68b5262dfb4141232d74977e6cad29b4d8e70707918f6fb3dd976`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `9beab7fd797f477d9e92c1c50327b290961d3ddf18e05fb5a6cec3e3c8f122bf`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification added in this refresh:

```text
python -m py_compile scripts\check_external_alpha_first_recipient_send_preflight.py tests\test_external_alpha_first_recipient_send_preflight.py
python -m pytest -q tests\test_external_alpha_first_recipient_send_preflight.py -> 8 passed
python -m pytest -q tests\test_external_alpha_first_recipient_pre_send_sequence.py tests\test_external_alpha_first_recipient_manual_send_go.py tests\test_external_alpha_first_recipient_operator_status.py -> 22 passed
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\check_external_alpha_pilot_ready.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\prepare_external_alpha_operator_dispatch_packet.py --verify-packet dist\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json -> PASS
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py --verify-receipt dist\cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE, 12 artifacts
python scripts\verify_external_alpha_release.py -> PASS
python scripts\verify_platform_alpha.py -> PASS
python scripts\prepare_external_alpha_first_recipient_send_workspace.py -> PASS
python scripts\check_external_alpha_first_recipient_send_preflight.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_manual_send_go.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_pre_send_sequence.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS, send BLOCKED
```

## 2026-05-18 Pilot-Ready Cleanup Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send, with the actual send still blocked until the operator fills the two local-only private fields.

- `scripts/check_external_alpha_pilot_ready.py` no longer contains duplicate `_pilot_ready_checks`, stale mojibake copy-paste readiness logic, duplicate recipient checklists, or mojibake pilot decision text.
- Pilot-ready verifier failures now report readable English body-hash and safety-check mismatch errors.
- `tests/test_external_alpha_pilot_ready.py` now asserts the readable verifier error.
- Current external alpha ZIP sha256: `08dc1bb295c47a1eaefac299b7dfb23bae04bfa4764fee5fbec42fdcda1b9ad2`.
- Current send-ready: `GO`, body sha256 `9d816d83512cfcab89bf3303183a946f5f835477c4d038c2fbf6fa7a1f50921f`.
- Current pilot-ready: `GO`, body sha256 `40b04f35c39e343429155c394ae727662aa1cf5fde5edc3017ee13f4a6cb48f6`.
- Current dispatch record: `READY_TO_SEND_ONE`, body sha256 `36e79b8a315b4f8f482ae429002aca67d1092eb3a600c6d16c91f150ca7db76e`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `e5a99590cae491ba890fec0b96b692aeedc467b181799f41a9fcc10c327db9c4`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `6916ce7b10c5a384f8d6309821bad0a9666d9c14e5f3c183dfe10003e623ee84`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification added in this refresh:

```text
python -m py_compile scripts\check_external_alpha_pilot_ready.py tests\test_external_alpha_pilot_ready.py
python -m pytest -q tests\test_external_alpha_pilot_ready.py -> 3 passed
python -m pytest -q tests\test_external_alpha_pilot_ready.py tests\test_external_alpha_dispatch_record.py tests\test_external_alpha_send_chain_audit.py tests\test_external_alpha_operator_dispatch_packet.py tests\test_external_alpha_first_recipient_operator_status.py -> 38 passed
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\check_external_alpha_pilot_ready.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS, READY_TO_SEND_ONE
python scripts\audit_external_alpha_operator_send_bypass.py -> PASS
python scripts\smoke_external_alpha_manual_send_go_rehearsal.py -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS, READY_TO_SEND_ONE, 12 artifacts
python scripts\verify_external_alpha_release.py -> PASS
python scripts\verify_platform_alpha.py -> PASS
python scripts\prepare_external_alpha_first_recipient_send_workspace.py -> PASS
python scripts\check_external_alpha_first_recipient_send_preflight.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_manual_send_go.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_pre_send_sequence.py -> expected FAIL/BLOCKED
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS, send BLOCKED
```

## 2026-05-18 Dispatch-Record Policy Cleanup Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send after the operator fills the private recipient/channel files. The actual send is still blocked by design.

This refresh cleaned the dispatch-record gate:

- `scripts/check_external_alpha_dispatch_record.py` now has one `_copy_paste_message_policy` implementation.
- The stale Korean/mojibake copy-paste policy branch was removed.
- Dispatch-record verifier hash/safety-check errors are readable English.
- `tests/test_external_alpha_dispatch_record.py` now asserts the readable verifier errors.

Current chain:

- External alpha ZIP sha256: `20d4a8549cfb0052095ebe8a24bbe94b4c681f5bff085f68d08d8ef5c7f7bb1c`
- Send-ready: `GO`, body sha256 `74ac7f8fc50cc37df83d8841258a0278eda38a44dfbc3abe4ed2c8ef5985a144`
- Handoff body sha256: `d37acfe4c1368079dc7c8ce411a02fdcbe5a6046a2ba986d3e881c92135661a9`
- Operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `32d6e446508045233c6e8daf818cdb85fecf2cfece9d11f23e45274999db1d6a`
- Final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts
- First-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `9386ce5a493c6187801da437d38cad332fd5b573c9ac29bdc51cedacddec3a0a`

Verification added in this refresh:

```text
python -m py_compile scripts\check_external_alpha_dispatch_record.py tests\test_external_alpha_dispatch_record.py
python -m pytest -q tests\test_external_alpha_dispatch_record.py -> 11 passed
python -m pytest -q tests\test_external_alpha_send_chain_audit.py tests\test_external_alpha_operator_dispatch_packet.py -> 12 passed
python -m pytest -q tests\test_external_alpha_first_recipient_operator_status.py -> 12 passed
python scripts\verify_platform_alpha.py -> PASS
python scripts\verify_external_alpha_release.py -> PASS
python scripts\check_external_alpha_dispatch_record.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS
```

## 2026-05-18 Handoff Cleanup Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send after the operator fills the private recipient/channel files. The actual send is still blocked by design.

This refresh cleaned the release handoff generator:

- `scripts/prepare_external_alpha_handoff.py` no longer contains stale mojibake recipient steps, duplicate `_copy_paste_message`, duplicate `_handoff_checks`, or broken defaults that are later overwritten.
- `tests/test_external_alpha_handoff.py` now asserts readable verifier errors.
- The final release chain was regenerated after the handoff cleanup.

Current chain:

- External alpha ZIP sha256: `ea331c09ce96dbf4a6a3d0282e75c59062fd31f6740212ca88634266a1d71eca`
- Send-ready: `GO`, body sha256 `20dce0e258c4cec13d3da223626d7c10303479f1a24d0b6219b7c1a7b0338673`
- Handoff body sha256: `83d12b96af919d9f5001f5f4b4db5a00e465b3a8e374255b08b05ccd9ceeee6c`
- Operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `9aadc8b84f6a07746ce04be93f6e33c5d371e4481a31327701da498009cedfd5`
- Final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts
- First-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `b8bb3bbe31b7a09cf6fb95d99d6730338a2c07f6d5a8f04faea1634fe06663e7`

Verification added in this refresh:

```text
python -m py_compile scripts\prepare_external_alpha_handoff.py tests\test_external_alpha_handoff.py scripts\check_external_alpha_send_ready.py
python -m pytest -q tests\test_external_alpha_handoff.py tests\test_external_alpha_send_ready.py -> 7 passed
python -m pytest -q tests\test_external_alpha_handoff.py tests\test_external_alpha_send_ready.py tests\test_external_alpha_diagnostics.py -> 10 passed
python -m pytest -q tests\test_external_alpha_release_bundle.py tests\test_external_alpha_install_surface.py -> 19 passed
python -m pytest -q tests\test_external_alpha_first_recipient_operator_status.py -> 12 passed
python scripts\verify_platform_alpha.py -> PASS
python scripts\verify_external_alpha_release.py -> PASS
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS
```

## 2026-05-18 Send-Ready/Diagnostics Cleanup Refresh

Verdict: external alpha remains ready for exactly one manual first-recipient alpha send, with the actual send still blocked until the operator fills the two local-only private fields. The release operator scripts are cleaner now: `check_external_alpha_send_ready.py` and `collect_external_alpha_diagnostics.py` no longer contain duplicate JSON keys, duplicate verifier functions, stale mojibake checks, or mojibake verifier messages.

- Current external alpha ZIP sha256: `6fc94c92aaa2ea7ce1fdae76e26feb94eff93c91053fc2c0abfe79e2edadb363`.
- Current send-ready: `GO`, body sha256 `6b18127142350043691e1265600d2c22d068e5b98aaddc6680cf9215406f0e4b`.
- Current operator dispatch packet: `READY_TO_SEND_ONE`, body sha256 `40554a68148a5dd27dce6a61b81333f481a65b7df40039521c503fc5eb2839bd`.
- Current final send-chain audit: `READY_TO_SEND_ONE`, 12 artifacts.
- Current first-recipient operator status: `FILL_PRIVATE_FIELDS`, `send_state=BLOCKED`, `manual_send_allowed=false`, body sha256 `5e17c090f6c4a11be397e482163b7b3edf5b665e75917c34bdaec151eba806e3`.
- Expected blocked private gates remain: `recipient_private_ready`, `operator_note_names_channel`, `operator_note_confirms_release_hash`.

Verification added in this refresh:

```text
python -m py_compile scripts\check_external_alpha_send_ready.py scripts\collect_external_alpha_diagnostics.py tests\test_external_alpha_send_ready.py tests\test_external_alpha_diagnostics.py
python -m pytest -q tests\test_external_alpha_send_ready.py tests\test_external_alpha_diagnostics.py -> 7 passed
python -m pytest -q tests\test_external_alpha_release_bundle.py tests\test_external_alpha_install_surface.py -> 19 passed
python -m pytest -q tests\test_external_alpha_first_recipient_operator_status.py -> 12 passed
python scripts\verify_platform_alpha.py -> PASS
python scripts\verify_external_alpha_release.py -> PASS
python scripts\check_external_alpha_send_ready.py -> PASS
python scripts\smoke_external_alpha_release_bundle.py -> PASS
python scripts\prepare_external_alpha_operator_dispatch_packet.py -> PASS
python scripts\audit_external_alpha_send_chain.py -> PASS
python scripts\check_external_alpha_first_recipient_operator_status.py -> PASS, FILL_PRIVATE_FIELDS
```
