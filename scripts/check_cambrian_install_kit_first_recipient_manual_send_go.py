"""Aggregate the final Cambrian install-kit GO/NO-GO before one manual send."""

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

from scripts.audit_cambrian_install_kit_operator_send_bypass import (  # noqa: E402
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
)
from scripts.check_cambrian_install_kit_first_recipient_operator_status import (  # noqa: E402
    OPERATOR_STATUS_MD_NAME,
    OPERATOR_STATUS_READY_RECEIPT_NAME,
)
from scripts.check_cambrian_install_kit_first_recipient_pre_send_sequence import (  # noqa: E402
    PRE_SEND_SEQUENCE_RECEIPT_NAME,
    InstallKitFirstRecipientPreSendSequenceError,
    check_first_recipient_pre_send_sequence,
    verify_first_recipient_pre_send_sequence_receipt_file,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (  # noqa: E402
    DEFAULT_WORKSPACE_DIR,
)
from scripts.prepare_cambrian_install_kit_release import RELEASE_BUNDLE_NAME  # noqa: E402
from scripts.smoke_cambrian_install_kit_manual_send_go_rehearsal import (  # noqa: E402
    MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
)


MANUAL_SEND_GO_SCHEMA_VERSION = "cambrian_install_kit_first_recipient_manual_send_go_v0_1"
MANUAL_SEND_GO_RECEIPT_NAME = "cambrian-install-kit-first-recipient-manual-send-go-receipt.json"

logger = logging.getLogger(__name__)


class InstallKitFirstRecipientManualSendGoError(RuntimeError):
    """Install-kit first-recipient manual send GO/NO-GO check failed."""


def check_first_recipient_manual_send_go(
    workspace_dir: Path | None = None,
    *,
    output_dir: Path | None = None,
    receipt_path: Path | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Return GO only when the pre-send sequence is ready for one manual send."""
    workspace = (workspace_dir or DEFAULT_WORKSPACE_DIR).resolve()
    dist = (output_dir or ROOT / "dist").resolve()
    pre_send_receipt_path = workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME

    pre_send_payload = _run_pre_send_sequence(
        workspace=workspace,
        dist=dist,
        receipt_path=pre_send_receipt_path,
        skip_verify=skip_verify,
    )
    payload = _manual_send_go_payload(pre_send_payload=pre_send_payload)

    target = (receipt_path or workspace / MANUAL_SEND_GO_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_first_recipient_manual_send_go_receipt_file(target, require_go=False)
    _assert_shareable_receipt_file(target, workspace)

    failed = [name for name, passed in payload["checks"].items() if passed is not True]
    if failed:
        raise InstallKitFirstRecipientManualSendGoError(
            "install-kit first-recipient manual send blocked checks: " + ", ".join(failed)
        )

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(target),
        "receipt_body_sha256": payload["manual_send_go_receipt_body_sha256"],
        "release_bundle_sha256": payload["release_bundle"]["sha256"],
    }


def verify_first_recipient_manual_send_go_receipt_file(
    path: Path,
    *,
    require_go: bool = True,
) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_manual_send_go_receipt_payload(payload, require_go=require_go)
    return payload


def verify_first_recipient_manual_send_go_receipt_payload(
    payload: dict[str, Any],
    *,
    require_go: bool = True,
) -> None:
    if payload.get("schema_version") != MANUAL_SEND_GO_SCHEMA_VERSION:
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt checks are missing.")
    go = all(value is True for value in checks.values())
    if payload.get("status") != ("pass" if go else "fail"):
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt status does not match checks.")
    if payload.get("verdict") != ("GO_TO_MANUALLY_SEND_ONE" if go else "BLOCKED_BEFORE_MANUAL_SEND"):
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt verdict does not match checks.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt must be safe_to_share.")
    recalculated = _receipt_checks(payload)
    if payload.get("manual_send_go_receipt_checks") != recalculated:
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt self-checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise InstallKitFirstRecipientManualSendGoError(
            "manual-send GO receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("manual_send_go_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt body hash mismatch.")
    if require_go and not go:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise InstallKitFirstRecipientManualSendGoError("manual-send GO receipt is blocked: " + ", ".join(failed))


def _run_pre_send_sequence(
    *,
    workspace: Path,
    dist: Path,
    receipt_path: Path,
    skip_verify: bool,
) -> dict[str, Any] | None:
    try:
        check_first_recipient_pre_send_sequence(
            workspace_dir=workspace,
            output_dir=dist,
            receipt_path=receipt_path,
            skip_verify=skip_verify,
        )
        return verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)
    except InstallKitFirstRecipientPreSendSequenceError:
        return _load_pre_send_receipt(receipt_path)


def _load_pre_send_receipt(path: Path) -> dict[str, Any] | None:
    try:
        return verify_first_recipient_pre_send_sequence_receipt_file(path, require_ready=False)
    except Exception:
        return None


def _manual_send_go_payload(*, pre_send_payload: dict[str, Any] | None) -> dict[str, Any]:
    pre_send_checks = pre_send_payload.get("checks") if isinstance(pre_send_payload, dict) else {}
    step_results = _dict(pre_send_payload, "step_results")
    gate_receipts = _dict(pre_send_payload, "gate_receipts")
    operator_gate = _dict(gate_receipts, "operator_status")
    bypass_gate = _dict(gate_receipts, "operator_send_bypass_audit")
    rehearsal_gate = _dict(gate_receipts, "manual_send_go_rehearsal")
    blocking_summary = _dict(pre_send_payload, "blocking_summary")
    policy = _dict(pre_send_payload, "policy")
    release = _dict(pre_send_payload, "release_bundle")
    release_current_match = operator_gate.get("release_current_artifacts_match")

    checks = {
        "pre_send_sequence_ready": pre_send_payload is not None
        and pre_send_payload.get("status") == "pass"
        and pre_send_payload.get("verdict") == "READY_TO_MANUALLY_SEND_ONE",
        "pre_send_receipt_body_hash_present": _looks_like_sha256(
            pre_send_payload.get("pre_send_sequence_receipt_body_sha256")
            if isinstance(pre_send_payload, dict)
            else None
        ),
        "pre_send_checks_all_true": isinstance(pre_send_checks, dict)
        and bool(pre_send_checks)
        and all(value is True for value in pre_send_checks.values()),
        "operator_status_ready_to_send": _dict(step_results, "operator_status").get("status") == "pass"
        and _dict(step_results, "operator_status").get("verdict") == "READY_TO_MANUALLY_SEND_ONE",
        "operator_status_ready_receipt_written": operator_gate.get("ready_receipt_file")
        == OPERATOR_STATUS_READY_RECEIPT_NAME,
        "operator_status_open_gates_empty": blocking_summary.get("open_gate_ids") == [],
        "operator_status_manual_send_allowed": operator_gate.get("manual_send_allowed") is True,
        "operator_status_release_current_artifacts_match": operator_gate.get(
            "release_current_artifacts_gate_passed"
        )
        is True
        and release_current_match is not False,
        "operator_send_bypass_audit_ready": _dict(step_results, "operator_send_bypass_audit").get("status")
        == "pass"
        and bypass_gate.get("verdict") == "NO_OPERATOR_STATUS_BYPASS",
        "manual_send_go_rehearsal_ready": _dict(step_results, "manual_send_go_rehearsal").get("status") == "pass"
        and rehearsal_gate.get("verdict") == "REHEARSAL_PASS",
        "release_bundle_hash_present": _looks_like_sha256(release.get("sha256")),
        "one_recipient_policy_locked": pre_send_checks.get("one_recipient_policy_locked") is True,
        "manual_dispatch_only": policy.get("script_sends_to_recipient") is False
        and policy.get("manual_operator_dispatch_required") is True,
        "script_does_not_send_to_recipient": True,
        "pre_send_go_no_go_only": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
    }
    go = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": MANUAL_SEND_GO_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if go else "fail",
        "verdict": "GO_TO_MANUALLY_SEND_ONE" if go else "BLOCKED_BEFORE_MANUAL_SEND",
        "safe_to_share": True,
        "release_bundle": {
            "file": RELEASE_BUNDLE_NAME,
            "sha256": release.get("sha256") if _looks_like_sha256(release.get("sha256")) else None,
        },
        "gate_receipts": {
            "pre_send_sequence": {
                "file": PRE_SEND_SEQUENCE_RECEIPT_NAME,
                "verdict": pre_send_payload.get("verdict") if isinstance(pre_send_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(pre_send_payload, "pre_send_sequence_receipt_body_sha256"),
                "blocked_checks": _safe_list(blocking_summary.get("blocked_checks")),
                "operator_status_board_file": blocking_summary.get("operator_status_board_file"),
                "human_next_steps": _safe_list(blocking_summary.get("human_next_steps")),
            },
            "operator_status": {
                "file": operator_gate.get("file"),
                "status_board_file": operator_gate.get("status_board_file"),
                "ready_receipt_file": operator_gate.get("ready_receipt_file"),
                "verdict": operator_gate.get("verdict"),
                "send_state": operator_gate.get("send_state"),
                "manual_send_allowed": operator_gate.get("manual_send_allowed") is True,
                "release_current_artifacts_checked": operator_gate.get("release_current_artifacts_checked") is True,
                "release_current_artifacts_match": release_current_match,
                "release_current_artifacts_gate_passed": operator_gate.get("release_current_artifacts_gate_passed"),
                "release_current_artifacts_status": operator_gate.get("release_current_artifacts_status"),
                "body_sha256": _body_hash(operator_gate, "body_sha256"),
            },
            "operator_send_bypass_audit": {
                "file": OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
                "verdict": bypass_gate.get("verdict"),
                "body_sha256": _body_hash(bypass_gate, "body_sha256"),
            },
            "manual_send_go_rehearsal": {
                "file": MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
                "verdict": rehearsal_gate.get("verdict"),
                "body_sha256": _body_hash(rehearsal_gate, "body_sha256"),
            },
        },
        "blocking_summary": {
            "blocked_checks": [name for name, passed in checks.items() if passed is not True],
            "pre_send_blocked_checks": _safe_list(blocking_summary.get("blocked_checks")),
            "open_gate_ids": _safe_list(blocking_summary.get("open_gate_ids")),
            "operator_status_board_file": blocking_summary.get("operator_status_board_file")
            or OPERATOR_STATUS_MD_NAME,
            "human_next_steps": _safe_list(blocking_summary.get("human_next_steps")),
            "next_action": (
                "Manually send exactly one release bundle, then record dispatch with the preserved READY operator-status receipt."
                if go
                else _blocked_next_action(blocking_summary)
            ),
        },
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "pre_send_go_no_go_only": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "operator_next_action": (
            "Manually send exactly one release bundle, then record dispatch with the preserved READY operator-status receipt."
            if go
            else _blocked_next_action(blocking_summary)
        ),
        "checks": checks,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["manual_send_go_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["manual_send_go_receipt_checks"] = _receipt_checks(payload)
    return payload


def _blocked_next_action(blocking_summary: dict[str, Any]) -> str:
    next_action = blocking_summary.get("next_action")
    if isinstance(next_action, str) and next_action:
        return "Do not send. " + next_action
    return "Do not send. Complete the blocked pre-send gates, then rerun this GO check."


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    go = bool(checks) and all(value is True for value in checks.values())
    release = _dict(payload, "release_bundle")
    gate_receipts = _dict(payload, "gate_receipts")
    pre_send = _dict(gate_receipts, "pre_send_sequence")
    operator = _dict(gate_receipts, "operator_status")
    bypass = _dict(gate_receipts, "operator_send_bypass_audit")
    rehearsal = _dict(gate_receipts, "manual_send_go_rehearsal")
    policy = _dict(payload, "policy")
    human_next_steps = pre_send.get("human_next_steps") if isinstance(pre_send.get("human_next_steps"), list) else []
    body_hash = payload.get("manual_send_go_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == MANUAL_SEND_GO_SCHEMA_VERSION,
        "status_matches_checks": payload.get("status") == ("pass" if go else "fail"),
        "verdict_matches_checks": payload.get("verdict")
        == ("GO_TO_MANUALLY_SEND_ONE" if go else "BLOCKED_BEFORE_MANUAL_SEND"),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "release_bundle_hash_present": _looks_like_sha256(release.get("sha256")),
        "pre_send_receipt_named": pre_send.get("file") == PRE_SEND_SEQUENCE_RECEIPT_NAME,
        "operator_status_board_named": operator.get("status_board_file") == OPERATOR_STATUS_MD_NAME,
        "operator_status_current_artifact_gate_recorded": isinstance(
            operator.get("release_current_artifacts_checked"), bool
        )
        and operator.get("release_current_artifacts_match") in {True, False, None}
        and isinstance(operator.get("release_current_artifacts_gate_passed"), bool)
        and operator.get("release_current_artifacts_gate_passed")
        == (operator.get("release_current_artifacts_match") is not False),
        "operator_bypass_receipt_hash_present": _looks_like_sha256(bypass.get("body_sha256")),
        "manual_send_rehearsal_receipt_hash_present": _looks_like_sha256(rehearsal.get("body_sha256")),
        "human_next_steps_controlled": (not human_next_steps)
        or all(
            isinstance(item, str)
            and item
            and "\n" not in item
            and str(ROOT) not in item
            and str(Path.home()) not in item
            for item in human_next_steps
        ),
        "manual_dispatch_only": policy.get("script_sends_to_recipient") is False
        and policy.get("manual_operator_dispatch_required") is True,
        "raw_private_values_omitted": policy.get("raw_private_values_in_receipt") is False,
        "local_paths_omitted": policy.get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _assert_shareable_receipt_file(path: Path, workspace: Path) -> None:
    text = path.read_text(encoding="utf-8")
    leaked = [
        item
        for item in (
            str(ROOT),
            str(Path.home()),
            str(workspace),
            "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER",
            "REPLACE_WITH_PRIVATE_SEND_CHANNEL",
            "real-recipient@example.com",
            "private channel: email",
        )
        if item and item in text
    ]
    if leaked:
        raise InstallKitFirstRecipientManualSendGoError(
            "manual-send GO receipt leaked local path or raw private text."
        )


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _body_hash(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return str(value) if _looks_like_sha256(value) else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise InstallKitFirstRecipientManualSendGoError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise InstallKitFirstRecipientManualSendGoError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise InstallKitFirstRecipientManualSendGoError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "manual_send_go_receipt_body_sha256", "manual_send_go_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate GO/NO-GO before one Cambrian install-kit manual send.")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing GO/NO-GO receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_manual_send_go_receipt_file(args.verify_receipt, require_go=False)
        except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
            logger.error("[FAIL] install kit first-recipient manual send GO receipt verification: %s", exc)
            return 1
        logger.info("[PASS] install kit first-recipient manual send GO receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["manual_send_go_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_manual_send_go(
            workspace_dir=args.workspace_dir,
            output_dir=args.output_dir,
            receipt_path=args.receipt,
            skip_verify=args.skip_verify,
        )
    except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
        logger.error("[FAIL] install kit first-recipient manual send GO: %s", exc)
        return 1

    logger.info("[PASS] install kit first-recipient manual send GO")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", Path(result["receipt_json"]).name)
    logger.info("release_bundle_sha256: %s", result["release_bundle_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
