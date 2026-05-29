"""Rehearse the external alpha private pilot workspace scaffold without real private data."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_private_pilot_workspace import (  # noqa: E402
    PRIVATE_WORKSPACE_RECEIPT_NAME,
    prepare_private_pilot_workspace,
    verify_private_pilot_workspace_receipt_file,
)


PRIVATE_WORKSPACE_REHEARSAL_SCHEMA_VERSION = "external_alpha_private_pilot_workspace_rehearsal_v0_1"
PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME = f"{RELEASE_SLUG}-private-workspace-rehearsal-receipt.json"

logger = logging.getLogger(__name__)


class PrivateWorkspaceRehearsalError(RuntimeError):
    """Private workspace rehearsal generation or verification failed."""


def smoke_private_pilot_workspace(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Run a temp private-workspace scaffold rehearsal and write a share-safe receipt."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    release = _release_summary(output_dir)

    with tempfile.TemporaryDirectory(prefix="cambrian-private-pilot-workspace-") as temp_name:
        temp_root = Path(temp_name).resolve()
        workspace_dir = temp_root / "private-workspace"
        scaffold_result = prepare_private_pilot_workspace(workspace_dir)
        scaffold_receipt_path = Path(str(scaffold_result["receipt_json"]))
        scaffold_receipt = verify_private_pilot_workspace_receipt_file(scaffold_receipt_path)
        generated_text = _generated_text(workspace_dir)
        payload = _rehearsal_payload(
            release=release,
            scaffold_receipt=scaffold_receipt,
            generated_text=generated_text,
            temp_root=temp_root,
        )

    receipt_path = output_dir / PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME
    _write_json(receipt_path, payload)
    verify_private_workspace_rehearsal_receipt_file(receipt_path)
    _assert_shareable_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "archive_sha256": payload["release"]["archive_sha256"],
        "receipt_body_sha256": payload["private_workspace_rehearsal_receipt_body_sha256"],
    }


def verify_private_workspace_rehearsal_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_private_workspace_rehearsal_receipt_payload(payload)
    return payload


def verify_private_workspace_rehearsal_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PRIVATE_WORKSPACE_REHEARSAL_SCHEMA_VERSION:
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "REHEARSAL_PASS":
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal must be safe_to_share.")
    if payload.get("real_private_workspace") is not False:
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal must not claim a real private workspace.")
    if payload.get("real_private_data_entered") is not False:
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal must not claim real private data.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal checks failed.")
    if payload.get("private_workspace_rehearsal_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal receipt body hash mismatch.")
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden = [str(ROOT), str(Path.home()), "Recipient identifier/contact goes here", "Keep raw feedback here"]
    leaked = [item for item in forbidden if item and item in serialized]
    if leaked:
        raise PrivateWorkspaceRehearsalError("private workspace rehearsal receipt contains local or private material.")


def _rehearsal_payload(
    *,
    release: dict[str, Any],
    scaffold_receipt: dict[str, Any],
    generated_text: str,
    temp_root: Path,
) -> dict[str, Any]:
    scaffold_policy = (
        scaffold_receipt.get("private_workspace_policy")
        if isinstance(scaffold_receipt.get("private_workspace_policy"), dict)
        else {}
    )
    scaffold_checks = scaffold_receipt.get("checks") if isinstance(scaffold_receipt.get("checks"), dict) else {}
    command_templates = (
        scaffold_receipt.get("command_templates")
        if isinstance(scaffold_receipt.get("command_templates"), dict)
        else {}
    )
    temp_path = str(temp_root)
    checks = {
        "release_archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "scaffold_receipt_passed": scaffold_receipt.get("status") == "pass"
        and scaffold_receipt.get("verdict") == "PRIVATE_WORKSPACE_SCAFFOLDED",
        "scaffold_receipt_hash_present": _looks_like_sha256(
            scaffold_receipt.get("private_workspace_receipt_body_sha256")
        ),
        "scaffold_checks_all_true": bool(scaffold_checks) and all(value is True for value in scaffold_checks.values()),
        "scaffold_omits_workspace_path": scaffold_policy.get("workspace_path_included") is False,
        "scaffold_omits_raw_private_values": scaffold_policy.get("raw_private_values_included") is False,
        "scaffold_gitignore_blocks_private_files": scaffold_policy.get("gitignore_blocks_private_files") is True,
        "scaffold_records_private_sha256_only": scaffold_policy.get("records_private_sha256_only") is True,
        "dispatch_command_private_workspace_only": "--private-workspace-dir <private-workspace>"
        in str(command_templates.get("record_dispatch")),
        "dispatch_command_requires_preflight": "--require-preflight-receipt"
        in str(command_templates.get("record_dispatch")),
        "checkpoint_command_private_workspace_only": "--private-workspace-dir <private-workspace>"
        in str(command_templates.get("record_recipient_checkpoint")),
        "checkpoint_command_requires_preflight": "--require-preflight-receipt"
        in str(command_templates.get("record_recipient_checkpoint")),
        "post_send_sequence_private_workspace_only": "--workspace-dir <private-workspace>"
        in str(command_templates.get("record_post_send_sequence")),
        "evidence_command_private_workspace_only": "--private-workspace-dir <private-workspace>"
        in str(command_templates.get("record_pilot_evidence")),
        "decision_command_private_workspace_only": "--private-workspace-dir <private-workspace>"
        in str(command_templates.get("record_pilot_decision")),
        "iteration_command_private_workspace_only": "--private-workspace-dir <private-workspace>"
        in str(command_templates.get("record_pilot_iteration")),
        "temporary_paths_omitted": temp_path not in generated_text,
        "real_private_workspace_not_claimed": True,
        "real_private_data_not_entered": True,
    }
    payload: dict[str, Any] = {
        "schema_version": PRIVATE_WORKSPACE_REHEARSAL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "REHEARSAL_PASS" if all(checks.values()) else "REHEARSAL_FAIL",
        "safe_to_share": True,
        "real_private_workspace": False,
        "real_private_data_entered": False,
        "purpose": (
            "Operator-only rehearsal of the private pilot workspace scaffold. This receipt proves the scaffold "
            "can be generated safely; it is not evidence that a real recipient, acknowledgement, feedback, issue, "
            "or decision note has been collected."
        ),
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "scaffold_receipt": {
            "file": PRIVATE_WORKSPACE_RECEIPT_NAME,
            "body_sha256": scaffold_receipt.get("private_workspace_receipt_body_sha256"),
            "safe_to_share": scaffold_receipt.get("safe_to_share"),
            "created_private_file_count": scaffold_policy.get("created_private_file_count"),
            "workspace_path_included": scaffold_policy.get("workspace_path_included"),
            "raw_private_values_included": scaffold_policy.get("raw_private_values_included"),
        },
        "private_workspace_policy": {
            "script_sends_to_recipient": False,
            "records_private_sha256_only": True,
            "actual_private_workspace_required_after_send": True,
            "receipt_is_rehearsal_only": True,
        },
        "do_not_share": [
            "private workspace path",
            "recipient raw identifier",
            "operator dispatch note raw text",
            "recipient acknowledgement raw text",
            "pilot feedback raw text",
            "pilot issue intake raw text",
            "operator decision note raw text",
            ".env",
            "API key or secret",
        ],
        "checks": checks,
    }
    payload["private_workspace_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _release_summary(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / f"{RELEASE_SLUG}.manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PrivateWorkspaceRehearsalError(f"release manifest is required: {manifest_path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PrivateWorkspaceRehearsalError(f"cannot parse release manifest: {manifest_path.name}") from exc
    archive = manifest.get("archive") if isinstance(manifest.get("archive"), dict) else {}
    return {
        "zip_file": archive.get("path") or f"{RELEASE_SLUG}.zip",
        "archive_sha256": archive.get("sha256"),
        "file_count": manifest.get("file_count"),
    }


def _generated_text(workspace_dir: Path) -> str:
    chunks: list[str] = []
    for path in sorted(item for item in workspace_dir.rglob("*") if item.is_file()):
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "private_workspace_rehearsal_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PrivateWorkspaceRehearsalError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PrivateWorkspaceRehearsalError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PrivateWorkspaceRehearsalError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_shareable_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [
        str(ROOT),
        str(Path.home()),
        "Recipient identifier/contact goes here",
        "Keep raw feedback here",
        "PRIVATE - DO NOT SHARE OR COMMIT",
    ]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise PrivateWorkspaceRehearsalError(f"private workspace rehearsal contains private material: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse external alpha private pilot workspace scaffold.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing private workspace rehearsal receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_private_workspace_rehearsal_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
            logger.error("[FAIL] external alpha private workspace rehearsal verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha private workspace rehearsal verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["private_workspace_rehearsal_receipt_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = smoke_private_pilot_workspace(Path(args.output_dir))
    except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
        logger.error("[FAIL] external alpha private workspace rehearsal: %s", exc)
        return 1

    logger.info("[PASS] external alpha private workspace rehearsal")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
