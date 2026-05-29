import json
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_cambrian_install_kit_dispatch_record import (
    DISPATCH_RECORD_JSON_NAME,
    DISPATCH_RECORD_MD_NAME,
    InstallKitDispatchRecordError,
    _dispatch_record_body_sha256,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.audit_cambrian_install_kit_operator_send_bypass import (
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    InstallKitOperatorSendBypassAuditError,
    audit_install_kit_operator_send_bypass,
    verify_operator_send_bypass_audit_file,
)
from scripts.smoke_cambrian_install_kit_manual_send_go_rehearsal import (
    MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
    PRIVATE_MARKERS as INSTALL_KIT_REHEARSAL_PRIVATE_MARKERS,
    InstallKitManualSendGoRehearsalError,
    smoke_manual_send_go_rehearsal,
    verify_manual_send_go_rehearsal_receipt_file,
)
from scripts.smoke_cambrian_install_kit_post_send_checkpoint import (
    POST_SEND_REHEARSAL_RECEIPT_NAME,
    PRIVATE_MARKERS as INSTALL_KIT_POST_SEND_PRIVATE_MARKERS,
    InstallKitPostSendCheckpointRehearsalError,
    smoke_post_send_checkpoint_rehearsal,
    verify_post_send_checkpoint_rehearsal_receipt_file,
)
from scripts.check_cambrian_install_kit_first_recipient_operator_status import (
    OPERATOR_STATUS_MD_NAME,
    OPERATOR_STATUS_RECEIPT_NAME,
    OPERATOR_STATUS_READY_RECEIPT_NAME,
    InstallKitFirstRecipientOperatorStatusError,
    check_first_recipient_operator_status,
    verify_first_recipient_operator_status_receipt_file,
)
from scripts.check_cambrian_install_kit_first_recipient_pre_send_sequence import (
    PRE_SEND_SEQUENCE_RECEIPT_NAME,
    InstallKitFirstRecipientPreSendSequenceError,
    check_first_recipient_pre_send_sequence,
    verify_first_recipient_pre_send_sequence_receipt_file,
)
from scripts.check_cambrian_install_kit_first_recipient_manual_send_go import (
    MANUAL_SEND_GO_RECEIPT_NAME,
    InstallKitFirstRecipientManualSendGoError,
    check_first_recipient_manual_send_go,
    verify_first_recipient_manual_send_go_receipt_file,
)
from scripts.check_cambrian_install_kit_first_recipient_post_send_sequence import (
    POST_SEND_SEQUENCE_RECEIPT_NAME as INSTALL_KIT_POST_SEND_SEQUENCE_RECEIPT_NAME,
    InstallKitFirstRecipientPostSendSequenceError,
    check_first_recipient_post_send_sequence,
    verify_first_recipient_post_send_sequence_receipt_file,
)
from scripts.check_cambrian_install_kit_recipient_checkpoint import (
    RECIPIENT_CHECKPOINT_JSON_NAME,
    RECIPIENT_CHECKPOINT_MD_NAME,
    InstallKitRecipientCheckpointError,
    _recipient_checkpoint_body_sha256,
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)
from scripts.prepare_cambrian_install_kit_release import (
    BUNDLE_AGENT_PROMPT_NAME,
    MCP_CONNECT_GUIDE_NAME,
    RELEASE_BUNDLE_NAME,
    _existing_build_result,
    _bundle_agent_prompt_markdown,
    _release_receipt,
    _release_bundle_manifest,
    _release_bundle_payload_checks,
    _bundle_installer_bat_text,
    _bundle_installer_sh_text,
    _standalone_bundle_installer_text,
    _standalone_bundle_gold_path_text,
    _standalone_bundle_verifier_text,
    _verify_release_bundle_manifest,
    _start_here_markdown,
    verify_release_bundle_current_artifacts,
    verify_release_receipt_file,
)
from scripts.smoke_cambrian_install_kit_release_bundle import (
    BUNDLE_SMOKE_RECEIPT_NAME,
    _smoke_receipt,
    verify_bundle_smoke_receipt_payload,
)
from scripts.check_cambrian_install_kit_send_ready import (
    SEND_READY_JSON_NAME,
    SEND_READY_MD_NAME,
    check_send_ready,
    _send_ready_body_sha256,
    _send_ready_checks,
    verify_send_ready_file,
)
from scripts.prepare_cambrian_install_kit_handoff import (
    _default_zip as default_handoff_zip,
    prepare_handoff,
    verify_handoff_file,
)
from scripts.verify_cambrian_install_kit import (
    verify_shareable_receipt_file,
    write_shareable_receipt,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (
    PRIVATE_RUNBOOK_NAME,
    PRIVATE_SEND_CHANNEL_PLACEHOLDER,
    WORKSPACE_RECEIPT_NAME,
    InstallKitFirstRecipientWorkspaceError,
    prepare_first_recipient_workspace,
    verify_first_recipient_workspace_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _write_install_kit_verification_receipt_fixture(tmp_path: Path, bundle_sha256: str = "f" * 64) -> None:
    result = {
        "status": "pass",
        "zip_file": str(ROOT / "private" / "cambrian-install-kit-0.3.0.zip"),
        "zip_sha256": "c" * 64,
        "manifest_version": "0.3.0",
        "failed_checks": [],
        "install_check": True,
        "offline": True,
        "checks": {
            "schema_version": True,
            "required_files_present": True,
            "wheel_present": True,
            "python_requires_present": True,
            "entrypoint_present": True,
            "mcp_entrypoint_present": True,
            "install_commands_present": True,
            "files_hashes_match": True,
            "install_script_passed": True,
            "install_receipt_present": True,
            "install_receipt_status_installed": True,
            "install_receipt_steps_passed": True,
            "install_receipt_company_snapshot_help_passed": True,
            "install_receipt_company_snapshot_next_command_present": True,
            "install_receipt_mcp_verify_passed": True,
            "install_receipt_mcp_next_command_present": True,
            "mcp_operability_receipt_present": True,
            "mcp_operability_receipt_go": True,
            "mcp_operability_installed_entrypoint": True,
            "mcp_operability_no_arbitrary_shell": True,
        },
    }
    write_shareable_receipt(tmp_path / "cambrian-install-kit-verification-receipt.json", result)
    install_receipt = {
        "schema_version": "cambrian_install_share_receipt_v0_1",
        "status": "installed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "all_steps_passed": True,
            "cambrian_help_passed": True,
            "cambrian_doctor_json_passed": True,
            "cambrian_company_snapshot_help_passed": True,
        },
    }
    gold_path_receipt = {
        "schema_version": "cambrian_bundle_gold_path_share_receipt_v0_1",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "proof_claim_allowed": False,
        "sale_ready": False,
        "checks": {
            "cambrian --help": True,
            "cambrian doctor": True,
            "company snapshot": True,
        },
        "capabilities_verified": {
            "ai_agents_created": True,
            "skills_generated_searched_and_fused": True,
            "harness_engineering_system_created": True,
            "evolution_proposed_previewed_and_applied": True,
            "company_snapshot_generated": True,
            "mcp_operability_verified": True,
        },
    }
    smoke = _smoke_receipt(
        bundle_name="cambrian-install-kit-release-bundle.zip",
        bundle_sha256=bundle_sha256,
        steps=[
            {"name": "verify release bundle manifest and hash chain", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "run extracted bundle verifier", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "install Cambrian from extracted bundle", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "run required AI Company Gold Path", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
        ],
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
    )
    (tmp_path / BUNDLE_SMOKE_RECEIPT_NAME).write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_install_share_receipt_fixture(path: Path) -> Path:
    payload = {
        "schema_version": "cambrian_install_share_receipt_v0_1",
        "generated_at": "2026-05-15T00:00:00+00:00",
        "status": "installed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "local_receipt_sha256": "d" * 64,
        "wheel": "cambrian-0.3.0-py3-none-any.whl",
        "offline": True,
        "steps": [
            {"name": "pip_install", "exit_code": 0, "status": "passed"},
            {"name": "cambrian_help", "exit_code": 0, "status": "passed"},
            {"name": "cambrian_doctor_json", "exit_code": 0, "status": "passed"},
            {"name": "cambrian_company_snapshot_help", "exit_code": 0, "status": "passed"},
        ],
        "checks": {
            "all_steps_passed": True,
            "cambrian_help_passed": True,
            "cambrian_doctor_json_passed": True,
            "cambrian_company_snapshot_help_passed": True,
        },
        "next_commands": [
            "cambrian --help",
            "cambrian doctor --json",
            "cambrian company snapshot --json",
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_gold_path_share_receipt_fixture(path: Path) -> Path:
    capabilities = {
        "ai_agents_created": True,
        "skills_generated_searched_and_fused": True,
        "harness_engineering_system_created": True,
        "evolution_proposed_previewed_and_applied": True,
        "company_snapshot_generated": True,
        "mcp_operability_verified": True,
    }
    payload = {
        "schema_version": "cambrian_bundle_gold_path_share_receipt_v0_1",
        "generated_at": "2026-05-15T00:00:00+00:00",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "local_receipt_sha256": "e" * 64,
        "checks": {
            "cambrian --help": True,
            "cambrian doctor": True,
            "project scan": True,
            "harness engineer dry-run": True,
            "skill fuse": True,
            "evolve apply": True,
            "company snapshot is private-safe artifact": True,
        },
        "capabilities_verified": capabilities,
        "proof_claim_allowed": False,
        "sale_ready": False,
        "do_not_share": [
            "cambrian_gold_path_receipt.json",
            ".env",
            "API keys",
            "raw private project data",
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_mcp_operability_receipt_fixture(
    path: Path,
    *,
    no_arbitrary_shell: bool = True,
    source_pythonpath: bool = False,
    server_command_mode: str = "installed_entrypoint",
    installed_entrypoint_command: bool = True,
) -> Path:
    payload = {
        "schema_version": "1.0.0",
        "generated_at": "2026-05-22T00:00:00+00:00",
        "verifier": "cambrian mcp verify",
        "server_command": (
            [str(path.parent / "private" / "cambrian-mcp.exe")]
            if installed_entrypoint_command
            else [sys.executable, "-m", "engine.project_mcp_server"]
        ),
        "server_command_mode": server_command_mode,
        "installed_entrypoint_command": installed_entrypoint_command,
        "installed_entrypoint_required": True,
        "installed_entrypoint_required_satisfied": installed_entrypoint_command,
        "server_cwd": str(path.parent / "private" / "recipient-project"),
        "source_pythonpath_injected": source_pythonpath,
        "tool_count": 2,
        "tool_names": ["cambrian_project_scan", "cambrian_harness_install"],
        "checks": {
            "initialize": True,
            "tools_list": True,
            "missing_cwd_blocked": True,
            "project_scan_with_explicit_cwd": True,
            "harness_install_requires_confirm": True,
            "allowlisted_cli_only": True,
            "no_arbitrary_shell": no_arbitrary_shell,
            "explicit_cwd_required": True,
        },
        "project_scan_command": "cambrian project scan --json",
        "project_scan_status": "success",
        "blocked_without_cwd": "cwd is required",
        "blocked_install_without_confirm": "confirm=true is required",
        "safety_boundary": {
            "allowlisted_cambrian_cli_only": True,
            "shell": False,
            "requires_explicit_cwd": True,
        },
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "verdict": (
            "GO"
            if no_arbitrary_shell and not source_pythonpath and installed_entrypoint_command and server_command_mode == "installed_entrypoint"
            else "NO_GO"
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _prepare_ready_install_kit_operator_status_fixture(tmp_path: Path) -> dict[str, Path | str]:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    recipient_path = workspace / "recipient-private.txt"
    note_path = workspace / "operator-dispatch-note-private.md"
    recipient_path.write_text("real-recipient@example.com\n", encoding="utf-8")
    note_path.write_text(f"private channel: email\nrelease bundle sha256: {bundle_sha}\n", encoding="utf-8")
    status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    manual_go = check_first_recipient_manual_send_go(
        workspace_dir=workspace,
        output_dir=tmp_path,
        skip_verify=True,
    )
    ready_status_payload = verify_first_recipient_operator_status_receipt_file(Path(str(status["ready_receipt_json"])))
    return {
        "workspace": workspace,
        "recipient_path": recipient_path,
        "note_path": note_path,
        "operator_status_receipt": Path(str(status["ready_receipt_json"])),
        "manual_send_go_receipt": Path(str(manual_go["receipt_json"])),
        "operator_status_body_sha256": str(ready_status_payload["operator_status_receipt_body_sha256"]),
        "manual_send_go_body_sha256": str(manual_go["receipt_body_sha256"]),
        "bundle_sha": bundle_sha,
    }


def _write_current_artifact_release_bundle_fixture(tmp_path: Path) -> tuple[Path, str]:
    import zipfile

    inner_zip = tmp_path / "cambrian-install-kit-0.3.0.zip"
    inner_manifest = {
        "entrypoint": "cambrian",
        "mcp_entrypoint": "cambrian-mcp",
        "package": {"version": "0.3.0"},
    }
    with zipfile.ZipFile(inner_zip, "w") as archive:
        archive.writestr("CAMBRIAN_INSTALL_KIT_MANIFEST.json", json.dumps(inner_manifest))

    verification_receipt = {"status": "pass", "receipt_body_sha256": "e" * 64}
    copy_paste_message = (
        "Run cambrian company snapshot --help, then use INSTALL_CAMBRIAN_FROM_BUNDLE.py, "
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py, cambrian_install_share_receipt.json, "
        "cambrian_gold_path_share_receipt.json, and mcp_operability_receipt.json. "
        "Treat local install, MCP, and gold-path receipts as local validation evidence only; "
        "do not claim public proof, sale readiness, marketplace readiness, success rate, "
        "or first-recipient confirmation from this local run. "
        "First-recipient confirmation requires a real human send and returned share-safe receipts through the sender checkpoint."
    )
    handoff = {
        "status": "ready_to_share",
        "handoff_body_sha256": "f" * 64,
        "copy_paste_message": copy_paste_message,
        "handoff_checks": {"claim_boundary_present": True},
    }
    send_ready = {
        "schema_version": "cambrian_install_kit_send_ready_v0_1",
        "generated_at": "2026-05-15T00:00:00+00:00",
        "verdict": "GO",
        "safe_to_share": True,
        "install_kit": {
            "zip_file": inner_zip.name,
            "zip_sha256": hashlib.sha256(inner_zip.read_bytes()).hexdigest(),
            "receipt_file": "cambrian-install-kit-verification-receipt.json",
            "receipt_body_sha256": verification_receipt["receipt_body_sha256"],
            "manifest_version": "0.3.0",
        },
        "handoff": {
            "file": "cambrian-install-kit-handoff.json",
            "markdown_file": "cambrian-install-kit-handoff.md",
            "body_sha256": handoff["handoff_body_sha256"],
            "verified_standalone": True,
        },
        "receipt": {
            "file": "cambrian-install-kit-verification-receipt.json",
            "body_sha256": verification_receipt["receipt_body_sha256"],
            "verified_standalone": True,
        },
        "verified_capabilities": {
            "company_snapshot_help": True,
            "company_snapshot_next_command": True,
            "mcp_operability": True,
        },
        "checks": {
            "handoff_checks_true": True,
            "receipt_checks_true": True,
            "zip_hash_present": True,
            "receipt_hash_matched": True,
            "company_snapshot_help_verified": True,
            "company_snapshot_next_command_verified": True,
            "mcp_operability_verified": True,
            "manual_dispatch_required": True,
            "max_one_recipient": True,
            "do_not_share_guardrails_present": True,
            "copy_paste_message_present": True,
            "copy_paste_message_mentions_bundle_installer": True,
            "copy_paste_message_mentions_gold_path_runner": True,
            "copy_paste_message_mentions_share_receipt": True,
            "copy_paste_message_mentions_gold_path_share_receipt": True,
            "copy_paste_message_mentions_mcp_operability_receipt": True,
            "copy_paste_message_marks_local_validation_only": True,
            "copy_paste_message_blocks_public_proof_claims": True,
            "copy_paste_message_blocks_first_recipient_claims": True,
        },
        "copy_paste_message": copy_paste_message,
        "dispatch_execution_policy": {
            "script_sends_to_recipient": False,
            "script_sends_copy_paste_message": False,
            "manual_operator_dispatch_required": True,
            "max_recipients_per_record": 1,
        },
        "artifact_chain": [
            {"kind": "install_kit_zip", "file": inner_zip.name, "sha256": hashlib.sha256(inner_zip.read_bytes()).hexdigest()},
            {"kind": "install_kit_receipt", "file": "cambrian-install-kit-verification-receipt.json", "sha256": verification_receipt["receipt_body_sha256"]},
            {"kind": "install_kit_handoff", "file": "cambrian-install-kit-handoff.json", "sha256": handoff["handoff_body_sha256"]},
        ],
        "do_not_share": [".env", "raw private project data"],
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    send_ready["send_ready_body_sha256"] = _send_ready_body_sha256(send_ready)
    send_ready["send_ready_checks"] = _send_ready_checks(send_ready)
    release_receipt = _release_receipt(
        {
            "status": "built",
            "zip_file": str(inner_zip),
            "zip_sha256": hashlib.sha256(inner_zip.read_bytes()).hexdigest(),
            "version": "0.3.0",
            "dependency_mode": "bundled_wheelhouse",
        },
        verification_receipt,
        handoff,
        send_ready,
    )
    files = {
        "START_HERE_CAMBRIAN_INSTALL_KIT.md": (
            "cambrian-install-kit-0.3.0.zip\n"
            "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py\n"
            "INSTALL_CAMBRIAN_FROM_BUNDLE.py\n"
            "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py\n"
            "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md\n"
            "MCP_EXTERNAL_CLIENT_CONNECT.md\n"
            "Required AI Company Gold Path\n"
            "cambrian mcp verify --receipt dist/mcp_operability_receipt.json\n"
            "cambrian_install_receipt.json\n"
            "cambrian_install_share_receipt.json\n"
            "cambrian_gold_path_share_receipt.json\n"
            "mcp_operability_receipt.json\n"
            "cambrian company snapshot --help\n"
            "share-safe local validation evidence only\n"
            "not a public proof claim\n"
            "First-recipient confirmation exists only after a real human send\n"
        ).encode("utf-8"),
        "cambrian-install-kit-0.3.0.zip": inner_zip.read_bytes(),
        "cambrian-install-kit-verification-receipt.json": json.dumps(verification_receipt).encode("utf-8"),
        "cambrian-install-kit-handoff.json": json.dumps(handoff).encode("utf-8"),
        "cambrian-install-kit-handoff.md": b"handoff",
        "cambrian-install-kit-send-ready.json": json.dumps(send_ready).encode("utf-8"),
        "cambrian-install-kit-send-ready.md": b"send ready",
        "cambrian-install-kit-release-receipt.json": json.dumps(release_receipt).encode("utf-8"),
        "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py": _standalone_bundle_verifier_text().encode("utf-8"),
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py": _standalone_bundle_installer_text().encode("utf-8"),
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py": _standalone_bundle_gold_path_text().encode("utf-8"),
        BUNDLE_AGENT_PROMPT_NAME: _bundle_agent_prompt_markdown(send_ready).encode("utf-8"),
        MCP_CONNECT_GUIDE_NAME: (
            "Use cambrian-mcp with explicit `cwd`.\n"
            "Run cambrian mcp verify --receipt dist/mcp_operability_receipt.json.\n"
            "Do not expose arbitrary shell access through MCP.\n"
        ).encode("utf-8"),
        "INSTALL_CAMBRIAN_FROM_BUNDLE.bat": _bundle_installer_bat_text().encode("utf-8"),
        "install_cambrian_from_bundle.sh": _bundle_installer_sh_text().encode("utf-8"),
    }
    paths = []
    for name, data in files.items():
        path = tmp_path / name
        path.write_bytes(data)
        paths.append(path)
    manifest = _release_bundle_manifest(paths)
    bundle = tmp_path / RELEASE_BUNDLE_NAME
    with zipfile.ZipFile(bundle, "w") as archive:
        for path in paths:
            archive.write(path, path.name)
        archive.writestr(
            "cambrian-install-kit-release-bundle-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    verified = verify_release_bundle_current_artifacts(bundle, output_dir=tmp_path)
    assert verified["current_artifact_checks"]["current_artifact_hashes_match_bundle"] is True

    bundle_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    install_receipt = {
        "schema_version": "cambrian_install_share_receipt_v0_1",
        "status": "installed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "all_steps_passed": True,
            "cambrian_help_passed": True,
            "cambrian_doctor_json_passed": True,
            "cambrian_company_snapshot_help_passed": True,
        },
    }
    gold_path_receipt = {
        "schema_version": "cambrian_bundle_gold_path_share_receipt_v0_1",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "proof_claim_allowed": False,
        "sale_ready": False,
        "checks": {
            "cambrian --help": True,
            "cambrian doctor": True,
            "company snapshot": True,
        },
        "capabilities_verified": {
            "ai_agents_created": True,
            "skills_generated_searched_and_fused": True,
            "harness_engineering_system_created": True,
            "evolution_proposed_previewed_and_applied": True,
            "company_snapshot_generated": True,
            "mcp_operability_verified": True,
        },
    }
    smoke = _smoke_receipt(
        bundle_name=RELEASE_BUNDLE_NAME,
        bundle_sha256=bundle_sha,
        steps=[
            {"name": "verify release bundle manifest and hash chain", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "run extracted bundle verifier", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "install Cambrian from extracted bundle", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "run required AI Company Gold Path", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
        ],
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
    )
    verify_bundle_smoke_receipt_payload(smoke)
    (tmp_path / BUNDLE_SMOKE_RECEIPT_NAME).write_text(
        json.dumps(smoke, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle, bundle_sha


def test_install_kit_first_recipient_workspace_prepares_private_runbook_and_safe_receipt(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"

    result = prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_workspace_receipt_file(Path(result["receipt_json"]))
    runbook = (workspace / PRIVATE_RUNBOOK_NAME).read_text(encoding="utf-8")
    operator_note = (workspace / "operator-dispatch-note-private.md").read_text(encoding="utf-8")
    serialized = json.dumps(receipt, ensure_ascii=False)

    assert result["verdict"] == "INSTALL_KIT_FIRST_RECIPIENT_WORKSPACE_READY"
    assert receipt["safe_to_share"] is True
    assert receipt["release_bundle"]["file"] == RELEASE_BUNDLE_NAME
    assert receipt["release_bundle_smoke"]["mcp_operability_verified"] is True
    assert receipt["workspace_artifacts"]["private_runbook_file"] == PRIVATE_RUNBOOK_NAME
    assert receipt["workspace_artifacts"]["workspace_receipt_file"] == WORKSPACE_RECEIPT_NAME
    assert receipt["workspace_artifacts"]["operator_status_receipt_file"] == OPERATOR_STATUS_RECEIPT_NAME
    assert receipt["workspace_artifacts"]["operator_status_ready_receipt_file"] == OPERATOR_STATUS_READY_RECEIPT_NAME
    assert receipt["workspace_artifacts"]["operator_status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert all(receipt["checks"].values())
    assert all(receipt["workspace_receipt_checks"].values())
    assert {item["file"] for item in receipt["private_files"]} == {
        "recipient-private.txt",
        "operator-dispatch-note-private.md",
        "recipient-ack-private.txt",
    }
    assert all(item["status"] == "placeholder" for item in receipt["private_files"])
    assert (workspace / "recipient-private.txt").is_file()
    assert (workspace / "operator-dispatch-note-private.md").is_file()
    assert (workspace / "recipient-ack-private.txt").is_file()
    assert (workspace / "returned-receipts" / "README_RETURNED_RECEIPTS_PRIVATE.md").is_file()
    assert f"private channel: {PRIVATE_SEND_CHANNEL_PLACEHOLDER}" in operator_note
    assert f"release bundle sha256: {bundle_sha}" in operator_note
    assert "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in operator_note

    for phrase in [
        "check_cambrian_install_kit_first_recipient_operator_status.py",
        "check_cambrian_install_kit_first_recipient_pre_send_sequence.py",
        "check_cambrian_install_kit_first_recipient_manual_send_go.py",
        "check_cambrian_install_kit_first_recipient_post_send_sequence.py",
        "READY_TO_MANUALLY_SEND_ONE",
        "check_cambrian_install_kit_dispatch_record.py",
        "check_cambrian_install_kit_recipient_checkpoint.py",
        "cambrian_install_share_receipt.json",
        "cambrian_gold_path_share_receipt.json",
        "mcp_operability_receipt.json",
        "--mcp-operability-receipt",
        "--operator-status-receipt",
        "--require-operator-status-receipt",
        "--manual-send-go-receipt",
        "--require-manual-send-go-receipt",
        '--sent-at-utc "<real-sent-at-utc>"',
        OPERATOR_STATUS_MD_NAME,
        "Cambrian does not send",
    ]:
        assert phrase in runbook
    assert "human-readable safe status board" in runbook
    assert "without raw recipient or channel values" in runbook
    assert "--sent-at-utc <real-sent-at-utc>" not in runbook
    assert "check_cambrian_install_kit_recipient_checkpoint.py --skip-verify" not in runbook
    assert "Replace `<real-sent-at-utc>` with the real UTC send timestamp" in runbook
    assert receipt["checks"]["private_runbook_shell_safe_placeholders"] is True
    assert receipt["checks"]["private_runbook_names_operator_status_board"] is True
    assert receipt["checks"]["private_runbook_two_edit_checklist"] is True
    assert receipt["checks"]["human_private_field_checklist_controlled"] is True
    assert receipt["checks"]["operator_commands_shell_safe_placeholders"] is True
    assert receipt["human_private_field_checklist"] == [
        {
            "step": 1,
            "file": "recipient-private.txt",
            "gate": "recipient_private_ready",
            "action": "Replace the whole file with exactly one non-empty recipient identifier or contact.",
        },
        {
            "step": 2,
            "file": "operator-dispatch-note-private.md",
            "gate": "operator_note_names_private_channel",
            "action": "Replace <private-send-channel> with the real private send channel and keep the current release bundle sha256.",
        },
    ]
    assert "Only these two files are edited before manual-send GO:" in runbook
    assert "`recipient-private.txt`: replace the whole file with exactly one non-empty recipient" in runbook
    assert (
        f"`operator-dispatch-note-private.md`: replace `{PRIVATE_SEND_CHANNEL_PLACEHOLDER}` "
        "with the real private send channel"
    ) in runbook

    assert "<private-workspace-dir>" in receipt["operator_commands"]["record_dispatch"]
    assert f'--operator-status-receipt "<private-workspace-dir>/{OPERATOR_STATUS_READY_RECEIPT_NAME}"' in receipt[
        "operator_commands"
    ]["record_dispatch"]
    assert f'--manual-send-go-receipt "<private-workspace-dir>/{MANUAL_SEND_GO_RECEIPT_NAME}"' in receipt[
        "operator_commands"
    ]["record_dispatch"]
    assert '--sent-at-utc "<real-sent-at-utc>"' in receipt["operator_commands"]["record_dispatch"]
    assert "--sent-at-utc <real-sent-at-utc>" not in receipt["operator_commands"]["record_dispatch"]
    assert "--require-operator-status-receipt" in receipt["operator_commands"]["record_dispatch"]
    assert "--require-manual-send-go-receipt" in receipt["operator_commands"]["record_dispatch"]
    assert "check_cambrian_install_kit_first_recipient_operator_status.py" in receipt["operator_commands"][
        "check_operator_status"
    ]
    assert "check_cambrian_install_kit_first_recipient_pre_send_sequence.py" in receipt["operator_commands"][
        "run_pre_send_sequence"
    ]
    assert "check_cambrian_install_kit_first_recipient_manual_send_go.py" in receipt["operator_commands"][
        "run_manual_send_go"
    ]
    assert "check_cambrian_install_kit_first_recipient_post_send_sequence.py" in receipt["operator_commands"][
        "run_post_send_sequence"
    ]
    assert '--mcp-operability-receipt "<private-workspace-dir>/returned-receipts/mcp_operability_receipt.json"' in receipt[
        "operator_commands"
    ]["record_recipient_checkpoint"]
    assert f'--operator-status-receipt "<private-workspace-dir>/{OPERATOR_STATUS_READY_RECEIPT_NAME}"' in receipt[
        "operator_commands"
    ]["record_recipient_checkpoint"]
    assert f'--manual-send-go-receipt "<private-workspace-dir>/{MANUAL_SEND_GO_RECEIPT_NAME}"' in receipt[
        "operator_commands"
    ]["record_recipient_checkpoint"]
    assert "--require-operator-status-receipt" in receipt["operator_commands"]["record_recipient_checkpoint"]
    assert "--require-manual-send-go-receipt" in receipt["operator_commands"]["record_recipient_checkpoint"]
    assert "--skip-verify" not in receipt["operator_commands"]["record_recipient_checkpoint"]
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
    assert "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in serialized
    assert "WAIT_FOR_ONE_CONFIRMED_LINE" not in serialized


def test_install_kit_first_recipient_workspace_preserves_existing_private_values(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    workspace.mkdir()
    recipient = workspace / "recipient-private.txt"
    operator_note = workspace / "operator-dispatch-note-private.md"
    recipient.write_text("real-private-recipient@example.com\n", encoding="utf-8")
    operator_note.write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\noperator note: private\n",
        encoding="utf-8",
    )

    result = prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_workspace_receipt_file(Path(result["receipt_json"]))
    private_files = {item["file"]: item for item in receipt["private_files"]}

    assert recipient.read_text(encoding="utf-8") == "real-private-recipient@example.com\n"
    assert operator_note.read_text(encoding="utf-8") == (
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\noperator note: private\n"
    )
    assert private_files["recipient-private.txt"]["status"] == "private_value_preserved"
    assert private_files["recipient-private.txt"]["sha256_present"] is True
    assert private_files["operator-dispatch-note-private.md"]["status"] == "private_value_preserved"
    assert private_files["operator-dispatch-note-private.md"]["sha256_present"] is True
    assert "real-private-recipient@example.com" not in json.dumps(receipt, ensure_ascii=False)
    assert "private channel: email" not in json.dumps(receipt, ensure_ascii=False)


def test_install_kit_first_recipient_workspace_body_hash_is_stable_across_regeneration(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"

    first = prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    second = prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_workspace_receipt_file(Path(second["receipt_json"]))

    assert first["receipt_body_sha256"] == second["receipt_body_sha256"]
    assert receipt["workspace_receipt_checks"]["body_hash_matched"] is True


def test_install_kit_first_recipient_workspace_receipt_rejects_tampering(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(b"release bundle")
    result = prepare_first_recipient_workspace(workspace_dir=tmp_path / "private-workspace", output_dir=tmp_path)
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    payload["checks"]["one_recipient_only"] = False
    tampered = tmp_path / "tampered-workspace-receipt.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientWorkspaceError):
        verify_first_recipient_workspace_receipt_file(tampered)


def test_install_kit_first_recipient_operator_status_blocks_placeholder_private_files(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)

    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))
    markdown = Path(str(result["receipt_md"])).read_text(encoding="utf-8")
    serialized = json.dumps(receipt, ensure_ascii=False)

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert result["manual_send_allowed"] is False
    assert f"release bundle sha256 {bundle_sha}" in result["next_action"]
    assert receipt["safe_to_share"] is True
    assert receipt["operator_gates"]["workspace_receipt_verified"] is True
    assert receipt["operator_gates"]["recipient_private_ready"] is False
    assert receipt["operator_gates"]["operator_note_ready"] is False
    assert receipt["operator_gates"]["manual_send_allowed"] is False
    assert receipt["operator_status_summary"]["send_state"] == "BLOCKED"
    assert receipt["operator_status_summary"]["open_gate_ids"] == [
        "recipient_private_ready",
        "operator_note_names_private_channel",
    ]
    assert receipt["operator_status_summary"]["private_file_statuses"]["recipient-private.txt"] == "placeholder"
    assert receipt["operator_status_summary"]["private_file_statuses"]["operator-dispatch-note-private.md"] == "placeholder"
    assert receipt["operator_launch_snapshot"] == {
        "stage": "FILL_PRIVATE_FIELDS",
        "send_state": "BLOCKED",
        "manual_send_allowed": False,
        "manual_operator_dispatch_required": True,
        "script_sends_to_recipient": False,
        "max_recipients": 1,
        "release_bundle_present": True,
        "release_bundle_sha256": bundle_sha,
        "release_bundle_current_artifacts_checked": False,
        "release_bundle_current_artifacts_match": None,
        "bundle_smoke_verified": True,
        "bundle_smoke_mcp_operability_verified": True,
        "private_workspace_ready": True,
        "recipient_private_ready": False,
        "recipient_private_exactly_one": False,
        "operator_note_ready": False,
        "operator_note_names_private_channel": False,
        "operator_note_confirms_current_release_hash": True,
        "dispatch_record_verdict": None,
        "dispatch_sent_recorded": False,
        "dispatch_sent_current": False,
        "open_gate_ids": [
            "recipient_private_ready",
            "operator_note_names_private_channel",
        ],
        "next_safe_action": result["next_action"],
        "safe_to_share": True,
    }
    assert receipt["operator_gates"]["operator_note_confirms_current_release_hash"] is True
    assert receipt["private_workspace"]["release_hash_matches_current_bundle"] is True
    assert receipt["release_bundle_smoke"]["release_hash_matches_current_bundle"] is True
    assert receipt["checks"]["operator_launch_snapshot_controlled"] is True
    assert receipt["operator_status_receipt_checks"]["operator_launch_snapshot_controlled"] is True
    assert receipt["operator_status_receipt_checks"]["absolute_paths_omitted"] is True
    assert receipt["operator_status_receipt_checks"]["operator_commands_shell_safe_placeholders"] is True
    assert receipt["operator_status_receipt_checks"]["operator_command_use_order_controlled"] is True
    assert receipt["operator_status_receipt_checks"]["human_private_field_checklist_controlled"] is True
    assert receipt["checks"]["human_private_field_checklist_controlled"] is True
    assert receipt["human_private_field_checklist"] == [
        {
            "step": 1,
            "file": "recipient-private.txt",
            "gate": "recipient_private_ready",
            "action": "Replace the whole file with exactly one non-empty recipient identifier or contact.",
        },
        {
            "step": 2,
            "file": "operator-dispatch-note-private.md",
            "gate": "operator_note_names_private_channel",
            "action": "Replace <private-send-channel> with the real private send channel and keep the current release bundle sha256.",
        },
    ]
    assert [item["command"] for item in receipt["operator_command_use_order"]] == [
        "prepare_workspace",
        "check_operator_status",
        "run_pre_send_sequence",
        "run_manual_send_go",
        "record_dispatch_after_manual_send",
        "run_post_send_sequence_after_manual_send",
        "record_recipient_checkpoint_after_return",
    ]
    assert {item["command"] for item in receipt["operator_command_use_order"]} == set(receipt["operator_commands"])
    assert [item["step"] for item in receipt["operator_command_use_order"]] == [1, 2, 3, 4, 5, 6, 7]
    dispatch_command = receipt["operator_commands"]["record_dispatch_after_manual_send"]
    assert f'--operator-status-receipt "<private-workspace-dir>/{OPERATOR_STATUS_READY_RECEIPT_NAME}"' in dispatch_command
    assert f'--manual-send-go-receipt "<private-workspace-dir>/{MANUAL_SEND_GO_RECEIPT_NAME}"' in dispatch_command
    assert '--sent-at-utc "<real-sent-at-utc>"' in dispatch_command
    assert "--sent-at-utc <real-sent-at-utc>" not in dispatch_command
    assert "--require-operator-status-receipt" in dispatch_command
    assert "--require-manual-send-go-receipt" in dispatch_command
    checkpoint_command = receipt["operator_commands"]["record_recipient_checkpoint_after_return"]
    assert "check_cambrian_install_kit_recipient_checkpoint.py" in checkpoint_command
    assert f'--operator-status-receipt "<private-workspace-dir>/{OPERATOR_STATUS_READY_RECEIPT_NAME}"' in checkpoint_command
    assert f'--manual-send-go-receipt "<private-workspace-dir>/{MANUAL_SEND_GO_RECEIPT_NAME}"' in checkpoint_command
    assert "--require-operator-status-receipt" in checkpoint_command
    assert "--require-manual-send-go-receipt" in checkpoint_command
    assert '--mcp-operability-receipt "<private-workspace-dir>/returned-receipts/mcp_operability_receipt.json"' in checkpoint_command
    assert '--sent-at-utc "<real-sent-at-utc>"' in checkpoint_command
    assert "--skip-verify" not in checkpoint_command
    assert result["ready_receipt_json"] is None
    assert Path(str(result["receipt_md"])).name == OPERATOR_STATUS_MD_NAME
    assert "Cambrian Install Kit First Recipient Operator Status" in markdown
    assert "- verdict: FILL_PRIVATE_FIELDS" in markdown
    assert "- send_state: BLOCKED" in markdown
    assert "- manual_send_allowed: False" in markdown
    assert "- script_sends_to_recipient: False" in markdown
    assert f"- release_bundle_sha256: {bundle_sha}" in markdown
    assert "- release_bundle_current_artifacts_checked: False" in markdown
    assert "- release_bundle_current_artifacts_match: None" in markdown
    assert "- bundle_smoke_mcp_operability_verified: True" in markdown
    assert "- recipient_private_ready" in markdown
    assert "- operator_note_names_private_channel" in markdown
    assert "recipient-private.txt: placeholder" in markdown
    assert "operator-dispatch-note-private.md: placeholder" in markdown
    assert "Human Edit Checklist" in markdown
    assert "1. recipient-private.txt: Replace the whole file with exactly one non-empty recipient identifier or contact." in markdown
    assert "2. operator-dispatch-note-private.md: Replace <private-send-channel> with the real private send channel and keep the current release bundle sha256." in markdown
    assert "Command Use Order" in markdown
    assert "3. run_pre_send_sequence: Before any send, continue only if it returns READY_TO_MANUALLY_SEND_ONE." in markdown
    assert "4. run_manual_send_go: Immediately before manual send, continue only if it returns GO_TO_MANUALLY_SEND_ONE." in markdown
    assert "5. record_dispatch_after_manual_send: After the human manually sends exactly one bundle" in markdown
    assert "7. record_recipient_checkpoint_after_return: After returned install, gold path, MCP" in markdown
    assert markdown.index("run_pre_send_sequence") < markdown.index("record_dispatch_after_manual_send")
    assert markdown.index("run_pre_send_sequence") < markdown.index("run_manual_send_go")
    assert markdown.index("run_manual_send_go") < markdown.index("record_dispatch_after_manual_send")
    assert markdown.index("record_dispatch_after_manual_send") < markdown.index("record_recipient_checkpoint_after_return")
    assert "record_dispatch_after_manual_send" in markdown
    assert "record_recipient_checkpoint_after_return" in markdown
    assert "does not send the install kit" in markdown
    assert not (workspace / OPERATOR_STATUS_READY_RECEIPT_NAME).exists()
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert str(workspace) not in markdown
    assert str(tmp_path) not in markdown
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
    assert "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in serialized
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in markdown
    assert "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in markdown


def test_install_kit_first_recipient_operator_status_blocks_unresolved_channel_template(
    tmp_path: Path,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    operator_note = (workspace / "operator-dispatch-note-private.md").read_text(encoding="utf-8")

    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))

    assert f"release bundle sha256: {bundle_sha}" in operator_note
    assert f"private channel: {PRIVATE_SEND_CHANNEL_PLACEHOLDER}" in operator_note
    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert result["manual_send_allowed"] is False
    assert result["ready_receipt_json"] is None
    assert receipt["operator_gates"]["recipient_private_ready"] is True
    assert receipt["operator_gates"]["operator_note_ready"] is False
    assert receipt["operator_launch_snapshot"]["recipient_private_ready"] is True
    assert receipt["operator_launch_snapshot"]["operator_note_names_private_channel"] is False
    assert receipt["operator_launch_snapshot"]["operator_note_confirms_current_release_hash"] is True
    assert receipt["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert receipt["operator_gates"]["operator_note_names_private_channel"] is False
    assert receipt["operator_gates"]["operator_note_confirms_current_release_hash"] is True
    assert receipt["operator_status_summary"]["open_gate_ids"] == [
        "operator_note_names_private_channel",
    ]
    assert receipt["operator_status_summary"]["private_file_statuses"]["operator-dispatch-note-private.md"] == "placeholder"
    assert not (workspace / OPERATOR_STATUS_READY_RECEIPT_NAME).exists()


@pytest.mark.parametrize(
    "channel_line",
    [
        "private channel:\n",
        "private channel:   \n",
        "private channel: <private-operator-note>\n",
        "channel:\n",
    ],
)
def test_install_kit_first_recipient_operator_status_blocks_empty_channel_value(
    tmp_path: Path,
    channel_line: str,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"{channel_line}release bundle sha256: {bundle_sha}\noperator note: private\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert result["manual_send_allowed"] is False
    assert result["ready_receipt_json"] is None
    assert receipt["operator_gates"]["recipient_private_ready"] is True
    assert receipt["operator_gates"]["operator_note_ready"] is False
    assert receipt["operator_gates"]["operator_note_names_private_channel"] is False
    assert receipt["operator_gates"]["operator_note_confirms_current_release_hash"] is True
    assert receipt["operator_status_summary"]["open_gate_ids"] == [
        "operator_note_names_private_channel",
    ]
    assert (
        receipt["operator_status_summary"]["private_file_statuses"]["operator-dispatch-note-private.md"]
        == "missing_private_channel"
    )
    assert not (workspace / OPERATOR_STATUS_READY_RECEIPT_NAME).exists()


@pytest.mark.parametrize(
    "recipient_text",
    [
        "<recipient>\n",
        "placeholder recipient\n",
        "replace me\n",
        "TODO\n",
    ],
)
def test_install_kit_first_recipient_operator_status_blocks_placeholder_like_recipient(
    tmp_path: Path,
    recipient_text: str,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text(recipient_text, encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert result["manual_send_allowed"] is False
    assert result["ready_receipt_json"] is None
    assert receipt["operator_gates"]["recipient_private_ready"] is False
    assert receipt["operator_gates"]["operator_note_ready"] is True
    assert receipt["operator_gates"]["exactly_one_recipient"] is False
    assert receipt["operator_status_summary"]["open_gate_ids"] == [
        "recipient_private_ready",
    ]
    assert receipt["operator_status_summary"]["private_file_statuses"]["recipient-private.txt"] == "placeholder"
    assert not (workspace / OPERATOR_STATUS_READY_RECEIPT_NAME).exists()


def test_install_kit_first_recipient_operator_status_allows_one_manual_send_when_private_fields_ready(
    tmp_path: Path,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))
    ready_receipt_path = Path(str(result["ready_receipt_json"]))
    ready_receipt = verify_first_recipient_operator_status_receipt_file(ready_receipt_path)
    markdown = Path(str(result["receipt_md"])).read_text(encoding="utf-8")
    serialized = json.dumps(receipt, ensure_ascii=False)

    assert result["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert ready_receipt_path.name == OPERATOR_STATUS_READY_RECEIPT_NAME
    assert ready_receipt["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert ready_receipt["operator_status_receipt_body_sha256"] == receipt["operator_status_receipt_body_sha256"]
    assert result["manual_send_allowed"] is True
    assert result["send_state"] == "READY_TO_SEND"
    assert result["open_gate_ids"] == []
    assert receipt["operator_gates"]["exactly_one_recipient"] is True
    assert receipt["operator_status_summary"]["send_state"] == "READY_TO_SEND"
    assert receipt["operator_status_summary"]["open_gate_ids"] == []
    assert receipt["operator_status_summary"]["private_file_statuses"]["recipient-private.txt"] == "ready"
    assert receipt["operator_status_summary"]["private_file_statuses"][
        "operator-dispatch-note-private.md"
    ] == "ready"
    assert receipt["operator_launch_snapshot"]["stage"] == "READY_TO_MANUALLY_SEND_ONE"
    assert receipt["operator_launch_snapshot"]["send_state"] == "READY_TO_SEND"
    assert receipt["operator_launch_snapshot"]["manual_send_allowed"] is True
    assert receipt["operator_launch_snapshot"]["script_sends_to_recipient"] is False
    assert receipt["operator_launch_snapshot"]["max_recipients"] == 1
    assert receipt["operator_launch_snapshot"]["release_bundle_sha256"] == bundle_sha
    assert receipt["operator_launch_snapshot"]["bundle_smoke_mcp_operability_verified"] is True
    assert receipt["operator_launch_snapshot"]["private_workspace_ready"] is True
    assert receipt["operator_launch_snapshot"]["recipient_private_ready"] is True
    assert receipt["operator_launch_snapshot"]["recipient_private_exactly_one"] is True
    assert receipt["operator_launch_snapshot"]["operator_note_ready"] is True
    assert receipt["operator_launch_snapshot"]["operator_note_names_private_channel"] is True
    assert receipt["operator_launch_snapshot"]["operator_note_confirms_current_release_hash"] is True
    assert receipt["operator_launch_snapshot"]["dispatch_sent_recorded"] is False
    assert receipt["operator_launch_snapshot"]["open_gate_ids"] == []
    assert receipt["operator_launch_snapshot"]["next_safe_action"] == result["next_action"]
    assert receipt["operator_status_receipt_checks"]["human_private_field_checklist_controlled"] is True
    assert "Human Edit Checklist" in markdown
    assert "- verdict: READY_TO_MANUALLY_SEND_ONE" in markdown
    assert "- send_state: READY_TO_SEND" in markdown
    assert "- manual_send_allowed: True" in markdown
    assert "- none" in markdown
    assert f"- release_bundle_sha256: {bundle_sha}" in markdown
    dispatch_command = receipt["operator_commands"]["record_dispatch_after_manual_send"]
    assert f'--operator-status-receipt "<private-workspace-dir>/{OPERATOR_STATUS_READY_RECEIPT_NAME}"' in dispatch_command
    assert f'--manual-send-go-receipt "<private-workspace-dir>/{MANUAL_SEND_GO_RECEIPT_NAME}"' in dispatch_command
    assert '--sent-at-utc "<real-sent-at-utc>"' in dispatch_command
    assert "--sent-at-utc <real-sent-at-utc>" not in dispatch_command
    assert "--require-operator-status-receipt" in dispatch_command
    assert "--require-manual-send-go-receipt" in dispatch_command
    assert receipt["operator_gates"]["operator_note_names_private_channel"] is True
    assert receipt["operator_gates"]["operator_note_confirms_current_release_hash"] is True
    assert receipt["private_hashes"]["recipient_private_sha256"]
    assert receipt["private_hashes"]["operator_dispatch_note_private_sha256"]
    assert "real-recipient@example.com" not in serialized
    assert "private channel: email" not in serialized
    assert "real-recipient@example.com" not in markdown
    assert "private channel: email" not in markdown
    assert str(workspace) not in serialized
    assert str(workspace) not in markdown


def test_install_kit_first_recipient_ready_receipt_survives_waiting_status_rerun(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    recipient_path = workspace / "recipient-private.txt"
    note_path = workspace / "operator-dispatch-note-private.md"
    recipient_path.write_text("real-recipient@example.com\n", encoding="utf-8")
    note_path.write_text(f"private channel: email\nrelease bundle sha256: {bundle_sha}\n", encoding="utf-8")

    ready_status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    ready_receipt_path = Path(str(ready_status["ready_receipt_json"]))
    manual_go = check_first_recipient_manual_send_go(
        workspace_dir=workspace,
        output_dir=tmp_path,
        skip_verify=True,
    )
    ready_before = verify_first_recipient_operator_status_receipt_file(ready_receipt_path)

    check_dispatch_record(
        output_dir=tmp_path,
        skip_verify=True,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        operator_status_receipt=ready_receipt_path,
        require_operator_status_receipt=True,
        manual_send_go_receipt=Path(str(manual_go["receipt_json"])),
        require_manual_send_go_receipt=True,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    waiting_status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    default_after = verify_first_recipient_operator_status_receipt_file(Path(waiting_status["receipt_json"]))
    ready_after = verify_first_recipient_operator_status_receipt_file(ready_receipt_path)

    assert waiting_status["verdict"] == "WAITING_FOR_RECIPIENT_RECEIPTS"
    assert waiting_status["ready_receipt_json"] is None
    assert default_after["verdict"] == "WAITING_FOR_RECIPIENT_RECEIPTS"
    assert default_after["operator_launch_snapshot"]["send_state"] == "WAITING_FOR_RECIPIENT"
    assert default_after["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert default_after["operator_launch_snapshot"]["dispatch_sent_recorded"] is True
    assert default_after["operator_launch_snapshot"]["dispatch_sent_current"] is True
    assert default_after["operator_launch_snapshot"]["open_gate_ids"] == ["recipient_receipts_returned"]
    assert ready_after["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert ready_after["operator_status_receipt_body_sha256"] == ready_before["operator_status_receipt_body_sha256"]


def test_install_kit_first_recipient_operator_status_rejects_stale_workspace_receipt(tmp_path: Path) -> None:
    old_bundle = b"old release bundle"
    old_bundle_sha = hashlib.sha256(old_bundle).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=old_bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(old_bundle)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)

    new_bundle = b"new release bundle"
    new_bundle_sha = hashlib.sha256(new_bundle).hexdigest()
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(new_bundle)
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=new_bundle_sha)

    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))

    assert result["verdict"] == "PREPARE_PRIVATE_WORKSPACE"
    assert receipt["private_workspace"]["release_hash_matches_current_bundle"] is False
    assert receipt["operator_status_summary"]["open_gate_ids"] == [
        "workspace_receipt_release_hash_matches_current_bundle"
    ]
    assert receipt["operator_gates"]["manual_send_allowed"] is False
    assert receipt["operator_launch_snapshot"]["send_state"] == "BLOCKED"
    assert receipt["operator_launch_snapshot"]["private_workspace_ready"] is False
    assert receipt["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert receipt["operator_launch_snapshot"]["open_gate_ids"] == [
        "workspace_receipt_release_hash_matches_current_bundle"
    ]


def test_install_kit_first_recipient_operator_status_rejects_stale_current_release_artifacts(
    tmp_path: Path,
) -> None:
    bundle, bundle_sha = _write_current_artifact_release_bundle_fixture(tmp_path)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\n",
        encoding="utf-8",
    )

    ready_result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    ready_receipt = verify_first_recipient_operator_status_receipt_file(
        Path(str(ready_result["ready_receipt_json"]))
    )

    assert ready_result["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert ready_receipt["release_bundle_current_artifacts"]["current_artifacts_match"] is True
    assert ready_receipt["operator_gates"]["release_bundle_current_artifacts_match"] is True
    assert verify_release_bundle_current_artifacts(bundle, output_dir=tmp_path)["current_artifact_checks"][
        "current_artifact_hashes_match_bundle"
    ] is True

    (tmp_path / "cambrian-install-kit-send-ready.json").write_text('{"stale": true}', encoding="utf-8")

    blocked_result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    blocked_receipt = verify_first_recipient_operator_status_receipt_file(
        Path(blocked_result["receipt_json"])
    )

    assert blocked_result["verdict"] == "PREPARE_RELEASE_BUNDLE"
    assert blocked_result["manual_send_allowed"] is False
    assert blocked_result["open_gate_ids"] == ["release_bundle_current_artifacts_match"]
    assert blocked_receipt["release_bundle_current_artifacts"]["comparison_applicable"] is True
    assert blocked_receipt["release_bundle_current_artifacts"]["current_artifacts_match"] is False
    assert blocked_receipt["release_bundle_current_artifacts"]["status"] == "stale_current_artifacts"
    assert blocked_receipt["operator_gates"]["release_bundle_current_artifacts_match"] is False
    assert blocked_receipt["operator_gates"]["manual_send_allowed"] is False
    assert blocked_receipt["operator_launch_snapshot"]["release_bundle_current_artifacts_checked"] is True
    assert blocked_receipt["operator_launch_snapshot"]["release_bundle_current_artifacts_match"] is False
    assert blocked_receipt["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert blocked_receipt["operator_launch_snapshot"]["open_gate_ids"] == [
        "release_bundle_current_artifacts_match"
    ]


def test_install_kit_first_recipient_operator_status_receipt_rejects_tampering(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    payload["checks"]["safe_to_share_true"] = False
    tampered = tmp_path / OPERATOR_STATUS_RECEIPT_NAME
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientOperatorStatusError):
        verify_first_recipient_operator_status_receipt_file(tampered)


def test_install_kit_first_recipient_operator_status_body_hash_is_stable_across_regeneration(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)

    first = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    second = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt = verify_first_recipient_operator_status_receipt_file(Path(second["receipt_json"]))

    assert first["receipt_body_sha256"] == second["receipt_body_sha256"]
    assert receipt["operator_status_receipt_checks"]["body_hash_matched"] is True


def test_install_kit_first_recipient_operator_status_cli_prints_safe_open_gates(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_cambrian_install_kit_first_recipient_operator_status.py",
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    combined = completed.stdout + completed.stderr

    assert "verdict: FILL_PRIVATE_FIELDS" in combined
    assert "send_state: BLOCKED" in combined
    assert "manual_send_allowed: false" in combined
    assert "recipient-private.txt=placeholder" in combined
    assert "operator-dispatch-note-private.md=placeholder" in combined
    assert "open_gates: recipient_private_ready, operator_note_names_private_channel" in combined
    assert f"next_action: Fill recipient-private.txt with exactly one recipient and make operator-dispatch-note-private.md name the private channel plus release bundle sha256 {bundle_sha}." in combined
    assert f"md     : {OPERATOR_STATUS_MD_NAME}" in combined
    assert str(workspace) not in combined
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in combined


def test_install_kit_first_recipient_pre_send_sequence_blocks_until_private_fields_ready(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    receipt_path = workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(InstallKitFirstRecipientPreSendSequenceError, match="operator_status_ready_to_send"):
        check_first_recipient_pre_send_sequence(
            workspace_dir=workspace,
            output_dir=tmp_path,
            receipt_path=receipt_path,
            skip_verify=True,
        )

    payload = verify_first_recipient_pre_send_sequence_receipt_file(receipt_path, require_ready=False)
    required_files = {item["file"]: item for item in payload["blocking_summary"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert payload["step_results"]["first_recipient_workspace"]["status"] == "pass"
    assert payload["step_results"]["operator_status"]["verdict"] == "FILL_PRIVATE_FIELDS"
    assert payload["step_results"]["operator_send_bypass_audit"]["status"] == "pass"
    assert payload["step_results"]["manual_send_go_rehearsal"]["status"] == "pass"
    assert payload["gate_receipts"]["operator_status"]["status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert payload["gate_receipts"]["operator_status"]["ready_receipt_file"] is None
    assert payload["gate_receipts"]["operator_status"]["release_current_artifacts_checked"] is False
    assert payload["gate_receipts"]["operator_status"]["release_current_artifacts_match"] is None
    assert payload["gate_receipts"]["operator_status"]["release_current_artifacts_gate_passed"] is True
    assert "operator_status_ready_to_send" in payload["blocking_summary"]["blocked_checks"]
    assert payload["blocking_summary"]["operator_status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert "Open cambrian-install-kit-first-recipient-operator-status.md" in " ".join(
        payload["blocking_summary"]["human_next_steps"]
    )
    assert "Fill recipient-private.txt with exactly one recipient" in " ".join(
        payload["blocking_summary"]["human_next_steps"]
    )
    assert "Replace <private-send-channel>" in " ".join(payload["blocking_summary"]["human_next_steps"])
    assert required_files["recipient-private.txt"]["status"] == "placeholder"
    assert required_files["recipient-private.txt"]["sha256_present"] is False
    assert required_files["recipient-private.txt"]["exactly_one_recipient"] is False
    assert required_files["operator-dispatch-note-private.md"]["status"] == "placeholder"
    assert required_files["operator-dispatch-note-private.md"]["mentions_channel"] is False
    assert required_files["operator-dispatch-note-private.md"]["contains_release_hash"] is True

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
    with pytest.raises(InstallKitFirstRecipientPreSendSequenceError, match="pre-send sequence receipt is blocked"):
        verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)


def test_install_kit_first_recipient_pre_send_sequence_goes_ready_when_private_fields_ready(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))

    result = check_first_recipient_pre_send_sequence(
        workspace_dir=workspace,
        output_dir=tmp_path,
        skip_verify=True,
    )
    receipt_path = Path(result["receipt_json"])
    payload = verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)
    required_files = {item["file"]: item for item in payload["blocking_summary"]["required_private_files"]}

    assert result["status"] == "pass"
    assert result["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert receipt_path.name == PRE_SEND_SEQUENCE_RECEIPT_NAME
    assert payload["gate_receipts"]["operator_status"]["ready_receipt_file"] == OPERATOR_STATUS_READY_RECEIPT_NAME
    assert payload["gate_receipts"]["operator_status"]["status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert payload["gate_receipts"]["operator_status"]["release_current_artifacts_checked"] is False
    assert payload["gate_receipts"]["operator_status"]["release_current_artifacts_match"] is None
    assert payload["gate_receipts"]["operator_status"]["release_current_artifacts_gate_passed"] is True
    assert payload["step_results"]["operator_status"]["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["step_results"]["operator_send_bypass_audit"]["verdict"] == "NO_OPERATOR_STATUS_BYPASS"
    assert payload["step_results"]["manual_send_go_rehearsal"]["verdict"] == "REHEARSAL_PASS"
    assert payload["blocking_summary"]["blocked_checks"] == []
    assert payload["blocking_summary"]["all_required_private_files_ready"] is True
    assert payload["blocking_summary"]["operator_status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert "Manually send exactly one release bundle." in payload["blocking_summary"]["human_next_steps"]
    assert f"Keep {OPERATOR_STATUS_READY_RECEIPT_NAME}" in " ".join(
        payload["blocking_summary"]["human_next_steps"]
    )
    assert required_files["recipient-private.txt"]["exactly_one_recipient"] is True
    assert required_files["operator-dispatch-note-private.md"]["mentions_channel"] is True
    assert required_files["operator-dispatch-note-private.md"]["contains_release_hash"] is True
    assert all(payload["checks"].values())
    assert all(payload["pre_send_sequence_receipt_checks"].values())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "real-recipient@example.com" not in serialized
    assert "private channel: email" not in serialized


def test_install_kit_first_recipient_pre_send_sequence_surfaces_stale_current_artifacts(
    tmp_path: Path,
) -> None:
    _bundle, bundle_sha = _write_current_artifact_release_bundle_fixture(tmp_path)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\n",
        encoding="utf-8",
    )

    ready = check_first_recipient_pre_send_sequence(
        workspace_dir=workspace,
        output_dir=tmp_path,
        skip_verify=True,
    )
    ready_payload = verify_first_recipient_pre_send_sequence_receipt_file(Path(ready["receipt_json"]))

    assert ready_payload["gate_receipts"]["operator_status"]["release_current_artifacts_checked"] is True
    assert ready_payload["gate_receipts"]["operator_status"]["release_current_artifacts_match"] is True
    assert ready_payload["gate_receipts"]["operator_status"]["release_current_artifacts_gate_passed"] is True
    assert ready_payload["checks"]["operator_status_release_current_artifacts_match"] is True

    (tmp_path / "cambrian-install-kit-send-ready.json").write_text('{"stale": true}', encoding="utf-8")

    with pytest.raises(
        InstallKitFirstRecipientPreSendSequenceError,
        match="operator_status_release_current_artifacts_match",
    ):
        check_first_recipient_pre_send_sequence(
            workspace_dir=workspace,
            output_dir=tmp_path,
            skip_verify=True,
        )

    blocked_payload = verify_first_recipient_pre_send_sequence_receipt_file(
        workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME,
        require_ready=False,
    )

    assert blocked_payload["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert blocked_payload["step_results"]["operator_status"]["verdict"] == "PREPARE_RELEASE_BUNDLE"
    assert blocked_payload["gate_receipts"]["operator_status"]["release_current_artifacts_checked"] is True
    assert blocked_payload["gate_receipts"]["operator_status"]["release_current_artifacts_match"] is False
    assert blocked_payload["gate_receipts"]["operator_status"]["release_current_artifacts_gate_passed"] is False
    assert blocked_payload["gate_receipts"]["operator_status"]["release_current_artifacts_status"] == "stale_current_artifacts"
    assert blocked_payload["checks"]["operator_status_release_current_artifacts_match"] is False
    assert "operator_status_release_current_artifacts_match" in blocked_payload["blocking_summary"]["blocked_checks"]


def test_install_kit_first_recipient_manual_send_go_blocks_until_pre_send_ready(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    receipt_path = workspace / MANUAL_SEND_GO_RECEIPT_NAME

    with pytest.raises(InstallKitFirstRecipientManualSendGoError, match="pre_send_sequence_ready"):
        check_first_recipient_manual_send_go(
            workspace_dir=workspace,
            output_dir=tmp_path,
            receipt_path=receipt_path,
            skip_verify=True,
        )

    payload = verify_first_recipient_manual_send_go_receipt_file(receipt_path, require_go=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert payload["release_bundle"]["file"] == RELEASE_BUNDLE_NAME
    assert payload["release_bundle"]["sha256"] == bundle_sha
    assert payload["checks"]["pre_send_sequence_ready"] is False
    assert payload["checks"]["operator_status_ready_to_send"] is False
    assert payload["checks"]["operator_send_bypass_audit_ready"] is True
    assert payload["checks"]["manual_send_go_rehearsal_ready"] is True
    assert payload["gate_receipts"]["pre_send_sequence"]["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert payload["gate_receipts"]["operator_status"]["verdict"] == "FILL_PRIVATE_FIELDS"
    assert payload["gate_receipts"]["operator_status"]["status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert payload["gate_receipts"]["operator_status"]["ready_receipt_file"] is None
    assert payload["blocking_summary"]["operator_status_board_file"] == OPERATOR_STATUS_MD_NAME
    assert "Open cambrian-install-kit-first-recipient-operator-status.md" in " ".join(
        payload["blocking_summary"]["human_next_steps"]
    )
    assert "Do not send." in payload["operator_next_action"]
    assert all(payload["manual_send_go_receipt_checks"].values())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
    with pytest.raises(InstallKitFirstRecipientManualSendGoError, match="manual-send GO receipt is blocked"):
        verify_first_recipient_manual_send_go_receipt_file(receipt_path)


def test_install_kit_first_recipient_manual_send_go_passes_when_private_fields_ready(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))

    result = check_first_recipient_manual_send_go(
        workspace_dir=workspace,
        output_dir=tmp_path,
        skip_verify=True,
    )
    payload = verify_first_recipient_manual_send_go_receipt_file(Path(result["receipt_json"]))

    assert result["status"] == "pass"
    assert result["verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert Path(result["receipt_json"]).name == MANUAL_SEND_GO_RECEIPT_NAME
    assert payload["gate_receipts"]["pre_send_sequence"]["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["gate_receipts"]["operator_status"]["ready_receipt_file"] == OPERATOR_STATUS_READY_RECEIPT_NAME
    assert payload["gate_receipts"]["operator_status"]["manual_send_allowed"] is True
    assert payload["gate_receipts"]["operator_send_bypass_audit"]["verdict"] == "NO_OPERATOR_STATUS_BYPASS"
    assert payload["gate_receipts"]["manual_send_go_rehearsal"]["verdict"] == "REHEARSAL_PASS"
    assert payload["blocking_summary"]["blocked_checks"] == []
    assert payload["operator_next_action"].startswith("Manually send exactly one release bundle")
    assert all(payload["checks"].values())
    assert all(payload["manual_send_go_receipt_checks"].values())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "real-recipient@example.com" not in serialized
    assert "private channel: email" not in serialized


def test_install_kit_first_recipient_manual_send_go_surfaces_stale_current_artifacts(
    tmp_path: Path,
) -> None:
    _bundle, bundle_sha = _write_current_artifact_release_bundle_fixture(tmp_path)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\n",
        encoding="utf-8",
    )

    go = check_first_recipient_manual_send_go(
        workspace_dir=workspace,
        output_dir=tmp_path,
        skip_verify=True,
    )
    go_payload = verify_first_recipient_manual_send_go_receipt_file(Path(go["receipt_json"]))

    assert go_payload["checks"]["operator_status_release_current_artifacts_match"] is True
    assert go_payload["gate_receipts"]["operator_status"]["release_current_artifacts_match"] is True

    (tmp_path / "cambrian-install-kit-send-ready.json").write_text('{"stale": true}', encoding="utf-8")

    with pytest.raises(
        InstallKitFirstRecipientManualSendGoError,
        match="operator_status_release_current_artifacts_match",
    ):
        check_first_recipient_manual_send_go(
            workspace_dir=workspace,
            output_dir=tmp_path,
            skip_verify=True,
        )

    blocked_payload = verify_first_recipient_manual_send_go_receipt_file(
        workspace / MANUAL_SEND_GO_RECEIPT_NAME,
        require_go=False,
    )

    assert blocked_payload["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert blocked_payload["gate_receipts"]["operator_status"]["verdict"] == "PREPARE_RELEASE_BUNDLE"
    assert blocked_payload["gate_receipts"]["operator_status"]["release_current_artifacts_match"] is False
    assert blocked_payload["gate_receipts"]["operator_status"]["release_current_artifacts_status"] == "stale_current_artifacts"
    assert blocked_payload["checks"]["operator_status_release_current_artifacts_match"] is False
    assert "operator_status_release_current_artifacts_match" in blocked_payload["blocking_summary"]["blocked_checks"]


def test_install_kit_first_recipient_manual_send_go_receipt_rejects_tampering(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    result = check_first_recipient_manual_send_go(
        workspace_dir=Path(str(ready["workspace"])),
        output_dir=tmp_path,
        skip_verify=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    payload["checks"]["manual_dispatch_only"] = False
    tampered = tmp_path / MANUAL_SEND_GO_RECEIPT_NAME
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientManualSendGoError):
        verify_first_recipient_manual_send_go_receipt_file(tampered)


def test_install_kit_first_recipient_pre_send_sequence_cli_blocked_output_is_safe(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py",
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--skip-verify",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    combined = completed.stdout + completed.stderr

    assert completed.returncode == 1, combined
    assert "pre-send sequence blocked checks" in combined
    assert f"status_board: {OPERATOR_STATUS_MD_NAME}" in combined
    assert "recipient-private.txt=placeholder" in combined
    assert "operator-dispatch-note-private.md=placeholder" in combined
    assert "required=exactly_one_recipient ready=false exactly_one_recipient=false" in combined
    assert "required=private_channel,current_release_hash ready=false" in combined
    assert "mentions_channel=false" in combined
    assert "contains_release_hash=true" in combined
    assert "Open cambrian-install-kit-first-recipient-operator-status.md" in combined
    assert str(workspace) not in combined
    assert str(tmp_path) not in combined
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in combined


def test_install_kit_first_recipient_pre_send_sequence_receipt_rejects_tampering(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    result = check_first_recipient_pre_send_sequence(
        workspace_dir=Path(str(ready["workspace"])),
        output_dir=tmp_path,
        skip_verify=True,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["max_recipients"] = 2
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientPreSendSequenceError):
        verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)


def test_install_kit_first_recipient_post_send_sequence_blocks_without_sent_at(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))
    receipt_path = workspace / INSTALL_KIT_POST_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(InstallKitFirstRecipientPostSendSequenceError, match="sent_at_utc_present"):
        check_first_recipient_post_send_sequence(
            workspace_dir=workspace,
            output_dir=tmp_path,
            receipt_path=receipt_path,
            skip_verify=True,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["step_results"]["dispatch_record"]["verdict"] == "SENT_AT_UTC_REQUIRED"
    assert "sent_at_utc_present" in payload["blocking_summary"]["blocked_checks"]
    assert payload["blocking_summary"]["ack_file"] == "recipient-ack-private.txt"
    assert payload["blocking_summary"]["required_returned_receipts"] == [
        "cambrian_install_share_receipt.json",
        "cambrian_gold_path_share_receipt.json",
        "mcp_operability_receipt.json",
    ]
    assert "Replace <real-sent-at-utc> with the real UTC timestamp" in " ".join(
        payload["blocking_summary"]["human_next_steps"]
    )
    assert payload["ack_summary"]["status"] == "placeholder"
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["manual_operator_dispatch_required"] is True

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized


def test_install_kit_first_recipient_post_send_sequence_rejects_placeholder_sent_at(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))
    receipt_path = workspace / INSTALL_KIT_POST_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(InstallKitFirstRecipientPostSendSequenceError, match="dispatch_recorded"):
        check_first_recipient_post_send_sequence(
            workspace_dir=workspace,
            output_dir=tmp_path,
            sent_at_utc="<real-sent-at-utc>",
            receipt_path=receipt_path,
            skip_verify=True,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["step_results"]["dispatch_record"]["verdict"] == "DISPATCH_NOT_RECORDED"
    assert "dispatch_recorded" in payload["blocking_summary"]["blocked_checks"]
    assert "sent_at_utc_present" not in payload["blocking_summary"]["blocked_checks"]


def test_install_kit_first_recipient_post_send_sequence_records_sent_and_waits_for_recipient(
    tmp_path: Path,
) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))

    result = check_first_recipient_post_send_sequence(
        workspace_dir=workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-15T10:00:00+00:00",
        skip_verify=True,
    )
    payload = verify_first_recipient_post_send_sequence_receipt_file(Path(result["receipt_json"]))

    assert result["status"] == "pass"
    assert result["verdict"] == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT"
    assert payload["step_results"]["dispatch_record"]["verdict"] == "SENT_ONE_RECORDED"
    assert payload["gate_receipts"]["operator_status_pre_send"]["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["gate_receipts"]["operator_status_pre_send"]["file"] == OPERATOR_STATUS_READY_RECEIPT_NAME
    assert payload["ack_summary"]["status"] == "placeholder"
    assert "Wait for the recipient to return share-safe install, gold path, and MCP operability receipts." in payload[
        "blocking_summary"
    ]["human_next_steps"]
    assert "Put exactly one CONFIRMED line in recipient-ack-private.txt after the recipient confirms." in payload[
        "blocking_summary"
    ]["human_next_steps"]
    assert payload["post_send_state"]["sent_recorded"] is True
    assert payload["post_send_state"]["recipient_checkpoint_verdict"] is None
    assert payload["gate_receipts"]["recipient_checkpoint"]["dispatch_copy_paste_message_policy"][
        "recorded"
    ] is False
    assert payload["checks"]["recipient_checkpoint_copy_paste_boundary_preserved"] is True
    assert all(payload["checks"].values())

    dispatch = verify_dispatch_record_file(tmp_path / DISPATCH_RECORD_JSON_NAME)
    assert dispatch["verdict"] == "SENT_ONE_RECORDED"


def test_install_kit_first_recipient_post_send_sequence_blocks_stale_current_artifacts(
    tmp_path: Path,
) -> None:
    _, bundle_sha = _write_current_artifact_release_bundle_fixture(tmp_path)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / "recipient-private.txt").write_text("real-recipient@example.com\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"private channel: email\nrelease bundle sha256: {bundle_sha}\n",
        encoding="utf-8",
    )
    status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    receipt_path = workspace / INSTALL_KIT_POST_SEND_SEQUENCE_RECEIPT_NAME

    assert status["verdict"] == "READY_TO_MANUALLY_SEND_ONE"

    (tmp_path / "cambrian-install-kit-send-ready.md").write_text("stale send ready", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientPostSendSequenceError, match="dispatch_recorded"):
        check_first_recipient_post_send_sequence(
            workspace_dir=workspace,
            output_dir=tmp_path,
            sent_at_utc="2026-05-15T10:00:00+00:00",
            receipt_path=receipt_path,
            skip_verify=True,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["step_results"]["dispatch_record"]["verdict"] == "DISPATCH_NOT_RECORDED"
    assert "release_current_artifacts_match_dispatch" in payload["step_results"]["dispatch_record"]["failed_checks"]
    assert "dispatch_recorded" in payload["blocking_summary"]["blocked_checks"]
    assert payload["gate_receipts"]["operator_status_pre_send"]["release_current_artifacts_gate_passed"] is True


def test_install_kit_first_recipient_post_send_sequence_confirms_gold_path(
    tmp_path: Path,
) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))
    returned = workspace / "returned-receipts"
    install_receipt = _write_install_share_receipt_fixture(returned / "cambrian_install_share_receipt.json")
    gold_path_receipt = _write_gold_path_share_receipt_fixture(returned / "cambrian_gold_path_share_receipt.json")
    mcp_receipt = _write_mcp_operability_receipt_fixture(returned / "mcp_operability_receipt.json")
    (workspace / "recipient-ack-private.txt").write_text("CONFIRMED\n", encoding="utf-8")

    result = check_first_recipient_post_send_sequence(
        workspace_dir=workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-15T10:00:00+00:00",
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
        mcp_operability_receipt=mcp_receipt,
        require_gold_path=True,
        skip_verify=True,
    )
    payload = verify_first_recipient_post_send_sequence_receipt_file(Path(result["receipt_json"]))

    assert result["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["step_results"]["dispatch_record"]["verdict"] == "SENT_ONE_RECORDED"
    assert payload["step_results"]["recipient_checkpoint"]["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["gate_receipts"]["operator_status_pre_send"]["release_current_artifacts_gate_passed"] is True
    checkpoint_boundary = payload["gate_receipts"]["recipient_checkpoint"]["dispatch_copy_paste_message_policy"]
    assert checkpoint_boundary["recorded"] is True
    assert len(checkpoint_boundary["copy_paste_message_sha256"]) == 64
    assert checkpoint_boundary["bundle_installer_named"] is True
    assert checkpoint_boundary["gold_path_runner_named"] is True
    assert checkpoint_boundary["mcp_operability_receipt_named"] is True
    assert checkpoint_boundary["local_validation_only"] is True
    assert checkpoint_boundary["public_proof_claim_blocked"] is True
    assert checkpoint_boundary["first_recipient_confirmation_requires_real_send"] is True
    assert checkpoint_boundary["boundary_preserved"] is True
    assert checkpoint_boundary["raw_copy_paste_message_included"] is False
    assert payload["checks"]["recipient_checkpoint_copy_paste_boundary_preserved"] is True
    assert payload["post_send_sequence_receipt_checks"]["recipient_checkpoint_copy_paste_boundary_safe"] is True
    assert payload["post_send_state"]["install_share_receipt_present"] is True
    assert payload["post_send_state"]["gold_path_share_receipt_present"] is True
    assert payload["post_send_state"]["mcp_operability_receipt_present"] is True
    assert payload["ack_summary"]["status"] == "ready"
    assert payload["ack_summary"]["sha256_present"] is True
    assert payload["returned_receipts"]["mcp_operability_receipt.json"]["present"] is True
    assert all(payload["checks"].values())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "real-recipient@example.com" not in serialized


def test_install_kit_first_recipient_post_send_sequence_blocks_missing_returned_receipt_safely(
    tmp_path: Path,
) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))
    missing_install_receipt = workspace / "returned-receipts" / "cambrian_install_share_receipt.json"
    receipt_path = workspace / INSTALL_KIT_POST_SEND_SEQUENCE_RECEIPT_NAME
    (workspace / "recipient-ack-private.txt").write_text("CONFIRMED\n", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientPostSendSequenceError, match="recipient_checkpoint_recorded_when_ack_ready"):
        check_first_recipient_post_send_sequence(
            workspace_dir=workspace,
            output_dir=tmp_path,
            sent_at_utc="2026-05-15T10:00:00+00:00",
            install_share_receipt=missing_install_receipt,
            receipt_path=receipt_path,
            require_recipient_checkpoint=True,
            skip_verify=True,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)
    returned_install = payload["returned_receipts"]["cambrian_install_share_receipt.json"]

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["post_send_state"]["install_share_receipt_requested"] is True
    assert payload["post_send_state"]["install_share_receipt_present"] is False
    assert returned_install["requested"] is True
    assert returned_install["present"] is False
    assert returned_install["status"] == "missing"
    assert returned_install["sha256"] is None
    assert returned_install["file"] is None
    assert "recipient_checkpoint_recorded_when_ack_ready" in payload["blocking_summary"]["blocked_checks"]
    assert "cambrian_install_share_receipt.json" in " ".join(payload["blocking_summary"]["human_next_steps"])

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert str(missing_install_receipt) not in serialized
    assert "real-recipient@example.com" not in serialized


def test_install_kit_first_recipient_post_send_sequence_receipt_rejects_tampering(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    result = check_first_recipient_post_send_sequence(
        workspace_dir=Path(str(ready["workspace"])),
        output_dir=tmp_path,
        sent_at_utc="2026-05-15T10:00:00+00:00",
        skip_verify=True,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["max_recipients"] = 2
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitFirstRecipientPostSendSequenceError):
        verify_first_recipient_post_send_sequence_receipt_file(receipt_path)


def test_cambrian_install_kit_doc_records_build_and_verify_commands() -> None:
    text = _read("docs/release/CAMBRIAN_INSTALL_KIT.md")

    for phrase in [
        "Cambrian Install Kit",
        "python scripts/prepare_cambrian_install_kit_release.py",
        "python scripts/prepare_cambrian_install_kit_release.py --skip-build",
        "--verify-release-receipt dist/cambrian-install-kit-release-receipt.json",
        "--verify-release-bundle dist/cambrian-install-kit-release-bundle.zip",
        "python scripts/build_cambrian_install_kit.py",
        "python scripts/verify_cambrian_install_kit.py --install-check",
        "python scripts/verify_cambrian_install_kit.py --install-check --offline",
        "--receipt dist/cambrian-install-kit-verification-receipt.json",
        "--verify-receipt dist/cambrian-install-kit-verification-receipt.json",
        "python scripts/prepare_cambrian_install_kit_handoff.py",
        "--verify-handoff dist/cambrian-install-kit-handoff.json",
        "python scripts/check_cambrian_install_kit_send_ready.py",
        "--verify-send-ready dist/cambrian-install-kit-send-ready.json",
        "python scripts/check_cambrian_install_kit_dispatch_record.py",
        "--verify-dispatch-record dist/cambrian-install-kit-dispatch-record.json",
        "python scripts/audit_cambrian_install_kit_operator_send_bypass.py",
        "--verify-receipt dist/cambrian-install-kit-operator-send-bypass-audit.json",
        "python scripts/smoke_cambrian_install_kit_manual_send_go_rehearsal.py",
        "--verify-receipt dist/cambrian-install-kit-manual-send-go-rehearsal-receipt.json",
        "python scripts/smoke_cambrian_install_kit_post_send_checkpoint.py",
        "--verify-receipt dist/cambrian-install-kit-post-send-checkpoint-rehearsal-receipt.json",
        "python scripts/check_cambrian_install_kit_recipient_checkpoint.py",
        "--verify-recipient-checkpoint dist/cambrian-install-kit-recipient-checkpoint.json",
        'python scripts/prepare_cambrian_install_kit_first_recipient_workspace.py --workspace-dir "<private-workspace-dir>"',
        'python scripts/check_cambrian_install_kit_first_recipient_operator_status.py --workspace-dir "<private-workspace-dir>"',
        'python scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py --workspace-dir "<private-workspace-dir>"',
        'python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py --workspace-dir "<private-workspace-dir>"',
        "cambrian-install-kit-first-recipient-operator-status-receipt.json",
        "cambrian-install-kit-first-recipient-operator-status-ready-receipt.json",
        "cambrian-install-kit-first-recipient-operator-status.md",
        "post-send recipient checkpoint command",
        "release_bundle_current_artifacts_match",
        "current-artifact match status",
        "current-artifact gate inherited from dispatch-record",
        "controlled command use order",
        "record_recipient_checkpoint_after_return",
        "body hash excludes `generated_at`",
        "handoff and send-ready receipt body hashes exclude `generated_at`",
        "dispatch-record and recipient-checkpoint body hashes exclude `generated_at`",
        "fixed synthetic `sent_at_utc`",
        "default dispatch verifier rejects it as standalone send evidence",
        "requires `synthetic_dispatch_not_standalone_proof`",
        "default recipient-checkpoint verifier rejects it as standalone recipient evidence",
        "requires `synthetic_checkpoint_not_standalone_proof`",
        "current `dist` artifact mismatches",
        "human_next_steps",
        "timestamp, acknowledgement, and returned receipt follow-up",
        "`--skip-verify` is reserved for synthetic regression tests",
        "cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json",
        "cambrian-install-kit-first-recipient-post-send-sequence-receipt.json",
        "SEND_CAMBRIAN_INSTALL_KIT_ONE_PRIVATE.md",
        "cambrian-install-kit-first-recipient-workspace-receipt.json",
        "workspace receipt body hash excludes `generated_at`",
        "python scripts/smoke_cambrian_install_kit_release_bundle.py --bundle",
        "python scripts/smoke_cambrian_install_kit_release_bundle.py --verify-receipt",
        "smoke-receipt.json`이 PASS일 때만 통과한다",
        "release bundle smoke receipt가 모두 PASS",
        '--gold-path-share-receipt "<path/to/cambrian_gold_path_share_receipt.json>"',
        "RECIPIENT_GOLD_PATH_CONFIRMED",
        "dist/cambrian-install-kit-0.3.0.zip",
        "dist/cambrian-install-kit-handoff.json",
        "dist/cambrian-install-kit-send-ready.json",
        "dist/cambrian-install-kit-dispatch-record.json",
        "dist/cambrian-install-kit-post-send-checkpoint-rehearsal-receipt.json",
        "dist/cambrian-install-kit-recipient-checkpoint.json",
        "dist/cambrian-install-kit-release-receipt.json",
        "dist/cambrian-install-kit-release-bundle-smoke-receipt.json",
        "dist/START_HERE_CAMBRIAN_INSTALL_KIT.md",
        "dist/MCP_EXTERNAL_CLIENT_CONNECT.md",
        "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py",
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py",
        "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md",
        "MCP_EXTERNAL_CLIENT_CONNECT.md",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.bat",
        "install_cambrian_from_bundle.sh",
        "dist/cambrian-install-kit-release-bundle.zip",
        "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md",
        "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md",
        "local validation evidence only, not public proof",
        "not to claim public proof, sale readiness, marketplace readiness",
        "handoff.md/json` and `cambrian-install-kit-send-ready.md/json` carry the same claim boundary",
        "release bundle verifier also requires that handoff/send-ready copy-paste boundary",
        "hashed copy-paste message policy proving the operator send text names install, gold path, MCP receipt",
        "preserves the dispatch copy-paste boundary as hashes and booleans",
        "post-send sequence receipt mirrors its dispatch copy-paste boundary",
        "cambrian_install_receipt.json",
        "cambrian_install_share_receipt.json",
        "cambrian_gold_path_share_receipt.json",
        "mcp_operability_receipt.json",
        '--mcp-operability-receipt "<path/to/mcp_operability_receipt.json>"',
        "cambrian --help",
        "cambrian doctor --json",
        "cambrian company snapshot --help",
        "cambrian company snapshot --json",
        "cambrian mcp verify --receipt dist/mcp_operability_receipt.json",
        "mcp_operability_receipt.json` beside `cambrian_install_receipt.json",
        "requested_cwd` / `resolved_cwd",
        "mcp_operability_verified: true",
        "server_command_mode: installed_entrypoint",
        "installed_entrypoint_command: true",
        "without the returned MCP receipt it must stop at install confirmation",
    ]:
        assert phrase in text
    assert "python scripts/check_cambrian_install_kit_recipient_checkpoint.py --skip-verify" not in text


def test_cambrian_install_kit_scripts_define_portable_artifacts() -> None:
    build_script = _read("scripts/build_cambrian_install_kit.py")
    verify_script = _read("scripts/verify_cambrian_install_kit.py")

    for phrase in [
        "install_cambrian.py",
        "INSTALL_CAMBRIAN.ps1",
        "INSTALL_CAMBRIAN.bat",
        "install_cambrian.sh",
        "CAMBRIAN_INSTALL_KIT_MANIFEST.json",
        "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md",
    ]:
        assert phrase in build_script
    assert "--project <PROJECT_DIR>" in build_script
    assert "cambrian_install_receipt.json" in build_script
    assert "cambrian_install_share_receipt.json" in build_script
    assert '"safe_to_share": False' in build_script
    assert '"safe_to_share": True' in build_script
    assert '"company", "snapshot", "--help"' in build_script
    assert "cambrian company snapshot --json" in build_script
    assert "mcp_entrypoint" in build_script
    assert "cambrian-mcp" in build_script
    assert "mcp_operability_receipt.json" in build_script
    assert "cambrian mcp verify --receipt mcp_operability_receipt.json" in build_script
    assert "cambrian_mcp_verify_passed" in build_script
    assert "install_check" in verify_script
    assert "--offline" in verify_script
    assert "files_hashes_match" in verify_script
    assert "install_receipt_company_snapshot_help_passed" in verify_script
    assert "install_receipt_company_snapshot_next_command_present" in verify_script
    assert "install_receipt_mcp_verify_passed" in verify_script
    assert "mcp_operability_installed_entrypoint" in verify_script
    assert "mcp_operability_no_arbitrary_shell" in verify_script
    assert "write_shareable_receipt" in verify_script
    assert "verify_shareable_receipt_file" in verify_script
    assert "raw_private_project_data_included" in verify_script


def test_cambrian_install_kit_is_linked_from_readme_and_checklist() -> None:
    readme = _read("README.md")
    checklist = _read("docs/release/RC_CHECKLIST.md")

    assert "scripts/build_cambrian_install_kit.py" in readme
    assert "scripts/prepare_cambrian_install_kit_release.py" in readme
    assert "scripts/verify_cambrian_install_kit.py --install-check" in readme
    assert "--receipt dist/cambrian-install-kit-verification-receipt.json" in readme
    assert "scripts/prepare_cambrian_install_kit_handoff.py" in readme
    assert "scripts/check_cambrian_install_kit_send_ready.py" in readme
    assert "docs/release/CAMBRIAN_INSTALL_KIT.md" in readme
    assert "cambrian company snapshot --help" in readme
    assert "Cambrian Install Kit Gate" in checklist
    assert "wheelhouse-only install" in checklist
    assert "install receipt records `cambrian --help`" in checklist
    assert "`cambrian company snapshot --help`" in checklist
    assert "install kit verification receipt omits absolute paths" in checklist
    assert "prepare_cambrian_install_kit_handoff.py" in checklist
    assert "check_cambrian_install_kit_send_ready.py" in checklist
    assert "prepare_cambrian_install_kit_release.py" in checklist
    assert "--verify-release-receipt dist/cambrian-install-kit-release-receipt.json" in checklist
    assert "--verify-release-bundle dist/cambrian-install-kit-release-bundle.zip" in checklist
    assert "synthetic install-kit rehearsal dispatch and recipient-checkpoint artifacts are rejected" in checklist
    assert "local receipts are local validation evidence only" in checklist
    assert "handoff and send-ready copy-paste messages carry the same" in checklist
    assert "release bundle verifier rejects bundles whose handoff/send-ready copy-paste messages omit" in checklist
    assert "dispatch-record preserves a hashed copy-paste message policy" in checklist
    assert "recipient-checkpoint preserves the dispatch copy-paste boundary" in checklist
    assert "first-recipient post-send sequence mirrors the recipient-checkpoint copy-paste boundary" in checklist
    assert "START_HERE_CAMBRIAN_INSTALL_KIT.md" in checklist
    assert "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in checklist


def test_rc_install_guide_names_company_snapshot_install_surface() -> None:
    guide = _read("docs/release/RC_INSTALL_GUIDE.md")

    for phrase in [
        "cambrian company snapshot --help",
        "python scripts/smoke_ai_company_gold_path.py",
        "raw private project data",
        "sale-ready marketplace listing",
    ]:
        assert phrase in guide


def test_next_session_handoff_records_install_kit_send_ready_state() -> None:
    handoff = _read("docs/release/NEXT_SESSION_HANDOFF.md")

    for phrase in [
        "2026-05-14 현재 install kit 상태",
        "dist/cambrian-install-kit-0.3.0.zip",
        "dist/cambrian-install-kit-verification-receipt.json",
        "dist/cambrian-install-kit-handoff.json",
        "dist/cambrian-install-kit-send-ready.json",
        "dist/cambrian-install-kit-release-receipt.json",
        "dist/START_HERE_CAMBRIAN_INSTALL_KIT.md",
        "dist/cambrian-install-kit-release-bundle.zip",
        "dist/INSTALL_CAMBRIAN_FROM_BUNDLE.py",
        "dist/RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py",
        "dist/INSTALL_CAMBRIAN_FROM_BUNDLE.bat",
        "dist/install_cambrian_from_bundle.sh",
        "send-ready verdict: GO",
        "cambrian company snapshot --help: PASS",
        "python scripts\\check_cambrian_install_kit_send_ready.py --verify-send-ready",
        "python scripts\\check_cambrian_install_kit_recipient_checkpoint.py --verify-recipient-checkpoint",
        "python scripts\\prepare_cambrian_install_kit_release.py",
        "python scripts\\prepare_cambrian_install_kit_release.py --skip-build",
        "python scripts\\prepare_cambrian_install_kit_release.py --verify-release-receipt",
        "python scripts\\prepare_cambrian_install_kit_release.py --verify-release-bundle",
        "python scripts\\smoke_cambrian_install_kit_release_bundle.py --bundle",
        "python scripts\\smoke_cambrian_install_kit_release_bundle.py --verify-receipt",
        "install kit release receipt: PASS",
        "install kit release receipt standalone verification: PASS",
        "install kit release bundle verification: PASS",
        "install kit release bundle required gold path smoke receipt: PASS",
        "dispatch-record requires release bundle smoke receipt: PASS",
        "recipient-checkpoint standalone verification: PASS",
        "recipient gold path checkpoint support: PASS",
        "top-level bundle installer smoke: PASS",
        "bundle gold path runner packaged: PASS",
        "bundle gold path e2e: PASS",
        "python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>",
        "cambrian_gold_path_share_receipt.json",
        "install kit focused tests: 32 passed",
        "스크립트가 수령자에게 ZIP이나 메시지를 직접 보내지 않는다",
    ]:
        assert phrase in handoff

    for phrase in [
        "2026-05-24 OS-11 Manual-Send GO Binding / Launch Blocker Refresh",
        "`SENT_ONE_RECORDED` is now bound to both the preserved `READY_TO_MANUALLY_SEND_ONE` operator-status receipt and the final `GO_TO_MANUALLY_SEND_ONE` manual-send GO receipt.",
        "Operator send-bypass audit now treats manual-send GO as part of required pre-send proof",
        "Recipient checkpoint now preserves `manual_send_go_pre_send`",
        "First-recipient private workspace and operator status now expose a controlled `human_private_field_checklist`",
        "Operator status now requires a real non-empty private channel value",
        "Install-kit and external alpha first-recipient gates now reject placeholder-like one-line recipient values",
        "Install-kit and external alpha dispatch records now reject future `sent_at_utc` values",
        "Standard first-recipient private workspace dispatch now requires its pre-send proof by default",
        "Synthetic rehearsal dispatch records now carry `synthetic_rehearsal_boundary`",
        "Install-kit synthetic recipient checkpoints now carry the same rehearsal boundary",
        "docs/release/CAMBRIAN_INSTALL_KIT.md` and `docs/release/RC_CHECKLIST.md` now explicitly state",
        "START_HERE_CAMBRIAN_INSTALL_KIT.md` and `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md` now state",
        "local validation evidence only, not public proof",
        "standalone bundle verifier now fail if those recipient-facing `START_HERE` and Codex/Claude prompt claim-boundary lines are missing",
        "handoff.md/json` and `cambrian-install-kit-send-ready.md/json` now carry the same copy-paste claim boundary",
        "Release bundle payload verification and the standalone bundle verifier now also lock the handoff/send-ready copy-paste claim-boundary checks",
        "Dispatch-record now preserves a hashed copy-paste message policy",
        "Recipient-checkpoint now preserves that dispatch copy-paste boundary",
        "First-recipient post-send sequence now mirrors the recipient-checkpoint copy-paste boundary",
        "dist\\cambrian-install-kit-release-bundle.zip sha256=ba629ea6a4db04c43b7f7e1cc7128952b3a1ab3f59805cdc68af25314477bfd9",
        "dist\\cambrian-install-kit-release-receipt.json body_sha256=c1d96d178e4fee354c7ef375281cdb4098e3a1a2fb284b5e261fbbbc30c79003",
        "dist\\cambrian-install-kit-release-bundle-smoke-receipt.json body_sha256=541b68b6ab1ad6bf9c99e6b3d75cd9a3a7e46eafcb20a54a16aa27829c4207d9",
        "dist\\cambrian-install-kit-handoff.json body_sha256=480bca22b4f202176e931115e1c35bcc03364f2971e0bd014f8ca76805ba4cd1",
        "dist\\cambrian-install-kit-send-ready.json body_sha256=19a7a3ec0cb338b48aa4b3b04f4ae586cd181e992e4878561daee3d3b28f347a",
        "dist\\cambrian-install-kit-dispatch-record.json body_sha256=79edf546163d8f132b7b94aec188441b66a49441d0db9ec34e12653cfb839c00",
        "dist\\cambrian-install-kit-recipient-checkpoint.json body_sha256=7073798b9ed0ec2689f9e0ee65aef370212d8bdc84dcf4de74804d9d3131c39f",
        "dist\\cambrian-install-kit-operator-send-bypass-audit.json body_sha256=c1c2769e02c248972d4428f18f2ad629767d253282553ada54d079bde34cb0fc",
        "dist\\cambrian-install-kit-manual-send-go-rehearsal-receipt.json body_sha256=1ee2dcb227ece6f8ffb380331f01ef2b4674e6e5d79a17d9b4db728743b438fe",
        "dist\\cambrian-install-kit-post-send-checkpoint-rehearsal-receipt.json body_sha256=a2dabb30eede2d565c5725889d693fe507bb9572934a1f61f69539177f75e1b6",
        ".cambrian\\private\\install-kit-first-recipient\\cambrian-install-kit-first-recipient-workspace-receipt.json body_sha256=2336da412f886d3235bcf2eec165e51f53d670fe96b10afee8a31c39d38793c3",
        ".cambrian\\private\\install-kit-first-recipient\\cambrian-install-kit-first-recipient-operator-status-receipt.json body_sha256=ed7bd2fed9bd82a2438eeede52666a698561aefde396f863f3621b6d2abaae42",
        ".cambrian\\private\\install-kit-first-recipient\\cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json body_sha256=7c6be17eb0f6812f0659a670622edcdb97ef4a5fd1a40d4308372b40c63960c4",
        ".cambrian\\private\\install-kit-first-recipient\\cambrian-install-kit-first-recipient-manual-send-go-receipt.json body_sha256=d255e3fd6ce71c048c9c1431b07386160cebe836819b6286f543bb11b206f7b8",
        ".cambrian\\private\\install-kit-first-recipient\\cambrian-install-kit-first-recipient-post-send-sequence-receipt.json body_sha256=f89d0e681a33cd002e04c0e26c237f718293ae4a932d58823662ab49d8e33325",
        "manual-send GO default verdict=BLOCKED_BEFORE_MANUAL_SEND",
        "open gates=recipient_private_ready, operator_note_names_private_channel",
        "python -m py_compile scripts\\prepare_cambrian_install_kit_handoff.py scripts\\check_cambrian_install_kit_send_ready.py scripts\\prepare_cambrian_install_kit_release.py -> PASS",
        "python -m py_compile scripts\\check_cambrian_install_kit_first_recipient_post_send_sequence.py tests\\test_cambrian_install_kit.py -> PASS",
        "python -m pytest -q tests\\test_cambrian_install_kit.py -k \"post_send_sequence\" -> 7 passed",
        "handoff_links_zip_and_receipt_without_private_paths or send_ready_links_artifact_chain_without_dispatching",
        "recipient-facing and handoff/send-ready claim-boundary checks true",
        "python -m pytest -q tests\\test_cambrian_install_kit.py tests\\test_ai_company_os_task_backlog.py -> 106 passed",
        "No external send, deploy, publish, git push, secret read, or private recipient data entry occurred.",
        "OS-11 remains the current launch-critical blocker until a human fills exactly one recipient and replaces <private-send-channel>",
    ]:
        assert phrase in handoff


def test_install_kit_shareable_receipt_omits_private_paths(tmp_path: Path) -> None:
    result = {
        "status": "pass",
        "zip_file": str(ROOT / "dist" / "cambrian-install-kit-0.3.0.zip"),
        "zip_sha256": "a" * 64,
        "manifest_version": "0.3.0",
        "failed_checks": [],
        "install_check": True,
        "offline": True,
        "checks": {
            "schema_version": True,
            "required_files_present": True,
            "wheel_present": True,
            "python_requires_present": True,
            "entrypoint_present": True,
            "mcp_entrypoint_present": True,
            "install_commands_present": True,
            "files_hashes_match": True,
            "install_script_passed": True,
            "install_receipt_present": True,
            "install_receipt_status_installed": True,
            "install_receipt_steps_passed": True,
            "install_receipt_company_snapshot_help_passed": True,
            "install_receipt_company_snapshot_next_command_present": True,
            "install_receipt_mcp_verify_passed": True,
            "install_receipt_mcp_next_command_present": True,
            "mcp_operability_receipt_present": True,
            "mcp_operability_receipt_go": True,
            "mcp_operability_installed_entrypoint": True,
            "mcp_operability_no_arbitrary_shell": True,
        },
        "install_result": {
            "receipt": {
                "project_root": str(ROOT),
            },
        },
    }

    receipt_path = write_shareable_receipt(tmp_path / "receipt.json", result)
    receipt = verify_shareable_receipt_file(receipt_path)
    text = receipt_path.read_text(encoding="utf-8")

    assert receipt["safe_to_share"] is True
    assert receipt["privacy"]["raw_private_project_data_included"] is False
    assert receipt["receipt_checks"]["absolute_paths_omitted"] is True
    assert str(ROOT) not in text
    assert "project_root" not in text
    assert receipt["verified_checks"]["install_receipt_company_snapshot_help_passed"] is True
    assert receipt["verified_checks"]["mcp_operability_receipt_go"] is True
    assert receipt["capabilities"]["mcp_operability"] is True
    assert receipt["receipt_checks"]["mcp_operability_verified"] is True


def test_install_kit_release_receipt_requires_full_chain() -> None:
    payload = _release_receipt(
        {
            "status": "built",
            "zip_file": str(ROOT / "dist" / "cambrian-install-kit-0.3.0.zip"),
            "zip_sha256": "d" * 64,
            "version": "0.3.0",
            "dependency_mode": "bundled_wheelhouse",
        },
        {
            "status": "pass",
            "receipt_body_sha256": "e" * 64,
        },
        {
            "status": "ready_to_share",
            "handoff_body_sha256": "f" * 64,
        },
        {
            "verdict": "GO",
            "send_ready_body_sha256": "1" * 64,
            "checks": {
                "company_snapshot_help_verified": True,
                "manual_dispatch_required": True,
            },
            "send_ready_checks": {
                "artifact_chain_complete": True,
            },
        },
    )

    assert payload["status"] == "pass"
    assert payload["release_receipt_checks"]["body_hash_matched"] is True
    assert payload["release_receipt_checks"]["absolute_paths_omitted"] is True
    assert payload["install_kit"]["zip_file"] == "cambrian-install-kit-0.3.0.zip"
    assert payload["checks"]["send_ready_go"] is True
    assert payload["checks"]["company_snapshot_help_verified"] is True
    assert payload["privacy"]["raw_private_project_data_included"] is False


def test_install_kit_start_here_names_recipient_first_steps() -> None:
    markdown = _start_here_markdown(
        {
            "install_kit": {
                "zip_file": "cambrian-install-kit-0.3.0.zip",
                "receipt_file": "cambrian-install-kit-verification-receipt.json",
            },
            "copy_paste_message": "설치 후 cambrian company snapshot --help가 PASS인지 확인하세요.",
            "do_not_share": [".env", "raw private project data"],
        }
    )

    for phrase in [
        "Start Here: Cambrian Install Kit",
        "Recipient Path",
        "cambrian-install-kit-0.3.0.zip",
        "python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>",
        "python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>",
        "cambrian mcp verify --receipt dist/mcp_operability_receipt.json",
        "MCP_EXTERNAL_CLIENT_CONNECT.md",
        "Required AI Company Gold Path",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.bat",
        "install_cambrian_from_bundle.sh",
        "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md",
        "cambrian_install_receipt.json",
        "cambrian_install_share_receipt.json",
        "cambrian_gold_path_share_receipt.json",
        "mcp_operability_receipt.json",
        "source_pythonpath_injected: false",
        "server_command_mode: installed_entrypoint",
        "installed_entrypoint_command: true",
        "no_arbitrary_shell: true",
        "ai_agents_created: true",
        "skills_generated_searched_and_fused: true",
        "harness_engineering_system_created: true",
        "evolution_proposed_previewed_and_applied: true",
        "company_snapshot_generated: true",
        "mcp_operability_verified: true",
        "safe_to_share: true",
        "absolute_paths_included: false",
        "cambrian-install-kit-release-receipt.json",
        "--verify-release-bundle",
        "--verify-release-receipt",
        "cambrian --help: passed",
        "cambrian doctor --json: passed",
        "cambrian company snapshot --help",
        ".env",
        "raw private project data",
        "Extract `cambrian-install-kit-release-bundle.zip`.",
        "Optional but recommended: run `python VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`.",
        "bash install_cambrian_from_bundle.sh --project /path/to/project",
        "This bundle prepares and verifies a local Cambrian install.",
        "It does not send files, upload data, publish a package, deploy a service, or contact recipients automatically.",
    ]:
        assert phrase in markdown
    assert "Optional AI Company Gold Path" not in markdown
    assert "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md" not in markdown
    assert "풀린 install kit 폴더" not in markdown
    assert "?ㅼ튂" not in markdown


def test_install_kit_release_bundle_agent_prompt_is_top_level_gold_path_contract() -> None:
    prompt = _bundle_agent_prompt_markdown(
        {
            "install_kit": {
                "zip_file": "cambrian-install-kit-0.3.0.zip",
            },
        }
    )

    for phrase in [
        "Cambrian Release Bundle Prompt For Codex/Claude",
        "Required AI Company Gold Path",
        "python VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py",
        "python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>",
        "python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>",
        "cambrian mcp verify --receipt dist/mcp_operability_receipt.json",
        "MCP_EXTERNAL_CLIENT_CONNECT.md",
        "cambrian-mcp",
        "explicit `cwd`",
        "arbitrary shell",
        "cambrian_install_share_receipt.json",
        "cambrian_gold_path_share_receipt.json",
        "mcp_operability_receipt.json",
        "ai_agents_created: true",
        "skills_generated_searched_and_fused: true",
        "harness_engineering_system_created: true",
        "evolution_proposed_previewed_and_applied: true",
        "company_snapshot_generated: true",
        "mcp_operability_verified: true",
        "mcp_operability_receipt.verdict: GO",
        "mcp_operability_receipt.server_command_mode: installed_entrypoint",
        "mcp_operability_receipt.installed_entrypoint_command: true",
        "mcp_operability_receipt.no_arbitrary_shell: true",
        "cambrian-install-kit-0.3.0.zip",
        "START_HERE_CAMBRIAN_INSTALL_KIT.md",
    ]:
        assert phrase in prompt

    assert "Do not publish, upload, email, or send anything automatically" in prompt


def test_install_kit_release_bundle_manifest_requires_start_here_and_chain(tmp_path: Path) -> None:
    files = []
    for name in [
        "START_HERE_CAMBRIAN_INSTALL_KIT.md",
        "cambrian-install-kit-0.3.0.zip",
        "cambrian-install-kit-verification-receipt.json",
        "cambrian-install-kit-handoff.json",
        "cambrian-install-kit-handoff.md",
        "cambrian-install-kit-send-ready.json",
        "cambrian-install-kit-send-ready.md",
        "cambrian-install-kit-release-receipt.json",
        "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py",
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py",
        "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md",
        "MCP_EXTERNAL_CLIENT_CONNECT.md",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.bat",
        "install_cambrian_from_bundle.sh",
    ]:
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        files.append(path)

    manifest = _release_bundle_manifest(files)
    names = {item["path"] for item in manifest["files"]} | {"cambrian-install-kit-release-bundle-manifest.json"}

    _verify_release_bundle_manifest(manifest, names)
    assert manifest["entrypoint"] == "START_HERE_CAMBRIAN_INSTALL_KIT.md"
    assert manifest["dispatch_execution_policy"]["script_sends_to_recipient"] is False
    assert manifest["privacy"]["raw_private_project_data_included"] is False


def test_install_kit_release_bundle_payload_checks_link_embedded_hashes(tmp_path: Path) -> None:
    import zipfile

    inner_zip = tmp_path / "cambrian-install-kit-0.3.0.zip"
    inner_manifest = {
        "entrypoint": "cambrian",
        "mcp_entrypoint": "cambrian-mcp",
        "package": {"version": "0.3.0"},
    }
    with zipfile.ZipFile(inner_zip, "w") as archive:
        archive.writestr("CAMBRIAN_INSTALL_KIT_MANIFEST.json", json.dumps(inner_manifest))
    verification_receipt = {"status": "pass", "receipt_body_sha256": "e" * 64}
    claim_boundary = (
        "Treat local install, MCP, and gold-path receipts as local validation evidence only; "
        "do not claim public proof, sale readiness, marketplace readiness, success rate, "
        "or first-recipient confirmation from this local run. "
        "First-recipient confirmation requires a real human send and returned share-safe receipts through the sender checkpoint."
    )
    handoff = {
        "status": "ready_to_share",
        "handoff_body_sha256": "f" * 64,
        "copy_paste_message": claim_boundary,
        "handoff_checks": {"claim_boundary_present": True},
    }
    send_ready = {
        "verdict": "GO",
        "send_ready_body_sha256": "1" * 64,
        "copy_paste_message": claim_boundary,
        "checks": {
            "company_snapshot_help_verified": True,
            "manual_dispatch_required": True,
            "copy_paste_message_marks_local_validation_only": True,
            "copy_paste_message_blocks_public_proof_claims": True,
            "copy_paste_message_blocks_first_recipient_claims": True,
        },
        "send_ready_checks": {"artifact_chain_complete": True},
    }
    release_receipt = _release_receipt(
        {
            "status": "built",
            "zip_file": str(inner_zip),
            "zip_sha256": hashlib.sha256(inner_zip.read_bytes()).hexdigest(),
            "version": "0.3.0",
            "dependency_mode": "bundled_wheelhouse",
        },
        verification_receipt,
        handoff,
        send_ready,
    )
    bundle_items = {
        "START_HERE_CAMBRIAN_INSTALL_KIT.md": (
            "cambrian-install-kit-0.3.0.zip\n"
            "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py\n"
            "INSTALL_CAMBRIAN_FROM_BUNDLE.py\n"
            "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py\n"
            "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md\n"
            "MCP_EXTERNAL_CLIENT_CONNECT.md\n"
            "Required AI Company Gold Path\n"
            "cambrian mcp verify --receipt dist/mcp_operability_receipt.json\n"
            "cambrian_install_receipt.json\n"
            "cambrian_install_share_receipt.json\n"
            "cambrian_gold_path_share_receipt.json\n"
            "mcp_operability_receipt.json\n"
            "cambrian company snapshot --help\n"
            "share-safe local validation evidence only\n"
            "not a public proof claim\n"
            "First-recipient confirmation exists only after a real human send\n"
        ).encode("utf-8"),
        "cambrian-install-kit-0.3.0.zip": inner_zip.read_bytes(),
        "cambrian-install-kit-verification-receipt.json": json.dumps(verification_receipt).encode("utf-8"),
        "cambrian-install-kit-handoff.json": json.dumps(handoff).encode("utf-8"),
        "cambrian-install-kit-send-ready.json": json.dumps(send_ready).encode("utf-8"),
        "cambrian-install-kit-release-receipt.json": json.dumps(release_receipt).encode("utf-8"),
        "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py": _standalone_bundle_verifier_text().encode("utf-8"),
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py": _standalone_bundle_installer_text().encode("utf-8"),
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py": _standalone_bundle_gold_path_text().encode("utf-8"),
        BUNDLE_AGENT_PROMPT_NAME: _bundle_agent_prompt_markdown(send_ready).encode("utf-8"),
        MCP_CONNECT_GUIDE_NAME: (
            "Use cambrian-mcp with explicit `cwd`.\n"
            "Run cambrian mcp verify --receipt dist/mcp_operability_receipt.json.\n"
            "Do not expose arbitrary shell access through MCP.\n"
        ).encode("utf-8"),
        "INSTALL_CAMBRIAN_FROM_BUNDLE.bat": _bundle_installer_bat_text().encode("utf-8"),
        "install_cambrian_from_bundle.sh": _bundle_installer_sh_text().encode("utf-8"),
    }

    checks = _release_bundle_payload_checks(bundle_items)

    assert checks["release_receipt_verified"] is True
    assert checks["install_kit_zip_hash_matched"] is True
    assert checks["verification_receipt_hash_matched"] is True
    assert checks["handoff_hash_matched"] is True
    assert checks["send_ready_hash_matched"] is True
    assert checks["standalone_verifier_present"] is True
    assert checks["standalone_installer_present"] is True
    assert checks["gold_path_runner_present"] is True
    assert checks["bundle_agent_prompt_present"] is True
    assert checks["mcp_connect_guide_present"] is True
    assert checks["windows_installer_wrapper_present"] is True
    assert checks["shell_installer_wrapper_present"] is True
    assert checks["start_here_mentions_standalone_installer"] is True
    assert checks["start_here_mentions_gold_path_runner"] is True
    assert checks["start_here_mentions_bundle_agent_prompt"] is True
    assert checks["start_here_mentions_mcp_guide"] is True
    assert checks["start_here_mentions_mcp_verify"] is True
    assert checks["bundle_agent_prompt_mentions_standalone_verifier"] is True
    assert checks["bundle_agent_prompt_mentions_standalone_installer"] is True
    assert checks["bundle_agent_prompt_mentions_gold_path_runner"] is True
    assert checks["bundle_agent_prompt_mentions_mcp_verify"] is True
    assert checks["bundle_agent_prompt_mentions_mcp_guide"] is True
    assert checks["bundle_agent_prompt_marks_gold_path_required"] is True
    assert checks["bundle_agent_prompt_mentions_share_receipts"] is True
    assert checks["bundle_agent_prompt_marks_receipts_local_validation_only"] is True
    assert checks["bundle_agent_prompt_blocks_public_proof_claims"] is True
    assert checks["bundle_agent_prompt_blocks_first_recipient_claims"] is True
    assert checks["start_here_marks_gold_path_required"] is True
    assert checks["start_here_does_not_mark_gold_path_optional"] is True
    assert checks["start_here_mentions_share_receipt"] is True
    assert checks["start_here_mentions_gold_path_share_receipt"] is True
    assert checks["start_here_marks_receipts_local_validation_only"] is True
    assert checks["start_here_blocks_public_proof_claims"] is True
    assert checks["start_here_blocks_first_recipient_claims"] is True
    assert checks["handoff_copy_paste_marks_receipts_local_validation_only"] is True
    assert checks["handoff_copy_paste_blocks_public_proof_claims"] is True
    assert checks["handoff_copy_paste_blocks_first_recipient_claims"] is True
    assert checks["handoff_checks_require_claim_boundary"] is True
    assert checks["send_ready_copy_paste_marks_receipts_local_validation_only"] is True
    assert checks["send_ready_copy_paste_blocks_public_proof_claims"] is True
    assert checks["send_ready_copy_paste_blocks_first_recipient_claims"] is True
    assert checks["send_ready_checks_require_claim_boundary"] is True
    assert checks["mcp_connect_guide_mentions_cambrian_mcp"] is True
    assert checks["mcp_connect_guide_mentions_mcp_verify"] is True
    assert checks["mcp_connect_guide_mentions_explicit_cwd"] is True
    assert checks["mcp_connect_guide_mentions_no_arbitrary_shell"] is True
    assert checks["artifacts_name_bundle_installer_matched"] is True
    assert checks["artifacts_name_bundle_gold_path_matched"] is True
    assert checks["artifacts_name_bundle_agent_prompt_matched"] is True
    assert checks["artifacts_name_mcp_connect_guide_matched"] is True
    assert checks["artifacts_name_bundle_installer_bat_matched"] is True
    assert checks["artifacts_name_bundle_installer_sh_matched"] is True
    assert checks["inner_install_kit_manifest_present"] is True
    assert checks["inner_install_kit_version_matched"] is True
    assert checks["inner_install_kit_entrypoint_present"] is True
    assert checks["inner_install_kit_mcp_entrypoint_present"] is True


def test_install_kit_release_bundle_current_artifact_check_rejects_stale_dist(tmp_path: Path) -> None:
    import zipfile

    inner_zip = tmp_path / "cambrian-install-kit-0.3.0.zip"
    inner_manifest = {
        "entrypoint": "cambrian",
        "mcp_entrypoint": "cambrian-mcp",
        "package": {"version": "0.3.0"},
    }
    with zipfile.ZipFile(inner_zip, "w") as archive:
        archive.writestr("CAMBRIAN_INSTALL_KIT_MANIFEST.json", json.dumps(inner_manifest))
    verification_receipt = {"status": "pass", "receipt_body_sha256": "e" * 64}
    claim_boundary = (
        "Treat local install, MCP, and gold-path receipts as local validation evidence only; "
        "do not claim public proof, sale readiness, marketplace readiness, success rate, "
        "or first-recipient confirmation from this local run. "
        "First-recipient confirmation requires a real human send and returned share-safe receipts through the sender checkpoint."
    )
    handoff = {
        "status": "ready_to_share",
        "handoff_body_sha256": "f" * 64,
        "copy_paste_message": claim_boundary,
        "handoff_checks": {"claim_boundary_present": True},
    }
    send_ready = {
        "verdict": "GO",
        "send_ready_body_sha256": "1" * 64,
        "copy_paste_message": claim_boundary,
        "checks": {
            "company_snapshot_help_verified": True,
            "manual_dispatch_required": True,
            "copy_paste_message_marks_local_validation_only": True,
            "copy_paste_message_blocks_public_proof_claims": True,
            "copy_paste_message_blocks_first_recipient_claims": True,
        },
        "send_ready_checks": {"artifact_chain_complete": True},
    }
    release_receipt = _release_receipt(
        {
            "status": "built",
            "zip_file": str(inner_zip),
            "zip_sha256": hashlib.sha256(inner_zip.read_bytes()).hexdigest(),
            "version": "0.3.0",
            "dependency_mode": "bundled_wheelhouse",
        },
        verification_receipt,
        handoff,
        send_ready,
    )
    files = {
        "START_HERE_CAMBRIAN_INSTALL_KIT.md": (
            "cambrian-install-kit-0.3.0.zip\n"
            "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py\n"
            "INSTALL_CAMBRIAN_FROM_BUNDLE.py\n"
            "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py\n"
            "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md\n"
            "MCP_EXTERNAL_CLIENT_CONNECT.md\n"
            "Required AI Company Gold Path\n"
            "cambrian mcp verify --receipt dist/mcp_operability_receipt.json\n"
            "cambrian_install_receipt.json\n"
            "cambrian_install_share_receipt.json\n"
            "cambrian_gold_path_share_receipt.json\n"
            "mcp_operability_receipt.json\n"
            "cambrian company snapshot --help\n"
            "share-safe local validation evidence only\n"
            "not a public proof claim\n"
            "First-recipient confirmation exists only after a real human send\n"
        ).encode("utf-8"),
        "cambrian-install-kit-0.3.0.zip": inner_zip.read_bytes(),
        "cambrian-install-kit-verification-receipt.json": json.dumps(verification_receipt).encode("utf-8"),
        "cambrian-install-kit-handoff.json": json.dumps(handoff).encode("utf-8"),
        "cambrian-install-kit-handoff.md": b"handoff",
        "cambrian-install-kit-send-ready.json": json.dumps(send_ready).encode("utf-8"),
        "cambrian-install-kit-send-ready.md": b"send ready",
        "cambrian-install-kit-release-receipt.json": json.dumps(release_receipt).encode("utf-8"),
        "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py": _standalone_bundle_verifier_text().encode("utf-8"),
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py": _standalone_bundle_installer_text().encode("utf-8"),
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py": _standalone_bundle_gold_path_text().encode("utf-8"),
        BUNDLE_AGENT_PROMPT_NAME: _bundle_agent_prompt_markdown(send_ready).encode("utf-8"),
        MCP_CONNECT_GUIDE_NAME: (
            "Use cambrian-mcp with explicit `cwd`.\n"
            "Run cambrian mcp verify --receipt dist/mcp_operability_receipt.json.\n"
            "Do not expose arbitrary shell access through MCP.\n"
        ).encode("utf-8"),
        "INSTALL_CAMBRIAN_FROM_BUNDLE.bat": _bundle_installer_bat_text().encode("utf-8"),
        "install_cambrian_from_bundle.sh": _bundle_installer_sh_text().encode("utf-8"),
    }
    paths = []
    for name, data in files.items():
        path = tmp_path / name
        path.write_bytes(data)
        paths.append(path)
    manifest = _release_bundle_manifest(paths)
    bundle = tmp_path / RELEASE_BUNDLE_NAME
    with zipfile.ZipFile(bundle, "w") as archive:
        for path in paths:
            archive.write(path, path.name)
        archive.writestr(
            "cambrian-install-kit-release-bundle-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    verified = verify_release_bundle_current_artifacts(bundle)
    assert verified["current_artifact_checks"]["current_artifact_hashes_match_bundle"] is True

    (tmp_path / "cambrian-install-kit-send-ready.json").write_text('{"stale": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="current artifact"):
        verify_release_bundle_current_artifacts(bundle)


def test_install_kit_release_bundle_smoke_receipt_requires_required_gold_path_receipt() -> None:
    install_receipt = {
        "schema_version": "cambrian_install_share_receipt_v0_1",
        "status": "installed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "all_steps_passed": True,
            "cambrian_help_passed": True,
            "cambrian_doctor_json_passed": True,
            "cambrian_company_snapshot_help_passed": True,
        },
    }
    gold_path_receipt = {
        "schema_version": "cambrian_bundle_gold_path_share_receipt_v0_1",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "proof_claim_allowed": False,
        "sale_ready": False,
        "checks": {
            "cambrian --help": True,
            "cambrian doctor": True,
            "company snapshot": True,
        },
        "capabilities_verified": {
            "ai_agents_created": True,
            "skills_generated_searched_and_fused": True,
            "harness_engineering_system_created": True,
            "evolution_proposed_previewed_and_applied": True,
            "company_snapshot_generated": True,
            "mcp_operability_verified": True,
        },
    }

    payload = _smoke_receipt(
        bundle_name="cambrian-install-kit-release-bundle.zip",
        bundle_sha256="a" * 64,
        steps=[
            {"name": "run extracted bundle verifier", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "install Cambrian from extracted bundle", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
            {"name": "run required AI Company Gold Path", "status": "passed", "exit_code": 0, "duration_seconds": 0.1},
        ],
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
    )

    verify_bundle_smoke_receipt_payload(payload)
    assert payload["status"] == "pass"
    assert payload["safe_to_share"] is True
    assert payload["checks"]["gold_path_capabilities_all_true"] is True
    assert payload["checks"]["gold_path_mcp_operability_verified"] is True
    assert payload["checks"]["gold_path_claim_boundaries_locked"] is True
    assert payload["gold_path_share_receipt"]["capabilities_all_true"] is True
    assert payload["gold_path_share_receipt"]["mcp_operability_verified"] is True
    assert payload["claim_boundaries"]["public_proof_claim_allowed"] is False
    assert payload["claim_boundaries"]["sale_ready"] is False
    assert BUNDLE_SMOKE_RECEIPT_NAME == "cambrian-install-kit-release-bundle-smoke-receipt.json"

    gold_path_receipt["capabilities_verified"]["company_snapshot_generated"] = False
    blocked = _smoke_receipt(
        bundle_name="cambrian-install-kit-release-bundle.zip",
        bundle_sha256="a" * 64,
        steps=[{"name": "run required AI Company Gold Path", "status": "passed", "exit_code": 0, "duration_seconds": 0.1}],
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
    )
    with pytest.raises(Exception, match="gold_path_capabilities_all_true"):
        verify_bundle_smoke_receipt_payload(blocked)


def test_install_kit_bundle_standalone_verifier_is_self_contained() -> None:
    script = _standalone_bundle_verifier_text()

    for phrase in [
        "cambrian_install_kit_bundle_local_verification_v0_1",
        "cambrian-install-kit-release-bundle-manifest.json",
        "START_HERE_CAMBRIAN_INSTALL_KIT.md",
        "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md",
        "MCP_EXTERNAL_CLIENT_CONNECT.md",
        "cambrian-install-kit-release-receipt.json",
        "CAMBRIAN_INSTALL_KIT_MANIFEST.json",
        "INSTALL_CAMBRIAN_FROM_BUNDLE.py",
        "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py",
        "bundle_agent_prompt_present",
        "mcp_connect_guide_present",
        "start_here_mentions_bundle_agent_prompt",
        "start_here_mentions_mcp_guide",
        "start_here_mentions_mcp_verify",
        "bundle_agent_prompt_mentions_mcp_guide",
        "bundle_agent_prompt_mentions_mcp_verify",
        "bundle_agent_prompt_marks_gold_path_required",
        "bundle_agent_prompt_mentions_share_receipts",
        "bundle_agent_prompt_marks_receipts_local_validation_only",
        "bundle_agent_prompt_blocks_public_proof_claims",
        "bundle_agent_prompt_blocks_first_recipient_claims",
        "gold_path_runner_present",
        "start_here_marks_gold_path_required",
        "start_here_does_not_mark_gold_path_optional",
        "start_here_mentions_gold_path_share_receipt",
        "start_here_marks_receipts_local_validation_only",
        "start_here_blocks_public_proof_claims",
        "start_here_blocks_first_recipient_claims",
        "handoff_copy_paste_marks_receipts_local_validation_only",
        "handoff_copy_paste_blocks_public_proof_claims",
        "handoff_copy_paste_blocks_first_recipient_claims",
        "handoff_checks_require_claim_boundary",
        "send_ready_copy_paste_marks_receipts_local_validation_only",
        "send_ready_copy_paste_blocks_public_proof_claims",
        "send_ready_copy_paste_blocks_first_recipient_claims",
        "send_ready_checks_require_claim_boundary",
        "mcp_connect_guide_mentions_cambrian_mcp",
        "mcp_connect_guide_mentions_mcp_verify",
        "mcp_connect_guide_mentions_explicit_cwd",
        "mcp_connect_guide_mentions_no_arbitrary_shell",
        "standalone_installer_present",
        "inner_install_kit_entrypoint_present",
        "inner_install_kit_mcp_entrypoint_present",
        "raise SystemExit(1)",
    ]:
        assert phrase in script


def test_install_kit_bundle_standalone_installer_is_self_contained() -> None:
    script = _standalone_bundle_installer_text()
    bat = _bundle_installer_bat_text()
    sh = _bundle_installer_sh_text()

    for phrase in [
        "INSTALL_KIT_DIR",
        "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py",
        "CAMBRIAN_INSTALL_KIT_MANIFEST.json",
        "--project",
        "--offline",
        "Target project directory where Cambrian will be installed.",
        "Project-local virtual environment directory name.",
        "Cambrian install kit ZIP was not found in the extracted release bundle directory.",
        "install_cambrian.py was not found inside the install kit ZIP.",
        "install_cambrian.py",
        "cambrian_install_receipt.json",
        "cambrian_install_share_receipt.json",
        "mcp_operability_receipt.json",
        "cambrian_command",
        "cambrian_mcp_command",
    ]:
        assert phrase in script
    assert all(ord(ch) < 128 for ch in script)
    assert "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in bat
    assert "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in sh


def test_install_kit_bundle_gold_path_runner_is_self_contained() -> None:
    script = _standalone_bundle_gold_path_text()

    for phrase in [
        "cambrian_bundle_gold_path_share_receipt_v0_1",
        "cambrian_gold_path_share_receipt.json",
        "cambrian_gold_path_receipt.json",
        ".cbgp",
        "debug_steps",
        "mcp operability verify",
        "cambrian mcp verify",
        "mcp_operability_receipt.json",
        "cambrian-mcp",
        "harness engineer dry-run",
        "skill fuse",
        "evolve apply",
        "company snapshot is private-safe artifact",
        "ai_agents_created",
        "skills_generated_searched_and_fused",
        "harness_engineering_system_created",
        "evolution_proposed_previewed_and_applied",
        "company_snapshot_generated",
        "mcp_operability_verified",
        "proof_claim_allowed",
        "sale_ready",
        "raw_private_project_data_included",
    ]:
        assert phrase in script


def test_install_kit_release_receipt_verifies_standalone(tmp_path: Path) -> None:
    payload = _release_receipt(
        {
            "status": "built",
            "zip_file": str(ROOT / "private" / "cambrian-install-kit-0.3.0.zip"),
            "zip_sha256": "d" * 64,
            "version": "0.3.0",
            "dependency_mode": "bundled_wheelhouse",
        },
        {"status": "pass", "receipt_body_sha256": "e" * 64},
        {"status": "ready_to_share", "handoff_body_sha256": "f" * 64},
        {
            "verdict": "GO",
            "send_ready_body_sha256": "1" * 64,
            "checks": {
                "company_snapshot_help_verified": True,
                "manual_dispatch_required": True,
            },
            "send_ready_checks": {"artifact_chain_complete": True},
        },
    )
    path = tmp_path / "release-receipt.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verified = verify_release_receipt_file(path)
    text = path.read_text(encoding="utf-8")

    assert verified["status"] == "pass"
    assert verified["release_receipt_checks"]["checks_all_true"] is True
    assert verified["release_receipt_checks"]["body_hash_matched"] is True
    assert str(ROOT) not in text


def test_install_kit_release_can_reuse_existing_zip(tmp_path: Path) -> None:
    import zipfile

    kit_zip = tmp_path / "cambrian-install-kit-0.3.0.zip"
    release_bundle_zip = tmp_path / "cambrian-install-kit-release-bundle.zip"
    manifest = {
        "schema_version": "cambrian_install_kit_v0_1",
        "dependency_mode": "bundled_wheelhouse",
        "package": {"version": "0.3.0"},
    }
    with zipfile.ZipFile(kit_zip, "w") as archive:
        archive.writestr("CAMBRIAN_INSTALL_KIT_MANIFEST.json", json.dumps(manifest))
    with zipfile.ZipFile(release_bundle_zip, "w") as archive:
        archive.writestr("START_HERE_CAMBRIAN_INSTALL_KIT.md", "not the install kit")

    result = _existing_build_result(tmp_path)

    assert result["status"] == "built"
    assert result["version"] == "0.3.0"
    assert result["dependency_mode"] == "bundled_wheelhouse"
    assert result["zip_file"].endswith("cambrian-install-kit-0.3.0.zip")


def test_install_kit_handoff_default_zip_ignores_release_bundle(tmp_path: Path, monkeypatch) -> None:
    import zipfile

    dist = tmp_path / "dist"
    dist.mkdir()
    kit_zip = dist / "cambrian-install-kit-0.3.0.zip"
    release_bundle_zip = dist / "cambrian-install-kit-release-bundle.zip"
    with zipfile.ZipFile(kit_zip, "w") as archive:
        archive.writestr("CAMBRIAN_INSTALL_KIT_MANIFEST.json", "{}")
    with zipfile.ZipFile(release_bundle_zip, "w") as archive:
        archive.writestr("START_HERE_CAMBRIAN_INSTALL_KIT.md", "not the install kit")

    monkeypatch.setattr("scripts.prepare_cambrian_install_kit_handoff._repo_root", lambda: tmp_path)

    assert default_handoff_zip().name == "cambrian-install-kit-0.3.0.zip"


def test_install_kit_handoff_links_zip_and_receipt_without_private_paths(tmp_path: Path) -> None:
    zip_path = tmp_path / "cambrian-install-kit-0.3.0.zip"
    zip_path.write_bytes(b"fake install kit")
    result = {
        "status": "pass",
        "zip_file": str(ROOT / "private" / zip_path.name),
        "zip_sha256": "b" * 64,
        "manifest_version": "0.3.0",
        "failed_checks": [],
        "install_check": True,
        "offline": True,
        "checks": {
            "schema_version": True,
            "required_files_present": True,
            "wheel_present": True,
            "python_requires_present": True,
            "entrypoint_present": True,
            "mcp_entrypoint_present": True,
            "install_commands_present": True,
            "files_hashes_match": True,
            "install_script_passed": True,
            "install_receipt_present": True,
            "install_receipt_status_installed": True,
            "install_receipt_steps_passed": True,
            "install_receipt_company_snapshot_help_passed": True,
            "install_receipt_company_snapshot_next_command_present": True,
            "install_receipt_mcp_verify_passed": True,
            "install_receipt_mcp_next_command_present": True,
            "mcp_operability_receipt_present": True,
            "mcp_operability_receipt_go": True,
            "mcp_operability_installed_entrypoint": True,
            "mcp_operability_no_arbitrary_shell": True,
        },
    }
    receipt_path = write_shareable_receipt(tmp_path / "receipt.json", result)

    prepared = prepare_handoff(
        output_dir=tmp_path,
        zip_path=zip_path,
        receipt_path=receipt_path,
        skip_verify=True,
    )
    handoff = verify_handoff_file(Path(prepared["handoff_json"]))
    text = Path(prepared["handoff_json"]).read_text(encoding="utf-8")

    assert handoff["safe_to_share"] is True
    assert handoff["verified_capabilities"]["company_snapshot_help"] is True
    assert handoff["verified_capabilities"]["mcp_operability"] is True
    assert handoff["handoff_checks"]["artifact_chain_complete"] is True
    assert handoff["handoff_checks"]["mcp_operability_verified"] is True
    assert handoff["handoff_checks"]["mcp_operability_named"] is True
    assert handoff["handoff_checks"]["claim_boundary_present"] is True
    assert handoff["dispatch_execution_policy"]["manual_operator_dispatch_required"] is True
    assert handoff["dispatch_execution_policy"]["script_sends_to_recipient"] is False
    assert str(ROOT) not in text
    assert "raw private project data" in handoff["do_not_share"]
    assert "INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>" in handoff["copy_paste_message"]
    assert "cambrian_install_share_receipt.json" in handoff["copy_paste_message"]
    assert "mcp_operability_receipt.json" in handoff["copy_paste_message"]
    assert "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>" in handoff["copy_paste_message"]
    assert "cambrian_gold_path_share_receipt.json" in handoff["copy_paste_message"]
    assert "local validation evidence only" in handoff["copy_paste_message"]
    assert "do not claim public proof" in handoff["copy_paste_message"]
    assert "First-recipient confirmation requires a real human send" in handoff["copy_paste_message"]
    assert "This is the Cambrian install kit release bundle." in handoff["copy_paste_message"]
    assert all(ord(ch) < 128 for ch in handoff["copy_paste_message"])
    assert all(ord(ch) < 128 for ch in "\n".join(handoff["recipient_steps"]))
    assert "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md" not in handoff["copy_paste_message"]
    assert "?ㅼ튂" not in text
    assert "媛" not in text
    assert handoff["handoff_checks"]["gold_path_runner_named"] is True
    assert handoff["handoff_checks"]["gold_path_share_receipt_named"] is True
    assert "cambrian_install_share_receipt.json" in " ".join(handoff["recipient_steps"])
    assert "mcp_operability_receipt.json" in " ".join(handoff["recipient_steps"])
    assert "cambrian_gold_path_share_receipt.json" in " ".join(handoff["recipient_steps"])
    assert "local validation evidence only" in " ".join(handoff["recipient_steps"])
    assert "INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>" in " ".join(handoff["recipient_steps"])
    assert "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>" in " ".join(handoff["recipient_steps"])


def test_install_kit_handoff_body_hash_is_stable_across_regeneration(tmp_path: Path) -> None:
    zip_path = tmp_path / "cambrian-install-kit-0.3.0.zip"
    zip_path.write_bytes(b"fake install kit")
    _write_install_kit_verification_receipt_fixture(tmp_path)
    receipt_path = tmp_path / "cambrian-install-kit-verification-receipt.json"

    first = prepare_handoff(output_dir=tmp_path, zip_path=zip_path, receipt_path=receipt_path, skip_verify=True)
    second = prepare_handoff(output_dir=tmp_path, zip_path=zip_path, receipt_path=receipt_path, skip_verify=True)

    assert first["handoff_body_sha256"] == second["handoff_body_sha256"]
    verify_handoff_file(Path(first["handoff_json"]))
    verify_handoff_file(Path(second["handoff_json"]))


def test_install_kit_send_ready_links_artifact_chain_without_dispatching(tmp_path: Path) -> None:
    zip_path = tmp_path / "cambrian-install-kit-0.3.0.zip"
    zip_path.write_bytes(b"fake install kit")
    result = {
        "status": "pass",
        "zip_file": str(ROOT / "private" / zip_path.name),
        "zip_sha256": "c" * 64,
        "manifest_version": "0.3.0",
        "failed_checks": [],
        "install_check": True,
        "offline": True,
        "checks": {
            "schema_version": True,
            "required_files_present": True,
            "wheel_present": True,
            "python_requires_present": True,
            "entrypoint_present": True,
            "mcp_entrypoint_present": True,
            "install_commands_present": True,
            "files_hashes_match": True,
            "install_script_passed": True,
            "install_receipt_present": True,
            "install_receipt_status_installed": True,
            "install_receipt_steps_passed": True,
            "install_receipt_company_snapshot_help_passed": True,
            "install_receipt_company_snapshot_next_command_present": True,
            "install_receipt_mcp_verify_passed": True,
            "install_receipt_mcp_next_command_present": True,
            "mcp_operability_receipt_present": True,
            "mcp_operability_receipt_go": True,
            "mcp_operability_installed_entrypoint": True,
            "mcp_operability_no_arbitrary_shell": True,
        },
    }
    write_shareable_receipt(tmp_path / "cambrian-install-kit-verification-receipt.json", result)
    prepare_handoff(
        output_dir=tmp_path,
        zip_path=zip_path,
        receipt_path=tmp_path / "cambrian-install-kit-verification-receipt.json",
        skip_verify=True,
    )

    prepared = check_send_ready(output_dir=tmp_path, skip_verify=True)
    payload = verify_send_ready_file(Path(prepared["send_ready_json"]))
    text = Path(prepared["send_ready_json"]).read_text(encoding="utf-8")
    markdown = Path(prepared["send_ready_md"]).read_text(encoding="utf-8")

    assert payload["verdict"] == "GO"
    assert payload["send_ready_checks"]["artifact_chain_complete"] is True
    assert payload["checks"]["company_snapshot_help_verified"] is True
    assert payload["checks"]["mcp_operability_verified"] is True
    assert payload["checks"]["copy_paste_message_mentions_bundle_installer"] is True
    assert payload["checks"]["copy_paste_message_mentions_gold_path_runner"] is True
    assert payload["checks"]["copy_paste_message_mentions_share_receipt"] is True
    assert payload["checks"]["copy_paste_message_mentions_gold_path_share_receipt"] is True
    assert payload["checks"]["copy_paste_message_mentions_mcp_operability_receipt"] is True
    assert payload["checks"]["copy_paste_message_marks_local_validation_only"] is True
    assert payload["checks"]["copy_paste_message_blocks_public_proof_claims"] is True
    assert payload["checks"]["copy_paste_message_blocks_first_recipient_claims"] is True
    assert payload["verified_capabilities"]["mcp_operability"] is True
    assert "INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>" in payload["copy_paste_message"]
    assert "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>" in payload["copy_paste_message"]
    assert "cambrian_install_share_receipt.json" in payload["copy_paste_message"]
    assert "cambrian_gold_path_share_receipt.json" in payload["copy_paste_message"]
    assert "mcp_operability_receipt.json" in payload["copy_paste_message"]
    assert "local validation evidence only" in payload["copy_paste_message"]
    assert "do not claim public proof" in payload["copy_paste_message"]
    assert "First-recipient confirmation requires a real human send" in payload["copy_paste_message"]
    assert "This is the Cambrian install kit release bundle." in payload["copy_paste_message"]
    assert all(ord(ch) < 128 for ch in payload["copy_paste_message"])
    assert "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md" not in payload["copy_paste_message"]
    assert "This send-ready receipt records install-kit delivery readiness only." in markdown
    assert all(ord(ch) < 128 for ch in markdown)
    assert payload["dispatch_execution_policy"]["script_sends_to_recipient"] is False
    assert payload["dispatch_execution_policy"]["manual_operator_dispatch_required"] is True
    assert str(ROOT) not in text


def test_install_kit_send_ready_body_hash_is_stable_across_regeneration(tmp_path: Path) -> None:
    zip_path = tmp_path / "cambrian-install-kit-0.3.0.zip"
    zip_path.write_bytes(b"fake install kit")
    _write_install_kit_verification_receipt_fixture(tmp_path)

    first = check_send_ready(output_dir=tmp_path, skip_verify=True)
    second = check_send_ready(output_dir=tmp_path, skip_verify=True)

    assert first["send_ready_body_sha256"] == second["send_ready_body_sha256"]
    verify_send_ready_file(Path(first["send_ready_json"]))
    verify_send_ready_file(Path(second["send_ready_json"]))


def test_install_kit_dispatch_record_outputs_ready_to_send_one(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    existing_send_ready = check_send_ready(output_dir=tmp_path, skip_verify=True)
    existing_send_ready_hash = existing_send_ready["send_ready_body_sha256"]
    prepared = check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    json_path = Path(prepared["dispatch_record_json"])
    md_path = Path(prepared["dispatch_record_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert prepared["status"] == "ready_to_dispatch_one"
    assert prepared["verdict"] == "READY_TO_SEND_ONE"
    assert json_path.name == DISPATCH_RECORD_JSON_NAME
    assert md_path.name == DISPATCH_RECORD_MD_NAME
    assert payload["schema_version"] == "cambrian_install_kit_dispatch_record_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["send_ready"]["body_sha256"] == existing_send_ready_hash
    assert payload["dispatch_record_body_sha256"] == _dispatch_record_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["dispatch_record_checks"].values())
    assert payload["dispatch_scope"]["target_recipients"] == 1
    assert payload["dispatch_scope"]["cohort_scaling_allowed"] is False
    assert payload["dispatch_scope"]["marketplace_listing_allowed"] is False
    assert payload["dispatch_scope"]["proof_claim_allowed"] is False
    assert payload["dispatch_execution_policy"]["script_sends_to_recipient"] is False
    assert payload["dispatch_execution_policy"]["script_sends_copy_paste_message"] is False
    assert payload["dispatch_execution_policy"]["manual_operator_dispatch_required"] is True
    assert payload["dispatch_execution_policy"]["records_private_sha256_only"] is True
    assert payload["dispatch_record"]["sent_recorded"] is False
    assert payload["dispatch_record"]["recipient_private_sha256"] is None
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert payload["checks"]["copy_paste_message_mentions_share_receipt"] is True
    assert payload["checks"]["copy_paste_message_mentions_gold_path_share_receipt"] is True
    assert payload["checks"]["copy_paste_message_mentions_gold_path_runner"] is True
    assert payload["checks"]["copy_paste_message_mentions_mcp_operability_receipt"] is True
    assert payload["checks"]["copy_paste_message_marks_local_validation_only"] is True
    assert payload["checks"]["copy_paste_message_blocks_public_proof_claims"] is True
    assert payload["checks"]["copy_paste_message_blocks_first_recipient_claims"] is True
    assert payload["checks"]["release_bundle_smoke_receipt_status_pass"] is True
    assert payload["checks"]["release_bundle_smoke_receipt_checks_true"] is True
    assert payload["checks"]["release_bundle_smoke_gold_path_confirmed"] is True
    assert payload["checks"]["release_bundle_smoke_mcp_operability_verified"] is True
    assert payload["checks"]["release_bundle_smoke_claim_boundaries_locked"] is True
    assert payload["release_bundle_smoke"]["file"] == BUNDLE_SMOKE_RECEIPT_NAME
    assert payload["release_bundle_smoke"]["gold_path_capabilities_all_true"] is True
    assert payload["release_bundle_smoke"]["mcp_operability_verified"] is True
    assert payload["release_bundle_smoke"]["gold_path_capabilities_verified"]["mcp_operability_verified"] is True
    assert payload["send_materials"]["copy_paste_message_policy"]["share_receipt_named"] is True
    assert payload["send_materials"]["copy_paste_message_policy"]["gold_path_share_receipt_named"] is True
    assert payload["send_materials"]["copy_paste_message_policy"]["gold_path_runner_named"] is True
    assert payload["send_materials"]["copy_paste_message_policy"]["mcp_operability_receipt_named"] is True
    assert payload["send_materials"]["copy_paste_message_policy"]["local_validation_only"] is True
    assert payload["send_materials"]["copy_paste_message_policy"]["public_proof_claim_blocked"] is True
    assert (
        payload["send_materials"]["copy_paste_message_policy"][
            "first_recipient_confirmation_requires_real_send"
        ]
        is True
    )

    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    assert {
        "install_kit_zip",
        "install_kit_receipt",
        "install_kit_handoff",
        "install_kit_send_ready",
        "install_kit_release_bundle_smoke",
        "install_kit_dispatch_record",
    }.issubset(set(chain_by_kind))
    assert chain_by_kind["install_kit_release_bundle_smoke"]["file"] == BUNDLE_SMOKE_RECEIPT_NAME
    assert chain_by_kind["install_kit_release_bundle_smoke"]["sha256"] == payload["release_bundle_smoke"]["body_sha256"]
    assert chain_by_kind["install_kit_dispatch_record"]["file"] == DISPATCH_RECORD_JSON_NAME
    assert chain_by_kind["install_kit_dispatch_record"]["sha256"] == payload["dispatch_record_body_sha256"]
    assert verify_dispatch_record_file(json_path)["dispatch_record_body_sha256"] == payload["dispatch_record_body_sha256"]

    assert "Cambrian Install Kit Dispatch Record" in markdown
    assert "READY_TO_SEND_ONE" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "MCP operability verified: True" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized


def test_install_kit_dispatch_record_body_hash_is_stable_across_regeneration(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)

    first = check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    second = check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    payload = verify_dispatch_record_file(Path(second["dispatch_record_json"]))

    assert first["dispatch_record_body_sha256"] == second["dispatch_record_body_sha256"]
    assert payload["dispatch_record_checks"]["body_hash_matched"] is True


def test_install_kit_dispatch_record_can_record_private_sent_hashes(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    prepared = check_dispatch_record(
        output_dir=tmp_path,
        skip_verify=True,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    payload = json.loads(Path(prepared["dispatch_record_json"]).read_text(encoding="utf-8"))

    assert prepared["status"] == "dispatch_recorded"
    assert prepared["verdict"] == "SENT_ONE_RECORDED"
    assert payload["dispatch_record"]["sent_recorded"] is True
    assert payload["dispatch_record"]["recipient_private_sha256"] == "a" * 64
    assert payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == "b" * 64
    assert payload["dispatch_record"]["sent_at_utc"] == "2026-05-15T10:00:00+00:00"
    assert payload["dispatch_execution_policy"]["sent_recorded_by_private_hashes_only"] is True
    assert payload["dispatch_record_checks"]["sent_record_consistent"] is True


def test_install_kit_dispatch_record_requires_operator_status_receipt_when_requested(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)

    with pytest.raises(InstallKitDispatchRecordError, match="operator status receipt is required"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            require_operator_status_receipt=True,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_dispatch_record_requires_pre_send_receipts_for_standard_workspace_by_default(
    tmp_path: Path,
) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)

    with pytest.raises(InstallKitDispatchRecordError, match="operator status receipt is required"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_file=Path(str(ready["recipient_path"])),
            operator_dispatch_note_private_file=Path(str(ready["note_path"])),
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_dispatch_record_requires_manual_send_go_receipt_when_requested(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    Path(str(ready["manual_send_go_receipt"])).unlink()

    with pytest.raises(InstallKitDispatchRecordError, match="manual-send GO receipt is required"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_file=Path(str(ready["recipient_path"])),
            operator_dispatch_note_private_file=Path(str(ready["note_path"])),
            operator_status_receipt=Path(str(ready["operator_status_receipt"])),
            require_operator_status_receipt=True,
            require_manual_send_go_receipt=True,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_dispatch_record_rejects_blocked_operator_status_when_required(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)

    with pytest.raises(InstallKitDispatchRecordError, match="READY_TO_MANUALLY_SEND_ONE"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_file=workspace / "recipient-private.txt",
            operator_dispatch_note_private_file=workspace / "operator-dispatch-note-private.md",
            operator_status_receipt=Path(status["receipt_json"]),
            require_operator_status_receipt=True,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_dispatch_record_accepts_ready_operator_status_when_required(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    workspace = Path(str(ready["workspace"]))

    prepared = check_dispatch_record(
        output_dir=tmp_path,
        skip_verify=True,
        recipient_private_file=Path(str(ready["recipient_path"])),
        operator_dispatch_note_private_file=Path(str(ready["note_path"])),
        operator_status_receipt=Path(str(ready["operator_status_receipt"])),
        require_operator_status_receipt=True,
        manual_send_go_receipt=Path(str(ready["manual_send_go_receipt"])),
        require_manual_send_go_receipt=True,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    payload = json.loads(Path(prepared["dispatch_record_json"]).read_text(encoding="utf-8"))
    markdown = Path(prepared["dispatch_record_md"]).read_text(encoding="utf-8")
    operator_status = payload["operator_status_pre_send"]
    manual_go = payload["manual_send_go_pre_send"]
    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    serialized = json.dumps(payload, ensure_ascii=False) + markdown

    assert prepared["verdict"] == "SENT_ONE_RECORDED"
    assert operator_status["required"] is True
    assert operator_status["present"] is True
    assert operator_status["verified_standalone"] is True
    assert operator_status["ready_to_send_one"] is True
    assert operator_status["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert operator_status["send_state"] == "READY_TO_SEND"
    assert operator_status["release_hash_matches_dispatch"] is True
    assert operator_status["private_hashes_match_dispatch"] is True
    assert manual_go["required"] is True
    assert manual_go["present"] is True
    assert manual_go["verified_standalone"] is True
    assert manual_go["ready_to_send_one"] is True
    assert manual_go["verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert manual_go["release_hash_matches_dispatch"] is True
    assert manual_go["operator_status_ready_receipt_matches"] is True
    assert manual_go["operator_status_body_matches_dispatch"] is True
    assert chain_by_kind["install_kit_operator_status"]["file"] == OPERATOR_STATUS_READY_RECEIPT_NAME
    assert chain_by_kind["install_kit_operator_status"]["sha256"] == ready["operator_status_body_sha256"]
    assert chain_by_kind["install_kit_manual_send_go"]["file"] == MANUAL_SEND_GO_RECEIPT_NAME
    assert chain_by_kind["install_kit_manual_send_go"]["sha256"] == ready["manual_send_go_body_sha256"]
    assert all(payload["dispatch_record_checks"].values())
    assert "real-recipient@example.com" not in serialized
    assert "private channel: email" not in serialized
    assert str(workspace) not in serialized


def test_install_kit_dispatch_record_rejects_stale_current_artifacts_after_ready_receipt(
    tmp_path: Path,
) -> None:
    bundle, bundle_sha = _write_current_artifact_release_bundle_fixture(tmp_path)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    recipient_path = workspace / "recipient-private.txt"
    note_path = workspace / "operator-dispatch-note-private.md"
    recipient_path.write_text("real-recipient@example.com\n", encoding="utf-8")
    note_path.write_text(f"private channel: email\nrelease bundle sha256: {bundle_sha}\n", encoding="utf-8")
    status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)

    assert status["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert verify_release_bundle_current_artifacts(bundle, output_dir=tmp_path)["current_artifact_checks"][
        "current_artifact_hashes_match_bundle"
    ] is True

    (tmp_path / "cambrian-install-kit-send-ready.md").write_text("stale send ready", encoding="utf-8")

    with pytest.raises(InstallKitDispatchRecordError, match="current artifacts"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_file=recipient_path,
            operator_dispatch_note_private_file=note_path,
            operator_status_receipt=Path(str(status["ready_receipt_json"])),
            require_operator_status_receipt=True,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_dispatch_record_rejects_placeholder_sent_at_when_recording(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)

    with pytest.raises(InstallKitDispatchRecordError, match="real UTC manual-send timestamp"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_file=Path(str(ready["recipient_path"])),
            operator_dispatch_note_private_file=Path(str(ready["note_path"])),
            operator_status_receipt=Path(str(ready["operator_status_receipt"])),
            require_operator_status_receipt=True,
            sent_at_utc="<real-sent-at-utc>",
        )


def test_install_kit_dispatch_record_rejects_future_sent_at_when_recording(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)

    with pytest.raises(InstallKitDispatchRecordError, match="must not be in the future"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_file=Path(str(ready["recipient_path"])),
            operator_dispatch_note_private_file=Path(str(ready["note_path"])),
            operator_status_receipt=Path(str(ready["operator_status_receipt"])),
            require_operator_status_receipt=True,
            sent_at_utc="2999-01-01T00:00:00+00:00",
        )


def test_install_kit_operator_send_bypass_audit_passes_for_status_gated_surfaces(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)

    result = audit_install_kit_operator_send_bypass(output_dir=tmp_path, workspace_dir=workspace)
    receipt = verify_operator_send_bypass_audit_file(Path(result["receipt_json"]))
    serialized = json.dumps(receipt, ensure_ascii=False)

    assert result["verdict"] == "NO_OPERATOR_STATUS_BYPASS"
    assert Path(result["receipt_json"]).name == OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME
    assert receipt["safe_to_share"] is True
    assert receipt["dispatch_record"]["verdict"] == "READY_TO_SEND_ONE"
    assert receipt["policy"]["status_receipt_required_before_sent_record"] is True
    assert receipt["policy"]["manual_send_go_receipt_required_before_sent_record"] is True
    assert receipt["checks"]["all_operator_dispatch_commands_require_operator_status"] is True
    assert receipt["checks"]["dispatch_script_requires_manual_send_go_when_required"] is True
    assert receipt["checks"]["recipient_checkpoint_requires_manual_send_go_when_post_send"] is True
    assert receipt["checks"]["post_send_sequence_requires_manual_send_go_when_recording"] is True
    assert receipt["checks"]["all_operator_command_placeholders_shell_safe"] is True
    assert receipt["checks"]["private_runbook_shell_safe_when_present"] is True
    assert all(receipt["checks"].values())
    assert all(receipt["operator_send_bypass_audit_checks"].values())
    assert {item["source"] for item in receipt["audited_sources"]} == {
        "dispatch_record_script",
        "first_recipient_operator_status_script",
        "first_recipient_post_send_sequence_script",
        "first_recipient_workspace_script",
        "install_kit_release_doc",
        "private_runbook",
        "recipient_checkpoint_script",
    }
    assert all(item["operator_command_placeholders_shell_safe"] is True for item in receipt["audited_sources"])
    assert all(item["dispatch_commands_require_manual_send_go"] is True for item in receipt["audited_sources"])
    assert all(item["dispatch_commands_require_pre_send_proof"] is True for item in receipt["audited_sources"])
    assert str(workspace) not in serialized
    assert str(tmp_path) not in serialized
    assert "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
    assert "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in serialized


def test_install_kit_operator_send_bypass_audit_rejects_shell_unsafe_private_runbook(
    tmp_path: Path,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    (workspace / PRIVATE_RUNBOOK_NAME).write_text(
        "python scripts/check_cambrian_install_kit_dispatch_record.py "
        "--recipient-private-file \"private-recipient.txt\" "
        "--operator-dispatch-note-private-file \"operator-note.md\" "
        "--operator-status-receipt \"operator-status-ready.json\" "
        "--require-operator-status-receipt "
        "--sent-at-utc <real-sent-at-utc>\n",
        encoding="utf-8",
    )

    with pytest.raises(InstallKitOperatorSendBypassAuditError, match="did not pass"):
        audit_install_kit_operator_send_bypass(output_dir=tmp_path, workspace_dir=workspace)


def test_install_kit_operator_send_bypass_audit_receipt_rejects_tampering(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    result = audit_install_kit_operator_send_bypass(output_dir=tmp_path, workspace_dir=tmp_path / "missing-private")
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    payload["checks"]["dispatch_script_requires_status_receipt_when_required"] = False
    tampered = tmp_path / "tampered-operator-send-bypass-audit.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitOperatorSendBypassAuditError):
        verify_operator_send_bypass_audit_file(tampered)


def test_install_kit_manual_send_go_rehearsal_reaches_sent_recorded_without_real_send(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)

    result = smoke_manual_send_go_rehearsal(output_dir=tmp_path, skip_verify=True)
    receipt = verify_manual_send_go_rehearsal_receipt_file(Path(result["receipt_json"]))
    serialized = json.dumps(receipt, ensure_ascii=False)

    assert result["verdict"] == "REHEARSAL_PASS"
    assert Path(result["receipt_json"]).name == MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    assert receipt["safe_to_share"] is True
    assert receipt["real_manual_send"] is False
    assert receipt["real_recipient_evidence"] is False
    assert receipt["synthetic_private_values_used"] is True
    assert receipt["release_bundle"]["sha256"] == bundle_sha
    assert receipt["rehearsed_flow"]["operator_status_verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert receipt["rehearsed_flow"]["operator_bypass_verdict"] == "NO_OPERATOR_STATUS_BYPASS"
    assert receipt["rehearsed_flow"]["dispatch_record_verdict"] == "SENT_ONE_RECORDED"
    assert receipt["rehearsed_flow"]["dispatch_operator_status_required"] is True
    assert receipt["rehearsed_flow"]["dispatch_synthetic_standalone_send_evidence_allowed"] is False
    assert receipt["checks"]["dispatch_operator_status_required"] is True
    assert receipt["checks"]["dispatch_private_hashes_match"] is True
    assert receipt["checks"]["synthetic_dispatch_not_standalone_proof"] is True
    assert receipt["checks"]["real_manual_send_not_claimed"] is True
    assert receipt["checks"]["script_did_not_send_to_recipient"] is True
    assert all(receipt["checks"].values())
    assert str(tmp_path) not in serialized
    for marker in INSTALL_KIT_REHEARSAL_PRIVATE_MARKERS:
        assert marker not in serialized


def test_install_kit_synthetic_rehearsal_dispatch_is_not_standalone_send_evidence(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)

    result = check_dispatch_record(
        output_dir=tmp_path,
        skip_verify=True,
        recipient_private_file=Path(str(ready["recipient_path"])),
        operator_dispatch_note_private_file=Path(str(ready["note_path"])),
        operator_status_receipt=Path(str(ready["operator_status_receipt"])),
        require_operator_status_receipt=True,
        allow_synthetic_rehearsal_without_manual_send_go_receipt=True,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    dispatch_path = Path(result["dispatch_record_json"])

    with pytest.raises(InstallKitDispatchRecordError, match="not standalone send evidence"):
        verify_dispatch_record_file(dispatch_path)

    payload = verify_dispatch_record_file(dispatch_path, allow_synthetic_rehearsal=True)
    assert payload["verdict"] == "SENT_ONE_RECORDED"
    assert payload["synthetic_rehearsal_boundary"]["standalone_send_evidence_allowed"] is False
    assert payload["synthetic_rehearsal_boundary"]["real_manual_send"] is False


def test_install_kit_synthetic_recipient_checkpoint_is_not_standalone_evidence(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    gold_path_receipt = _write_gold_path_share_receipt_fixture(tmp_path / "cambrian_gold_path_share_receipt.json")
    mcp_receipt = _write_mcp_operability_receipt_fixture(tmp_path / "mcp_operability_receipt.json")

    prepared = check_recipient_checkpoint(
        output_dir=tmp_path,
        skip_verify=True,
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
        mcp_operability_receipt=mcp_receipt,
        recipient_private_file=ready["recipient_path"],
        operator_dispatch_note_private_file=ready["note_path"],
        operator_status_receipt=ready["operator_status_receipt"],
        require_operator_status_receipt=True,
        manual_send_go_receipt=ready["manual_send_go_receipt"],
        require_manual_send_go_receipt=True,
        recipient_ack_private_sha256="c" * 64,
        sent_at_utc="2026-05-15T10:00:00+00:00",
        allow_synthetic_rehearsal=True,
    )
    checkpoint_path = Path(prepared["recipient_checkpoint_json"])

    with pytest.raises(InstallKitRecipientCheckpointError, match="not standalone recipient evidence"):
        verify_recipient_checkpoint_file(checkpoint_path)

    payload = verify_recipient_checkpoint_file(checkpoint_path, allow_synthetic_rehearsal=True)
    assert payload["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["synthetic_rehearsal_boundary"]["standalone_recipient_evidence_allowed"] is False
    assert payload["synthetic_rehearsal_boundary"]["standalone_send_evidence_allowed"] is False
    assert payload["synthetic_rehearsal_boundary"]["real_manual_send"] is False
    assert payload["recipient_checkpoint_checks"]["synthetic_boundary_not_standalone_when_present"] is True


def test_install_kit_manual_send_go_rehearsal_body_hash_is_stable_across_regeneration(
    tmp_path: Path,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)

    first = smoke_manual_send_go_rehearsal(
        output_dir=tmp_path,
        receipt_path=tmp_path / "manual-send-go-first.json",
        skip_verify=True,
    )
    second = smoke_manual_send_go_rehearsal(
        output_dir=tmp_path,
        receipt_path=tmp_path / "manual-send-go-second.json",
        skip_verify=True,
    )

    assert first["receipt_body_sha256"] == second["receipt_body_sha256"]
    verify_manual_send_go_rehearsal_receipt_file(Path(first["receipt_json"]))
    verify_manual_send_go_rehearsal_receipt_file(Path(second["receipt_json"]))


def test_install_kit_manual_send_go_rehearsal_receipt_rejects_tampering(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    result = smoke_manual_send_go_rehearsal(output_dir=tmp_path, skip_verify=True)
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    payload["real_manual_send"] = True
    tampered = tmp_path / "tampered-manual-send-go-rehearsal.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitManualSendGoRehearsalError):
        verify_manual_send_go_rehearsal_receipt_file(tampered)


def test_install_kit_post_send_checkpoint_rehearsal_confirms_gold_path_without_real_recipient(
    tmp_path: Path,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)

    result = smoke_post_send_checkpoint_rehearsal(output_dir=tmp_path, skip_verify=True)
    receipt = verify_post_send_checkpoint_rehearsal_receipt_file(Path(result["receipt_json"]))
    serialized = json.dumps(receipt, ensure_ascii=False)

    assert result["verdict"] == "REHEARSAL_PASS"
    assert Path(result["receipt_json"]).name == POST_SEND_REHEARSAL_RECEIPT_NAME
    assert receipt["safe_to_share"] is True
    assert receipt["real_recipient_evidence"] is False
    assert receipt["synthetic_private_values_used"] is True
    assert receipt["release_bundle"]["sha256"] == bundle_sha
    assert receipt["rehearsed_flow"]["manual_send_go_verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert receipt["rehearsed_flow"]["recipient_checkpoint_verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert receipt["rehearsed_flow"]["dispatch_manual_send_go_required"] is True
    assert receipt["rehearsed_flow"]["recipient_checkpoint_operator_status_required"] is True
    assert receipt["rehearsed_flow"]["recipient_checkpoint_manual_send_go_required"] is True
    assert receipt["rehearsed_flow"]["returned_mcp_server_command_mode"] == "installed_entrypoint"
    assert receipt["checks"]["manual_send_go_ready_to_send"] is True
    assert receipt["checks"]["dispatch_manual_send_go_required"] is True
    assert receipt["checks"]["synthetic_dispatch_not_standalone_proof"] is True
    assert receipt["checks"]["synthetic_checkpoint_not_standalone_proof"] is True
    assert receipt["checks"]["recipient_checkpoint_operator_status_required"] is True
    assert receipt["checks"]["recipient_checkpoint_operator_status_ready"] is True
    assert receipt["checks"]["recipient_checkpoint_manual_send_go_required"] is True
    assert receipt["checks"]["returned_mcp_installed_entrypoint"] is True
    assert receipt["checks"]["script_did_not_send_to_recipient"] is True
    assert receipt["rehearsed_flow"]["dispatch_synthetic_standalone_send_evidence_allowed"] is False
    assert receipt["rehearsed_flow"]["recipient_checkpoint_synthetic_standalone_recipient_evidence_allowed"] is False
    assert all(receipt["checks"].values())
    assert str(tmp_path) not in serialized
    for marker in INSTALL_KIT_POST_SEND_PRIVATE_MARKERS:
        assert marker not in serialized


def test_install_kit_post_send_checkpoint_rehearsal_body_hash_is_stable_across_regeneration(
    tmp_path: Path,
) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)

    first = smoke_post_send_checkpoint_rehearsal(
        output_dir=tmp_path,
        receipt_path=tmp_path / "post-send-first.json",
        skip_verify=True,
    )
    second = smoke_post_send_checkpoint_rehearsal(
        output_dir=tmp_path,
        receipt_path=tmp_path / "post-send-second.json",
        skip_verify=True,
    )

    assert first["receipt_body_sha256"] == second["receipt_body_sha256"]
    verify_post_send_checkpoint_rehearsal_receipt_file(Path(first["receipt_json"]))
    verify_post_send_checkpoint_rehearsal_receipt_file(Path(second["receipt_json"]))


def test_install_kit_post_send_checkpoint_rehearsal_receipt_rejects_tampering(tmp_path: Path) -> None:
    bundle_bytes = b"release bundle"
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    _write_install_kit_verification_receipt_fixture(tmp_path, bundle_sha256=bundle_sha)
    (tmp_path / RELEASE_BUNDLE_NAME).write_bytes(bundle_bytes)
    result = smoke_post_send_checkpoint_rehearsal(output_dir=tmp_path, skip_verify=True)
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    payload["real_recipient_evidence"] = True
    tampered = tmp_path / "tampered-post-send-rehearsal.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitPostSendCheckpointRehearsalError):
        verify_post_send_checkpoint_rehearsal_receipt_file(tampered)


def test_install_kit_dispatch_record_hashes_private_files_without_leaking_paths(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    recipient_path.write_text("first install kit recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent via private channel\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()

    prepared = check_dispatch_record(
        output_dir=tmp_path,
        skip_verify=True,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    json_path = Path(prepared["dispatch_record_json"])
    md_path = Path(prepared["dispatch_record_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False) + md_path.read_text(encoding="utf-8")

    assert payload["dispatch_record"]["recipient_private_sha256"] == expected_recipient_hash
    assert payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == expected_note_hash
    assert str(recipient_path) not in serialized
    assert str(note_path) not in serialized
    assert "recipient.txt" not in serialized
    assert "operator-note.txt" not in serialized
    assert "first install kit recipient private identifier" not in serialized
    assert "sent via private channel" not in serialized


def test_install_kit_dispatch_record_rejects_partial_sent_record(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    with pytest.raises(InstallKitDispatchRecordError, match="recipient/note/sent_at"):
        check_dispatch_record(
            output_dir=tmp_path,
            skip_verify=True,
            recipient_private_sha256="a" * 64,
        )


def test_install_kit_dispatch_record_verifier_rejects_tampering(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    prepared = check_dispatch_record(output_dir=tmp_path, skip_verify=True)
    json_path = Path(prepared["dispatch_record_json"])
    tampered_path = tmp_path / "tampered-dispatch-record.json"
    tampered = json.loads(json_path.read_text(encoding="utf-8"))
    tampered["dispatch_scope"]["cohort_scaling_allowed"] = True
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitDispatchRecordError, match="본문 해시"):
        verify_dispatch_record_file(tampered_path)


def test_install_kit_recipient_checkpoint_outputs_waiting_state(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    prepared = check_recipient_checkpoint(output_dir=tmp_path, skip_verify=True)
    json_path = Path(prepared["recipient_checkpoint_json"])
    md_path = Path(prepared["recipient_checkpoint_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert prepared["status"] == "awaiting_recipient_install"
    assert prepared["verdict"] == "WAITING_FOR_RECIPIENT"
    assert json_path.name == RECIPIENT_CHECKPOINT_JSON_NAME
    assert md_path.name == RECIPIENT_CHECKPOINT_MD_NAME
    assert payload["schema_version"] == "cambrian_install_kit_recipient_checkpoint_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["recipient_checkpoint_body_sha256"] == _recipient_checkpoint_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["recipient_checkpoint_checks"].values())
    assert payload["dispatch_record"]["verdict"] == "READY_TO_SEND_ONE"
    assert payload["dispatch_record"]["sent_recorded"] is False
    assert payload["dispatch_record"]["mcp_operability_verified"] is True
    assert len(payload["dispatch_copy_paste_message_policy"]["copy_paste_message_sha256"]) == 64
    assert payload["dispatch_copy_paste_message_policy"]["bundle_installer_named"] is True
    assert payload["dispatch_copy_paste_message_policy"]["gold_path_runner_named"] is True
    assert payload["dispatch_copy_paste_message_policy"]["mcp_operability_receipt_named"] is True
    assert payload["dispatch_copy_paste_message_policy"]["local_validation_only"] is True
    assert payload["dispatch_copy_paste_message_policy"]["public_proof_claim_blocked"] is True
    assert payload["dispatch_copy_paste_message_policy"]["first_recipient_confirmation_requires_real_send"] is True
    assert payload["checks"]["dispatch_copy_paste_policy_hashed"] is True
    assert payload["checks"]["dispatch_copy_paste_policy_marks_local_validation_only"] is True
    assert payload["recipient_checkpoint_checks"]["dispatch_copy_paste_boundary_preserved"] is True
    assert payload["recipient_checkpoint"]["recipient_ack_private_sha256"] is None
    assert payload["recipient_checkpoint"]["install_share_receipt_sha256"] is None
    assert payload["recipient_checkpoint"]["gold_path_share_receipt_sha256"] is None
    assert payload["recipient_checkpoint"]["mcp_operability_receipt_sha256"] is None
    assert payload["recipient_checkpoint"]["raw_ack_included"] is False
    assert payload["recipient_checkpoint"]["raw_install_receipt_path_included"] is False
    assert payload["recipient_checkpoint"]["raw_gold_path_receipt_path_included"] is False
    assert payload["recipient_checkpoint"]["raw_mcp_operability_receipt_path_included"] is False
    assert payload["install_share_receipt"]["present"] is False
    assert payload["gold_path_share_receipt"]["present"] is False
    assert payload["mcp_operability_receipt"]["present"] is False
    assert payload["blocking_summary"]["missing_evidence"] == ["SENT_ONE_RECORDED dispatch record"]
    assert payload["blocking_summary"]["required_returned_receipts"] == [
        "cambrian_install_share_receipt.json",
        "cambrian_gold_path_share_receipt.json",
        "mcp_operability_receipt.json",
    ]
    assert payload["blocking_summary"]["ack_file"] == "recipient-ack-private.txt"
    assert payload["blocking_summary"]["proof_closed"] is False
    assert "Do not claim recipient proof before the real manual send is recorded." in payload[
        "blocking_summary"
    ]["human_next_steps"]
    assert "Run the first-recipient pre-send sequence until READY_TO_MANUALLY_SEND_ONE." in payload[
        "blocking_summary"
    ]["human_next_steps"]
    assert payload["operator_next_action"].startswith("Do not claim recipient proof yet.")
    assert payload["metrics"]["recipient_install_confirmed"] is False
    assert payload["metrics"]["recipient_gold_path_confirmed"] is False
    assert payload["metrics"]["recipient_mcp_operability_confirmed"] is False
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False

    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    assert {
        "install_kit_zip",
        "install_kit_receipt",
        "install_kit_handoff",
        "install_kit_send_ready",
        "install_kit_dispatch_record",
        "install_kit_recipient_checkpoint",
    }.issubset(set(chain_by_kind))
    assert chain_by_kind["install_kit_recipient_checkpoint"]["file"] == RECIPIENT_CHECKPOINT_JSON_NAME
    assert chain_by_kind["install_kit_recipient_checkpoint"]["sha256"] == payload["recipient_checkpoint_body_sha256"]
    assert verify_recipient_checkpoint_file(json_path)["recipient_checkpoint_body_sha256"] == payload["recipient_checkpoint_body_sha256"]

    assert "Cambrian Install Kit Recipient Checkpoint" in markdown
    assert "WAITING_FOR_RECIPIENT" in markdown
    assert "recipient install confirmed: False" in markdown
    assert "recipient MCP operability confirmed: False" in markdown
    assert "MCP operability verified before send: True" in markdown
    assert "Dispatch Copy-Paste Boundary" in markdown
    assert "local validation only: True" in markdown
    assert "first-recipient confirmation requires real send: True" in markdown
    assert "Missing Evidence" in markdown
    assert "SENT_ONE_RECORDED dispatch record" in markdown
    assert "Human Next Steps" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized


def test_install_kit_recipient_checkpoint_body_hash_is_stable_across_regeneration(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)

    first = check_recipient_checkpoint(output_dir=tmp_path, skip_verify=True)
    second = check_recipient_checkpoint(output_dir=tmp_path, skip_verify=True)
    payload = verify_recipient_checkpoint_file(Path(second["recipient_checkpoint_json"]))

    assert first["recipient_checkpoint_body_sha256"] == second["recipient_checkpoint_body_sha256"]
    assert payload["recipient_checkpoint_checks"]["body_hash_matched"] is True


def test_install_kit_recipient_checkpoint_confirms_install_with_share_receipt(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    prepared = check_recipient_checkpoint(
        output_dir=tmp_path,
        skip_verify=True,
        install_share_receipt=install_receipt,
        recipient_private_file=ready["recipient_path"],
        operator_dispatch_note_private_file=ready["note_path"],
        operator_status_receipt=ready["operator_status_receipt"],
        require_operator_status_receipt=True,
        recipient_ack_private_sha256="c" * 64,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    payload = json.loads(Path(prepared["recipient_checkpoint_json"]).read_text(encoding="utf-8"))

    assert prepared["status"] == "recipient_install_confirmed"
    assert prepared["verdict"] == "RECIPIENT_INSTALL_CONFIRMED"
    assert payload["dispatch_record"]["verdict"] == "SENT_ONE_RECORDED"
    assert payload["dispatch_record"]["sent_recorded"] is True
    assert payload["operator_status_pre_send"]["required"] is True
    assert payload["operator_status_pre_send"]["ready_to_send_one"] is True
    assert payload["recipient_checkpoint"]["recipient_ack_private_sha256"] == "c" * 64
    assert payload["recipient_checkpoint"]["install_share_receipt_sha256"] == hashlib.sha256(install_receipt.read_bytes()).hexdigest()
    assert payload["install_share_receipt"]["present"] is True
    assert payload["install_share_receipt"]["safe_to_share"] is True
    assert payload["install_share_receipt"]["checks_all_true"] is True
    assert payload["install_share_receipt"]["cambrian_help_passed"] is True
    assert payload["install_share_receipt"]["cambrian_doctor_json_passed"] is True
    assert payload["install_share_receipt"]["cambrian_company_snapshot_help_passed"] is True
    assert payload["blocking_summary"]["missing_evidence"] == [
        "mcp_operability_receipt.json",
        "cambrian_gold_path_share_receipt.json",
    ]
    assert "Gold path confirmation requires the returned installed-entrypoint MCP operability receipt." in payload[
        "blocking_summary"
    ]["human_next_steps"]
    assert payload["blocking_summary"]["proof_closed"] is False
    assert payload["metrics"]["recipient_ack_recorded"] is True
    assert payload["metrics"]["recipient_install_confirmed"] is True
    assert all(payload["checks"].values())
    assert all(payload["recipient_checkpoint_checks"].values())


@pytest.mark.parametrize(
    ("receipt_kwarg", "filename", "expected_message"),
    [
        (
            "install_share_receipt",
            "cambrian_install_share_receipt.json",
            "install share receipt file is missing or still a placeholder",
        ),
        (
            "gold_path_share_receipt",
            "cambrian_gold_path_share_receipt.json",
            "gold path share receipt file is missing or still a placeholder",
        ),
        (
            "mcp_operability_receipt",
            "mcp_operability_receipt.json",
            "MCP operability receipt file is missing or still a placeholder",
        ),
    ],
)
def test_install_kit_recipient_checkpoint_blocks_missing_returned_receipts(
    tmp_path: Path,
    receipt_kwarg: str,
    filename: str,
    expected_message: str,
) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    missing_receipt = tmp_path / filename

    with pytest.raises(InstallKitRecipientCheckpointError, match=expected_message):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            **{receipt_kwarg: missing_receipt},
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            operator_status_receipt=ready["operator_status_receipt"],
            require_operator_status_receipt=True,
            recipient_ack_private_sha256="c" * 64,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )

    assert not (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).exists()
    assert not (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).exists()


def test_install_kit_recipient_checkpoint_cli_rejects_placeholder_returned_receipt_safely(
    tmp_path: Path,
) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    placeholder = "<cambrian_install_share_receipt.json>"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_cambrian_install_kit_recipient_checkpoint.py"),
            "--output-dir",
            str(tmp_path),
            "--skip-verify",
            "--install-share-receipt",
            placeholder,
            "--recipient-private-file",
            str(ready["recipient_path"]),
            "--operator-dispatch-note-private-file",
            str(ready["note_path"]),
            "--operator-status-receipt",
            str(ready["operator_status_receipt"]),
            "--require-operator-status-receipt",
            "--recipient-ack-private-sha256",
            "c" * 64,
            "--sent-at-utc",
            "2026-05-15T10:00:00+00:00",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "install share receipt file is missing or still a placeholder." in output
    assert placeholder not in output
    assert str(ROOT) not in output
    assert str(tmp_path) not in output
    assert "real-recipient@example.com" not in output
    assert "private channel: email" not in output
    assert not (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).exists()
    assert not (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).exists()


def test_install_kit_recipient_checkpoint_requires_operator_status_for_post_send_evidence(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")

    with pytest.raises(InstallKitRecipientCheckpointError, match="operator status receipt is required"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            install_share_receipt=install_receipt,
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            recipient_ack_private_sha256="c" * 64,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_rejects_stale_current_artifacts_after_ready_receipt(
    tmp_path: Path,
) -> None:
    _, bundle_sha = _write_current_artifact_release_bundle_fixture(tmp_path)
    workspace = tmp_path / "private-workspace"
    prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=tmp_path)
    recipient_path = workspace / "recipient-private.txt"
    note_path = workspace / "operator-dispatch-note-private.md"
    recipient_path.write_text("real-recipient@example.com\n", encoding="utf-8")
    note_path.write_text(f"private channel: email\nrelease bundle sha256: {bundle_sha}\n", encoding="utf-8")
    status = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")

    assert status["verdict"] == "READY_TO_MANUALLY_SEND_ONE"

    (tmp_path / "cambrian-install-kit-send-ready.md").write_text("stale send ready", encoding="utf-8")

    with pytest.raises(InstallKitRecipientCheckpointError, match="current artifacts"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            install_share_receipt=install_receipt,
            recipient_private_file=recipient_path,
            operator_dispatch_note_private_file=note_path,
            operator_status_receipt=Path(str(status["ready_receipt_json"])),
            require_operator_status_receipt=True,
            recipient_ack_private_sha256="c" * 64,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_confirms_gold_path_with_share_receipts(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    gold_path_receipt = _write_gold_path_share_receipt_fixture(tmp_path / "cambrian_gold_path_share_receipt.json")
    mcp_receipt = _write_mcp_operability_receipt_fixture(tmp_path / "mcp_operability_receipt.json")
    prepared = check_recipient_checkpoint(
        output_dir=tmp_path,
        skip_verify=True,
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
        mcp_operability_receipt=mcp_receipt,
        recipient_private_file=ready["recipient_path"],
        operator_dispatch_note_private_file=ready["note_path"],
        operator_status_receipt=ready["operator_status_receipt"],
        require_operator_status_receipt=True,
        recipient_ack_private_sha256="c" * 64,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    json_path = Path(prepared["recipient_checkpoint_json"])
    md_path = Path(prepared["recipient_checkpoint_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert prepared["status"] == "recipient_gold_path_confirmed"
    assert prepared["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["operator_status_pre_send"]["required"] is True
    assert payload["operator_status_pre_send"]["ready_to_send_one"] is True
    assert payload["operator_status_pre_send"]["release_hash_matches_dispatch"] is True
    assert payload["operator_status_pre_send"]["release_current_artifacts_gate_passed"] is True
    assert payload["operator_status_pre_send"]["private_hashes_match_dispatch"] is True
    assert payload["recipient_checkpoint"]["install_share_receipt_sha256"] == hashlib.sha256(install_receipt.read_bytes()).hexdigest()
    assert payload["recipient_checkpoint"]["gold_path_share_receipt_sha256"] == hashlib.sha256(gold_path_receipt.read_bytes()).hexdigest()
    assert payload["recipient_checkpoint"]["mcp_operability_receipt_sha256"] == hashlib.sha256(mcp_receipt.read_bytes()).hexdigest()
    assert payload["recipient_checkpoint"]["raw_gold_path_receipt_path_included"] is False
    assert payload["recipient_checkpoint"]["raw_mcp_operability_receipt_path_included"] is False
    assert payload["install_share_receipt"]["checks_all_true"] is True
    assert payload["gold_path_share_receipt"]["present"] is True
    assert payload["gold_path_share_receipt"]["status"] == "passed"
    assert payload["gold_path_share_receipt"]["safe_to_share"] is True
    assert payload["gold_path_share_receipt"]["checks_all_true"] is True
    assert payload["gold_path_share_receipt"]["capabilities_all_true"] is True
    assert all(payload["gold_path_share_receipt"]["capabilities_verified"].values())
    assert payload["mcp_operability_receipt"]["present"] is True
    assert payload["mcp_operability_receipt"]["verdict"] == "GO"
    assert payload["mcp_operability_receipt"]["checks_all_true"] is True
    assert payload["mcp_operability_receipt"]["installed_wheel_mode"] is True
    assert payload["mcp_operability_receipt"]["server_command_mode"] == "installed_entrypoint"
    assert payload["mcp_operability_receipt"]["installed_entrypoint_command"] is True
    assert payload["mcp_operability_receipt"]["no_arbitrary_shell"] is True
    assert payload["mcp_operability_receipt"]["explicit_cwd_required"] is True
    assert payload["gold_path_share_receipt"]["proof_claim_allowed"] is False
    assert payload["gold_path_share_receipt"]["sale_ready"] is False
    assert payload["metrics"]["recipient_install_confirmed"] is True
    assert payload["metrics"]["recipient_gold_path_confirmed"] is True
    assert payload["metrics"]["recipient_mcp_operability_confirmed"] is True
    assert payload["blocking_summary"]["missing_evidence"] == []
    assert payload["blocking_summary"]["proof_closed"] is True
    assert "Collect controlled feedback before sending to another recipient." in payload["blocking_summary"][
        "human_next_steps"
    ]
    assert payload["operator_next_action"].startswith("Recipient gold path proof is closed.")
    assert all(payload["metrics"]["gold_path_capabilities_verified"].values())
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert all(payload["checks"].values())
    assert all(payload["recipient_checkpoint_checks"].values())
    assert verify_recipient_checkpoint_file(json_path)["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert "RECIPIENT_GOLD_PATH_CONFIRMED" in markdown
    assert "recipient gold path confirmed: True" in markdown
    assert "recipient MCP operability confirmed: True" in markdown
    assert "gold path capabilities all true: True" in markdown
    assert "returned MCP receipt no arbitrary shell: True" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(install_receipt) not in serialized
    assert str(gold_path_receipt) not in serialized
    assert str(mcp_receipt) not in serialized


def test_install_kit_recipient_checkpoint_rejects_gold_path_without_install_receipt(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    gold_path_receipt = _write_gold_path_share_receipt_fixture(tmp_path / "cambrian_gold_path_share_receipt.json")

    with pytest.raises(InstallKitRecipientCheckpointError, match="install share receipt"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            gold_path_share_receipt=gold_path_receipt,
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            operator_status_receipt=ready["operator_status_receipt"],
            require_operator_status_receipt=True,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_rejects_gold_path_without_mcp_receipt(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    gold_path_receipt = _write_gold_path_share_receipt_fixture(tmp_path / "cambrian_gold_path_share_receipt.json")

    with pytest.raises(InstallKitRecipientCheckpointError, match="MCP operability receipt"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            install_share_receipt=install_receipt,
            gold_path_share_receipt=gold_path_receipt,
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            operator_status_receipt=ready["operator_status_receipt"],
            require_operator_status_receipt=True,
            recipient_ack_private_sha256="c" * 64,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_rejects_mcp_receipt_without_install_receipt(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    mcp_receipt = _write_mcp_operability_receipt_fixture(tmp_path / "mcp_operability_receipt.json")

    with pytest.raises(InstallKitRecipientCheckpointError, match="install share receipt"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            mcp_operability_receipt=mcp_receipt,
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            operator_status_receipt=ready["operator_status_receipt"],
            require_operator_status_receipt=True,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_rejects_weak_mcp_receipt(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    mcp_receipt = _write_mcp_operability_receipt_fixture(
        tmp_path / "mcp_operability_receipt.json",
        no_arbitrary_shell=False,
    )

    with pytest.raises(InstallKitRecipientCheckpointError, match="MCP operability receipt"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            install_share_receipt=install_receipt,
            mcp_operability_receipt=mcp_receipt,
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            operator_status_receipt=ready["operator_status_receipt"],
            require_operator_status_receipt=True,
            recipient_ack_private_sha256="c" * 64,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_rejects_source_module_mcp_receipt(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    mcp_receipt = _write_mcp_operability_receipt_fixture(
        tmp_path / "mcp_operability_receipt.json",
        server_command_mode="source_module",
        installed_entrypoint_command=False,
    )

    with pytest.raises(InstallKitRecipientCheckpointError, match="MCP operability receipt"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            install_share_receipt=install_receipt,
            mcp_operability_receipt=mcp_receipt,
            recipient_private_file=ready["recipient_path"],
            operator_dispatch_note_private_file=ready["note_path"],
            operator_status_receipt=ready["operator_status_receipt"],
            require_operator_status_receipt=True,
            recipient_ack_private_sha256="c" * 64,
            sent_at_utc="2026-05-15T10:00:00+00:00",
        )


def test_install_kit_recipient_checkpoint_accepts_windows_bom_receipts(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    gold_path_receipt = _write_gold_path_share_receipt_fixture(tmp_path / "cambrian_gold_path_share_receipt.json")
    mcp_receipt = _write_mcp_operability_receipt_fixture(tmp_path / "mcp_operability_receipt.json")
    install_receipt.write_text(install_receipt.read_text(encoding="utf-8"), encoding="utf-8-sig")
    gold_path_receipt.write_text(gold_path_receipt.read_text(encoding="utf-8"), encoding="utf-8-sig")
    mcp_receipt.write_text(mcp_receipt.read_text(encoding="utf-8"), encoding="utf-8-sig")

    prepared = check_recipient_checkpoint(
        output_dir=tmp_path,
        skip_verify=True,
        install_share_receipt=install_receipt,
        gold_path_share_receipt=gold_path_receipt,
        mcp_operability_receipt=mcp_receipt,
        recipient_private_file=ready["recipient_path"],
        operator_dispatch_note_private_file=ready["note_path"],
        operator_status_receipt=ready["operator_status_receipt"],
        require_operator_status_receipt=True,
        recipient_ack_private_sha256="c" * 64,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )

    assert prepared["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"


def test_install_kit_recipient_checkpoint_rejects_receipt_before_sent_dispatch(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")

    with pytest.raises(InstallKitRecipientCheckpointError, match="SENT_ONE_RECORDED"):
        check_recipient_checkpoint(
            output_dir=tmp_path,
            skip_verify=True,
            install_share_receipt=install_receipt,
        )


def test_install_kit_recipient_checkpoint_hashes_private_ack_without_leaking_paths(tmp_path: Path) -> None:
    ready = _prepare_ready_install_kit_operator_status_fixture(tmp_path)
    install_receipt = _write_install_share_receipt_fixture(tmp_path / "cambrian_install_share_receipt.json")
    private_dir = ready["workspace"]
    recipient_path = ready["recipient_path"]
    note_path = ready["note_path"]
    ack_path = Path(private_dir) / "recipient-ack.txt"
    ack_path.write_text("installed and ran cambrian doctor privately\n", encoding="utf-8")
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()

    prepared = check_recipient_checkpoint(
        output_dir=tmp_path,
        skip_verify=True,
        install_share_receipt=install_receipt,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        operator_status_receipt=ready["operator_status_receipt"],
        require_operator_status_receipt=True,
        recipient_ack_private_file=ack_path,
        sent_at_utc="2026-05-15T10:00:00+00:00",
    )
    json_path = Path(prepared["recipient_checkpoint_json"])
    md_path = Path(prepared["recipient_checkpoint_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False) + md_path.read_text(encoding="utf-8")

    assert payload["recipient_checkpoint"]["recipient_ack_private_sha256"] == expected_ack_hash
    assert payload["recipient_checkpoint"]["raw_ack_included"] is False
    assert payload["recipient_checkpoint"]["raw_install_receipt_path_included"] is False
    for private_path in [recipient_path, note_path, ack_path, install_receipt]:
        assert str(private_path) not in serialized
    for private_path in [recipient_path, note_path, ack_path]:
        assert private_path.name not in serialized
    for raw_text in [
        "real-recipient@example.com",
        "private channel: email",
        "installed and ran cambrian doctor privately",
    ]:
        assert raw_text not in serialized


def test_install_kit_recipient_checkpoint_verifier_rejects_tampering(tmp_path: Path) -> None:
    _write_install_kit_verification_receipt_fixture(tmp_path)
    prepared = check_recipient_checkpoint(output_dir=tmp_path, skip_verify=True)
    json_path = Path(prepared["recipient_checkpoint_json"])
    tampered_path = tmp_path / "tampered-recipient-checkpoint.json"
    tampered = json.loads(json_path.read_text(encoding="utf-8"))
    tampered["metrics"]["sale_ready"] = True
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(InstallKitRecipientCheckpointError, match="recipient-checkpoint"):
        verify_recipient_checkpoint_file(tampered_path)
