"""Create a one-recipient operator dispatch packet for the external alpha."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_external_alpha_send_chain import audit_send_chain  # noqa: E402
from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_dispatch_record import (  # noqa: E402
    DISPATCH_RECORD_JSON_NAME,
    DISPATCH_RECORD_MD_NAME,
    verify_dispatch_record_file,
)
from scripts.check_external_alpha_pilot_iteration import check_pilot_iteration  # noqa: E402
from scripts.check_external_alpha_pilot_ready import (  # noqa: E402
    PILOT_DISPATCH_MD_NAME,
    PILOT_READY_JSON_NAME,
    verify_pilot_ready_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import (  # noqa: E402
    PRIVATE_WORKSPACE_RECEIPT_NAME,
)
from scripts.smoke_external_alpha_post_send_checkpoint import (  # noqa: E402
    POST_SEND_REHEARSAL_RECEIPT_NAME,
    smoke_post_send_checkpoint,
    verify_post_send_rehearsal_receipt_file,
)
from scripts.smoke_external_alpha_pilot_learning_loop import (  # noqa: E402
    PILOT_LEARNING_REHEARSAL_RECEIPT_NAME,
    smoke_pilot_learning_loop,
    verify_pilot_learning_rehearsal_receipt_file,
)
from scripts.smoke_external_alpha_private_pilot_workspace import (  # noqa: E402
    PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME,
    smoke_private_pilot_workspace,
    verify_private_workspace_rehearsal_receipt_file,
)
from scripts.smoke_external_alpha_release_bundle import SMOKE_RECEIPT_NAME, verify_bundle_smoke_receipt_file  # noqa: E402


PACKET_SCHEMA_VERSION = "external_alpha_operator_dispatch_packet_v0_1"
PACKET_JSON_NAME = f"{RELEASE_SLUG}-operator-dispatch-packet.json"
PACKET_MD_NAME = f"{RELEASE_SLUG}-operator-dispatch-packet.md"
PREFLIGHT_RECEIPT_NAME = "external-alpha-first-recipient-send-preflight-receipt.json"
MANUAL_SEND_GO_RECEIPT_NAME = "external-alpha-first-recipient-manual-send-go-receipt.json"
PRE_SEND_SEQUENCE_RECEIPT_NAME = "external-alpha-first-recipient-pre-send-sequence-receipt.json"
POST_SEND_SEQUENCE_RECEIPT_NAME = "external-alpha-first-recipient-post-send-sequence-receipt.json"
OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME = f"{RELEASE_SLUG}-operator-send-bypass-audit.json"
MOJIBAKE_MARKERS = ("�", "?뺤", "泥", "蹂대", "臾몄", "瑜?", "媛")

logger = logging.getLogger(__name__)


class OperatorDispatchPacketError(RuntimeError):
    """Operator dispatch packet generation or verification failed."""


def prepare_operator_dispatch_packet(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    refresh_chain: bool = True,
    skip_build: bool = False,
) -> dict[str, Any]:
    """Create a private-safe packet that tells the operator exactly what to send once."""
    output_dir = output_dir.resolve()
    if refresh_chain:
        check_pilot_iteration(output_dir=output_dir, skip_build=skip_build)

    audit = audit_send_chain(output_dir, require_operator_bypass_audit=False)
    dispatch_record = verify_dispatch_record_file(output_dir / DISPATCH_RECORD_JSON_NAME)
    pilot_ready = verify_pilot_ready_file(output_dir / PILOT_READY_JSON_NAME)
    bundle_smoke = verify_bundle_smoke_receipt_file(output_dir / SMOKE_RECEIPT_NAME)
    smoke_private_pilot_workspace(output_dir)
    private_workspace_rehearsal = verify_private_workspace_rehearsal_receipt_file(
        output_dir / PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME
    )
    smoke_post_send_checkpoint(output_dir)
    post_send_rehearsal = verify_post_send_rehearsal_receipt_file(output_dir / POST_SEND_REHEARSAL_RECEIPT_NAME)
    smoke_pilot_learning_loop(output_dir)
    pilot_learning_rehearsal = verify_pilot_learning_rehearsal_receipt_file(
        output_dir / PILOT_LEARNING_REHEARSAL_RECEIPT_NAME
    )

    payload = _packet_payload(
        audit=audit,
        dispatch_record=dispatch_record,
        pilot_ready=pilot_ready,
        bundle_smoke=bundle_smoke,
        private_workspace_rehearsal=private_workspace_rehearsal,
        post_send_rehearsal=post_send_rehearsal,
        pilot_learning_rehearsal=pilot_learning_rehearsal,
    )
    json_path = output_dir / PACKET_JSON_NAME
    md_path = output_dir / PACKET_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_packet_markdown(payload), encoding="utf-8")
    verify_operator_dispatch_packet_file(json_path)
    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "packet_json": str(json_path),
        "packet_md": str(md_path),
        "archive_sha256": payload["release"]["archive_sha256"],
        "packet_body_sha256": payload["operator_dispatch_packet_body_sha256"],
    }


def verify_operator_dispatch_packet_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_operator_dispatch_packet_payload(payload)
    return payload


def verify_operator_dispatch_packet_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise OperatorDispatchPacketError("operator dispatch packet schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "READY_TO_SEND_ONE":
        raise OperatorDispatchPacketError("operator dispatch packet is not ready to send one.")
    if payload.get("safe_to_share") is not True:
        raise OperatorDispatchPacketError("operator dispatch packet safe_to_share must be true.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise OperatorDispatchPacketError("operator dispatch packet checks failed.")
    packet_checks = payload.get("operator_dispatch_packet_checks")
    recalculated = _packet_checks(payload)
    if packet_checks != recalculated:
        raise OperatorDispatchPacketError("operator dispatch packet self-checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise OperatorDispatchPacketError("operator dispatch packet self-check failed: " + ", ".join(failed))
    if payload.get("operator_dispatch_packet_body_sha256") != _packet_body_sha256(payload):
        raise OperatorDispatchPacketError("operator dispatch packet body hash mismatch.")


def _packet_payload(
    *,
    audit: dict[str, Any],
    dispatch_record: dict[str, Any],
    pilot_ready: dict[str, Any],
    bundle_smoke: dict[str, Any],
    private_workspace_rehearsal: dict[str, Any],
    post_send_rehearsal: dict[str, Any],
    pilot_learning_rehearsal: dict[str, Any],
) -> dict[str, Any]:
    release = dispatch_record.get("release") if isinstance(dispatch_record.get("release"), dict) else {}
    send_materials = (
        dispatch_record.get("send_materials") if isinstance(dispatch_record.get("send_materials"), dict) else {}
    )
    copy_paste_message = str(pilot_ready.get("pilot_dispatch", {}).get("copy_paste_message") or "")
    dispatch_policy = (
        dispatch_record.get("dispatch_execution_policy")
        if isinstance(dispatch_record.get("dispatch_execution_policy"), dict)
        else {}
    )
    bundle_smoke_receipt = (
        dispatch_record.get("bundle_smoke_receipt")
        if isinstance(dispatch_record.get("bundle_smoke_receipt"), dict)
        else {}
    )
    private_workspace_release = (
        private_workspace_rehearsal.get("release")
        if isinstance(private_workspace_rehearsal.get("release"), dict)
        else {}
    )
    private_workspace_scaffold = (
        private_workspace_rehearsal.get("scaffold_receipt")
        if isinstance(private_workspace_rehearsal.get("scaffold_receipt"), dict)
        else {}
    )
    post_send_release = (
        post_send_rehearsal.get("release") if isinstance(post_send_rehearsal.get("release"), dict) else {}
    )
    post_send_checks = (
        post_send_rehearsal.get("checks") if isinstance(post_send_rehearsal.get("checks"), dict) else {}
    )
    post_send_policy = (
        post_send_rehearsal.get("private_input_policy")
        if isinstance(post_send_rehearsal.get("private_input_policy"), dict)
        else {}
    )
    pilot_learning_release = (
        pilot_learning_rehearsal.get("release")
        if isinstance(pilot_learning_rehearsal.get("release"), dict)
        else {}
    )
    pilot_learning_flow = (
        pilot_learning_rehearsal.get("rehearsed_flow")
        if isinstance(pilot_learning_rehearsal.get("rehearsed_flow"), dict)
        else {}
    )
    checks = {
        "final_audit_ready_to_send_one": audit.get("status") == "pass"
        and audit.get("verdict") == "READY_TO_SEND_ONE",
        "dispatch_record_ready_to_send_one": dispatch_record.get("verdict") == "READY_TO_SEND_ONE",
        "bundle_smoke_matches_release": bundle_smoke_receipt.get("release_archive_sha256")
        == release.get("archive_sha256")
        == audit.get("archive_sha256")
        == bundle_smoke.get("release_bundle", {}).get("archive_sha256"),
        "private_workspace_rehearsal_passed": private_workspace_rehearsal.get("status") == "pass"
        and private_workspace_rehearsal.get("verdict") == "REHEARSAL_PASS",
        "private_workspace_rehearsal_matches_release": private_workspace_release.get("archive_sha256")
        == release.get("archive_sha256")
        == audit.get("archive_sha256"),
        "private_workspace_rehearsal_no_real_private_claim": private_workspace_rehearsal.get(
            "real_private_workspace"
        )
        is False
        and private_workspace_rehearsal.get("real_private_data_entered") is False,
        "private_workspace_rehearsal_scaffold_safe": private_workspace_scaffold.get("safe_to_share") is True
        and private_workspace_scaffold.get("workspace_path_included") is False
        and private_workspace_scaffold.get("raw_private_values_included") is False,
        "post_send_rehearsal_passed": post_send_rehearsal.get("status") == "pass"
        and post_send_rehearsal.get("verdict") == "REHEARSAL_PASS",
        "post_send_rehearsal_matches_release": post_send_release.get("archive_sha256")
        == release.get("archive_sha256")
        == audit.get("archive_sha256"),
        "post_send_rehearsal_no_real_recipient_claim": post_send_rehearsal.get("real_recipient_evidence")
        is False,
        "post_send_rehearsal_real_preflight_gate": post_send_checks.get("preflight_generated_by_real_gate")
        is True
        and post_send_policy.get("preflight_generated_by_real_gate") is True,
        "post_send_rehearsal_operator_note_template_contract": post_send_checks.get(
            "operator_note_template_used"
        )
        is True
        and post_send_checks.get("operator_note_template_preflight_contract") is True,
        "pilot_learning_rehearsal_passed": pilot_learning_rehearsal.get("status") == "pass"
        and pilot_learning_rehearsal.get("verdict") == "REHEARSAL_PASS",
        "pilot_learning_rehearsal_matches_release": pilot_learning_release.get("archive_sha256")
        == release.get("archive_sha256")
        == audit.get("archive_sha256"),
        "pilot_learning_rehearsal_no_real_pilot_claim": pilot_learning_rehearsal.get("real_pilot_evidence")
        is False,
        "pilot_learning_rehearsal_patch_before_next": pilot_learning_flow.get("pilot_iteration_verdict")
        == "PATCH_BEFORE_NEXT",
        "copy_paste_message_hash_matched": send_materials.get("copy_paste_message_sha256")
        == _text_sha256(copy_paste_message),
        "copy_paste_message_present": bool(copy_paste_message.strip()),
        "copy_paste_message_names_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message,
        "copy_paste_message_ascii_only": _is_ascii(copy_paste_message),
        "copy_paste_message_mojibake_free": _is_mojibake_free(copy_paste_message),
        "manual_dispatch_only": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_only": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_record.get("dispatch_scope", {}).get("target_participants") == 1,
        "private_hash_recording_only": dispatch_policy.get("records_private_sha256_only") is True,
        "claim_boundaries_locked": dispatch_record.get("metrics", {}).get("proof_claim_allowed") is False
        and dispatch_record.get("metrics", {}).get("sale_ready") is False
        and dispatch_record.get("metrics", {}).get("success_rate") is None,
    }
    payload: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "READY_TO_SEND_ONE" if all(checks.values()) else "BLOCKED",
        "safe_to_share": True,
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "operator_send_once": {
            "attach_zip_file": release.get("zip_file"),
            "copy_paste_message": copy_paste_message,
            "copy_paste_message_sha256": _text_sha256(copy_paste_message),
            "max_recipients": 1,
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
        },
        "required_before_send": {
            "final_audit": {
                "verdict": audit.get("verdict"),
                "chain_depth": audit.get("final_chain_depth"),
                "archive_sha256": audit.get("archive_sha256"),
                "receipt_body_sha256": audit.get("receipt_body_sha256"),
                "bundle_smoke_receipt_body_sha256": audit.get("bundle_smoke_receipt_body_sha256"),
            },
            "dispatch_record": {
                "file": DISPATCH_RECORD_JSON_NAME,
                "markdown": DISPATCH_RECORD_MD_NAME,
                "body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
            },
            "bundle_smoke_receipt": {
                "file": SMOKE_RECEIPT_NAME,
                "body_sha256": bundle_smoke_receipt.get("body_sha256"),
                "release_archive_sha256": bundle_smoke_receipt.get("release_archive_sha256"),
            },
            "private_workspace_scaffold_rehearsal": {
                "file": PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME,
                "body_sha256": private_workspace_rehearsal.get(
                    "private_workspace_rehearsal_receipt_body_sha256"
                ),
                "release_archive_sha256": private_workspace_release.get("archive_sha256"),
                "real_private_workspace": private_workspace_rehearsal.get("real_private_workspace"),
                "real_private_data_entered": private_workspace_rehearsal.get("real_private_data_entered"),
                "scaffold_receipt_body_sha256": private_workspace_scaffold.get("body_sha256"),
                "verdict": private_workspace_rehearsal.get("verdict"),
            },
            "post_send_checkpoint_rehearsal": {
                "file": POST_SEND_REHEARSAL_RECEIPT_NAME,
                "body_sha256": post_send_rehearsal.get("post_send_rehearsal_receipt_body_sha256"),
                "release_archive_sha256": post_send_release.get("archive_sha256"),
                "real_recipient_evidence": post_send_rehearsal.get("real_recipient_evidence"),
                "preflight_generated_by_real_gate": post_send_checks.get("preflight_generated_by_real_gate"),
                "operator_note_template_used": post_send_checks.get("operator_note_template_used"),
                "operator_note_template_preflight_contract": post_send_checks.get(
                    "operator_note_template_preflight_contract"
                ),
                "verdict": post_send_rehearsal.get("verdict"),
            },
            "pilot_learning_loop_rehearsal": {
                "file": PILOT_LEARNING_REHEARSAL_RECEIPT_NAME,
                "body_sha256": pilot_learning_rehearsal.get("pilot_learning_rehearsal_receipt_body_sha256"),
                "release_archive_sha256": pilot_learning_release.get("archive_sha256"),
                "real_pilot_evidence": pilot_learning_rehearsal.get("real_pilot_evidence"),
                "verdict": pilot_learning_rehearsal.get("verdict"),
                "iteration_verdict": pilot_learning_flow.get("pilot_iteration_verdict"),
            },
            "pilot_dispatch_markdown": PILOT_DISPATCH_MD_NAME,
        },
        "before_manual_send": {
            "prepare_private_workspace_command": (
                "python scripts/prepare_external_alpha_private_pilot_workspace.py "
                "--workspace-dir <private-workspace-dir>"
            ),
            "prepare_first_recipient_workspace_command": (
                "python scripts/prepare_external_alpha_first_recipient_send_workspace.py "
                "--workspace-dir <private-workspace-dir> "
                f"--operator-packet dist\\{PACKET_JSON_NAME}"
            ),
            "pre_send_preflight_command": (
                "python scripts/check_external_alpha_first_recipient_send_preflight.py "
                "--workspace-dir <private-workspace-dir> "
                f"--operator-packet dist\\{PACKET_JSON_NAME}"
            ),
            "expected_preflight_receipt": PREFLIGHT_RECEIPT_NAME,
            "operator_bypass_audit_command": (
                "python scripts/audit_external_alpha_operator_send_bypass.py "
                "--workspace-dir <private-workspace-dir>"
            ),
            "expected_operator_bypass_audit_receipt": OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
            "final_send_chain_audit_command": "python scripts/audit_external_alpha_send_chain.py",
            "manual_send_go_command": (
                "python scripts/check_external_alpha_first_recipient_manual_send_go.py "
                "--workspace-dir <private-workspace-dir>"
            ),
            "expected_manual_send_go_receipt": MANUAL_SEND_GO_RECEIPT_NAME,
            "pre_send_sequence_command": (
                "python scripts/check_external_alpha_first_recipient_pre_send_sequence.py "
                "--workspace-dir <private-workspace-dir>"
            ),
            "expected_pre_send_sequence_receipt": PRE_SEND_SEQUENCE_RECEIPT_NAME,
            "operator_status_command": (
                "python scripts/check_external_alpha_first_recipient_operator_status.py "
                "--workspace-dir <private-workspace-dir>"
            ),
            "expected_operator_status_receipt": "external-alpha-first-recipient-operator-status-receipt.json",
        },
        "after_manual_send": {
            "private_workspace_receipt": PRIVATE_WORKSPACE_RECEIPT_NAME,
            "post_send_sequence_command": (
                "python scripts/check_external_alpha_first_recipient_post_send_sequence.py "
                "--workspace-dir <private-workspace-dir> "
                "--sent-at-utc <sent-at-utc>"
            ),
            "expected_post_send_sequence_receipt": POST_SEND_SEQUENCE_RECEIPT_NAME,
            "record_command": (
                "python scripts/check_external_alpha_dispatch_record.py "
                "--private-workspace-dir <private-workspace-dir> "
                "--sent-at-utc <sent-at-utc> "
                "--require-preflight-receipt"
            ),
            "then_checkpoint_command": (
                "python scripts/check_external_alpha_recipient_checkpoint.py "
                "--private-workspace-dir <private-workspace-dir> "
                "--sent-at-utc <sent-at-utc> "
                "--require-preflight-receipt "
                "--builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json>"
            ),
            "expected_recipient_receipt": "external_alpha_builder_gold_path_share_receipt.json",
        },
        "do_not_share": [
            ".env",
            "browser localStorage",
            "recipient raw identifier",
            "dispatch message thread raw text",
            "operator dispatch note raw text",
            "raw AI reply",
            "API key or secret",
        ],
        "checks": checks,
    }
    payload["operator_dispatch_packet_body_sha256"] = _packet_body_sha256(payload)
    payload["operator_dispatch_packet_checks"] = _packet_checks(payload)
    return payload


def _packet_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """Verify the operator dispatch packet is share-safe and ready for one manual send."""
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
    expected_operator_packet_arg = f"--operator-packet dist\\{PACKET_JSON_NAME}"
    first_recipient_workspace_command = str(before_manual.get("prepare_first_recipient_workspace_command"))
    pre_send_preflight_command = str(before_manual.get("pre_send_preflight_command"))
    return {
        "schema_version_present": payload.get("schema_version") == PACKET_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready_to_send_one": payload.get("verdict") == "READY_TO_SEND_ONE",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "copy_paste_message_hash_matched": send_once.get("copy_paste_message_sha256")
        == _text_sha256(copy_paste_message),
        "copy_paste_message_names_prompt": "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md"
        in copy_paste_message,
        "copy_paste_message_names_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message,
        "copy_paste_message_names_zip": f"{RELEASE_SLUG}.zip" in copy_paste_message,
        "copy_paste_message_asks_short_ack": "CONFIRMED" in copy_paste_message
        and "reply only" in copy_paste_message,
        "copy_paste_message_ascii_only": _is_ascii(copy_paste_message),
        "copy_paste_message_mojibake_free": _is_mojibake_free(copy_paste_message),
        "manual_dispatch_only": send_once.get("script_sends_to_recipient") is False
        and send_once.get("manual_operator_dispatch_required") is True,
        "one_recipient_only": send_once.get("max_recipients") == 1,
        "final_audit_chain_depth_at_least_12": before.get("final_audit", {}).get("chain_depth", 0) >= 12,
        "dispatch_record_hash_present": _looks_like_sha256(before.get("dispatch_record", {}).get("body_sha256")),
        "bundle_smoke_hash_present": _looks_like_sha256(before.get("bundle_smoke_receipt", {}).get("body_sha256")),
        "private_workspace_rehearsal_hash_present": _looks_like_sha256(
            before.get("private_workspace_scaffold_rehearsal", {}).get("body_sha256")
        ),
        "private_workspace_rehearsal_no_real_private_claim": before.get(
            "private_workspace_scaffold_rehearsal", {}
        ).get("real_private_workspace")
        is False
        and before.get("private_workspace_scaffold_rehearsal", {}).get("real_private_data_entered") is False,
        "private_workspace_rehearsal_release_hash_matched": before.get(
            "private_workspace_scaffold_rehearsal", {}
        ).get("release_archive_sha256")
        == release.get("archive_sha256"),
        "private_workspace_scaffold_receipt_hash_present": _looks_like_sha256(
            before.get("private_workspace_scaffold_rehearsal", {}).get("scaffold_receipt_body_sha256")
        ),
        "post_send_rehearsal_hash_present": _looks_like_sha256(
            before.get("post_send_checkpoint_rehearsal", {}).get("body_sha256")
        ),
        "post_send_rehearsal_no_real_recipient_claim": before.get("post_send_checkpoint_rehearsal", {}).get(
            "real_recipient_evidence"
        )
        is False,
        "post_send_rehearsal_release_hash_matched": before.get("post_send_checkpoint_rehearsal", {}).get(
            "release_archive_sha256"
        )
        == release.get("archive_sha256"),
        "post_send_rehearsal_real_preflight_gate": before.get("post_send_checkpoint_rehearsal", {}).get(
            "preflight_generated_by_real_gate"
        )
        is True,
        "post_send_rehearsal_operator_note_template_contract": before.get(
            "post_send_checkpoint_rehearsal", {}
        ).get("operator_note_template_used")
        is True
        and before.get("post_send_checkpoint_rehearsal", {}).get("operator_note_template_preflight_contract")
        is True,
        "pilot_learning_rehearsal_hash_present": _looks_like_sha256(
            before.get("pilot_learning_loop_rehearsal", {}).get("body_sha256")
        ),
        "pilot_learning_rehearsal_no_real_pilot_claim": before.get("pilot_learning_loop_rehearsal", {}).get(
            "real_pilot_evidence"
        )
        is False,
        "pilot_learning_rehearsal_release_hash_matched": before.get("pilot_learning_loop_rehearsal", {}).get(
            "release_archive_sha256"
        )
        == release.get("archive_sha256"),
        "pilot_learning_rehearsal_patch_before_next": before.get("pilot_learning_loop_rehearsal", {}).get(
            "iteration_verdict"
        )
        == "PATCH_BEFORE_NEXT",
        "after_send_commands_private_workspace_only": "--private-workspace-dir <private-workspace-dir>"
        in str(after.get("record_command"))
        and "--private-workspace-dir <private-workspace-dir>" in str(after.get("then_checkpoint_command")),
        "after_send_record_command_requires_preflight": "--require-preflight-receipt"
        in str(after.get("record_command")),
        "after_send_checkpoint_command_requires_preflight": "--require-preflight-receipt"
        in str(after.get("then_checkpoint_command")),
        "post_send_sequence_command_present": "check_external_alpha_first_recipient_post_send_sequence.py"
        in str(after.get("post_send_sequence_command"))
        and "--workspace-dir <private-workspace-dir>" in str(after.get("post_send_sequence_command"))
        and "--sent-at-utc <sent-at-utc>" in str(after.get("post_send_sequence_command")),
        "post_send_sequence_receipt_named": after.get("expected_post_send_sequence_receipt")
        == POST_SEND_SEQUENCE_RECEIPT_NAME,
        "private_workspace_scaffold_command_present": "prepare_external_alpha_private_pilot_workspace.py"
        in str(before_manual.get("prepare_private_workspace_command"))
        and "--workspace-dir <private-workspace-dir>" in str(before_manual.get("prepare_private_workspace_command")),
        "first_recipient_workspace_command_present": "prepare_external_alpha_first_recipient_send_workspace.py"
        in first_recipient_workspace_command
        and "--workspace-dir <private-workspace-dir>" in first_recipient_workspace_command,
        "first_recipient_workspace_command_uses_operator_packet": expected_operator_packet_arg
        in first_recipient_workspace_command,
        "pre_send_preflight_command_present": "check_external_alpha_first_recipient_send_preflight.py"
        in pre_send_preflight_command
        and "--workspace-dir <private-workspace-dir>" in pre_send_preflight_command,
        "pre_send_preflight_command_uses_operator_packet": expected_operator_packet_arg in pre_send_preflight_command,
        "pre_send_preflight_receipt_named": before_manual.get("expected_preflight_receipt") == PREFLIGHT_RECEIPT_NAME,
        "operator_bypass_audit_command_present": "audit_external_alpha_operator_send_bypass.py"
        in str(before_manual.get("operator_bypass_audit_command"))
        and "--workspace-dir <private-workspace-dir>" in str(before_manual.get("operator_bypass_audit_command")),
        "operator_bypass_audit_receipt_named": before_manual.get("expected_operator_bypass_audit_receipt")
        == OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
        "final_send_chain_audit_command_present": str(before_manual.get("final_send_chain_audit_command"))
        == "python scripts/audit_external_alpha_send_chain.py",
        "final_send_chain_audit_no_internal_skip_flag": "--skip-operator-bypass-audit"
        not in str(before_manual.get("final_send_chain_audit_command")),
        "manual_send_go_command_present": "check_external_alpha_first_recipient_manual_send_go.py"
        in str(before_manual.get("manual_send_go_command"))
        and "--workspace-dir <private-workspace-dir>" in str(before_manual.get("manual_send_go_command")),
        "manual_send_go_receipt_named": before_manual.get("expected_manual_send_go_receipt")
        == MANUAL_SEND_GO_RECEIPT_NAME,
        "pre_send_sequence_command_present": "check_external_alpha_first_recipient_pre_send_sequence.py"
        in str(before_manual.get("pre_send_sequence_command"))
        and "--workspace-dir <private-workspace-dir>" in str(before_manual.get("pre_send_sequence_command")),
        "pre_send_sequence_receipt_named": before_manual.get("expected_pre_send_sequence_receipt")
        == PRE_SEND_SEQUENCE_RECEIPT_NAME,
        "operator_status_command_present": "check_external_alpha_first_recipient_operator_status.py"
        in str(before_manual.get("operator_status_command"))
        and "--workspace-dir <private-workspace-dir>" in str(before_manual.get("operator_status_command")),
        "operator_status_receipt_named": before_manual.get("expected_operator_status_receipt")
        == "external-alpha-first-recipient-operator-status-receipt.json",
        "private_workspace_receipt_named": after.get("private_workspace_receipt") == PRIVATE_WORKSPACE_RECEIPT_NAME,
        "expected_gold_path_receipt_named": after.get("expected_recipient_receipt")
        == "external_alpha_builder_gold_path_share_receipt.json",
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _packet_body_sha256(payload),
    }


def _packet_markdown(payload: dict[str, Any]) -> str:
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    packet_checks = "\n".join(
        f"- {name}: {passed}" for name, passed in payload["operator_dispatch_packet_checks"].items()
    )
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian External Alpha Operator Dispatch Packet

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- packet body sha256: {payload["operator_dispatch_packet_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- final audit chain depth: {payload["required_before_send"]["final_audit"]["chain_depth"]}
- dispatch-record body sha256: {payload["required_before_send"]["dispatch_record"]["body_sha256"]}
- bundle smoke receipt body sha256: {payload["required_before_send"]["bundle_smoke_receipt"]["body_sha256"]}
- private workspace rehearsal body sha256: {payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["body_sha256"]}
- private workspace rehearsal real private workspace: {payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["real_private_workspace"]}
- private workspace rehearsal real private data entered: {payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["real_private_data_entered"]}
- post-send rehearsal body sha256: {payload["required_before_send"]["post_send_checkpoint_rehearsal"]["body_sha256"]}
- post-send rehearsal real recipient evidence: {payload["required_before_send"]["post_send_checkpoint_rehearsal"]["real_recipient_evidence"]}
- post-send rehearsal real preflight gate: {payload["required_before_send"]["post_send_checkpoint_rehearsal"]["preflight_generated_by_real_gate"]}
- post-send rehearsal operator note template contract: {payload["required_before_send"]["post_send_checkpoint_rehearsal"]["operator_note_template_preflight_contract"]}
- pilot learning rehearsal body sha256: {payload["required_before_send"]["pilot_learning_loop_rehearsal"]["body_sha256"]}
- pilot learning rehearsal real pilot evidence: {payload["required_before_send"]["pilot_learning_loop_rehearsal"]["real_pilot_evidence"]}
- pilot learning rehearsal iteration verdict: {payload["required_before_send"]["pilot_learning_loop_rehearsal"]["iteration_verdict"]}

## Send Exactly Once

- attach zip file: {payload["operator_send_once"]["attach_zip_file"]}
- max recipients: {payload["operator_send_once"]["max_recipients"]}
- script sends to recipient: {payload["operator_send_once"]["script_sends_to_recipient"]}
- manual operator dispatch required: {payload["operator_send_once"]["manual_operator_dispatch_required"]}
- copy-paste message sha256: {payload["operator_send_once"]["copy_paste_message_sha256"]}

```text
{payload["operator_send_once"]["copy_paste_message"]}
```

## Before Manual Send

```bash
{payload["before_manual_send"]["prepare_private_workspace_command"]}
```

```bash
{payload["before_manual_send"]["prepare_first_recipient_workspace_command"]}
```

Fill `recipient-private.txt` and `operator-dispatch-note-private.md`. The operator dispatch note must name the private send channel and include the exact release ZIP sha256 `{payload["release"]["archive_sha256"]}`, then run:

```bash
{payload["before_manual_send"]["pre_send_preflight_command"]}
```

Expected preflight receipt: `{payload["before_manual_send"]["expected_preflight_receipt"]}`

Run the operator-surface bypass audit after the private runbook exists and before sending:

```bash
{payload["before_manual_send"]["operator_bypass_audit_command"]}
```

Expected operator bypass audit receipt: `{payload["before_manual_send"]["expected_operator_bypass_audit_receipt"]}`

Run the final send-chain audit. It must report `READY_TO_SEND_ONE` and include the bypass receipt:

```bash
{payload["before_manual_send"]["final_send_chain_audit_command"]}
```

Run the private GO/NO-GO aggregator. It must report `GO_TO_MANUALLY_SEND_ONE` before you send:

```bash
{payload["before_manual_send"]["manual_send_go_command"]}
```

Expected manual send GO receipt: `{payload["before_manual_send"]["expected_manual_send_go_receipt"]}`

Shortcut: run the full pre-send sequence. It must report `READY_TO_MANUALLY_SEND_ONE` before you send:

```bash
{payload["before_manual_send"]["pre_send_sequence_command"]}
```

Expected pre-send sequence receipt: `{payload["before_manual_send"]["expected_pre_send_sequence_receipt"]}`

Check the safe operator stage any time you are unsure what comes next:

```bash
{payload["before_manual_send"]["operator_status_command"]}
```

Expected operator status receipt: `{payload["before_manual_send"]["expected_operator_status_receipt"]}`

## After Manual Send

Run the post-send sequence first. It records dispatch with the required preflight receipt and waits for acknowledgement when needed:

```bash
{payload["after_manual_send"]["post_send_sequence_command"]}
```

Expected post-send sequence receipt: `{payload["after_manual_send"]["expected_post_send_sequence_receipt"]}`

The lower-level commands remain available for manual inspection:

```bash
{payload["after_manual_send"]["record_command"]}
```

```bash
{payload["after_manual_send"]["then_checkpoint_command"]}
```

Expected recipient receipt: `{payload["after_manual_send"]["expected_recipient_receipt"]}`

## Checks

{checks}

## Packet Self Checks

{packet_checks}

## Do Not Share

{do_not_share}
"""


def _packet_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_dispatch_packet_body_sha256", "operator_dispatch_packet_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_ascii(value: str) -> bool:
    return all(ord(char) < 128 for char in value)


def _is_mojibake_free(value: str) -> bool:
    return not any(marker in value for marker in MOJIBAKE_MARKERS)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise OperatorDispatchPacketError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise OperatorDispatchPacketError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise OperatorDispatchPacketError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_shareable_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise OperatorDispatchPacketError(f"operator dispatch packet contains local path or test secret: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a one-recipient external alpha operator dispatch packet.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing release artifacts when refreshing chain.")
    parser.add_argument("--no-refresh-chain", action="store_true", help="Do not regenerate pilot iteration before packet.")
    parser.add_argument("--verify-packet", default=None, help="Verify an existing operator dispatch packet JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_packet:
        try:
            payload = verify_operator_dispatch_packet_file(Path(args.verify_packet))
        except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
            logger.error("[FAIL] external alpha operator dispatch packet verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha operator dispatch packet verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["operator_dispatch_packet_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = prepare_operator_dispatch_packet(
            Path(args.output_dir),
            refresh_chain=not args.no_refresh_chain,
            skip_build=args.skip_build,
        )
    except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
        logger.error("[FAIL] external alpha operator dispatch packet: %s", exc)
        return 1

    logger.info("[PASS] external alpha operator dispatch packet")
    logger.info("verdict: %s", result["verdict"])
    logger.info("packet : %s", result["packet_md"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["packet_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

