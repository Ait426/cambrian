from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_cambrian_install_kit_handoff import (  # noqa: E402
    HANDOFF_JSON_NAME,
    HANDOFF_MD_NAME,
    prepare_handoff,
    verify_handoff_file,
)
from scripts.verify_cambrian_install_kit import (  # noqa: E402
    verify_shareable_receipt_file,
)


SEND_READY_SCHEMA_VERSION = "cambrian_install_kit_send_ready_v0_1"
SEND_READY_JSON_NAME = "cambrian-install-kit-send-ready.json"
SEND_READY_MD_NAME = "cambrian-install-kit-send-ready.md"
RECEIPT_NAME = "cambrian-install-kit-verification-receipt.json"


def _repo_root() -> Path:
    return ROOT


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_send_ready(output_dir: Path | None = None, skip_verify: bool = False) -> dict[str, Any]:
    """Install kit handoff와 receipt를 발송 직전 GO/NO-GO 판정서로 묶는다."""
    dist = (output_dir or _repo_root() / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)
    handoff_result = prepare_handoff(output_dir=dist, skip_verify=skip_verify)
    handoff_path = Path(str(handoff_result["handoff_json"]))
    receipt_path = Path(str(handoff_result["receipt_json"]))
    handoff = verify_handoff_file(handoff_path)
    receipt = verify_shareable_receipt_file(receipt_path)
    payload = _send_ready_payload(handoff, receipt)

    json_path = dist / SEND_READY_JSON_NAME
    md_path = dist / SEND_READY_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_send_ready_markdown(payload), encoding="utf-8")
    verify_send_ready_file(json_path)
    return {
        "status": "prepared",
        "verdict": payload["verdict"],
        "send_ready_json": str(json_path),
        "send_ready_md": str(md_path),
        "handoff_json": str(handoff_path),
        "receipt_json": str(receipt_path),
        "send_ready_body_sha256": payload["send_ready_body_sha256"],
    }


def verify_send_ready_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("install kit send-ready JSON 객체가 아닙니다.")
    _verify_send_ready(payload)
    return payload


def _send_ready_payload(handoff: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    handoff_checks = handoff.get("handoff_checks") if isinstance(handoff.get("handoff_checks"), dict) else {}
    receipt_checks = receipt.get("receipt_checks") if isinstance(receipt.get("receipt_checks"), dict) else {}
    policy = handoff.get("dispatch_execution_policy") if isinstance(handoff.get("dispatch_execution_policy"), dict) else {}
    install_kit = handoff.get("install_kit") if isinstance(handoff.get("install_kit"), dict) else {}
    capabilities = handoff.get("verified_capabilities") if isinstance(handoff.get("verified_capabilities"), dict) else {}
    checks = {
        "handoff_checks_true": bool(handoff_checks) and all(value is True for value in handoff_checks.values()),
        "receipt_checks_true": bool(receipt_checks) and all(value is True for value in receipt_checks.values()),
        "zip_hash_present": _looks_like_sha256(install_kit.get("zip_sha256")),
        "receipt_hash_matched": install_kit.get("receipt_body_sha256") == receipt.get("receipt_body_sha256"),
        "company_snapshot_help_verified": capabilities.get("company_snapshot_help") is True,
        "company_snapshot_next_command_verified": capabilities.get("company_snapshot_next_command") is True,
        "mcp_operability_verified": capabilities.get("mcp_operability") is True,
        "manual_dispatch_required": policy.get("script_sends_to_recipient") is False
        and policy.get("script_sends_copy_paste_message") is False
        and policy.get("manual_operator_dispatch_required") is True,
        "max_one_recipient": policy.get("max_recipients_per_record") == 1,
        "do_not_share_guardrails_present": ".env" in handoff.get("do_not_share", [])
        and "raw private project data" in handoff.get("do_not_share", []),
        "copy_paste_message_present": isinstance(handoff.get("copy_paste_message"), str)
        and "cambrian company snapshot --help" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_mentions_bundle_installer": isinstance(handoff.get("copy_paste_message"), str)
        and "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_mentions_gold_path_runner": isinstance(handoff.get("copy_paste_message"), str)
        and "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_mentions_share_receipt": isinstance(handoff.get("copy_paste_message"), str)
        and "cambrian_install_share_receipt.json" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_mentions_gold_path_share_receipt": isinstance(handoff.get("copy_paste_message"), str)
        and "cambrian_gold_path_share_receipt.json" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_mentions_mcp_operability_receipt": isinstance(handoff.get("copy_paste_message"), str)
        and "mcp_operability_receipt.json" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_marks_local_validation_only": isinstance(handoff.get("copy_paste_message"), str)
        and "local validation evidence only" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_blocks_public_proof_claims": isinstance(handoff.get("copy_paste_message"), str)
        and "do not claim public proof" in handoff.get("copy_paste_message", ""),
        "copy_paste_message_blocks_first_recipient_claims": isinstance(handoff.get("copy_paste_message"), str)
        and "First-recipient confirmation requires a real human send" in handoff.get("copy_paste_message", ""),
    }
    verdict = "GO" if all(value is True for value in checks.values()) else "NO_GO"
    payload: dict[str, Any] = {
        "schema_version": SEND_READY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "safe_to_share": True,
        "install_kit": {
            "zip_file": install_kit.get("zip_file"),
            "zip_sha256": install_kit.get("zip_sha256"),
            "receipt_file": install_kit.get("receipt_file"),
            "receipt_body_sha256": install_kit.get("receipt_body_sha256"),
            "manifest_version": install_kit.get("manifest_version"),
        },
        "handoff": {
            "file": HANDOFF_JSON_NAME,
            "markdown_file": HANDOFF_MD_NAME,
            "body_sha256": handoff.get("handoff_body_sha256"),
            "verified_standalone": True,
        },
        "receipt": {
            "file": RECEIPT_NAME,
            "body_sha256": receipt.get("receipt_body_sha256"),
            "verified_standalone": True,
        },
        "verified_capabilities": capabilities,
        "checks": checks,
        "copy_paste_message": handoff.get("copy_paste_message"),
        "dispatch_execution_policy": policy,
        "artifact_chain": [
            {
                "kind": "install_kit_zip",
                "file": str(install_kit.get("zip_file") or ""),
                "sha256": str(install_kit.get("zip_sha256") or ""),
            },
            {
                "kind": "install_kit_receipt",
                "file": str(install_kit.get("receipt_file") or ""),
                "sha256": str(receipt.get("receipt_body_sha256") or ""),
            },
            {
                "kind": "install_kit_handoff",
                "file": HANDOFF_JSON_NAME,
                "sha256": str(handoff.get("handoff_body_sha256") or ""),
            },
        ],
        "do_not_share": handoff.get("do_not_share"),
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    payload["send_ready_body_sha256"] = _send_ready_body_sha256(payload)
    payload["send_ready_checks"] = _send_ready_checks(payload)
    return payload


def _send_ready_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "send_ready_body_sha256", "send_ready_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _send_ready_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(_repo_root())
    home = str(Path.home())
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    body_hash = payload.get("send_ready_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == SEND_READY_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "verdict_go": payload.get("verdict") == "GO",
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": {"install_kit_zip", "install_kit_receipt", "install_kit_handoff"}.issubset(
            {str(item.get("kind") or "") for item in chain if isinstance(item, dict)}
        ),
        "manual_dispatch_policy_present": payload.get("dispatch_execution_policy", {}).get("manual_operator_dispatch_required") is True,
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _send_ready_body_sha256(payload),
    }


def _verify_send_ready(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SEND_READY_SCHEMA_VERSION:
        raise ValueError("install kit send-ready schema_version이 올바르지 않습니다.")
    send_ready_checks = payload.get("send_ready_checks") if isinstance(payload.get("send_ready_checks"), dict) else {}
    failed = [name for name, passed in send_ready_checks.items() if passed is not True]
    if failed:
        raise ValueError("install kit send-ready 검증 실패: " + ", ".join(failed))
    if payload.get("send_ready_body_sha256") != _send_ready_body_sha256(payload):
        raise ValueError("install kit send-ready 본문 해시가 일치하지 않습니다.")


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _send_ready_markdown(payload: dict[str, Any]) -> str:
    kit = payload["install_kit"]
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian Install Kit Send Ready

## Verdict

`{payload["verdict"]}`

## Artifact

- ZIP: `{kit["zip_file"]}`
- ZIP sha256: `{kit["zip_sha256"]}`
- Receipt: `{kit["receipt_file"]}`
- Receipt body sha256: `{kit["receipt_body_sha256"]}`
- Handoff: `{payload["handoff"]["file"]}`
- Handoff body sha256: `{payload["handoff"]["body_sha256"]}`

## Copy-Paste Message

```text
{payload["copy_paste_message"]}
```

## Do Not Share

{do_not_share}

## Boundary

This send-ready receipt records install-kit delivery readiness only. Scripts do not send ZIP files, upload data, publish packages, or send messages to recipients automatically.
"""
    return f"""# Cambrian Install Kit Send Ready

## Verdict

`{payload["verdict"]}`

## Artifact

- ZIP: `{kit["zip_file"]}`
- ZIP sha256: `{kit["zip_sha256"]}`
- Receipt: `{kit["receipt_file"]}`
- Receipt body sha256: `{kit["receipt_body_sha256"]}`
- Handoff: `{payload["handoff"]["file"]}`
- Handoff body sha256: `{payload["handoff"]["body_sha256"]}`

## Copy-Paste Message

```text
{payload["copy_paste_message"]}
```

## Do Not Share

{do_not_share}

## Boundary

이 판정서는 install kit 발송 준비 상태만 기록한다. 스크립트는 수령자에게 ZIP이나 메시지를 직접 보내지 않는다.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian install kit 발송 직전 GO/NO-GO를 확인한다.")
    parser.add_argument("--output-dir", type=Path, default=None, help="send-ready 산출물 출력 폴더. 기본값은 dist")
    parser.add_argument("--skip-verify", action="store_true", help="handoff 준비 시 ZIP 재검증을 건너뛴다.")
    parser.add_argument("--verify-send-ready", type=Path, default=None, help="기존 send-ready JSON만 검증한다.")
    args = parser.parse_args()
    if args.verify_send_ready:
        payload = verify_send_ready_file(args.verify_send_ready)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    result = check_send_ready(output_dir=args.output_dir, skip_verify=bool(args.skip_verify))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
