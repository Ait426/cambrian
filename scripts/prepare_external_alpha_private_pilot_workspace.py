"""Prepare a local-only private workspace for the first external alpha pilot."""

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

from scripts.build_external_alpha_release import RELEASE_SLUG  # noqa: E402


PRIVATE_WORKSPACE_SCHEMA_VERSION = "external_alpha_private_pilot_workspace_v0_1"
PRIVATE_WORKSPACE_RECEIPT_NAME = "external-alpha-private-pilot-workspace-scaffold-receipt.json"
DEFAULT_PRIVATE_WORKSPACE_DIR = ROOT / ".cambrian" / "private" / "external-alpha-first-pilot"

PRIVATE_FILE_SPECS: tuple[dict[str, str], ...] = (
    {
        "file": "recipient-private.txt",
        "purpose": "Raw recipient identifier and private contact context.",
        "placeholder": (
            "PRIVATE - DO NOT SHARE OR COMMIT\n"
            "Recipient identifier/contact goes here after the operator selects exactly one pilot recipient.\n"
        ),
    },
    {
        "file": "operator-dispatch-note-private.md",
        "purpose": "Raw operator note for the manual send event.",
        "placeholder": (
            "PRIVATE - DO NOT SHARE OR COMMIT\n"
            "Record the private channel, sent_at_utc, attachment hash checked, and operator note here.\n"
        ),
    },
    {
        "file": "recipient-ack-private.txt",
        "purpose": "Raw short recipient acknowledgement. The first-recipient flow expects exactly CONFIRMED.",
        "placeholder": (
            "PRIVATE - DO NOT SHARE OR COMMIT\n"
            "Paste only CONFIRMED here after the recipient replies with the requested acknowledgement.\n"
        ),
    },
    {
        "file": "pilot-feedback-private.md",
        "purpose": "Raw pilot feedback form response.",
        "placeholder": (
            "PRIVATE - DO NOT SHARE OR COMMIT\n"
            "Keep raw feedback here. Public artifacts must receive only sha256 and controlled tags.\n"
        ),
    },
    {
        "file": "pilot-issue-intake-private.md",
        "purpose": "Raw issue intake notes from the first pilot.",
        "placeholder": (
            "PRIVATE - DO NOT SHARE OR COMMIT\n"
            "Keep raw issue intake here. Public artifacts must receive only sha256 and controlled tags.\n"
        ),
    },
    {
        "file": "operator-decision-note-private.md",
        "purpose": "Raw operator decision note for continue, fix_before_next, or stop_and_redesign.",
        "placeholder": (
            "PRIVATE - DO NOT SHARE OR COMMIT\n"
            "Write the private decision rationale here after evidence is collected.\n"
        ),
    },
)

logger = logging.getLogger(__name__)


class PrivatePilotWorkspaceError(RuntimeError):
    """Private pilot workspace generation or verification failed."""


def prepare_private_pilot_workspace(
    workspace_dir: Path = DEFAULT_PRIVATE_WORKSPACE_DIR,
    *,
    receipt_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create local-only private pilot templates and a share-safe scaffold receipt."""
    workspace_dir = workspace_dir.resolve()
    _assert_safe_workspace_dir(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    files_to_write = _workspace_files(workspace_dir)
    existing = [path.name for path, _text in files_to_write if path.exists()]
    if existing and not force:
        raise PrivatePilotWorkspaceError(
            "private pilot workspace already has files; use --force only before real private data is entered: "
            + ", ".join(sorted(existing))
        )

    for path, text in files_to_write:
        path.write_text(text, encoding="utf-8")

    resolved_receipt_path = (receipt_path or workspace_dir / PRIVATE_WORKSPACE_RECEIPT_NAME).resolve()
    receipt = _write_private_workspace_receipt(workspace_dir=workspace_dir, receipt_path=resolved_receipt_path)

    return {
        "status": receipt["status"],
        "verdict": receipt["verdict"],
        "workspace_dir": str(workspace_dir),
        "receipt_json": str(resolved_receipt_path),
        "receipt_body_sha256": receipt["private_workspace_receipt_body_sha256"],
        "private_files": [spec["file"] for spec in PRIVATE_FILE_SPECS],
    }


def refresh_private_pilot_workspace_guides(
    workspace_dir: Path = DEFAULT_PRIVATE_WORKSPACE_DIR,
    *,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Refresh generated private runbook guidance without overwriting raw private input files."""
    workspace_dir = workspace_dir.resolve()
    _assert_safe_workspace_dir(workspace_dir)
    missing = [spec["file"] for spec in PRIVATE_FILE_SPECS if not (workspace_dir / spec["file"]).is_file()]
    if missing:
        raise PrivatePilotWorkspaceError("private pilot workspace is missing required files: " + ", ".join(sorted(missing)))

    (workspace_dir / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    (workspace_dir / "README_PRIVATE.md").write_text(_private_readme(), encoding="utf-8")
    resolved_receipt_path = (receipt_path or workspace_dir / PRIVATE_WORKSPACE_RECEIPT_NAME).resolve()
    receipt = _write_private_workspace_receipt(workspace_dir=workspace_dir, receipt_path=resolved_receipt_path)

    return {
        "status": receipt["status"],
        "verdict": receipt["verdict"],
        "workspace_dir": str(workspace_dir),
        "receipt_json": str(resolved_receipt_path),
        "receipt_body_sha256": receipt["private_workspace_receipt_body_sha256"],
        "private_files": [spec["file"] for spec in PRIVATE_FILE_SPECS],
    }


def verify_private_pilot_workspace_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_private_pilot_workspace_receipt_payload(payload)
    return payload


def verify_private_pilot_workspace_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PRIVATE_WORKSPACE_SCHEMA_VERSION:
        raise PrivatePilotWorkspaceError("private pilot workspace receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "PRIVATE_WORKSPACE_SCAFFOLDED":
        raise PrivatePilotWorkspaceError("private pilot workspace receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PrivatePilotWorkspaceError("private pilot workspace receipt must be safe_to_share.")
    policy = payload.get("private_workspace_policy") if isinstance(payload.get("private_workspace_policy"), dict) else {}
    if policy.get("workspace_path_included") is not False:
        raise PrivatePilotWorkspaceError("private pilot workspace receipt must omit the workspace path.")
    if policy.get("raw_private_values_included") is not False:
        raise PrivatePilotWorkspaceError("private pilot workspace receipt must omit raw private values.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PrivatePilotWorkspaceError("private pilot workspace receipt checks failed.")
    if payload.get("private_workspace_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PrivatePilotWorkspaceError("private pilot workspace receipt body hash mismatch.")


def _workspace_files(workspace_dir: Path) -> list[tuple[Path, str]]:
    files = [(workspace_dir / ".gitignore", "*\n!.gitignore\n")]
    files.extend((workspace_dir / spec["file"], spec["placeholder"]) for spec in PRIVATE_FILE_SPECS)
    files.append((workspace_dir / "README_PRIVATE.md", _private_readme()))
    return files


def _write_private_workspace_receipt(*, workspace_dir: Path, receipt_path: Path | None) -> dict[str, Any]:
    receipt = _workspace_receipt(workspace_dir=workspace_dir)
    receipt_path = (receipt_path or workspace_dir / PRIVATE_WORKSPACE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, receipt)
    verify_private_pilot_workspace_receipt_file(receipt_path)
    _assert_shareable_receipt_file(receipt_path, workspace_dir)
    return receipt


def _private_readme() -> str:
    return f"""# External Alpha First Pilot Private Workspace

This directory is local-only. Do not share it, commit it, paste it into chat, or attach screenshots of it.

## Files

- recipient-private.txt
- operator-dispatch-note-private.md
- recipient-ack-private.txt
- pilot-feedback-private.md
- pilot-issue-intake-private.md
- operator-decision-note-private.md

## Before Manual Send

Fill `recipient-private.txt` and `operator-dispatch-note-private.md`, then check the current safe operator status. The operator dispatch note must name the private send channel and include the exact release ZIP sha256 from the operator dispatch packet:

```bash
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir <private-workspace>
```

Run the full pre-send sequence. If blocked, it names only safe private file statuses and does not print raw private text:

```bash
python scripts/check_external_alpha_first_recipient_pre_send_sequence.py --workspace-dir <private-workspace>
```

## After Manual Send

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir <private-workspace> --sent-at-utc <sent-at-utc>
```

Receipt-only verification does not require `--sent-at-utc`:

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --verify-receipt <private-workspace>\\external-alpha-first-recipient-post-send-sequence-receipt.json
```

Check the safe operator status again:

```bash
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir <private-workspace>
```

## After Recipient Acknowledges

Store exactly one non-empty `CONFIRMED` line in `recipient-ack-private.txt`, then rerun the same post-send sequence with the original `sent_at_utc`:

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir <private-workspace> --sent-at-utc <sent-at-utc>
```

If the recipient provides a safe builder gold path share receipt:

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir <private-workspace> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json>
```

Lower-level checkpoint command:

```bash
python scripts/check_external_alpha_recipient_checkpoint.py --private-workspace-dir <private-workspace> --sent-at-utc <sent-at-utc> --require-preflight-receipt --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json>
```

## After Feedback And Issue Intake

```bash
python scripts/check_external_alpha_pilot_evidence.py --private-workspace-dir <private-workspace> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

## After Operator Decision

```bash
python scripts/check_external_alpha_pilot_decision.py --private-workspace-dir <private-workspace> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

## After Iteration Decision

```bash
python scripts/check_external_alpha_pilot_iteration.py --private-workspace-dir <private-workspace> --sent-at-utc <sent-at-utc> --builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> --operator-decision <continue|fix_before_next|stop_and_redesign> --outcome-tag <controlled-outcome-tag> --friction-tag <controlled-friction-tag> --missing-skill-tag <controlled-missing-skill-tag>
```

The public release chain must store only private sha256 values, controlled tags, and share-safe receipts.
"""


def _workspace_receipt(*, workspace_dir: Path) -> dict[str, Any]:
    files = [{"file": spec["file"], "purpose": spec["purpose"]} for spec in PRIVATE_FILE_SPECS]
    command_templates = _command_templates()
    checks = {
        "workspace_path_omitted": True,
        "raw_private_values_omitted": True,
        "gitignore_blocks_private_files": (workspace_dir / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n",
        "expected_private_templates_created": all((workspace_dir / spec["file"]).is_file() for spec in PRIVATE_FILE_SPECS),
        "private_readme_created": (workspace_dir / "README_PRIVATE.md").is_file(),
        "dispatch_command_uses_private_workspace": "--private-workspace-dir <private-workspace>"
        in command_templates["record_dispatch"],
        "post_send_sequence_uses_private_workspace": "--workspace-dir <private-workspace>"
        in command_templates["record_post_send_sequence"]
        and "check_external_alpha_first_recipient_post_send_sequence.py"
        in command_templates["record_post_send_sequence"],
        "pre_send_preflight_uses_private_workspace": "--workspace-dir <private-workspace>"
        in command_templates["pre_send_preflight"]
        and "check_external_alpha_first_recipient_send_preflight.py" in command_templates["pre_send_preflight"],
        "operator_status_uses_private_workspace": "--workspace-dir <private-workspace>"
        in command_templates["operator_status"]
        and "check_external_alpha_first_recipient_operator_status.py" in command_templates["operator_status"],
        "pre_send_sequence_uses_private_workspace": "--workspace-dir <private-workspace>"
        in command_templates["pre_send_sequence"]
        and "check_external_alpha_first_recipient_pre_send_sequence.py" in command_templates["pre_send_sequence"],
        "post_send_receipt_verification_present": "--verify-receipt <private-workspace>"
        in command_templates["verify_post_send_sequence"]
        and "check_external_alpha_first_recipient_post_send_sequence.py"
        in command_templates["verify_post_send_sequence"],
        "recipient_checkpoint_uses_private_workspace": "--private-workspace-dir <private-workspace>"
        in command_templates["record_recipient_checkpoint"],
        "pilot_evidence_uses_private_workspace": "--private-workspace-dir <private-workspace>"
        in command_templates["record_pilot_evidence"],
        "pilot_decision_uses_private_workspace": "--private-workspace-dir <private-workspace>"
        in command_templates["record_pilot_decision"],
        "pilot_iteration_uses_private_workspace": "--private-workspace-dir <private-workspace>"
        in command_templates["record_pilot_iteration"],
    }
    payload: dict[str, Any] = {
        "schema_version": PRIVATE_WORKSPACE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "PRIVATE_WORKSPACE_SCAFFOLDED" if all(checks.values()) else "PRIVATE_WORKSPACE_BLOCKED",
        "safe_to_share": True,
        "release": {
            "slug": RELEASE_SLUG,
            "operator_packet": f"{RELEASE_SLUG}-operator-dispatch-packet.json",
        },
        "private_workspace_policy": {
            "workspace_path_included": False,
            "raw_private_values_included": False,
            "template_placeholders_only": True,
            "created_private_file_count": len(PRIVATE_FILE_SPECS),
            "gitignore_blocks_private_files": True,
            "script_sends_to_recipient": False,
            "records_private_sha256_only": True,
        },
        "private_files": files,
        "command_templates": command_templates,
        "do_not_share": [
            "recipient raw identifier",
            "operator dispatch note raw text",
            "recipient acknowledgement raw text",
            "pilot feedback raw text",
            "pilot issue intake raw text",
            "operator decision note raw text",
            "private workspace path",
            ".env",
            "API key or secret",
        ],
        "checks": checks,
    }
    payload["private_workspace_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _command_templates() -> dict[str, str]:
    return {
        "prepare_workspace": (
            "python scripts/prepare_external_alpha_private_pilot_workspace.py "
            "--workspace-dir <private-workspace>"
        ),
        "pre_send_preflight": (
            "python scripts/check_external_alpha_first_recipient_send_preflight.py "
            "--workspace-dir <private-workspace> "
            "--operator-packet dist\\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json"
        ),
        "operator_status": (
            "python scripts/check_external_alpha_first_recipient_operator_status.py "
            "--workspace-dir <private-workspace>"
        ),
        "pre_send_sequence": (
            "python scripts/check_external_alpha_first_recipient_pre_send_sequence.py "
            "--workspace-dir <private-workspace>"
        ),
        "record_dispatch": (
            "python scripts/check_external_alpha_dispatch_record.py "
            "--private-workspace-dir <private-workspace> "
            "--sent-at-utc <sent-at-utc> "
            "--require-preflight-receipt"
        ),
        "record_post_send_sequence": (
            "python scripts/check_external_alpha_first_recipient_post_send_sequence.py "
            "--workspace-dir <private-workspace> "
            "--sent-at-utc <sent-at-utc>"
        ),
        "verify_post_send_sequence": (
            "python scripts/check_external_alpha_first_recipient_post_send_sequence.py "
            "--verify-receipt <private-workspace>\\external-alpha-first-recipient-post-send-sequence-receipt.json"
        ),
        "record_recipient_checkpoint": (
            "python scripts/check_external_alpha_recipient_checkpoint.py "
            "--private-workspace-dir <private-workspace> "
            "--sent-at-utc <sent-at-utc> "
            "--require-preflight-receipt "
            "--builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json>"
        ),
        "record_pilot_evidence": (
            "python scripts/check_external_alpha_pilot_evidence.py "
            "--private-workspace-dir <private-workspace> "
            "--sent-at-utc <sent-at-utc> "
            "--builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> "
            "--operator-decision <continue|fix_before_next|stop_and_redesign> "
            "--outcome-tag <controlled-outcome-tag> "
            "--friction-tag <controlled-friction-tag> "
            "--missing-skill-tag <controlled-missing-skill-tag>"
        ),
        "record_pilot_decision": (
            "python scripts/check_external_alpha_pilot_decision.py "
            "--private-workspace-dir <private-workspace> "
            "--sent-at-utc <sent-at-utc> "
            "--builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> "
            "--operator-decision <continue|fix_before_next|stop_and_redesign> "
            "--outcome-tag <controlled-outcome-tag> "
            "--friction-tag <controlled-friction-tag> "
            "--missing-skill-tag <controlled-missing-skill-tag>"
        ),
        "record_pilot_iteration": (
            "python scripts/check_external_alpha_pilot_iteration.py "
            "--private-workspace-dir <private-workspace> "
            "--sent-at-utc <sent-at-utc> "
            "--builder-gold-path-share-receipt <external_alpha_builder_gold_path_share_receipt.json> "
            "--operator-decision <continue|fix_before_next|stop_and_redesign> "
            "--outcome-tag <controlled-outcome-tag> "
            "--friction-tag <controlled-friction-tag> "
            "--missing-skill-tag <controlled-missing-skill-tag>"
        ),
    }


def _assert_safe_workspace_dir(path: Path) -> None:
    root = ROOT.resolve()
    blocked = [root, root / "dist", root / ".git", root / "build"]
    if path in blocked:
        raise PrivatePilotWorkspaceError("private workspace target is too broad or unsafe.")
    if _is_relative_to(path, root / "dist") or _is_relative_to(path, root / ".git") or _is_relative_to(path, root / "build"):
        raise PrivatePilotWorkspaceError("private workspace cannot be inside dist, .git, or build.")


def _assert_shareable_receipt_file(path: Path, workspace_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
        "Paste only the private acknowledgement",
        "Keep raw feedback here",
        "Keep raw issue intake here",
        "Write the private decision rationale",
    ]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise PrivatePilotWorkspaceError("private pilot workspace receipt leaked local path or placeholder body.")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "private_workspace_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PrivatePilotWorkspaceError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PrivatePilotWorkspaceError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PrivatePilotWorkspaceError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the local-only private workspace for one external alpha pilot.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_PRIVATE_WORKSPACE_DIR))
    parser.add_argument("--receipt", default=None, help="Optional share-safe receipt JSON path.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite scaffold files. Use only before any real private data is entered.",
    )
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing private workspace receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_private_pilot_workspace_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
            logger.error("[FAIL] external alpha private pilot workspace receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha private pilot workspace receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["private_workspace_receipt_body_sha256"])
        return 0

    try:
        result = prepare_private_pilot_workspace(
            Path(args.workspace_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
            force=args.force,
        )
    except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
        logger.error("[FAIL] external alpha private pilot workspace: %s", exc)
        return 1

    logger.info("[PASS] external alpha private pilot workspace")
    logger.info("verdict  : %s", result["verdict"])
    logger.info("workspace: %s", result["workspace_dir"])
    logger.info("receipt  : %s", result["receipt_json"])
    logger.info("body     : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
