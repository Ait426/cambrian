from __future__ import annotations

import json
import shutil
import subprocess
import hashlib
from pathlib import Path

import pytest

from scripts.check_external_alpha_recipient_checkpoint import (
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)
from scripts.check_external_alpha_pilot_iteration import (
    check_pilot_iteration,
    verify_pilot_iteration_file,
)


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "web" / "platform" / "index.html"


def _read_platform() -> str:
    return PLATFORM.read_text(encoding="utf-8")


def _extract_const_line(source: str, name: str) -> str:
    marker = f"const {name} = "
    start = source.index(marker)
    end = source.index("\n", start)
    return source[start:end].strip()


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace_start = source.index("{", start)
    depth = 0
    for index in range(brace_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract JavaScript function: {name}")


def _platform_receipt_js_source() -> str:
    source = _read_platform()
    return "\n\n".join(
        [
            _extract_const_line(source, "BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA"),
            _extract_function(source, "lineageVerificationReportIsPass"),
            _extract_function(source, "currentPassingLineageVerificationReport"),
            _extract_function(source, "builderGoldPathReceiptState"),
            _extract_function(source, "renderBuilderGoldPathReceiptSummary"),
            _extract_function(source, "downloadBuilderGoldPathShareReceipt"),
        ]
    )


def _gold_path_runtime_fixture() -> dict:
    hex64 = "a" * 64
    return {
        "records": [
            {
                "agent_id": "document-organizer",
                "version_label": "v1-builder",
                "lifecycle_stage": "builder_private_draft",
                "source": "builder",
                "bundle": {"generated_by": "web/platform/index.html"},
                "private_debug_path": "C:/Users/private/should-not-leak",
            },
            {
                "agent_id": "document-organizer",
                "version_label": "v2-promoted",
                "lifecycle_stage": "promoted_private_version",
                "source": "evolution_handoff",
                "fingerprint": hex64,
                "bundle": {"generated_by": "web/platform/index.html"},
            },
        ],
        "audits": [
            {
                "agent_id": "document-organizer",
                "version_label": "v2-promoted",
                "candidate_pack_hash": "b" * 64,
                "promoted_pack_hash": hex64,
                "diff_report_hash": "c" * 64,
                "record_fingerprint": "d" * 64,
                "record": {
                    "source": {
                        "candidate_diff_status": "review_pass_not_promoted",
                    },
                },
            },
        ],
        "lineage_report": {
            "report_kind": "private_hub_lineage_card_verifier_report_v0_1",
            "status": "pass",
            "effect": "report_only",
            "agent_id": "document-organizer",
            "version_label": "v2-promoted",
            "receipt_checksum": "lvr-12345678",
            "side_effects": {
                "hub_storage_write": False,
                "promotion_audit_storage_write": False,
                "runner_handoff_write": False,
                "installs_or_runs_agent": False,
            },
            "report_privacy": {
                "stores_raw_card": False,
                "stores_raw_inputs": False,
                "stores_raw_outputs": False,
                "stores_secrets": False,
                "echoes_non_lineage_identity": False,
            },
            "checks": [
                {"name": "content_hash_matches_hub", "status": "pass"},
                {"name": "audit_link_matches_hub", "status": "pass"},
            ],
        },
    }


def _write_platform_generated_builder_gold_path_share_receipt(path: Path, tmp_path: Path) -> Path:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not available for the platform receipt runtime contract test.")

    script = f"""
const assert = require('assert');
const fs = require('fs');
const fixture = {json.dumps(_gold_path_runtime_fixture(), ensure_ascii=False)};
let report = fixture.lineage_report;
const hubVerificationSummary = {{ hidden: true, innerHTML: '' }};
const hubImportStatus = {{ textContent: '' }};

function readHubRecords() {{
  return fixture.records;
}}

function readPromotionAuditRecords() {{
  return fixture.audits;
}}

function promotionAuditsForHubRecord(audits, record) {{
  return audits.filter((audit) => audit.agent_id === record.agent_id && audit.version_label === record.version_label);
}}

function currentVerificationReportPayload() {{
  return report;
}}

function promotionAuditMatchesHubRecord(audit, record) {{
  return Boolean(audit && record && audit.agent_id === record.agent_id && audit.version_label === record.version_label && audit.promoted_pack_hash === record.fingerprint);
}}

function looksLikeSha256(value) {{
  return /^[a-f0-9]{{64}}$/.test(String(value || ''));
}}

function escapeHtml(value) {{
  return String(value || '');
}}

function downloadJson() {{}}

{_platform_receipt_js_source()}

const state = builderGoldPathReceiptState();
assert.strictEqual(state.ready, true);
fs.writeFileSync(process.argv[2], JSON.stringify(state.receipt, null, 2) + '\\n', 'utf8');
"""
    script_path = tmp_path / "write_platform_gold_path_receipt.js"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(script_path), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return path


def test_platform_generated_receipt_closes_external_alpha_recipient_checkpoint(tmp_path: Path) -> None:
    receipt_path = _write_platform_generated_builder_gold_path_share_receipt(
        tmp_path / "external_alpha_builder_gold_path_share_receipt.json",
        tmp_path,
    )
    expected_receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    result = check_recipient_checkpoint(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_sha256="c" * 64,
        builder_gold_path_share_receipt=receipt_path,
    )
    json_path = Path(result["recipient_checkpoint_json"])
    payload = verify_recipient_checkpoint_file(json_path)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert result["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["shared_checkpoint"]["builder_gold_path"]["present"] is True
    assert payload["shared_checkpoint"]["builder_gold_path"]["sha256"] == expected_receipt_hash
    assert payload["shared_checkpoint"]["builder_gold_path"]["checks_all_true"] is True
    assert payload["shared_checkpoint"]["builder_gold_path"]["capabilities_all_true"] is True
    assert all(payload["shared_checkpoint"]["builder_gold_path"]["capabilities_verified"].values())
    assert payload["private_checkpoint_fingerprints"]["builder_gold_path_share_receipt_sha256"] == expected_receipt_hash
    assert payload["metrics"]["builder_gold_path_confirmed"] is True
    assert all(payload["metrics"]["builder_gold_path_capabilities_verified"].values())
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["success_rate_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert payload["recipient_checkpoint_checks"]["builder_gold_path_receipt_valid_or_absent"] is True
    assert payload["recipient_checkpoint_checks"]["builder_gold_path_claim_boundaries_locked"] is True
    assert str(receipt_path) not in serialized
    assert "C:/Users/private/should-not-leak" not in serialized


def test_platform_generated_receipt_can_drive_controlled_pilot_iteration(tmp_path: Path) -> None:
    receipt_path = _write_platform_generated_builder_gold_path_share_receipt(
        tmp_path / "external_alpha_builder_gold_path_share_receipt.json",
        tmp_path,
    )
    expected_receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    result = check_pilot_iteration(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_sha256="c" * 64,
        builder_gold_path_share_receipt=receipt_path,
        feedback_private_sha256="d" * 64,
        issue_intake_private_sha256="e" * 64,
        operator_decision="continue",
        operator_note_private_sha256="f" * 64,
        outcome_tag="completed_gold_path",
        friction_tags=["none"],
        missing_skill_tags=["none"],
    )
    iteration_json = Path(result["pilot_iteration_json"])
    iteration_payload = verify_pilot_iteration_file(iteration_json)
    checkpoint_payload = json.loads(
        (tmp_path / "cambrian-agent-platform-external-alpha-recipient-checkpoint.json").read_text(encoding="utf-8")
    )
    evidence_payload = json.loads(
        (tmp_path / "cambrian-agent-platform-external-alpha-pilot-evidence.json").read_text(encoding="utf-8")
    )
    review_payload = json.loads(
        (tmp_path / "cambrian-agent-platform-external-alpha-pilot-review.json").read_text(encoding="utf-8")
    )

    assert result["status"] == "next_single_pilot_ready"
    assert result["verdict"] == "SEND_ONE_MORE"
    assert checkpoint_payload["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert checkpoint_payload["shared_checkpoint"]["builder_gold_path"]["sha256"] == expected_receipt_hash
    assert review_payload["recipient_checkpoint"]["builder_gold_path_share_receipt_sha256"] == expected_receipt_hash
    assert evidence_payload["verdict"] == "READY_FOR_DECISION"
    assert evidence_payload["pilot_learning_summary"]["outcome_tag"] == "completed_gold_path"
    assert any(
        item["kind"] == "builder_gold_path_share_receipt" and item["sha256"] == expected_receipt_hash
        for item in evidence_payload["artifact_chain"]
    )
    assert iteration_payload["pilot_decision"]["selected"] == "continue"
    assert iteration_payload["pilot_learning_summary"]["outcome_tag"] == "completed_gold_path"
    assert iteration_payload["iteration_plan"]["max_next_participants"] == 1
    assert iteration_payload["iteration_plan"]["scaling_allowed"] is False
    assert iteration_payload["publish_boundary"]["cohort_scaling_allowed"] is False
    assert iteration_payload["publish_boundary"]["marketplace_listing_allowed"] is False
    assert iteration_payload["metrics"]["success_rate"] is None
    assert iteration_payload["metrics"]["proof_claim_allowed"] is False
    assert iteration_payload["metrics"]["sale_ready"] is False
    assert iteration_payload["pilot_iteration_checks"]["continue_limited_to_one"] is True

    serialized = (
        json.dumps(checkpoint_payload, ensure_ascii=False)
        + json.dumps(review_payload, ensure_ascii=False)
        + json.dumps(evidence_payload, ensure_ascii=False)
        + json.dumps(iteration_payload, ensure_ascii=False)
        + iteration_json.with_suffix(".md").read_text(encoding="utf-8")
    )
    assert str(receipt_path) not in serialized
    assert "C:/Users/private/should-not-leak" not in serialized
    assert "success_rate\": 1" not in serialized


def test_builder_gold_path_receipt_runtime_contract(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not available for the platform receipt runtime contract test.")

    source = _read_platform()
    js_parts = [
        _extract_const_line(source, "BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA"),
        _extract_function(source, "lineageVerificationReportIsPass"),
        _extract_function(source, "currentPassingLineageVerificationReport"),
        _extract_function(source, "builderGoldPathReceiptState"),
        _extract_function(source, "renderBuilderGoldPathReceiptSummary"),
        _extract_function(source, "downloadBuilderGoldPathShareReceipt"),
    ]
    js_source = "\n\n".join(js_parts)

    hex64 = "a" * 64
    fixture = {
        "records": [
            {
                "agent_id": "document-organizer",
                "version_label": "v1-builder",
                "lifecycle_stage": "builder_private_draft",
                "source": "builder",
                "bundle": {"generated_by": "web/platform/index.html"},
                "private_debug_path": "C:/Users/private/should-not-leak",
            },
            {
                "agent_id": "document-organizer",
                "version_label": "v2-promoted",
                "lifecycle_stage": "promoted_private_version",
                "source": "evolution_handoff",
                "fingerprint": hex64,
                "bundle": {"generated_by": "web/platform/index.html"},
            },
        ],
        "audits": [
            {
                "agent_id": "document-organizer",
                "version_label": "v2-promoted",
                "candidate_pack_hash": "b" * 64,
                "promoted_pack_hash": hex64,
                "diff_report_hash": "c" * 64,
                "record_fingerprint": "d" * 64,
                "record": {
                    "source": {
                        "candidate_diff_status": "review_pass_not_promoted",
                    },
                },
            },
        ],
        "lineage_report": {
            "report_kind": "private_hub_lineage_card_verifier_report_v0_1",
            "status": "pass",
            "effect": "report_only",
            "agent_id": "document-organizer",
            "version_label": "v2-promoted",
            "receipt_checksum": "lvr-12345678",
            "side_effects": {
                "hub_storage_write": False,
                "promotion_audit_storage_write": False,
                "runner_handoff_write": False,
                "installs_or_runs_agent": False,
            },
            "report_privacy": {
                "stores_raw_card": False,
                "stores_raw_inputs": False,
                "stores_raw_outputs": False,
                "stores_secrets": False,
                "echoes_non_lineage_identity": False,
            },
            "checks": [
                {"name": "content_hash_matches_hub", "status": "pass"},
                {"name": "audit_link_matches_hub", "status": "pass"},
            ],
        },
    }

    script = f"""
const assert = require('assert');
const fixture = {json.dumps(fixture, ensure_ascii=False)};
let report = fixture.lineage_report;
let downloads = [];
const hubVerificationSummary = {{ hidden: true, innerHTML: '' }};
const hubImportStatus = {{ textContent: '' }};

function readHubRecords() {{
  return fixture.records;
}}

function readPromotionAuditRecords() {{
  return fixture.audits;
}}

function promotionAuditsForHubRecord(audits, record) {{
  return audits.filter((audit) => audit.agent_id === record.agent_id && audit.version_label === record.version_label);
}}

function currentVerificationReportPayload() {{
  return report;
}}

function promotionAuditMatchesHubRecord(audit, record) {{
  return Boolean(audit && record && audit.agent_id === record.agent_id && audit.version_label === record.version_label && audit.promoted_pack_hash === record.fingerprint);
}}

function looksLikeSha256(value) {{
  return /^[a-f0-9]{{64}}$/.test(String(value || ''));
}}

function escapeHtml(value) {{
  return String(value || '');
}}

function downloadJson(filename, payload) {{
  downloads.push({{ filename, payload }});
}}

{js_source}

assert.strictEqual(lineageVerificationReportIsPass(report), true);
const sideEffectReport = {{
  ...report,
  side_effects: {{ ...report.side_effects, hub_storage_write: true }},
}};
assert.strictEqual(lineageVerificationReportIsPass(sideEffectReport), false);

const state = builderGoldPathReceiptState();
assert.strictEqual(state.ready, true);
assert.deepStrictEqual(state.errors, []);
assert.strictEqual(state.receipt.schema_version, 'external_alpha_builder_gold_path_share_receipt_v0_1');
assert.strictEqual(state.receipt.status, 'passed');
assert.strictEqual(state.receipt.safe_to_share, true);
assert.strictEqual(state.receipt.proof_claim_allowed, false);
assert.strictEqual(state.receipt.success_rate_claim_allowed, false);
assert.strictEqual(state.receipt.sale_ready, false);
assert.strictEqual(state.receipt.checks.builder_golden_path_completed, true);
assert.strictEqual(state.receipt.checks.manual_no_api_runner_used, true);
assert.strictEqual(state.receipt.checks.promotion_audit_lineage_verified, true);
assert.strictEqual(state.receipt.checks.raw_browser_storage_excluded, true);
assert.ok(Object.values(state.receipt.capabilities_verified).every(Boolean));
assert.strictEqual(state.receipt.evidence_basis.evidence_kind, 'browser_share_safe_summary_v0_1');
assert.strictEqual(state.receipt.evidence_basis.download_paths_excluded, true);
assert.strictEqual(state.receipt.evidence_basis.lineage_report_receipt_checksum, 'lvr-12345678');
assert.strictEqual(JSON.stringify(state.receipt).includes('C:/Users/private'), false);

downloadBuilderGoldPathShareReceipt();
assert.strictEqual(downloads.length, 1);
assert.strictEqual(downloads[0].filename, 'external_alpha_builder_gold_path_share_receipt.json');
assert.strictEqual(downloads[0].payload.schema_version, state.receipt.schema_version);
assert.strictEqual(downloads[0].payload.status, state.receipt.status);
assert.strictEqual(downloads[0].payload.safe_to_share, state.receipt.safe_to_share);
assert.deepStrictEqual(downloads[0].payload.checks, state.receipt.checks);
assert.deepStrictEqual(downloads[0].payload.capabilities_verified, state.receipt.capabilities_verified);
assert.deepStrictEqual(downloads[0].payload.evidence_basis, state.receipt.evidence_basis);

report = {{ ...fixture.lineage_report, status: 'fail' }};
downloads = [];
const blocked = builderGoldPathReceiptState();
assert.strictEqual(blocked.ready, false);
assert.strictEqual(blocked.receipt.capabilities_verified.private_hub_lineage_verified, false);
downloadBuilderGoldPathShareReceipt();
assert.strictEqual(downloads.length, 0);
assert.ok(hubImportStatus.textContent.includes('gold path receipt'));
"""

    script_path = tmp_path / "gold_path_receipt_runtime_test.js"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [node, str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
