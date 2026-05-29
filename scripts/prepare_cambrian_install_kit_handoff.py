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

from scripts.verify_cambrian_install_kit import (
    verify_install_kit,
    verify_shareable_receipt_file,
    write_shareable_receipt,
)


HANDOFF_SCHEMA_VERSION = "cambrian_install_kit_handoff_v0_1"
HANDOFF_JSON_NAME = "cambrian-install-kit-handoff.json"
HANDOFF_MD_NAME = "cambrian-install-kit-handoff.md"
RECEIPT_NAME = "cambrian-install-kit-verification-receipt.json"
RELEASE_BUNDLE_NAME = "cambrian-install-kit-release-bundle.zip"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_zip() -> Path:
    candidates = sorted(
        (
            path
            for path in (_repo_root() / "dist").glob("cambrian-install-kit-*.zip")
            if path.name != RELEASE_BUNDLE_NAME
        ),
        key=lambda path: path.stat().st_mtime,
    )
    if candidates:
        return candidates[-1]
    return _repo_root() / "dist" / "cambrian-install-kit-0.3.0.zip"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prepare_handoff(
    output_dir: Path | None = None,
    zip_path: Path | None = None,
    receipt_path: Path | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Cambrian install kit ZIP과 공유 receipt를 수령자 handoff로 묶는다."""
    root = _repo_root()
    dist = (output_dir or root / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)
    resolved_zip = (zip_path or _default_zip()).resolve()
    resolved_receipt = (receipt_path or dist / RECEIPT_NAME).resolve()

    if not skip_verify:
        result = verify_install_kit(resolved_zip, install_check=True, offline=True)
        write_shareable_receipt(resolved_receipt, result)
    receipt = verify_shareable_receipt_file(resolved_receipt)
    payload = _handoff_payload(resolved_zip, resolved_receipt, receipt)

    json_path = dist / HANDOFF_JSON_NAME
    md_path = dist / HANDOFF_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_handoff_markdown(payload), encoding="utf-8")
    verify_handoff_file(json_path)
    return {
        "status": "prepared",
        "handoff_json": str(json_path),
        "handoff_md": str(md_path),
        "receipt_json": str(resolved_receipt),
        "zip_file": str(resolved_zip),
        "handoff_body_sha256": payload["handoff_body_sha256"],
    }


def verify_handoff_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("install kit handoff JSON 객체가 아닙니다.")
    _verify_handoff(payload)
    return payload


def _handoff_payload(zip_path: Path, receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    zip_name = zip_path.name
    receipt_name = receipt_path.name
    copy_paste_message = (
        "이 파일은 Cambrian install kit release bundle입니다. 압축을 풀고 "
        "`python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>`를 실행하세요. "
        "Windows에서는 `INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\\path\\to\\project`를 사용할 수 있습니다. "
        "install kit ZIP만 따로 받았다면 INSTALL_PROMPT_FOR_CODEX_CLAUDE.md를 따라 설치하세요. "
        "설치 후 cambrian_install_receipt.json에서 cambrian --help, "
        "cambrian doctor --json, cambrian company snapshot --help가 PASS인지 확인하세요. "
        "그 다음 `python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>`를 실행하고 "
        "cambrian_gold_path_share_receipt.json의 status가 passed인지 확인하세요. "
        "문제가 있으면 절대경로가 들어 있는 cambrian_install_receipt.json 대신 "
        "cambrian_install_share_receipt.json, cambrian_gold_path_share_receipt.json 또는 공유 가능한 install kit verification receipt만 보내세요. "
        "비밀값, .env, 사용자 원문 파일, 스크린샷 원문은 보내지 마세요."
    )
    payload: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_to_share",
        "safe_to_share": True,
        "install_kit": {
            "zip_file": zip_name,
            "zip_sha256": _sha256(zip_path),
            "receipt_file": receipt_name,
            "receipt_body_sha256": receipt.get("receipt_body_sha256"),
            "manifest_version": receipt.get("install_kit", {}).get("manifest_version"),
        },
        "recipient_steps": [
            "release bundle ZIP 압축을 푼다.",
            "bundle 루트에서 python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>를 실행한다.",
            "Windows에서는 INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\\path\\to\\project를 사용할 수 있다.",
            "install kit ZIP만 따로 받은 경우 INSTALL_PROMPT_FOR_CODEX_CLAUDE.md 내용을 Claude/Codex에 붙여넣는다.",
            "cambrian_install_receipt.json의 PASS step을 확인한다.",
            "bundle 루트에서 python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>를 실행한다.",
            "cambrian_gold_path_share_receipt.json의 status: passed와 capabilities_verified가 모두 true인지 확인한다.",
            "지원 요청에는 cambrian_install_receipt.json 대신 cambrian_install_share_receipt.json만 공유한다.",
            "gold path 지원 요청에는 cambrian_gold_path_receipt.json 대신 cambrian_gold_path_share_receipt.json만 공유한다.",
            "AI Company evidence가 쌓인 뒤 cambrian company snapshot --json을 실행할 수 있다.",
        ],
        "verified_capabilities": {
            "offline_install": receipt.get("verification", {}).get("offline") is True,
            "cambrian_help": receipt.get("capabilities", {}).get("cambrian_help") is True,
            "doctor_json": receipt.get("capabilities", {}).get("doctor_json") is True,
            "company_snapshot_help": receipt.get("capabilities", {}).get("company_snapshot_help") is True,
            "company_snapshot_next_command": receipt.get("capabilities", {}).get("company_snapshot_next_command") is True,
        },
        "do_not_share": [
            ".env",
            "API keys or secrets",
            "raw private project data",
            "temporary install paths",
            "screenshots containing private code or user data",
        ],
        "copy_paste_message": copy_paste_message,
        "dispatch_execution_policy": {
            "script_sends_to_recipient": False,
            "script_sends_copy_paste_message": False,
            "manual_operator_dispatch_required": True,
            "max_recipients_per_record": 1,
        },
        "artifact_chain": [
            {"kind": "install_kit_zip", "file": zip_name, "sha256": _sha256(zip_path)},
            {"kind": "install_kit_receipt", "file": receipt_name, "sha256": str(receipt.get("receipt_body_sha256") or "")},
        ],
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    payload["copy_paste_message"] = (
        "This is the Cambrian install kit release bundle. Extract it, then run "
        "`python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>` from the extracted bundle directory. "
        "On Windows, you may run `INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\\path\\to\\project`. "
        "After install, confirm `cambrian_install_share_receipt.json` exists and is safe to share. "
        "The local install receipt should show `cambrian --help`, `cambrian doctor --json`, "
        "and `cambrian company snapshot --help` passed. "
        "Then run `python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>` and confirm "
        "`cambrian_gold_path_share_receipt.json` has status `passed`. "
        "If support is needed, share only `cambrian_install_share_receipt.json`, "
        "`cambrian_gold_path_share_receipt.json`, and requested share-safe summaries. "
        "Do not share `.env`, API keys, secrets, raw private project data, temporary install paths, "
        "or screenshots containing private code or user data."
    )
    claim_boundary_message = (
        "Treat local install, MCP, and gold-path receipts as local validation evidence only; "
        "do not claim public proof, sale readiness, marketplace readiness, success rate, "
        "or first-recipient confirmation from this local run. "
        "First-recipient confirmation requires a real human send and returned share-safe receipts through the sender checkpoint."
    )
    payload["recipient_steps"] = [
        "Extract the release bundle ZIP.",
        "From the bundle root, run python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>.",
        "On Windows, use INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\\path\\to\\project if preferred.",
        "Confirm cambrian_install_receipt.json and cambrian_install_share_receipt.json were written in the target project.",
        "Confirm the install receipt shows cambrian --help, cambrian doctor --json, and cambrian company snapshot --help passed.",
        "From the bundle root, run python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>.",
        "Confirm cambrian_gold_path_share_receipt.json has status: passed and all capabilities_verified values are true.",
        "For support, share only cambrian_install_share_receipt.json unless local debug receipts are explicitly requested.",
        "For gold path support, share only cambrian_gold_path_share_receipt.json unless local debug receipts are explicitly requested.",
        claim_boundary_message,
        "Run cambrian company snapshot --json only after private evidence boundaries are understood.",
    ]
    payload["copy_paste_message"] = (
        f"{payload['copy_paste_message']} "
        "Confirm mcp_operability_receipt.json has verdict: GO, server_command_mode: installed_entrypoint, "
        "installed_entrypoint_command: true, source_pythonpath_injected: false, and no_arbitrary_shell: true. "
        f"{claim_boundary_message}"
    )
    payload["recipient_steps"].insert(
        5,
        "mcp_operability_receipt.json has verdict: GO, installed_entrypoint, source_pythonpath_injected: false, and no_arbitrary_shell.",
    )
    payload["verified_capabilities"]["mcp_operability"] = receipt.get("capabilities", {}).get("mcp_operability") is True
    payload["handoff_body_sha256"] = _handoff_body_sha256(payload)
    payload["handoff_checks"] = _handoff_checks(payload)
    return payload


def _handoff_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "handoff_body_sha256", "handoff_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _handoff_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(_repo_root())
    home = str(Path.home())
    capabilities = payload.get("verified_capabilities") if isinstance(payload.get("verified_capabilities"), dict) else {}
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    policy = payload.get("dispatch_execution_policy") if isinstance(payload.get("dispatch_execution_policy"), dict) else {}
    body_hash = payload.get("handoff_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == HANDOFF_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "status_ready": payload.get("status") == "ready_to_share",
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "verified_capabilities_all_true": bool(capabilities) and all(value is True for value in capabilities.values()),
        "company_snapshot_help_verified": capabilities.get("company_snapshot_help") is True,
        "artifact_chain_complete": {"install_kit_zip", "install_kit_receipt"}.issubset(
            {str(item.get("kind") or "") for item in chain if isinstance(item, dict)}
        ),
        "manual_dispatch_required": policy.get("script_sends_to_recipient") is False
        and policy.get("manual_operator_dispatch_required") is True,
        "do_not_share_guardrails_present": ".env" in payload.get("do_not_share", [])
        and "raw private project data" in payload.get("do_not_share", []),
        "gold_path_runner_named": "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py" in serialized,
        "gold_path_share_receipt_named": "cambrian_gold_path_share_receipt.json" in serialized,
        "mcp_operability_named": "mcp_operability_receipt.json" in serialized,
        "mcp_operability_verified": capabilities.get("mcp_operability") is True,
        "claim_boundary_present": "local validation evidence only" in serialized
        and "do not claim public proof" in serialized
        and "First-recipient confirmation requires a real human send" in serialized,
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _handoff_body_sha256(payload),
    }


def _verify_handoff(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        raise ValueError("install kit handoff schema_version이 올바르지 않습니다.")
    checks = payload.get("handoff_checks") if isinstance(payload.get("handoff_checks"), dict) else {}
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise ValueError("install kit handoff 검증 실패: " + ", ".join(failed))
    if payload.get("handoff_body_sha256") != _handoff_body_sha256(payload):
        raise ValueError("install kit handoff 본문 해시가 일치하지 않습니다.")


def _handoff_markdown(payload: dict[str, Any]) -> str:
    kit = payload["install_kit"]
    steps = "\n".join(f"{idx}. {step}" for idx, step in enumerate(payload["recipient_steps"], start=1))
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian Install Kit Handoff

## Artifact

- ZIP: `{kit["zip_file"]}`
- ZIP sha256: `{kit["zip_sha256"]}`
- Receipt: `{kit["receipt_file"]}`
- Receipt body sha256: `{kit["receipt_body_sha256"]}`

## Recipient Steps

{steps}

## Copy-Paste Message

```text
{payload["copy_paste_message"]}
```

## Do Not Share

{do_not_share}

## Boundary

This handoff records install-kit delivery readiness only. Scripts do not send files, upload data, publish packages, or send messages to recipients automatically.
"""
    return f"""# Cambrian Install Kit Handoff

## Artifact

- ZIP: `{kit["zip_file"]}`
- ZIP sha256: `{kit["zip_sha256"]}`
- Receipt: `{kit["receipt_file"]}`
- Receipt body sha256: `{kit["receipt_body_sha256"]}`

## Recipient Steps

{steps}

## Copy-Paste Message

```text
{payload["copy_paste_message"]}
```

## Do Not Share

{do_not_share}

## Boundary

이 handoff는 install kit 전달 준비 상태만 기록한다. 스크립트는 수령자에게 파일이나 메시지를 직접 보내지 않는다.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian install kit handoff를 생성하거나 검증한다.")
    parser.add_argument("--output-dir", type=Path, default=None, help="handoff 산출물 출력 폴더. 기본값은 dist")
    parser.add_argument("--zip", type=Path, default=None, help="handoff에 연결할 install kit ZIP")
    parser.add_argument("--receipt", type=Path, default=None, help="handoff에 연결할 install kit verification receipt")
    parser.add_argument("--skip-verify", action="store_true", help="ZIP 재검증과 receipt 재생성을 건너뛴다.")
    parser.add_argument("--verify-handoff", type=Path, default=None, help="기존 handoff JSON만 검증한다.")
    args = parser.parse_args()
    if args.verify_handoff:
        payload = verify_handoff_file(args.verify_handoff)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    result = prepare_handoff(
        output_dir=args.output_dir,
        zip_path=args.zip,
        receipt_path=args.receipt,
        skip_verify=bool(args.skip_verify),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
