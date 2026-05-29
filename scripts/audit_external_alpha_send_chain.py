"""Non-mutating final audit for the external alpha send chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, INCLUDED_FILES, RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import DISPATCH_RECORD_JSON_NAME, verify_dispatch_record_file
from scripts.check_external_alpha_pilot_decision import PILOT_DECISION_JSON_NAME, verify_pilot_decision_file
from scripts.check_external_alpha_pilot_evidence import (
    DIAGNOSTICS_NAME,
    PILOT_EVIDENCE_JSON_NAME,
    verify_diagnostics_file,
    verify_pilot_evidence_file,
)
from scripts.check_external_alpha_pilot_iteration import PILOT_ITERATION_JSON_NAME, verify_pilot_iteration_file
from scripts.check_external_alpha_pilot_ready import PILOT_READY_JSON_NAME, verify_pilot_ready_file
from scripts.check_external_alpha_pilot_review import PILOT_REVIEW_JSON_NAME, verify_pilot_review_file
from scripts.check_external_alpha_recipient_checkpoint import (
    RECIPIENT_CHECKPOINT_JSON_NAME,
    verify_recipient_checkpoint_file,
)
from scripts.check_external_alpha_send_ready import SEND_READY_JSON_NAME, verify_send_ready_file
from scripts.prepare_external_alpha_handoff import HANDOFF_JSON_NAME, RECEIPT_NAME, verify_handoff_file
from scripts.smoke_external_alpha_manual_send_go_rehearsal import (
    MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
    verify_manual_send_go_rehearsal_receipt_file,
)
from scripts.smoke_external_alpha_release_bundle import SMOKE_RECEIPT_NAME, verify_bundle_smoke_receipt_file
from scripts.verify_external_alpha_release import DEFAULT_MANIFEST, DEFAULT_ZIP, verify_release, verify_shareable_receipt_file


PACKET_JSON_NAME = f"{RELEASE_SLUG}-operator-dispatch-packet.json"
OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME = f"{RELEASE_SLUG}-operator-send-bypass-audit.json"
OPERATOR_DISPATCH_PACKET_SCHEMA_VERSION = "external_alpha_operator_dispatch_packet_v0_1"
OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION = "external_alpha_operator_send_bypass_audit_v0_1"
PREFLIGHT_RECEIPT_NAME = "external-alpha-first-recipient-send-preflight-receipt.json"
PRIVATE_WORKSPACE_RECEIPT_NAME = "external-alpha-private-pilot-workspace-scaffold-receipt.json"
MOJIBAKE_MARKERS = ("�", "?뺤", "泥", "蹂대", "臾몄", "瑜?", "媛")

EXPECTED_PRESEND_VERDICTS = {
    "send_ready": "GO",
    "pilot_ready": "GO",
    "dispatch_record": "READY_TO_SEND_ONE",
    "recipient_checkpoint": "WAITING_FOR_RECIPIENT",
    "pilot_review": "WAITING_FOR_EVIDENCE",
    "pilot_evidence": "NO_DECISION",
    "pilot_decision": "NO_DECISION",
    "pilot_iteration": "NO_ITERATION",
}

logger = logging.getLogger(__name__)


class SendChainAuditError(Exception):
    """External alpha final send-chain audit failed."""


def audit_send_chain(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    require_operator_bypass_audit: bool = True,
    require_manual_send_go_rehearsal: bool = True,
) -> dict[str, Any]:
    """Read existing dist artifacts and verify the final pre-send chain without writing files."""
    output_dir = output_dir.resolve()
    zip_path = output_dir / DEFAULT_ZIP.name
    manifest_path = output_dir / DEFAULT_MANIFEST.name

    release = verify_release(zip_path=zip_path, manifest_path=manifest_path)
    archive_sha256 = str(release.get("archive_sha256") or "")
    if _sha256_file(zip_path) != archive_sha256:
        raise SendChainAuditError("release ZIP sha256 does not match verifier result.")

    try:
        bundle_smoke = verify_bundle_smoke_receipt_file(output_dir / SMOKE_RECEIPT_NAME)
    except Exception as exc:  # noqa: BLE001 - convert to the final audit failure contract.
        raise SendChainAuditError(f"bundle smoke receipt verification failed: {exc}") from exc

    receipt = verify_shareable_receipt_file(output_dir / RECEIPT_NAME)
    handoff = verify_handoff_file(output_dir / HANDOFF_JSON_NAME)
    send_ready = verify_send_ready_file(output_dir / SEND_READY_JSON_NAME)
    pilot_ready = verify_pilot_ready_file(output_dir / PILOT_READY_JSON_NAME)
    dispatch_record = verify_dispatch_record_file(output_dir / DISPATCH_RECORD_JSON_NAME)
    recipient_checkpoint = verify_recipient_checkpoint_file(output_dir / RECIPIENT_CHECKPOINT_JSON_NAME)
    pilot_review = verify_pilot_review_file(output_dir / PILOT_REVIEW_JSON_NAME)
    pilot_evidence = verify_pilot_evidence_file(output_dir / PILOT_EVIDENCE_JSON_NAME)
    pilot_decision = verify_pilot_decision_file(output_dir / PILOT_DECISION_JSON_NAME)
    pilot_iteration = verify_pilot_iteration_file(output_dir / PILOT_ITERATION_JSON_NAME)
    operator_packet = _read_operator_packet(output_dir / PACKET_JSON_NAME) if require_operator_bypass_audit else None
    operator_bypass_audit = (
        _verify_operator_send_bypass_audit_file(output_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME)
        if require_operator_bypass_audit
        else None
    )
    manual_send_go_rehearsal = (
        _verify_manual_send_go_rehearsal_file(output_dir / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME)
        if require_operator_bypass_audit and require_manual_send_go_rehearsal
        else None
    )

    diagnostics_path = output_dir / DIAGNOSTICS_NAME
    diagnostics_verified = diagnostics_path.is_file()
    if diagnostics_verified:
        verify_diagnostics_file(diagnostics_path)

    payloads = {
        "handoff": handoff,
        "send_ready": send_ready,
        "pilot_ready": pilot_ready,
        "dispatch_record": dispatch_record,
        "recipient_checkpoint": recipient_checkpoint,
        "pilot_review": pilot_review,
        "pilot_evidence": pilot_evidence,
        "pilot_decision": pilot_decision,
        "pilot_iteration": pilot_iteration,
    }
    expected_hash_by_kind = {
        "release_zip": archive_sha256,
        "bundle_smoke_receipt_json": bundle_smoke["receipt_body_sha256"],
        "receipt_json": receipt["receipt_body_sha256"],
        "handoff_json": handoff["handoff_body_sha256"],
        "send_ready_json": send_ready["send_ready_body_sha256"],
        "pilot_ready_json": pilot_ready["pilot_ready_body_sha256"],
        "dispatch_record_json": dispatch_record["dispatch_record_body_sha256"],
        "recipient_checkpoint_json": recipient_checkpoint["recipient_checkpoint_body_sha256"],
        "pilot_review_json": pilot_review["pilot_review_body_sha256"],
        "pilot_evidence_json": pilot_evidence["pilot_evidence_body_sha256"],
        "pilot_decision_json": pilot_decision["pilot_decision_body_sha256"],
        "pilot_iteration_json": pilot_iteration["pilot_iteration_body_sha256"],
    }

    checks = {
        "release_verified": release.get("status") == "pass",
        "release_sources_match_current_manifest": _source_files_match_release_manifest(manifest_path),
        "diagnostics_verified_or_not_required": diagnostics_verified,
        "bundle_smoke_verified": bundle_smoke.get("status") == "pass",
        "bundle_smoke_release_hash_matches": bundle_smoke.get("release_bundle", {}).get("archive_sha256")
        == archive_sha256,
        "receipt_matches_handoff": handoff.get("receipt", {}).get("body_sha256") == receipt["receipt_body_sha256"],
        "receipt_matches_send_ready": send_ready.get("receipt", {}).get("body_sha256")
        == receipt["receipt_body_sha256"],
        "send_ready_receipt_cross_check": send_ready.get("checks", {}).get(
            "handoff_receipt_body_matches_current_receipt"
        )
        is True,
        "single_recipient_ready": dispatch_record.get("verdict") == "READY_TO_SEND_ONE",
        "recipient_not_recorded_yet": recipient_checkpoint.get("verdict") == "WAITING_FOR_RECIPIENT",
        "evidence_not_overclaimed": pilot_review.get("verdict") == "WAITING_FOR_EVIDENCE"
        and pilot_evidence.get("verdict") == "NO_DECISION"
        and pilot_decision.get("verdict") == "NO_DECISION"
        and pilot_iteration.get("verdict") == "NO_ITERATION",
        "all_release_hashes_match": all(
            _payload_release_hash(payload) == archive_sha256 for payload in payloads.values()
        ),
        "expected_presend_verdicts": all(
            payloads[name].get("verdict") == verdict for name, verdict in EXPECTED_PRESEND_VERDICTS.items()
        ),
        "artifact_chains_match_payload_hashes": all(
            _artifact_chain_matches(payload, expected_hash_by_kind) for payload in payloads.values()
        ),
        "final_chain_complete": _final_chain_complete(pilot_iteration, expected_hash_by_kind),
    }
    if require_operator_bypass_audit:
        checks.update(
            {
                "operator_packet_ready_to_send_one": operator_packet is not None
                and operator_packet.get("verdict") == "READY_TO_SEND_ONE",
                "operator_packet_release_hash_matches": operator_packet is not None
                and _payload_release_hash(operator_packet) == archive_sha256,
                "operator_packet_self_checks_passed": operator_packet is not None
                and _operator_packet_self_checks_passed(operator_packet),
                "operator_packet_recalculated_self_checks_match": operator_packet is not None
                and _operator_packet_recalculated_self_checks_match(operator_packet),
                "operator_packet_post_send_real_preflight_gate": operator_packet is not None
                and _operator_packet_post_send_rehearsal(operator_packet).get("preflight_generated_by_real_gate")
                is True
                and operator_packet.get("operator_dispatch_packet_checks", {}).get(
                    "post_send_rehearsal_real_preflight_gate"
                )
                is True,
                "operator_packet_post_send_template_contract": operator_packet is not None
                and _operator_packet_post_send_rehearsal(operator_packet).get("operator_note_template_used")
                is True
                and _operator_packet_post_send_rehearsal(operator_packet).get(
                    "operator_note_template_preflight_contract"
                )
                is True
                and operator_packet.get("operator_dispatch_packet_checks", {}).get(
                    "post_send_rehearsal_operator_note_template_contract"
                )
                is True,
                "operator_send_bypass_audit_verified": operator_bypass_audit is not None
                and operator_bypass_audit.get("status") == "pass"
                and operator_bypass_audit.get("verdict") == "NO_OPERATOR_PREFLIGHT_BYPASS",
                "operator_send_bypass_audit_release_hash_matches": operator_bypass_audit is not None
                and _payload_release_hash(operator_bypass_audit) == archive_sha256,
                "operator_send_bypass_audit_packet_hash_matches": operator_bypass_audit is not None
                and operator_packet is not None
                and operator_bypass_audit.get("operator_packet", {}).get("body_sha256")
                == operator_packet.get("operator_dispatch_packet_body_sha256"),
                "manual_send_go_rehearsal_verified": not require_manual_send_go_rehearsal
                or (
                    manual_send_go_rehearsal is not None
                    and manual_send_go_rehearsal.get("status") == "pass"
                    and manual_send_go_rehearsal.get("verdict") == "REHEARSAL_PASS"
                ),
                "manual_send_go_rehearsal_release_hash_matches": not require_manual_send_go_rehearsal
                or (manual_send_go_rehearsal is not None and _payload_release_hash(manual_send_go_rehearsal) == archive_sha256),
                "manual_send_go_rehearsal_no_real_manual_send_claim": not require_manual_send_go_rehearsal
                or (manual_send_go_rehearsal is not None and manual_send_go_rehearsal.get("real_manual_send") is False),
                "manual_send_go_rehearsal_no_real_recipient_claim": not require_manual_send_go_rehearsal
                or (
                    manual_send_go_rehearsal is not None
                    and manual_send_go_rehearsal.get("real_recipient_evidence") is False
                ),
                "manual_send_go_rehearsal_template_contract": not require_manual_send_go_rehearsal
                or (
                    manual_send_go_rehearsal is not None
                    and manual_send_go_rehearsal.get("checks", {}).get("operator_note_template_used") is True
                    and manual_send_go_rehearsal.get("checks", {}).get("operator_note_template_preflight_contract")
                    is True
                ),
                "manual_send_go_rehearsal_operator_status_ready": not require_manual_send_go_rehearsal
                or (
                    manual_send_go_rehearsal is not None
                    and manual_send_go_rehearsal.get("checks", {}).get("operator_status_ready_to_send") is True
                    and manual_send_go_rehearsal.get("rehearsed_flow", {}).get("operator_status_verdict")
                    == "READY_TO_MANUALLY_SEND_ONE"
                ),
                "manual_send_go_rehearsal_operator_status_packet_bound": not require_manual_send_go_rehearsal
                or (
                    manual_send_go_rehearsal is not None
                    and manual_send_go_rehearsal.get("checks", {}).get(
                        "operator_status_manual_send_go_packet_bound"
                    )
                    is True
                    and manual_send_go_rehearsal.get("rehearsed_flow", {}).get(
                        "operator_status_manual_send_go_packet_bound"
                    )
                    is True
                ),
            }
        )
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise SendChainAuditError("final send-chain audit failed: " + ", ".join(failed))

    return {
        "status": "pass",
        "verdict": "READY_TO_SEND_ONE",
        "zip_file": f"{RELEASE_SLUG}.zip",
        "archive_sha256": archive_sha256,
        "bundle_smoke_receipt_body_sha256": bundle_smoke["receipt_body_sha256"],
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "operator_packet_body_sha256": (
            operator_packet["operator_dispatch_packet_body_sha256"] if operator_packet is not None else None
        ),
        "operator_send_bypass_audit_required": require_operator_bypass_audit,
        "manual_send_go_rehearsal_required": require_operator_bypass_audit and require_manual_send_go_rehearsal,
        "operator_send_bypass_audit_body_sha256": (
            operator_bypass_audit["operator_send_bypass_audit_body_sha256"]
            if operator_bypass_audit is not None
            else None
        ),
        "manual_send_go_rehearsal_body_sha256": (
            manual_send_go_rehearsal["manual_send_go_rehearsal_receipt_body_sha256"]
            if manual_send_go_rehearsal is not None
            else None
        ),
        "final_chain_depth": len(pilot_iteration.get("artifact_chain", [])),
        "diagnostics_verified": diagnostics_verified,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the external alpha dist send chain without rewriting artifacts.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Artifact directory. Defaults to dist.")
    parser.add_argument(
        "--skip-operator-bypass-audit",
        action="store_true",
        help="Internal packet-build escape hatch. Final release gates should not use this.",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        result = audit_send_chain(
            Path(args.output_dir),
            require_operator_bypass_audit=not args.skip_operator_bypass_audit,
        )
    except Exception as exc:  # noqa: BLE001 - present the blocking audit reason directly.
        logger.error("[FAIL] external alpha final send-chain audit: %s", exc)
        return 1

    logger.info("[PASS] external alpha final send-chain audit")
    logger.info("verdict : %s", result["verdict"])
    logger.info("zip     : %s", result["zip_file"])
    logger.info("sha256  : %s", result["archive_sha256"])
    logger.info("smoke   : %s", result["bundle_smoke_receipt_body_sha256"])
    logger.info("receipt : %s", result["receipt_body_sha256"])
    logger.info("bypass  : %s", result["operator_send_bypass_audit_body_sha256"])
    logger.info("manual : %s", result["manual_send_go_rehearsal_body_sha256"])
    logger.info("chain   : %s artifacts", result["final_chain_depth"])
    return 0


def _payload_release_hash(payload: dict[str, Any]) -> str | None:
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    value = release.get("archive_sha256")
    return value if isinstance(value, str) else None


def _read_operator_packet(path: Path) -> dict[str, Any]:
    payload = _read_json(path, "operator dispatch packet")
    if payload.get("schema_version") != OPERATOR_DISPATCH_PACKET_SCHEMA_VERSION:
        raise SendChainAuditError("operator dispatch packet schema_version mismatch.")
    if payload.get("safe_to_share") is not True:
        raise SendChainAuditError("operator dispatch packet is not safe_to_share.")
    if payload.get("verdict") != "READY_TO_SEND_ONE":
        raise SendChainAuditError("operator dispatch packet is not READY_TO_SEND_ONE.")
    body_hash = payload.get("operator_dispatch_packet_body_sha256")
    if not _looks_like_sha256(body_hash):
        raise SendChainAuditError("operator dispatch packet body hash is missing.")
    if body_hash != _operator_packet_body_sha256(payload):
        raise SendChainAuditError("operator dispatch packet body hash mismatch.")
    if not _operator_packet_self_checks_passed(payload):
        raise SendChainAuditError("operator dispatch packet self-checks failed.")
    if not _operator_packet_recalculated_self_checks_match(payload):
        raise SendChainAuditError("operator dispatch packet recalculated self-checks mismatch.")
    return payload


def _verify_manual_send_go_rehearsal_file(path: Path) -> dict[str, Any]:
    try:
        return verify_manual_send_go_rehearsal_receipt_file(path)
    except Exception as exc:  # noqa: BLE001 - convert to final audit failure contract.
        raise SendChainAuditError(f"manual-send GO rehearsal receipt verification failed: {exc}") from exc


def _operator_packet_recalculated_self_checks_match(payload: dict[str, Any]) -> bool:
    stored = (
        payload.get("operator_dispatch_packet_checks")
        if isinstance(payload.get("operator_dispatch_packet_checks"), dict)
        else {}
    )
    recalculated = _operator_packet_recalculated_critical_checks(payload)
    return bool(stored) and all(stored.get(name) is True and passed is True for name, passed in recalculated.items())


def _operator_packet_recalculated_critical_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    send_once = payload.get("operator_send_once") if isinstance(payload.get("operator_send_once"), dict) else {}
    before = payload.get("required_before_send") if isinstance(payload.get("required_before_send"), dict) else {}
    before_manual = payload.get("before_manual_send") if isinstance(payload.get("before_manual_send"), dict) else {}
    after = payload.get("after_manual_send") if isinstance(payload.get("after_manual_send"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    body_hash = payload.get("operator_dispatch_packet_body_sha256")
    copy_paste_message = str(send_once.get("copy_paste_message") or "")
    post_send = _operator_packet_post_send_rehearsal(payload)
    expected_operator_packet_arg = f"--operator-packet dist\\{PACKET_JSON_NAME}"
    first_recipient_workspace_command = str(before_manual.get("prepare_first_recipient_workspace_command"))
    pre_send_preflight_command = str(before_manual.get("pre_send_preflight_command"))
    return {
        "schema_version_present": payload.get("schema_version") == OPERATOR_DISPATCH_PACKET_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready_to_send_one": payload.get("verdict") == "READY_TO_SEND_ONE",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "copy_paste_message_hash_matched": send_once.get("copy_paste_message_sha256")
        == _text_sha256(copy_paste_message),
        "copy_paste_message_names_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message,
        "copy_paste_message_ascii_only": _is_ascii(copy_paste_message),
        "copy_paste_message_mojibake_free": _is_mojibake_free(copy_paste_message),
        "manual_dispatch_only": send_once.get("script_sends_to_recipient") is False
        and send_once.get("manual_operator_dispatch_required") is True,
        "one_recipient_only": send_once.get("max_recipients") == 1,
        "post_send_rehearsal_hash_present": _looks_like_sha256(post_send.get("body_sha256")),
        "post_send_rehearsal_no_real_recipient_claim": post_send.get("real_recipient_evidence") is False,
        "post_send_rehearsal_release_hash_matched": post_send.get("release_archive_sha256")
        == release.get("archive_sha256"),
        "post_send_rehearsal_real_preflight_gate": post_send.get("preflight_generated_by_real_gate") is True,
        "post_send_rehearsal_operator_note_template_contract": post_send.get("operator_note_template_used")
        is True
        and post_send.get("operator_note_template_preflight_contract") is True,
        "pre_send_preflight_command_present": "check_external_alpha_first_recipient_send_preflight.py"
        in pre_send_preflight_command
        and "--workspace-dir <private-workspace-dir>" in pre_send_preflight_command,
        "first_recipient_workspace_command_uses_operator_packet": expected_operator_packet_arg
        in first_recipient_workspace_command,
        "pre_send_preflight_command_uses_operator_packet": expected_operator_packet_arg in pre_send_preflight_command,
        "pre_send_preflight_receipt_named": before_manual.get("expected_preflight_receipt")
        == PREFLIGHT_RECEIPT_NAME,
        "final_send_chain_audit_command_present": str(before_manual.get("final_send_chain_audit_command"))
        == "python scripts/audit_external_alpha_send_chain.py",
        "final_send_chain_audit_no_internal_skip_flag": "--skip-operator-bypass-audit"
        not in str(before_manual.get("final_send_chain_audit_command")),
        "after_send_record_command_requires_preflight": "--require-preflight-receipt"
        in str(after.get("record_command")),
        "after_send_checkpoint_command_requires_preflight": "--require-preflight-receipt"
        in str(after.get("then_checkpoint_command")),
        "private_workspace_receipt_named": after.get("private_workspace_receipt") == PRIVATE_WORKSPACE_RECEIPT_NAME,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _operator_packet_body_sha256(payload),
    }


def _operator_packet_self_checks_passed(payload: dict[str, Any]) -> bool:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    packet_checks = (
        payload.get("operator_dispatch_packet_checks")
        if isinstance(payload.get("operator_dispatch_packet_checks"), dict)
        else {}
    )
    return bool(checks) and all(value is True for value in checks.values()) and bool(packet_checks) and all(
        value is True for value in packet_checks.values()
    )


def _operator_packet_post_send_rehearsal(payload: dict[str, Any]) -> dict[str, Any]:
    required = payload.get("required_before_send") if isinstance(payload.get("required_before_send"), dict) else {}
    post_send = (
        required.get("post_send_checkpoint_rehearsal")
        if isinstance(required.get("post_send_checkpoint_rehearsal"), dict)
        else {}
    )
    return post_send


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_ascii(value: str) -> bool:
    return all(ord(char) < 128 for char in value)


def _is_mojibake_free(value: str) -> bool:
    return not any(marker in value for marker in MOJIBAKE_MARKERS)


def _verify_operator_send_bypass_audit_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path, "operator send bypass audit")
    if payload.get("schema_version") != OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION:
        raise SendChainAuditError("operator send bypass audit schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "NO_OPERATOR_PREFLIGHT_BYPASS":
        raise SendChainAuditError("operator send bypass audit did not pass.")
    if payload.get("safe_to_share") is not True:
        raise SendChainAuditError("operator send bypass audit is not safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise SendChainAuditError("operator send bypass audit checks failed.")
    audit_checks = payload.get("operator_send_bypass_audit_checks")
    if not isinstance(audit_checks, dict) or any(value is not True for value in audit_checks.values()):
        raise SendChainAuditError("operator send bypass audit self-checks failed.")
    body_hash = payload.get("operator_send_bypass_audit_body_sha256")
    if not _looks_like_sha256(body_hash):
        raise SendChainAuditError("operator send bypass audit body hash is missing.")
    if body_hash != _operator_bypass_audit_body_sha256(payload):
        raise SendChainAuditError("operator send bypass audit body hash mismatch.")
    return payload


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SendChainAuditError(f"{label} file is missing: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SendChainAuditError(f"{label} JSON parse failed: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SendChainAuditError(f"{label} JSON payload must be an object: {path.name}")
    return payload


def _operator_packet_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_dispatch_packet_body_sha256", "operator_dispatch_packet_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _operator_bypass_audit_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_send_bypass_audit_body_sha256", "operator_send_bypass_audit_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _artifact_chain_matches(payload: dict[str, Any], expected_hash_by_kind: dict[str, str]) -> bool:
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    for item in chain:
        if not isinstance(item, dict):
            return False
        kind = item.get("kind")
        if kind in expected_hash_by_kind and item.get("sha256") != expected_hash_by_kind[kind]:
            return False
    return True


def _final_chain_complete(payload: dict[str, Any], expected_hash_by_kind: dict[str, str]) -> bool:
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    chain_kinds = {item.get("kind") for item in chain if isinstance(item, dict)}
    return set(expected_hash_by_kind).issubset(chain_kinds)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files_match_release_manifest(manifest_path: Path, source_root: Path = ROOT) -> bool:
    """Return whether the current source allowlist still matches the built release manifest."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    by_path = {item.get("path"): item for item in files if isinstance(item, dict) and isinstance(item.get("path"), str)}
    for relative in INCLUDED_FILES:
        source_path = source_root / relative
        entry = by_path.get(relative.replace("\\", "/"))
        if not isinstance(entry, dict) or not source_path.is_file():
            return False
        data = source_path.read_bytes()
        if entry.get("bytes") != len(data) or entry.get("sha256") != hashlib.sha256(data).hexdigest():
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
