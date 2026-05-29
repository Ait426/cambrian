"""외부 알파 첫 파일럿 발송 후 운영 GO/NO-GO 게이트를 실행한다."""

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

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.check_external_alpha_send_ready import (
    SEND_READY_JSON_NAME,
    SEND_READY_MD_NAME,
    check_send_ready,
    verify_send_ready_file,
)
from scripts.prepare_external_alpha_handoff import HANDOFF_JSON_NAME, HANDOFF_MD_NAME, RECEIPT_NAME
from scripts.verify_external_alpha_release import verify_shareable_receipt_file


PILOT_READY_SCHEMA_VERSION = "external_alpha_pilot_ready_v0_1"
PILOT_READY_JSON_NAME = f"{RELEASE_SLUG}-pilot-ready.json"
PILOT_READY_MD_NAME = f"{RELEASE_SLUG}-pilot-ready.md"
PILOT_DISPATCH_MD_NAME = f"{RELEASE_SLUG}-pilot-dispatch.md"
PILOT_TEMPLATE_PATHS = (
    "docs/launch/PILOT_ISSUE_INTAKE.md",
    "docs/launch/PILOT_FEEDBACK_FORM.md",
)

logger = logging.getLogger(__name__)


class PilotReadyError(Exception):
    """외부 알파 파일럿 준비 판정 실패."""


def check_pilot_ready(output_dir: Path = DEFAULT_OUTPUT_DIR, skip_build: bool = False) -> dict[str, Any]:
    """send-ready 산출물을 기반으로 첫 외부 파일럿 운영 준비 상태를 판정한다."""
    output_dir = output_dir.resolve()
    send_ready_result = check_send_ready(output_dir, skip_build=skip_build)
    send_ready_path = Path(str(send_ready_result["send_ready_json"]))
    receipt_path = Path(str(send_ready_result["receipt_json"]))

    send_ready = verify_send_ready_file(send_ready_path)
    receipt = verify_shareable_receipt_file(receipt_path)
    payload = _pilot_ready_payload(send_ready, receipt)

    json_path = output_dir / PILOT_READY_JSON_NAME
    md_path = output_dir / PILOT_READY_MD_NAME
    dispatch_path = output_dir / PILOT_DISPATCH_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_pilot_ready_markdown(payload), encoding="utf-8")
    dispatch_path.write_text(_pilot_dispatch_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)
    _assert_shareable_file(dispatch_path)

    result = {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "pilot_ready_json": str(json_path),
        "pilot_ready_md": str(md_path),
        "pilot_dispatch_md": str(dispatch_path),
        "send_ready_json": str(send_ready_path),
        "receipt_json": str(receipt_path),
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }
    if payload["verdict"] != "GO":
        failed = [name for name, passed in payload["checks"].items() if passed is not True]
        raise PilotReadyError("pilot-ready check failed: " + ", ".join(failed))
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="외부 알파 첫 파일럿 운영 GO/NO-GO 판정서를 생성한다.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="릴리즈 산출물 폴더. 기본값은 dist")
    parser.add_argument("--skip-build", action="store_true", help="기존 ZIP, manifest, handoff, send-ready를 재사용한다.")
    parser.add_argument("--verify-pilot-ready", default=None, help="pilot-ready JSON만 단독 검증한다.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_pilot_ready:
        try:
            payload = verify_pilot_ready_file(Path(args.verify_pilot_ready))
        except Exception as exc:  # noqa: BLE001 - 운영 검증 실패 이유를 한 줄로 전달한다.
            logger.error("[FAIL] external alpha pilot-ready verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha pilot-ready verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pilot_ready_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_pilot_ready(Path(args.output_dir), skip_build=args.skip_build)
    except Exception as exc:  # noqa: BLE001 - 운영 게이트는 실패 조건을 사용자에게 직접 보여준다.
        logger.error("[FAIL] external alpha pilot-ready: %s", exc)
        return 1

    logger.info("[PASS] external alpha pilot-ready")
    logger.info("verdict      : %s", result["verdict"])
    logger.info("pilot_ready_md: %s", result["pilot_ready_md"])
    logger.info("dispatch_md  : %s", result["pilot_dispatch_md"])
    logger.info("zip          : %s", result["zip_file"])
    logger.info("sha256       : %s", result["archive_sha256"])
    return 0


def _pilot_ready_payload(send_ready: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Combine send-ready, receipt, and pilot templates into one readiness payload."""
    release = send_ready.get("release") if isinstance(send_ready.get("release"), dict) else {}
    handoff = send_ready.get("handoff") if isinstance(send_ready.get("handoff"), dict) else {}
    receipt_summary = send_ready.get("receipt") if isinstance(send_ready.get("receipt"), dict) else {}
    send_ready_checks = send_ready.get("send_ready_checks") if isinstance(send_ready.get("send_ready_checks"), dict) else {}
    checks = send_ready.get("checks") if isinstance(send_ready.get("checks"), dict) else {}
    dispatch_execution_policy = (
        send_ready.get("dispatch_execution_policy")
        if isinstance(send_ready.get("dispatch_execution_policy"), dict)
        else {}
    )
    do_not_share = send_ready.get("do_not_share") if isinstance(send_ready.get("do_not_share"), list) else []
    copy_paste_message = str(send_ready.get("copy_paste_message") or "")
    template_checks = _pilot_template_checks()
    pilot_success_criteria = _pilot_success_criteria()
    pilot_decision_thresholds = _pilot_decision_thresholds()

    business_checks = {
        "send_ready_go": send_ready.get("status") == "ready_to_send" and send_ready.get("verdict") == "GO",
        "send_ready_checks_true": bool(send_ready_checks) and all(value is True for value in send_ready_checks.values()),
        "send_ready_business_checks_true": bool(checks) and all(value is True for value in checks.values()),
        "release_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "handoff_referenced": handoff.get("file") == HANDOFF_JSON_NAME and handoff.get("markdown") == HANDOFF_MD_NAME,
        "receipt_referenced": receipt_summary.get("file") == RECEIPT_NAME and receipt.get("status") == "pass",
        "receipt_safe_to_share": receipt.get("safe_to_share") is True,
        "pilot_templates_present": template_checks["issue_intake_exists"] and template_checks["feedback_form_exists"],
        "issue_intake_privacy_guidance": template_checks["issue_intake_privacy_note"]
        and template_checks["issue_intake_redaction_guidance"],
        "feedback_storage_guidance": template_checks["feedback_storage_note"]
        and template_checks["feedback_no_commit"]
        and template_checks["feedback_private_workspace"],
        "support_privacy_guardrails": ".env" in do_not_share and "raw AI reply" in do_not_share,
        "copy_paste_message_ready": "sha256:" in copy_paste_message
        and "provider API key" in copy_paste_message
        and "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message
        and "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in copy_paste_message
        and "CONFIRMED" in copy_paste_message
        and "reply only" in copy_paste_message,
        "pilot_success_criteria_actionable": len(pilot_success_criteria) >= 5
        and any("promoted pack" in item for item in pilot_success_criteria)
        and any("diagnostics" in item for item in pilot_success_criteria),
        "pilot_stop_rule_present": "stop_and_redesign" in pilot_decision_thresholds,
    }
    verdict = "GO" if all(business_checks.values()) else "NO_GO"
    payload = {
        "schema_version": PILOT_READY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pilot_ready" if verdict == "GO" else "blocked",
        "verdict": verdict,
        "safe_to_share": True,
        "release": {
            "version": release.get("version"),
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "send_ready": {
            "file": SEND_READY_JSON_NAME,
            "markdown": SEND_READY_MD_NAME,
            "body_sha256": send_ready.get("send_ready_body_sha256"),
            "verified_standalone": True,
        },
        "handoff": {
            "file": HANDOFF_JSON_NAME,
            "markdown": HANDOFF_MD_NAME,
            "body_sha256": handoff.get("body_sha256"),
            "verified_standalone": True,
        },
        "receipt": {
            "file": RECEIPT_NAME,
            "body_sha256": receipt_summary.get("body_sha256"),
            "verified_standalone": True,
            "safe_to_share": receipt.get("safe_to_share") is True,
        },
        "pilot_templates": list(PILOT_TEMPLATE_PATHS),
        "pilot_template_checks": template_checks,
        "dispatch_execution_policy": dispatch_execution_policy,
        "pilot_dispatch": _pilot_dispatch(copy_paste_message),
        "pilot_success_criteria": pilot_success_criteria,
        "pilot_decision_thresholds": pilot_decision_thresholds,
        "checks": business_checks,
        "operator_next_action": (
            "Manually send the ZIP and pilot-dispatch copy_paste_message to exactly one external alpha "
            "recipient, then record only private hashes after sending."
            if verdict == "GO"
            else "Fix the failed checks, then rerun pilot-ready."
        ),
        "do_not_share": do_not_share,
    }
    payload["pilot_ready_body_sha256"] = _pilot_ready_body_sha256(payload)
    payload["artifact_chain"] = _pilot_artifact_chain(send_ready, payload)
    payload["pilot_ready_checks"] = _pilot_ready_checks(payload)
    verify_pilot_ready_payload(payload)
    return payload


def verify_pilot_ready_file(path: Path) -> dict[str, Any]:
    """Read and verify a pilot-ready JSON file."""
    payload = _read_json(path)
    verify_pilot_ready_payload(payload)
    return payload


def verify_pilot_ready_payload(payload: dict[str, Any]) -> None:
    """Verify the pilot-ready JSON contract for the first external send."""
    if payload.get("schema_version") != PILOT_READY_SCHEMA_VERSION:
        raise PilotReadyError("pilot-ready schema_version is invalid.")
    if payload.get("status") != "pilot_ready":
        raise PilotReadyError(f"pilot-ready status is not pilot_ready: {payload.get('status')}")
    if payload.get("verdict") != "GO":
        raise PilotReadyError(f"pilot-ready verdict is not GO: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise PilotReadyError("pilot-ready safe_to_share is not true.")

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PilotReadyError("pilot-ready checks are not all true.")

    pilot_ready_checks = payload.get("pilot_ready_checks") if isinstance(payload.get("pilot_ready_checks"), dict) else {}
    if not pilot_ready_checks:
        raise PilotReadyError("pilot_ready_checks is missing.")
    if payload.get("pilot_ready_body_sha256") != _pilot_ready_body_sha256(payload):
        raise PilotReadyError("pilot-ready body hash does not match.")
    recalculated_checks = _pilot_ready_checks(payload)
    if pilot_ready_checks != recalculated_checks:
        raise PilotReadyError("pilot-ready safety checks do not match the current body.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise PilotReadyError("pilot-ready safety checks failed: " + ", ".join(failed_checks))


def _pilot_template_checks() -> dict[str, bool]:
    """첫 파일럿 템플릿이 개인정보 보호와 사후 판단 기준을 담는지 확인한다."""
    issue_path = ROOT / PILOT_TEMPLATE_PATHS[0]
    feedback_path = ROOT / PILOT_TEMPLATE_PATHS[1]
    issue_text = issue_path.read_text(encoding="utf-8") if issue_path.is_file() else ""
    feedback_text = feedback_path.read_text(encoding="utf-8") if feedback_path.is_file() else ""
    return {
        "issue_intake_exists": issue_path.is_file(),
        "issue_intake_privacy_note": "Privacy note" in issue_text,
        "issue_intake_redaction_guidance": all(
            phrase in issue_text for phrase in ["API keys", "local absolute paths", "private source", "personal information"]
        ),
        "feedback_form_exists": feedback_path.is_file(),
        "feedback_storage_note": "Storage note" in feedback_text,
        "feedback_no_commit": "Do not commit filled forms" in feedback_text,
        "feedback_private_workspace": "private workspace" in feedback_text,
    }


def _pilot_success_criteria() -> list[str]:
    """Observable success criteria for the first external alpha pilot."""
    return [
        "The recipient opens Builder from QUICKSTART_EXTERNAL_ALPHA.md or START_CAMBRIAN_AGENT_PLATFORM.bat.",
        "The recipient creates or imports a promoted pack and promotion audit record.",
        "Private Download Hub shows promoted_private=true, proof claims blocked, sale claims blocked, and audit count 1.",
        "If anything fails, the recipient follows EXTERNAL_ALPHA_SUPPORT_PACKET.md and sends only receipt/diagnostics JSON.",
        "Pilot notes are captured in docs/launch/PILOT_ISSUE_INTAKE.md and docs/launch/PILOT_FEEDBACK_FORM.md without raw private data.",
    ]


def _pilot_decision_thresholds() -> dict[str, list[str]]:
    """Operational thresholds for continue, fix, or stop decisions after the first pilot."""
    return {
        "continue": [
            "The recipient opens Builder locally and completes the sample promoted-pack flow.",
            "The recipient can share diagnostics and receipt artifacts marked safe_to_share.",
            "Proof, sale, and performance claims remain clearly blocked instead of overstated.",
        ],
        "fix_before_next": [
            "The batch file, install instructions, or handoff wording blocks the recipient.",
            "The recipient cannot tell what to send back using the support packet alone.",
            "The same unclear step appears twice in pilot feedback.",
        ],
        "stop_and_redesign": [
            "The recipient believes they need an API key, cloud account, public marketplace, or payment setup.",
            "The recipient tries to send secrets, private source files, or raw AI replies.",
            "The product presents proof or sale readiness more strongly than the alpha actually supports.",
        ],
    }


def _pilot_dispatch(copy_paste_message: str) -> dict[str, Any]:
    """Build the manual first-pilot dispatch packet for exactly one recipient."""
    return {
        "target_participants": 1,
        "timebox_minutes": 10,
        "execution_policy": _pilot_dispatch_execution_policy(),
        "send_to_recipient": [
            f"{RELEASE_SLUG}.zip",
            "ZIP sha256",
            "QUICKSTART_EXTERNAL_ALPHA.md",
            "copy_paste_message",
        ],
        "copy_paste_message": copy_paste_message,
        "recipient_checklist": [
            "Read QUICKSTART_EXTERNAL_ALPHA.md first.",
            "Use START_HERE_EXTERNAL_ALPHA.md only if the quickstart path is unclear.",
            "If delegating to Claude/Codex, paste RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md exactly.",
            "Run START_CAMBRIAN_AGENT_PLATFORM.bat.",
            "In Builder, create the promoted pack and promotion audit record.",
            "Confirm promoted private, proof blocked, sale blocked, and audit count 1.",
            "If anything fails, read EXTERNAL_ALPHA_SUPPORT_PACKET.md and send only receipt/diagnostics JSON.",
        ],
        "collect_after_pilot": [
            "docs/launch/PILOT_FEEDBACK_FORM.md",
            "docs/launch/PILOT_ISSUE_INTAKE.md",
            "external_alpha_release_verification_receipt.json",
            "external_alpha_diagnostics.json",
        ],
        "operator_rule": (
            "Send to exactly one external alpha recipient first. Review the result before expanding "
            "to another recipient."
        ),
    }


def _pilot_dispatch_execution_policy() -> dict[str, Any]:
    return {
        "script_sends_to_recipient": False,
        "script_sends_copy_paste_message": False,
        "manual_operator_dispatch_required": True,
        "max_recipients_per_pilot": 1,
        "cohort_scaling_allowed": False,
        "records_private_sha256_only_after_send": True,
        "raw_private_content_included": False,
    }


def _pilot_ready_body_sha256(payload: dict[str, Any]) -> str:
    """pilot-ready 검증 본문만 정규화해 sha256 해시를 계산한다."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pilot_ready_body_sha256", "artifact_chain", "pilot_ready_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pilot_artifact_chain(send_ready: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    """send-ready 증거 체인에 pilot-ready 판정서 해시를 덧붙인다."""
    source_chain = send_ready.get("artifact_chain") if isinstance(send_ready.get("artifact_chain"), list) else []
    chain = [
        {
            "kind": str(item.get("kind") or ""),
            "file": str(item.get("file") or ""),
            "sha256": str(item.get("sha256") or ""),
        }
        for item in source_chain
        if isinstance(item, dict)
    ]
    chain.append(
        {
            "kind": "pilot_ready_json",
            "file": PILOT_READY_JSON_NAME,
            "sha256": str(payload.get("pilot_ready_body_sha256") or ""),
        }
    )
    return chain


def _pilot_ready_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """Verify the pilot-ready payload can be shared and sent to one recipient."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    send_ready = payload.get("send_ready") if isinstance(payload.get("send_ready"), dict) else {}
    handoff = payload.get("handoff") if isinstance(payload.get("handoff"), dict) else {}
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    dispatch_execution_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    dispatch = payload.get("pilot_dispatch") if isinstance(payload.get("pilot_dispatch"), dict) else {}
    dispatch_policy = (
        dispatch.get("execution_policy") if isinstance(dispatch.get("execution_policy"), dict) else {}
    )
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    copy_paste_message = str(dispatch.get("copy_paste_message") or "")
    body_hash = payload.get("pilot_ready_body_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    return {
        "schema_version_present": payload.get("schema_version") == PILOT_READY_SCHEMA_VERSION,
        "verdict_go": payload.get("verdict") == "GO",
        "pilot_ready_status": payload.get("status") == "pilot_ready",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "send_ready_body_hash_present": _looks_like_sha256(send_ready.get("body_sha256")),
        "send_ready_verified_standalone": send_ready.get("verified_standalone") is True,
        "receipt_body_hash_present": _looks_like_sha256(receipt.get("body_sha256")),
        "receipt_verified_standalone": receipt.get("verified_standalone") is True,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": {
            "release_zip",
            "handoff_json",
            "receipt_json",
            "send_ready_json",
            "pilot_ready_json",
        }.issubset(set(chain_by_kind)),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_handoff_hash_matched": chain_by_kind.get("handoff_json", {}).get("sha256")
        == handoff.get("body_sha256"),
        "artifact_chain_receipt_hash_matched": chain_by_kind.get("receipt_json", {}).get("sha256")
        == receipt.get("body_sha256"),
        "artifact_chain_send_ready_hash_matched": chain_by_kind.get("send_ready_json", {}).get("sha256")
        == send_ready.get("body_sha256"),
        "artifact_chain_pilot_ready_hash_matched": chain_by_kind.get("pilot_ready_json", {}).get("sha256")
        == body_hash,
        "pilot_templates_named": set(payload.get("pilot_templates", [])) == set(PILOT_TEMPLATE_PATHS),
        "dispatch_timebox_present": dispatch.get("timebox_minutes") == 10,
        "dispatch_execution_policy_matched": dispatch_execution_policy == DISPATCH_EXECUTION_POLICY,
        "dispatch_execution_policy_manual_only": dispatch_execution_policy.get("script_sends_to_recipient") is False
        and dispatch_execution_policy.get("script_sends_copy_paste_message") is False
        and dispatch_execution_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_execution_policy_one_recipient": dispatch_execution_policy.get("max_recipients_per_record") == 1
        and dispatch_execution_policy.get("cohort_scaling_allowed") is False,
        "dispatch_execution_policy_private_hash_only": dispatch_execution_policy.get("records_private_sha256_only") is True
        and dispatch_execution_policy.get("raw_private_content_included") is False,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_pilot") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only_after_send") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "dispatch_collects_feedback": "docs/launch/PILOT_FEEDBACK_FORM.md"
        in dispatch.get("collect_after_pilot", []),
        "dispatch_collects_issue_intake": "docs/launch/PILOT_ISSUE_INTAKE.md"
        in dispatch.get("collect_after_pilot", []),
        "dispatch_recipient_ack_request_present": "CONFIRMED" in copy_paste_message
        and "reply only" in copy_paste_message,
        "dispatch_quickstart_present": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message
        and any("QUICKSTART_EXTERNAL_ALPHA.md" in str(item) for item in dispatch.get("recipient_checklist", [])),
        "dispatch_agent_prompt_present": "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md"
        in copy_paste_message
        and any(
            "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in str(item)
            for item in dispatch.get("recipient_checklist", [])
        ),
        "do_not_share_guardrails_present": ".env" in do_not_share and "raw AI reply" in do_not_share,
        "pilot_ready_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "pilot_ready_body_hash_matched": body_hash == _pilot_ready_body_sha256(payload),
    }


def _pilot_ready_markdown(payload: dict[str, Any]) -> str:
    """파일럿 준비 판정서를 사람이 읽을 수 있는 Markdown으로 만든다."""
    dispatch_execution_policy = payload["dispatch_execution_policy"]
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    success = "\n".join(f"{index}. {item}" for index, item in enumerate(payload["pilot_success_criteria"], start=1))
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    continue_rules = "\n".join(f"- {item}" for item in payload["pilot_decision_thresholds"]["continue"])
    fix_rules = "\n".join(f"- {item}" for item in payload["pilot_decision_thresholds"]["fix_before_next"])
    stop_rules = "\n".join(f"- {item}" for item in payload["pilot_decision_thresholds"]["stop_and_redesign"])
    return f"""# Cambrian External Alpha Pilot Ready

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- pilot-ready body sha256: {payload["pilot_ready_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- send-ready: {payload["send_ready"]["file"]}
- send-ready body sha256: {payload["send_ready"]["body_sha256"]}
- handoff: {payload["handoff"]["file"]}
- receipt: {payload["receipt"]["file"]}

## Checks

{checks}

## Artifact Chain

{artifact_chain}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_execution_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_execution_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_execution_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_execution_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_execution_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_execution_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_execution_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_execution_policy["sent_recorded_by_private_hashes_only"]}

## Pilot Success Criteria

{success}

## Continue

{continue_rules}

## Fix Before Next

{fix_rules}

## Stop And Redesign

{stop_rules}

## Do Not Share

{do_not_share}

## Agent Prompt

- QUICKSTART_EXTERNAL_ALPHA.md
- RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md

## Operator Next Action

{payload["operator_next_action"]}
"""


def _pilot_dispatch_markdown(payload: dict[str, Any]) -> str:
    """첫 외부 파일럿 발송용 운영표를 Markdown으로 만든다."""
    dispatch = payload["pilot_dispatch"]
    execution_policy = dispatch["execution_policy"]
    recipient_checklist = "\n".join(
        f"{index}. {item}" for index, item in enumerate(dispatch["recipient_checklist"], start=1)
    )
    collect_after_pilot = "\n".join(f"- {item}" for item in dispatch["collect_after_pilot"])
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    stop_rules = "\n".join(f"- {item}" for item in payload["pilot_decision_thresholds"]["stop_and_redesign"])
    return f"""# Cambrian External Alpha Pilot Dispatch

## Send One First

- target participants: {dispatch["target_participants"]}
- timebox minutes: {dispatch["timebox_minutes"]}
- verdict: {payload["verdict"]}
- pilot-ready body sha256: {payload["pilot_ready_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}

## Execution Policy

- script sends to recipient: {execution_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {execution_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {execution_policy["manual_operator_dispatch_required"]}
- max recipients per pilot: {execution_policy["max_recipients_per_pilot"]}
- cohort scaling allowed: {execution_policy["cohort_scaling_allowed"]}
- records private sha256 only after send: {execution_policy["records_private_sha256_only_after_send"]}
- raw private content included: {execution_policy["raw_private_content_included"]}

## Copy Paste Message

```text
{dispatch["copy_paste_message"]}
```

## Recipient Checklist

{recipient_checklist}

## Collect After Pilot

{collect_after_pilot}

## Do Not Share

{do_not_share}

## Stop And Redesign If

{stop_rules}

## Operator Rule

{dispatch["operator_rule"]}
"""


def _read_json(path: Path) -> dict[str, Any]:
    """JSON 파일을 읽고 객체인지 확인한다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PilotReadyError(f"JSON 파일을 읽을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PilotReadyError(f"JSON 파싱 실패: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PilotReadyError(f"JSON 객체가 아닙니다: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON 파일을 안정적인 순서로 쓴다."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _looks_like_sha256(value: Any) -> bool:
    """sha256 문자열 형식인지 확인한다."""
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _assert_shareable_file(path: Path) -> None:
    """생성된 판정서에 로컬 절대경로와 테스트 시크릿이 없는지 확인한다."""
    text = path.read_text(encoding="utf-8")
    forbidden_fragments = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [fragment for fragment in forbidden_fragments if fragment and fragment in text]
    if found:
        raise PilotReadyError(f"pilot-ready 판정서에 공유하면 안 되는 경로 또는 값이 포함되었습니다: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
