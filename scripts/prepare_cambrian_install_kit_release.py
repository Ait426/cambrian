from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_cambrian_install_kit import build_install_kit  # noqa: E402
from scripts.check_cambrian_install_kit_send_ready import (  # noqa: E402
    SEND_READY_JSON_NAME,
    check_send_ready,
    verify_send_ready_file,
)
from scripts.prepare_cambrian_install_kit_handoff import (  # noqa: E402
    HANDOFF_JSON_NAME,
    verify_handoff_file,
)
from scripts.verify_cambrian_install_kit import (  # noqa: E402
    verify_shareable_receipt_file,
)


RELEASE_RECEIPT_SCHEMA_VERSION = "cambrian_install_kit_release_receipt_v0_1"
RELEASE_RECEIPT_NAME = "cambrian-install-kit-release-receipt.json"
INSTALL_KIT_RECEIPT_NAME = "cambrian-install-kit-verification-receipt.json"
START_HERE_NAME = "START_HERE_CAMBRIAN_INSTALL_KIT.md"
RELEASE_BUNDLE_NAME = "cambrian-install-kit-release-bundle.zip"
RELEASE_BUNDLE_MANIFEST_NAME = "cambrian-install-kit-release-bundle-manifest.json"
BUNDLE_VERIFIER_NAME = "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py"
BUNDLE_INSTALLER_NAME = "INSTALL_CAMBRIAN_FROM_BUNDLE.py"
BUNDLE_GOLD_PATH_NAME = "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py"
BUNDLE_AGENT_PROMPT_NAME = "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md"
BUNDLE_INSTALLER_BAT_NAME = "INSTALL_CAMBRIAN_FROM_BUNDLE.bat"
BUNDLE_INSTALLER_SH_NAME = "install_cambrian_from_bundle.sh"
MCP_CONNECT_GUIDE_NAME = "MCP_EXTERNAL_CLIENT_CONNECT.md"


def prepare_release(
    output_dir: Path | None = None,
    include_dependency_wheels: bool = True,
    skip_build: bool = False,
) -> dict[str, Any]:
    """Install kit build부터 send-ready GO까지 한 번에 준비한다."""
    dist = (output_dir or ROOT / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)
    build_result = (
        _existing_build_result(dist)
        if skip_build
        else build_install_kit(output_dir=dist, include_dependency_wheels=include_dependency_wheels)
    )
    send_ready_result = check_send_ready(output_dir=dist, skip_verify=False)
    receipt_path = dist / INSTALL_KIT_RECEIPT_NAME
    handoff_path = dist / HANDOFF_JSON_NAME
    send_ready_path = dist / SEND_READY_JSON_NAME
    receipt = verify_shareable_receipt_file(receipt_path)
    handoff = verify_handoff_file(handoff_path)
    send_ready = verify_send_ready_file(send_ready_path)
    start_here_path = dist / START_HERE_NAME
    start_here_path.write_text(_start_here_markdown(send_ready), encoding="utf-8")
    bundle_verifier_path = dist / BUNDLE_VERIFIER_NAME
    bundle_verifier_path.write_text(_standalone_bundle_verifier_text(), encoding="utf-8")
    bundle_installer_path = dist / BUNDLE_INSTALLER_NAME
    bundle_installer_path.write_text(_standalone_bundle_installer_text(), encoding="utf-8")
    bundle_gold_path_path = dist / BUNDLE_GOLD_PATH_NAME
    bundle_gold_path_path.write_text(_standalone_bundle_gold_path_text(), encoding="utf-8")
    bundle_agent_prompt_path = dist / BUNDLE_AGENT_PROMPT_NAME
    bundle_agent_prompt_path.write_text(_bundle_agent_prompt_markdown(send_ready), encoding="utf-8")
    mcp_connect_guide_source = ROOT / "docs" / "release" / MCP_CONNECT_GUIDE_NAME
    mcp_connect_guide_path = dist / MCP_CONNECT_GUIDE_NAME
    mcp_connect_guide_path.write_text(mcp_connect_guide_source.read_text(encoding="utf-8"), encoding="utf-8")
    bundle_installer_bat_path = dist / BUNDLE_INSTALLER_BAT_NAME
    bundle_installer_bat_path.write_text(_bundle_installer_bat_text(), encoding="utf-8")
    bundle_installer_sh_path = dist / BUNDLE_INSTALLER_SH_NAME
    bundle_installer_sh_path.write_text(_bundle_installer_sh_text(), encoding="utf-8")
    payload = _release_receipt(build_result, receipt, handoff, send_ready)
    release_receipt_path = dist / RELEASE_RECEIPT_NAME
    release_receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bundle_path = _write_release_bundle(
        dist=dist,
        install_kit_zip=Path(str(build_result.get("zip_file") or "")),
        release_receipt_path=release_receipt_path,
        start_here_path=start_here_path,
        bundle_verifier_path=bundle_verifier_path,
        bundle_installer_path=bundle_installer_path,
        bundle_gold_path_path=bundle_gold_path_path,
        bundle_agent_prompt_path=bundle_agent_prompt_path,
        mcp_connect_guide_path=mcp_connect_guide_path,
        bundle_installer_bat_path=bundle_installer_bat_path,
        bundle_installer_sh_path=bundle_installer_sh_path,
    )
    return {
        "schema_version": RELEASE_RECEIPT_SCHEMA_VERSION,
        "status": "prepared",
        "verdict": send_ready.get("verdict"),
        "zip_file": build_result.get("zip_file"),
        "zip_sha256": build_result.get("zip_sha256"),
        "verification_receipt": str(receipt_path),
        "handoff_json": str(handoff_path),
        "send_ready_json": str(send_ready_path),
        "start_here": str(start_here_path),
        "bundle_verifier": str(bundle_verifier_path),
        "bundle_installer": str(bundle_installer_path),
        "bundle_gold_path": str(bundle_gold_path_path),
        "bundle_agent_prompt": str(bundle_agent_prompt_path),
        "mcp_connect_guide": str(mcp_connect_guide_path),
        "bundle_installer_bat": str(bundle_installer_bat_path),
        "bundle_installer_sh": str(bundle_installer_sh_path),
        "release_receipt": str(release_receipt_path),
        "release_bundle": str(bundle_path),
        "release_bundle_sha256": _sha256(bundle_path),
    }


def verify_release_receipt_file(path: Path) -> dict[str, Any]:
    """Install kit release receipt만 읽어 공유 안전성과 무결성을 검증한다."""
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("install kit release receipt JSON 객체가 아닙니다.")
    _verify_release_receipt(payload)
    return payload


def verify_release_bundle_file(path: Path) -> dict[str, Any]:
    """수령자 전달용 release bundle ZIP이 필요한 파일과 해시를 담는지 검증한다."""
    bundle_path = path.resolve()
    if not bundle_path.exists():
        raise FileNotFoundError(f"install kit release bundle을 찾을 수 없습니다: {bundle_path}")
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        if RELEASE_BUNDLE_MANIFEST_NAME not in names:
            raise ValueError("release bundle manifest가 없습니다.")
        manifest = json.loads(archive.read(RELEASE_BUNDLE_MANIFEST_NAME).decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("release bundle manifest JSON 객체가 아닙니다.")
        _verify_release_bundle_manifest(manifest, names)
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                raise ValueError("release bundle manifest file item이 객체가 아닙니다.")
            name = str(item.get("path") or "")
            if name == RELEASE_BUNDLE_MANIFEST_NAME:
                continue
            data = archive.read(name)
            import hashlib

            if hashlib.sha256(data).hexdigest() != item.get("sha256"):
                raise ValueError(f"release bundle file hash mismatch: {name}")
        bundle_items = {
            name: archive.read(name)
            for name in names
            if name != RELEASE_BUNDLE_MANIFEST_NAME
        }
        payload_checks = _release_bundle_payload_checks(bundle_items)
        failed_payload_checks = [name for name, passed in payload_checks.items() if passed is not True]
        if failed_payload_checks:
            raise ValueError("release bundle payload 검증 실패: " + ", ".join(failed_payload_checks))
        manifest["payload_checks"] = payload_checks
    return manifest


def verify_release_bundle_current_artifacts(path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Verify the sender-side bundle still matches the current prepared artifacts."""
    bundle_path = path.resolve()
    artifact_dir = (output_dir or bundle_path.parent).resolve()
    manifest = verify_release_bundle_file(bundle_path)
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    missing: list[str] = []
    mismatched: list[str] = []
    checked: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("path") or "")
        expected_sha = str(item.get("sha256") or "")
        if not name or name == RELEASE_BUNDLE_MANIFEST_NAME:
            continue
        current_path = artifact_dir / name
        if not current_path.exists():
            missing.append(name)
            continue
        checked.append(name)
        if _sha256(current_path) != expected_sha:
            mismatched.append(name)
    checks = {
        "artifact_dir_present": artifact_dir.exists(),
        "manifest_files_checked": bool(checked),
        "current_artifacts_present": not missing,
        "current_artifact_hashes_match_bundle": not mismatched,
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        details = []
        if missing:
            details.append("missing=" + ", ".join(missing))
        if mismatched:
            details.append("mismatched=" + ", ".join(mismatched))
        suffix = ": " + "; ".join(details) if details else ""
        raise ValueError("release bundle current artifact verification failed: " + ", ".join(failed) + suffix)
    manifest["current_artifact_checks"] = checks
    manifest["current_artifact_summary"] = {
        "artifact_dir_name": artifact_dir.name,
        "checked_count": len(checked),
    }
    return manifest


def _existing_build_result(dist: Path) -> dict[str, Any]:
    candidates = sorted(
        (
            path
            for path in dist.glob("cambrian-install-kit-*.zip")
            if path.name != RELEASE_BUNDLE_NAME
        ),
        key=lambda path: path.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"기존 install kit ZIP을 찾을 수 없습니다: {dist}")
    zip_path = candidates[-1].resolve()
    manifest: dict[str, Any] = {}
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open("CAMBRIAN_INSTALL_KIT_MANIFEST.json") as handle:
            manifest = json.loads(handle.read().decode("utf-8"))
    return {
        "schema_version": manifest.get("schema_version"),
        "status": "built",
        "version": manifest.get("package", {}).get("version"),
        "zip_file": str(zip_path),
        "zip_sha256": _sha256(zip_path),
        "dependency_mode": manifest.get("dependency_mode"),
    }


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_release_bundle(
    dist: Path,
    install_kit_zip: Path,
    release_receipt_path: Path,
    start_here_path: Path,
    bundle_verifier_path: Path,
    bundle_installer_path: Path,
    bundle_gold_path_path: Path,
    bundle_agent_prompt_path: Path,
    mcp_connect_guide_path: Path,
    bundle_installer_bat_path: Path,
    bundle_installer_sh_path: Path,
) -> Path:
    required = [
        start_here_path,
        bundle_verifier_path,
        bundle_installer_path,
        bundle_gold_path_path,
        bundle_agent_prompt_path,
        mcp_connect_guide_path,
        bundle_installer_bat_path,
        bundle_installer_sh_path,
        install_kit_zip,
        dist / INSTALL_KIT_RECEIPT_NAME,
        dist / HANDOFF_JSON_NAME,
        dist / "cambrian-install-kit-handoff.md",
        dist / SEND_READY_JSON_NAME,
        dist / "cambrian-install-kit-send-ready.md",
        release_receipt_path,
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("release bundle 필수 파일 누락: " + ", ".join(str(path) for path in missing))

    bundle_path = dist / RELEASE_BUNDLE_NAME
    if bundle_path.exists():
        bundle_path.unlink()
    manifest = _release_bundle_manifest(required)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in required:
            archive.write(path, path.name)
        archive.writestr(RELEASE_BUNDLE_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    verify_release_bundle_file(bundle_path)
    verify_release_bundle_current_artifacts(bundle_path, output_dir=dist)
    return bundle_path


def _release_bundle_manifest(paths: list[Path]) -> dict[str, Any]:
    return {
        "schema_version": "cambrian_install_kit_release_bundle_v0_1",
        "safe_to_share": True,
        "entrypoint": START_HERE_NAME,
        "dispatch_execution_policy": {
            "script_sends_to_recipient": False,
            "script_sends_copy_paste_message": False,
            "manual_operator_dispatch_required": True,
            "max_recipients_per_record": 1,
        },
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in paths
        ],
    }


def _verify_release_bundle_manifest(manifest: dict[str, Any], names: set[str]) -> None:
    install_kit_zip_names = {
        name
        for name in names
        if name.startswith("cambrian-install-kit-")
        and name.endswith(".zip")
        and name != RELEASE_BUNDLE_NAME
    }
    required = {
        START_HERE_NAME,
        BUNDLE_VERIFIER_NAME,
        BUNDLE_INSTALLER_NAME,
        BUNDLE_GOLD_PATH_NAME,
        BUNDLE_AGENT_PROMPT_NAME,
        MCP_CONNECT_GUIDE_NAME,
        BUNDLE_INSTALLER_BAT_NAME,
        BUNDLE_INSTALLER_SH_NAME,
        INSTALL_KIT_RECEIPT_NAME,
        HANDOFF_JSON_NAME,
        "cambrian-install-kit-handoff.md",
        SEND_READY_JSON_NAME,
        "cambrian-install-kit-send-ready.md",
        RELEASE_RECEIPT_NAME,
        RELEASE_BUNDLE_MANIFEST_NAME,
    }
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    listed = {str(item.get("path") or "") for item in files if isinstance(item, dict)}
    privacy = manifest.get("privacy") if isinstance(manifest.get("privacy"), dict) else {}
    policy = manifest.get("dispatch_execution_policy") if isinstance(manifest.get("dispatch_execution_policy"), dict) else {}
    checks = {
        "required_files_present": required.issubset(names),
        "manifest_files_listed": required.difference({RELEASE_BUNDLE_MANIFEST_NAME}).issubset(listed),
        "single_install_kit_zip_present": len(install_kit_zip_names) == 1,
        "install_kit_zip_listed": bool(install_kit_zip_names) and install_kit_zip_names.issubset(listed),
        "entrypoint_start_here": manifest.get("entrypoint") == START_HERE_NAME,
        "safe_to_share_true": manifest.get("safe_to_share") is True,
        "absolute_paths_omitted": privacy.get("absolute_paths_included") is False,
        "raw_private_project_data_omitted": privacy.get("raw_private_project_data_included") is False,
        "secrets_omitted": privacy.get("secrets_included") is False,
        "manual_dispatch_required": policy.get("script_sends_to_recipient") is False
        and policy.get("script_sends_copy_paste_message") is False
        and policy.get("manual_operator_dispatch_required") is True,
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise ValueError("release bundle manifest 검증 실패: " + ", ".join(failed))


def _release_bundle_payload_checks(bundle_items: dict[str, bytes]) -> dict[str, bool]:
    import hashlib

    release_receipt = _json_from_bundle_item(bundle_items, RELEASE_RECEIPT_NAME)
    verification_receipt = _json_from_bundle_item(bundle_items, INSTALL_KIT_RECEIPT_NAME)
    handoff = _json_from_bundle_item(bundle_items, HANDOFF_JSON_NAME)
    send_ready = _json_from_bundle_item(bundle_items, SEND_READY_JSON_NAME)
    start_here = bundle_items.get(START_HERE_NAME, b"").decode("utf-8", errors="replace")
    bundle_agent_prompt = bundle_items.get(BUNDLE_AGENT_PROMPT_NAME, b"").decode("utf-8", errors="replace")
    mcp_connect_guide = bundle_items.get(MCP_CONNECT_GUIDE_NAME, b"").decode("utf-8", errors="replace")
    handoff_copy_paste_message = str(handoff.get("copy_paste_message") or "")
    handoff_checks = handoff.get("handoff_checks") if isinstance(handoff.get("handoff_checks"), dict) else {}
    send_ready_copy_paste_message = str(send_ready.get("copy_paste_message") or "")
    send_ready_checks = send_ready.get("checks") if isinstance(send_ready.get("checks"), dict) else {}
    install_kit = release_receipt.get("install_kit") if isinstance(release_receipt.get("install_kit"), dict) else {}
    artifacts = release_receipt.get("artifacts") if isinstance(release_receipt.get("artifacts"), dict) else {}
    artifact_hashes = (
        release_receipt.get("artifact_hashes")
        if isinstance(release_receipt.get("artifact_hashes"), dict)
        else {}
    )
    install_kit_zip_name = str(install_kit.get("zip_file") or "")
    install_kit_zip_bytes = bundle_items.get(install_kit_zip_name, b"")
    inner_manifest = _install_kit_manifest_from_zip_bytes(install_kit_zip_bytes)
    try:
        _verify_release_receipt(release_receipt)
        release_receipt_verified = True
    except ValueError:
        release_receipt_verified = False
    return {
        "release_receipt_verified": release_receipt_verified,
        "start_here_present": START_HERE_NAME in bundle_items,
        "standalone_verifier_present": BUNDLE_VERIFIER_NAME in bundle_items,
        "standalone_installer_present": BUNDLE_INSTALLER_NAME in bundle_items,
        "gold_path_runner_present": BUNDLE_GOLD_PATH_NAME in bundle_items,
        "bundle_agent_prompt_present": BUNDLE_AGENT_PROMPT_NAME in bundle_items,
        "mcp_connect_guide_present": MCP_CONNECT_GUIDE_NAME in bundle_items,
        "windows_installer_wrapper_present": BUNDLE_INSTALLER_BAT_NAME in bundle_items,
        "shell_installer_wrapper_present": BUNDLE_INSTALLER_SH_NAME in bundle_items,
        "start_here_mentions_standalone_verifier": BUNDLE_VERIFIER_NAME in start_here,
        "start_here_mentions_standalone_installer": BUNDLE_INSTALLER_NAME in start_here,
        "start_here_mentions_gold_path_runner": BUNDLE_GOLD_PATH_NAME in start_here,
        "start_here_mentions_bundle_agent_prompt": BUNDLE_AGENT_PROMPT_NAME in start_here,
        "bundle_agent_prompt_mentions_standalone_verifier": BUNDLE_VERIFIER_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_standalone_installer": BUNDLE_INSTALLER_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_gold_path_runner": BUNDLE_GOLD_PATH_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_mcp_verify": "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_mcp_guide": MCP_CONNECT_GUIDE_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_marks_gold_path_required": "Required AI Company Gold Path" in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_share_receipts": "cambrian_install_share_receipt.json" in bundle_agent_prompt
        and "cambrian_gold_path_share_receipt.json" in bundle_agent_prompt,
        "bundle_agent_prompt_marks_receipts_local_validation_only": "local validation evidence only" in bundle_agent_prompt,
        "bundle_agent_prompt_blocks_public_proof_claims": "Do not claim public proof" in bundle_agent_prompt,
        "bundle_agent_prompt_blocks_first_recipient_claims": "First-recipient confirmation requires a real human send" in bundle_agent_prompt,
        "start_here_marks_gold_path_required": "Required AI Company Gold Path" in start_here,
        "start_here_does_not_mark_gold_path_optional": "Optional AI Company Gold Path" not in start_here,
        "start_here_mentions_install_kit_zip": bool(install_kit_zip_name) and install_kit_zip_name in start_here,
        "start_here_mentions_install_receipt": "cambrian_install_receipt.json" in start_here,
        "start_here_mentions_share_receipt": "cambrian_install_share_receipt.json" in start_here,
        "start_here_mentions_gold_path_share_receipt": "cambrian_gold_path_share_receipt.json" in start_here,
        "start_here_marks_receipts_local_validation_only": "share-safe local validation evidence only" in start_here,
        "start_here_blocks_public_proof_claims": "not a public proof claim" in start_here,
        "start_here_blocks_first_recipient_claims": "First-recipient confirmation exists only after a real human send" in start_here,
        "handoff_copy_paste_marks_receipts_local_validation_only": "local validation evidence only" in handoff_copy_paste_message,
        "handoff_copy_paste_blocks_public_proof_claims": "do not claim public proof" in handoff_copy_paste_message,
        "handoff_copy_paste_blocks_first_recipient_claims": "First-recipient confirmation requires a real human send" in handoff_copy_paste_message,
        "handoff_checks_require_claim_boundary": handoff_checks.get("claim_boundary_present") is True,
        "send_ready_copy_paste_marks_receipts_local_validation_only": "local validation evidence only" in send_ready_copy_paste_message,
        "send_ready_copy_paste_blocks_public_proof_claims": "do not claim public proof" in send_ready_copy_paste_message,
        "send_ready_copy_paste_blocks_first_recipient_claims": "First-recipient confirmation requires a real human send" in send_ready_copy_paste_message,
        "send_ready_checks_require_claim_boundary": send_ready_checks.get("copy_paste_message_marks_local_validation_only") is True
        and send_ready_checks.get("copy_paste_message_blocks_public_proof_claims") is True
        and send_ready_checks.get("copy_paste_message_blocks_first_recipient_claims") is True,
        "start_here_mentions_mcp_guide": MCP_CONNECT_GUIDE_NAME in start_here,
        "start_here_mentions_mcp_verify": "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in start_here,
        "mcp_connect_guide_mentions_cambrian_mcp": "cambrian-mcp" in mcp_connect_guide,
        "mcp_connect_guide_mentions_mcp_verify": "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in mcp_connect_guide,
        "mcp_connect_guide_mentions_explicit_cwd": "explicit `cwd`" in mcp_connect_guide,
        "mcp_connect_guide_mentions_no_arbitrary_shell": "arbitrary shell" in mcp_connect_guide,
        "start_here_mentions_company_snapshot_help": "cambrian company snapshot --help" in start_here,
        "install_kit_zip_hash_matched": bool(install_kit_zip_bytes)
        and hashlib.sha256(install_kit_zip_bytes).hexdigest() == install_kit.get("zip_sha256"),
        "verification_receipt_hash_matched": verification_receipt.get("receipt_body_sha256")
        == artifact_hashes.get("verification_receipt_body_sha256"),
        "handoff_hash_matched": handoff.get("handoff_body_sha256") == artifact_hashes.get("handoff_body_sha256"),
        "send_ready_hash_matched": send_ready.get("send_ready_body_sha256")
        == artifact_hashes.get("send_ready_body_sha256"),
        "artifacts_name_start_here_matched": artifacts.get("start_here") == START_HERE_NAME,
        "artifacts_name_bundle_verifier_matched": artifacts.get("bundle_verifier") == BUNDLE_VERIFIER_NAME,
        "artifacts_name_bundle_installer_matched": artifacts.get("bundle_installer") == BUNDLE_INSTALLER_NAME,
        "artifacts_name_bundle_gold_path_matched": artifacts.get("bundle_gold_path") == BUNDLE_GOLD_PATH_NAME,
        "artifacts_name_bundle_agent_prompt_matched": artifacts.get("bundle_agent_prompt") == BUNDLE_AGENT_PROMPT_NAME,
        "artifacts_name_mcp_connect_guide_matched": artifacts.get("mcp_connect_guide") == MCP_CONNECT_GUIDE_NAME,
        "artifacts_name_bundle_installer_bat_matched": artifacts.get("bundle_installer_bat") == BUNDLE_INSTALLER_BAT_NAME,
        "artifacts_name_bundle_installer_sh_matched": artifacts.get("bundle_installer_sh") == BUNDLE_INSTALLER_SH_NAME,
        "artifacts_name_verification_receipt_matched": artifacts.get("verification_receipt") == INSTALL_KIT_RECEIPT_NAME,
        "artifacts_name_handoff_matched": artifacts.get("handoff_json") == HANDOFF_JSON_NAME,
        "artifacts_name_send_ready_matched": artifacts.get("send_ready_json") == SEND_READY_JSON_NAME,
        "inner_install_kit_manifest_present": bool(inner_manifest),
        "inner_install_kit_version_matched": inner_manifest.get("package", {}).get("version") == install_kit.get("version"),
        "inner_install_kit_entrypoint_present": inner_manifest.get("entrypoint") == "cambrian",
        "inner_install_kit_mcp_entrypoint_present": inner_manifest.get("mcp_entrypoint") == "cambrian-mcp",
    }


def _json_from_bundle_item(bundle_items: dict[str, bytes], name: str) -> dict[str, Any]:
    try:
        payload = json.loads(bundle_items.get(name, b"{}").decode("utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _install_kit_manifest_from_zip_bytes(data: bytes) -> dict[str, Any]:
    if not data:
        return {}
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            payload = json.loads(archive.read("CAMBRIAN_INSTALL_KIT_MANIFEST.json").decode("utf-8"))
    except (KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return {}
    return payload if isinstance(payload, dict) else {}


def _release_receipt(
    build_result: dict[str, Any],
    receipt: dict[str, Any],
    handoff: dict[str, Any],
    send_ready: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "build_status_built": build_result.get("status") == "built",
        "dependency_mode_recorded": isinstance(build_result.get("dependency_mode"), str),
        "verification_receipt_pass": receipt.get("status") == "pass",
        "handoff_ready_to_share": handoff.get("status") == "ready_to_share",
        "send_ready_go": send_ready.get("verdict") == "GO",
        "company_snapshot_help_verified": send_ready.get("checks", {}).get("company_snapshot_help_verified") is True,
        "manual_dispatch_required": send_ready.get("checks", {}).get("manual_dispatch_required") is True,
        "artifact_chain_complete": send_ready.get("send_ready_checks", {}).get("artifact_chain_complete") is True,
    }
    payload = {
        "schema_version": RELEASE_RECEIPT_SCHEMA_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "safe_to_share": True,
        "install_kit": {
            "zip_file": Path(str(build_result.get("zip_file") or "")).name,
            "zip_sha256": build_result.get("zip_sha256"),
            "version": build_result.get("version"),
            "dependency_mode": build_result.get("dependency_mode"),
        },
        "artifacts": {
            "start_here": START_HERE_NAME,
            "bundle_verifier": BUNDLE_VERIFIER_NAME,
            "bundle_installer": BUNDLE_INSTALLER_NAME,
            "bundle_gold_path": BUNDLE_GOLD_PATH_NAME,
            "bundle_agent_prompt": BUNDLE_AGENT_PROMPT_NAME,
            "mcp_connect_guide": MCP_CONNECT_GUIDE_NAME,
            "bundle_installer_bat": BUNDLE_INSTALLER_BAT_NAME,
            "bundle_installer_sh": BUNDLE_INSTALLER_SH_NAME,
            "verification_receipt": INSTALL_KIT_RECEIPT_NAME,
            "handoff_json": HANDOFF_JSON_NAME,
            "send_ready_json": SEND_READY_JSON_NAME,
        },
        "artifact_hashes": {
            "verification_receipt_body_sha256": receipt.get("receipt_body_sha256"),
            "handoff_body_sha256": handoff.get("handoff_body_sha256"),
            "send_ready_body_sha256": send_ready.get("send_ready_body_sha256"),
        },
        "checks": checks,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    payload["release_receipt_body_sha256"] = _release_receipt_body_sha256(payload)
    payload["release_receipt_checks"] = _release_receipt_checks(payload)
    return payload


def _start_here_markdown(send_ready: dict[str, Any]) -> str:
    install_kit = send_ready.get("install_kit") if isinstance(send_ready.get("install_kit"), dict) else {}
    copy_paste_message = str(send_ready.get("copy_paste_message") or "")
    do_not_share = send_ready.get("do_not_share") if isinstance(send_ready.get("do_not_share"), list) else []
    do_not_share_text = "\n".join(f"- {item}" for item in do_not_share)
    return f"""# Start Here: Cambrian Install Kit

## Recipient Path

1. Extract `cambrian-install-kit-release-bundle.zip`.
2. Open a terminal in the extracted bundle directory.
3. Optional but recommended: run `python VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`.
4. Install Cambrian into a target project:

```bash
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>
```

Windows shortcut:

```bat
INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\\path\\to\\project
```

macOS/Linux shortcut:

```bash
bash install_cambrian_from_bundle.sh --project /path/to/project
```

5. If Claude or Codex is doing the install for you, paste `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md`.
6. After install, confirm these files exist in the target project:

```text
cambrian_install_receipt.json
cambrian_install_share_receipt.json
mcp_operability_receipt.json
```

7. Run the Required AI Company Gold Path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>
```

8. Confirm the share-safe gold path receipt exists:

```text
cambrian_gold_path_share_receipt.json
```

9. For support, share only `cambrian_install_share_receipt.json`, `cambrian_gold_path_share_receipt.json`, and the share-safe summary requested by support. Do not share local debug receipts unless explicitly asked.

Expected install receipt:

```text
cambrian --help: passed
cambrian doctor --json: passed
cambrian company snapshot --help: passed
```

Expected share-safe install receipt:

```text
cambrian_install_share_receipt.json
safe_to_share: true
absolute_paths_included: false
```

Required AI Company Gold Path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>
```

Required MCP External Client Verification:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

Read `{MCP_CONNECT_GUIDE_NAME}` before connecting Codex/Claude/other MCP clients. It names the installed `cambrian-mcp` server, the required explicit `cwd`, and the no-arbitrary-shell safety boundary.

Expected MCP operability receipt:

```text
mcp_operability_receipt.json
verdict: GO
source_pythonpath_injected: false
server_command_mode: installed_entrypoint
installed_entrypoint_command: true
no_arbitrary_shell: true
explicit_cwd_required: true
```

Expected share-safe gold path receipt:

```text
cambrian_gold_path_share_receipt.json
ai_agents_created: true
skills_generated_searched_and_fused: true
harness_engineering_system_created: true
evolution_proposed_previewed_and_applied: true
company_snapshot_generated: true
mcp_operability_verified: true
```

## Files In This Bundle

- `{install_kit.get("zip_file")}`
- `{install_kit.get("receipt_file")}`
- `VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`
- `INSTALL_CAMBRIAN_FROM_BUNDLE.py`
- `RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py`
- `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md`
- `{MCP_CONNECT_GUIDE_NAME}`
- `INSTALL_CAMBRIAN_FROM_BUNDLE.bat`
- `install_cambrian_from_bundle.sh`
- `cambrian-install-kit-handoff.md`
- `cambrian-install-kit-send-ready.md`
- `cambrian-install-kit-release-receipt.json`

## Sender Verification

```bash
python scripts/prepare_cambrian_install_kit_release.py --verify-release-receipt dist/cambrian-install-kit-release-receipt.json
python scripts/prepare_cambrian_install_kit_release.py --verify-release-bundle dist/cambrian-install-kit-release-bundle.zip
```

Expected:

```text
status: pass
verdict: GO
cambrian company snapshot --help: verified
```

## Recipient Message

```text
Extract this Cambrian install kit release bundle, then run `python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>`.
After install, run `python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>`.
If you use Codex, Claude, Cursor, or another MCP client, read `MCP_EXTERNAL_CLIENT_CONNECT.md` and verify `mcp_operability_receipt.json`.
Share only the safe receipts unless support explicitly asks for local debug receipts.
```

## Do Not Share

{do_not_share_text}

## Boundary

This bundle prepares and verifies a local Cambrian install. It does not send files, upload data, publish a package, deploy a service, or contact recipients automatically.

The local install, MCP, and gold path receipts are share-safe local validation evidence only. They are not a public proof claim, success-rate claim, sale-ready claim, marketplace claim, or first-recipient confirmation by themselves. First-recipient confirmation exists only after a real human send plus returned share-safe install, gold path, and MCP receipts are recorded through the sender checkpoint.
"""
    return f"""# Start Here: Cambrian Install Kit

## Recipient Path

1. 이 bundle ZIP을 푼다.
2. 선택 사항으로 `python VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`를 실행해 bundle 내부 해시 체인을 확인한다.
3. 가장 간단한 설치는 `python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>`를 실행한다.
4. Windows에서는 `INSTALL_CAMBRIAN_FROM_BUNDLE.bat --project C:\\path\\to\\project`를 사용할 수 있다.
5. Claude/Codex에게 맡길 때는 release bundle 최상단의 `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md`를 붙여넣는다.
6. 설치가 끝나면 대상 프로젝트 폴더의 `cambrian_install_receipt.json`과 `cambrian_install_share_receipt.json`을 확인한다.
7. 이어서 `python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>`를 실행해 AI Company Gold Path를 검증한다.
8. 지원 요청이 필요하면 절대경로가 들어 있는 `cambrian_install_receipt.json`과 `cambrian_gold_path_receipt.json` 대신 `cambrian_install_share_receipt.json`과 `cambrian_gold_path_share_receipt.json`만 공유한다.

Expected install receipt:

```text
cambrian --help: passed
cambrian doctor --json: passed
cambrian company snapshot --help: passed
```

Expected share-safe install receipt:

```text
cambrian_install_share_receipt.json
safe_to_share: true
absolute_paths_included: false
```

Required AI Company Gold Path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>
```

Required MCP External Client Verification:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

Read `{MCP_CONNECT_GUIDE_NAME}` before connecting Codex/Claude/other MCP clients. It names the installed `cambrian-mcp` server, the required explicit `cwd`, and the no-arbitrary-shell safety boundary.

Expected MCP operability receipt:

```text
mcp_operability_receipt.json
verdict: GO
source_pythonpath_injected: false
server_command_mode: installed_entrypoint
installed_entrypoint_command: true
no_arbitrary_shell: true
explicit_cwd_required: true
```

Expected share-safe gold path receipt:

```text
cambrian_gold_path_share_receipt.json
ai_agents_created: true
skills_generated_searched_and_fused: true
harness_engineering_system_created: true
evolution_proposed_previewed_and_applied: true
company_snapshot_generated: true
mcp_operability_verified: true
```

## Files In This Bundle

- `{install_kit.get("zip_file")}`
- `{install_kit.get("receipt_file")}`
- `VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py`
- `INSTALL_CAMBRIAN_FROM_BUNDLE.py`
- `RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py`
- `INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md`
- `{MCP_CONNECT_GUIDE_NAME}`
- `INSTALL_CAMBRIAN_FROM_BUNDLE.bat`
- `install_cambrian_from_bundle.sh`
- `cambrian-install-kit-handoff.md`
- `cambrian-install-kit-send-ready.md`
- `cambrian-install-kit-release-receipt.json`

## Sender Verification

```bash
python scripts/prepare_cambrian_install_kit_release.py --verify-release-receipt dist/cambrian-install-kit-release-receipt.json
python scripts/prepare_cambrian_install_kit_release.py --verify-release-bundle dist/cambrian-install-kit-release-bundle.zip
```

Expected:

```text
status: pass
verdict: GO
cambrian company snapshot --help: verified
```

## Recipient Message

```text
{copy_paste_message}
```

## Do Not Share

{do_not_share_text}

## Boundary

이 패킷은 Cambrian 설치 준비물이다. 스크립트는 수령자에게 파일이나 메시지를 직접 보내지 않는다.
"""

def _bundle_agent_prompt_markdown(send_ready: dict[str, Any]) -> str:
    install_kit = send_ready.get("install_kit") if isinstance(send_ready.get("install_kit"), dict) else {}
    zip_name = install_kit.get("zip_file") or "cambrian-install-kit-<version>.zip"
    return f"""# Cambrian Release Bundle Prompt For Codex/Claude

You are working inside the extracted Cambrian release bundle directory.

Goal: install Cambrian into the target project, then run the Required AI Company Gold Path.

Use this exact local bundle contract:

1. Verify the release bundle:

```bash
python VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py
```

2. Install Cambrian into the target project:

```bash
python INSTALL_CAMBRIAN_FROM_BUNDLE.py --project <PROJECT_DIR>
```

3. Run the Required AI Company Gold Path:

```bash
python RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py --project <PROJECT_DIR>
```

4. Verify the installed MCP server surface:

```bash
cambrian mcp verify --receipt dist/mcp_operability_receipt.json
```

Read `{MCP_CONNECT_GUIDE_NAME}` before connecting an external client. Use the installed `cambrian-mcp` command with an explicit `cwd`; do not grant arbitrary shell access through MCP.

5. Confirm these receipts exist in `<PROJECT_DIR>`:

```text
cambrian_install_share_receipt.json
cambrian_gold_path_share_receipt.json
mcp_operability_receipt.json
```

Success means:

```text
cambrian --help: passed
cambrian doctor --json: passed
cambrian company snapshot --help: passed
ai_agents_created: true
skills_generated_searched_and_fused: true
harness_engineering_system_created: true
evolution_proposed_previewed_and_applied: true
company_snapshot_generated: true
mcp_operability_verified: true
mcp_operability_receipt.verdict: GO
mcp_operability_receipt.server_command_mode: installed_entrypoint
mcp_operability_receipt.installed_entrypoint_command: true
mcp_operability_receipt.no_arbitrary_shell: true
```

Files you should expect beside this prompt:

```text
{zip_name}
VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py
INSTALL_CAMBRIAN_FROM_BUNDLE.py
RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py
START_HERE_CAMBRIAN_INSTALL_KIT.md
{MCP_CONNECT_GUIDE_NAME}
```

Treat receipts as local validation evidence only. Do not claim public proof, sale readiness, marketplace readiness, success rate, or first-recipient confirmation from this run. First-recipient confirmation requires a real human send and returned share-safe receipts through the sender checkpoint.

Do not publish, upload, email, or send anything automatically. Report only share-safe receipt summaries unless the user explicitly asks for more.
"""


def _standalone_bundle_verifier_text() -> str:
    return r'''from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any


MANIFEST_NAME = "cambrian-install-kit-release-bundle-manifest.json"
START_HERE_NAME = "START_HERE_CAMBRIAN_INSTALL_KIT.md"
RELEASE_RECEIPT_NAME = "cambrian-install-kit-release-receipt.json"
VERIFICATION_RECEIPT_NAME = "cambrian-install-kit-verification-receipt.json"
HANDOFF_JSON_NAME = "cambrian-install-kit-handoff.json"
SEND_READY_JSON_NAME = "cambrian-install-kit-send-ready.json"
BUNDLE_VERIFIER_NAME = "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py"
BUNDLE_INSTALLER_NAME = "INSTALL_CAMBRIAN_FROM_BUNDLE.py"
BUNDLE_GOLD_PATH_NAME = "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py"
BUNDLE_AGENT_PROMPT_NAME = "INSTALL_CAMBRIAN_RELEASE_BUNDLE_PROMPT_FOR_CODEX_CLAUDE.md"
BUNDLE_INSTALLER_BAT_NAME = "INSTALL_CAMBRIAN_FROM_BUNDLE.bat"
BUNDLE_INSTALLER_SH_NAME = "install_cambrian_from_bundle.sh"
MCP_CONNECT_GUIDE_NAME = "MCP_EXTERNAL_CLIENT_CONNECT.md"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_inner_manifest(zip_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            payload = json.loads(archive.read("CAMBRIAN_INSTALL_KIT_MANIFEST.json").decode("utf-8"))
    except (KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return {}
    return payload if isinstance(payload, dict) else {}


def verify(root: Path) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    manifest = _read_json(manifest_path)
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    file_hashes: dict[str, bool] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "")
        path = root / rel
        file_hashes[rel] = path.exists() and path.stat().st_size == int(item.get("bytes") or -1) and _sha256_bytes(path.read_bytes()) == item.get("sha256")

    release_receipt = _read_json(root / RELEASE_RECEIPT_NAME)
    verification_receipt = _read_json(root / VERIFICATION_RECEIPT_NAME)
    handoff = _read_json(root / HANDOFF_JSON_NAME)
    send_ready = _read_json(root / SEND_READY_JSON_NAME)
    install_kit = release_receipt.get("install_kit") if isinstance(release_receipt.get("install_kit"), dict) else {}
    artifact_hashes = release_receipt.get("artifact_hashes") if isinstance(release_receipt.get("artifact_hashes"), dict) else {}
    install_kit_zip = root / str(install_kit.get("zip_file") or "")
    inner_manifest = _read_inner_manifest(install_kit_zip)
    start_here = (root / START_HERE_NAME).read_text(encoding="utf-8") if (root / START_HERE_NAME).exists() else ""
    bundle_agent_prompt = (root / BUNDLE_AGENT_PROMPT_NAME).read_text(encoding="utf-8") if (root / BUNDLE_AGENT_PROMPT_NAME).exists() else ""
    mcp_connect_guide = (root / MCP_CONNECT_GUIDE_NAME).read_text(encoding="utf-8") if (root / MCP_CONNECT_GUIDE_NAME).exists() else ""
    handoff_copy_paste_message = str(handoff.get("copy_paste_message") or "")
    handoff_checks = handoff.get("handoff_checks") if isinstance(handoff.get("handoff_checks"), dict) else {}
    send_ready_copy_paste_message = str(send_ready.get("copy_paste_message") or "")
    send_ready_checks = send_ready.get("checks") if isinstance(send_ready.get("checks"), dict) else {}
    checks = {
        "manifest_present": manifest_path.exists(),
        "all_manifest_file_hashes_match": bool(file_hashes) and all(file_hashes.values()),
        "start_here_present": (root / START_HERE_NAME).exists(),
        "standalone_verifier_present": (root / BUNDLE_VERIFIER_NAME).exists(),
        "standalone_installer_present": (root / BUNDLE_INSTALLER_NAME).exists(),
        "gold_path_runner_present": (root / BUNDLE_GOLD_PATH_NAME).exists(),
        "bundle_agent_prompt_present": (root / BUNDLE_AGENT_PROMPT_NAME).exists(),
        "mcp_connect_guide_present": (root / MCP_CONNECT_GUIDE_NAME).exists(),
        "windows_installer_wrapper_present": (root / BUNDLE_INSTALLER_BAT_NAME).exists(),
        "shell_installer_wrapper_present": (root / BUNDLE_INSTALLER_SH_NAME).exists(),
        "start_here_mentions_standalone_installer": BUNDLE_INSTALLER_NAME in start_here,
        "start_here_mentions_gold_path_runner": BUNDLE_GOLD_PATH_NAME in start_here,
        "start_here_mentions_bundle_agent_prompt": BUNDLE_AGENT_PROMPT_NAME in start_here,
        "start_here_mentions_mcp_guide": MCP_CONNECT_GUIDE_NAME in start_here,
        "start_here_mentions_mcp_verify": "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in start_here,
        "bundle_agent_prompt_mentions_standalone_verifier": BUNDLE_VERIFIER_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_standalone_installer": BUNDLE_INSTALLER_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_gold_path_runner": BUNDLE_GOLD_PATH_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_mcp_guide": MCP_CONNECT_GUIDE_NAME in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_mcp_verify": "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in bundle_agent_prompt,
        "bundle_agent_prompt_marks_gold_path_required": "Required AI Company Gold Path" in bundle_agent_prompt,
        "bundle_agent_prompt_mentions_share_receipts": "cambrian_install_share_receipt.json" in bundle_agent_prompt
        and "cambrian_gold_path_share_receipt.json" in bundle_agent_prompt,
        "bundle_agent_prompt_marks_receipts_local_validation_only": "local validation evidence only" in bundle_agent_prompt,
        "bundle_agent_prompt_blocks_public_proof_claims": "Do not claim public proof" in bundle_agent_prompt,
        "bundle_agent_prompt_blocks_first_recipient_claims": "First-recipient confirmation requires a real human send" in bundle_agent_prompt,
        "start_here_marks_gold_path_required": "Required AI Company Gold Path" in start_here,
        "start_here_does_not_mark_gold_path_optional": "Optional AI Company Gold Path" not in start_here,
        "start_here_mentions_install_receipt": "cambrian_install_receipt.json" in start_here,
        "start_here_mentions_share_receipt": "cambrian_install_share_receipt.json" in start_here,
        "start_here_mentions_gold_path_share_receipt": "cambrian_gold_path_share_receipt.json" in start_here,
        "start_here_marks_receipts_local_validation_only": "share-safe local validation evidence only" in start_here,
        "start_here_blocks_public_proof_claims": "not a public proof claim" in start_here,
        "start_here_blocks_first_recipient_claims": "First-recipient confirmation exists only after a real human send" in start_here,
        "handoff_copy_paste_marks_receipts_local_validation_only": "local validation evidence only" in handoff_copy_paste_message,
        "handoff_copy_paste_blocks_public_proof_claims": "do not claim public proof" in handoff_copy_paste_message,
        "handoff_copy_paste_blocks_first_recipient_claims": "First-recipient confirmation requires a real human send" in handoff_copy_paste_message,
        "handoff_checks_require_claim_boundary": handoff_checks.get("claim_boundary_present") is True,
        "send_ready_copy_paste_marks_receipts_local_validation_only": "local validation evidence only" in send_ready_copy_paste_message,
        "send_ready_copy_paste_blocks_public_proof_claims": "do not claim public proof" in send_ready_copy_paste_message,
        "send_ready_copy_paste_blocks_first_recipient_claims": "First-recipient confirmation requires a real human send" in send_ready_copy_paste_message,
        "send_ready_checks_require_claim_boundary": send_ready_checks.get("copy_paste_message_marks_local_validation_only") is True
        and send_ready_checks.get("copy_paste_message_blocks_public_proof_claims") is True
        and send_ready_checks.get("copy_paste_message_blocks_first_recipient_claims") is True,
        "start_here_mentions_company_snapshot_help": "cambrian company snapshot --help" in start_here,
        "mcp_connect_guide_mentions_cambrian_mcp": "cambrian-mcp" in mcp_connect_guide,
        "mcp_connect_guide_mentions_mcp_verify": "cambrian mcp verify --receipt dist/mcp_operability_receipt.json" in mcp_connect_guide,
        "mcp_connect_guide_mentions_explicit_cwd": "explicit `cwd`" in mcp_connect_guide,
        "mcp_connect_guide_mentions_no_arbitrary_shell": "arbitrary shell" in mcp_connect_guide,
        "release_receipt_status_pass": release_receipt.get("status") == "pass",
        "release_receipt_checks_true": all(
            value is True
            for value in (release_receipt.get("release_receipt_checks") if isinstance(release_receipt.get("release_receipt_checks"), dict) else {}).values()
        ),
        "install_kit_zip_hash_matched": install_kit_zip.exists() and _sha256_bytes(install_kit_zip.read_bytes()) == install_kit.get("zip_sha256"),
        "verification_receipt_hash_matched": verification_receipt.get("receipt_body_sha256") == artifact_hashes.get("verification_receipt_body_sha256"),
        "handoff_hash_matched": handoff.get("handoff_body_sha256") == artifact_hashes.get("handoff_body_sha256"),
        "send_ready_hash_matched": send_ready.get("send_ready_body_sha256") == artifact_hashes.get("send_ready_body_sha256"),
        "inner_install_kit_manifest_present": bool(inner_manifest),
        "inner_install_kit_entrypoint_present": inner_manifest.get("entrypoint") == "cambrian",
        "inner_install_kit_mcp_entrypoint_present": inner_manifest.get("mcp_entrypoint") == "cambrian-mcp",
        "inner_install_kit_version_matched": inner_manifest.get("package", {}).get("version") == install_kit.get("version"),
        "manual_dispatch_required": manifest.get("dispatch_execution_policy", {}).get("manual_operator_dispatch_required") is True
        and manifest.get("dispatch_execution_policy", {}).get("script_sends_to_recipient") is False,
        "privacy_flags_safe": manifest.get("privacy", {}).get("absolute_paths_included") is False
        and manifest.get("privacy", {}).get("raw_private_project_data_included") is False
        and manifest.get("privacy", {}).get("secrets_included") is False,
    }
    return {
        "schema_version": "cambrian_install_kit_bundle_local_verification_v0_1",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if passed is not True],
    }


if __name__ == "__main__":
    result = verify(Path(__file__).resolve().parent)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result["status"] != "pass":
        raise SystemExit(1)
'''


def _standalone_bundle_gold_path_text() -> str:
    return r'''from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUEST_TEXT = "check refresh token login failure"
FUSION_GOAL = "trace refresh token login failure and inspect Jest auth test risk together"
MCP_VERIFY_COMMAND_HINT = "cambrian mcp verify --receipt dist/mcp_operability_receipt.json"


def _scripts_dir(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv_dir: Path) -> Path:
    return _scripts_dir(venv_dir) / ("python.exe" if os.name == "nt" else "python")


def _venv_cambrian(venv_dir: Path) -> Path:
    return _scripts_dir(venv_dir) / ("cambrian.exe" if os.name == "nt" else "cambrian")


def _venv_cambrian_mcp(venv_dir: Path) -> Path:
    return _scripts_dir(venv_dir) / ("cambrian-mcp.exe" if os.name == "nt" else "cambrian-mcp")


def _run(command: list[str | Path], cwd: Path, *, name: str, timeout: int = 90) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {
        "name": name,
        "command": [str(item) for item in command],
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "passed" if result.returncode == 0 else "failed",
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_project(project_dir: Path) -> None:
    _write(project_dir / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(project_dir / "tsconfig.json", "{}")
    _write(project_dir / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(project_dir / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _write_answers(project_dir: Path) -> None:
    answers = """session_id: install-kit-gold-path
answers:
  primary_goal: Investigate auth login bugs safely.
  test_command: npm test
  build_command: npm run build
  change_policy: proposal_only
  forbidden_scope:
    - no automatic patch apply
    - no DB schema changes
  important_paths:
    - backend/src/middleware/authMiddleware.ts
    - backend/tests/auth.test.ts
  validation_standard: Relevant Jest tests pass and regression risk is explained.
"""
    _write(project_dir / ".cambrian" / "interview" / "answers.yaml", answers)


def _json_from_stdout(step: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(step.get("stdout") or "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{step['name']} JSON output parse failed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{step['name']} JSON output is not an object")
    return payload


def _expand_outcome_evidence(project_dir: Path, python: Path) -> dict[str, Any]:
    code = r"""
from pathlib import Path
import sys
import yaml

project_dir = Path(sys.argv[1])
outcomes_path = project_dir / ".cambrian" / "evidence" / "outcomes.yaml"
payload = yaml.safe_load(outcomes_path.read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise SystemExit("outcomes evidence must be a YAML object")
outcomes = payload.get("outcomes", [])
if not isinstance(outcomes, list) or not outcomes:
    raise SystemExit("outcomes evidence is missing")
seed = dict(outcomes[-1])
seed_job_id = str(seed.get("job_id") or "job-maturity")
expanded = [dict(item) for item in outcomes if isinstance(item, dict)]
for index in range(len(expanded), 10):
    item = dict(seed)
    item["job_id"] = f"{seed_job_id}-maturity-{index + 1:03d}"
    expanded.append(item)
payload["outcomes"] = expanded
outcomes_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
"""
    return _run([python, "-c", code, str(project_dir)], cwd=project_dir, name="expand evolution maturity evidence")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_steps(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": item["name"],
            "exit_code": item["exit_code"],
            "duration_seconds": item["duration_seconds"],
            "status": item["status"],
        }
        for item in commands
    ]


def run(project: Path, venv_name: str, keep_fixture: bool) -> dict[str, Any]:
    project_root = project.resolve()
    venv_dir = project_root / venv_name
    python = _venv_python(venv_dir)
    cambrian = _venv_cambrian(venv_dir)
    cambrian_mcp = _venv_cambrian_mcp(venv_dir)
    if not python.exists() or not cambrian.exists():
        raise SystemExit(f"Cambrian venv was not found under {project_root / venv_name}. Run INSTALL_CAMBRIAN_FROM_BUNDLE.py first.")

    run_id = datetime.now(timezone.utc).strftime("r%Y%m%d%H%M%S")
    fixture_dir = project_root / ".cbgp" / run_id / "fixture"
    _write_project(fixture_dir)

    commands: list[dict[str, Any]] = []
    checks: list[dict[str, str]] = []
    errors: list[str] = []

    def mark(name: str, passed: bool) -> None:
        checks.append({"name": name, "status": "passed" if passed else "failed"})

    def run_required(name: str, command: list[str | Path], cwd: Path) -> dict[str, Any]:
        item = _run(command, cwd=cwd, name=name)
        commands.append(item)
        mark(name, item["exit_code"] == 0)
        if item["exit_code"] != 0:
            raise RuntimeError(f"command failed: {name}")
        return item

    try:
        run_required("cambrian --help", [cambrian, "--help"], project_root)
        run_required(
            "mcp operability verify",
            [
                cambrian,
                "mcp",
                "verify",
                "--receipt",
                project_root / "mcp_operability_receipt.json",
                "--server-cwd",
                project_root,
                "--server-command-json",
                json.dumps([str(cambrian_mcp)]),
                "--json",
            ],
            project_root,
        )
        run_required("cambrian doctor", [cambrian, "doctor", "--json"], fixture_dir)
        run_required("project scan", [cambrian, "project", "scan", "--json"], fixture_dir)
        run_required("harness interview start", [cambrian, "harness", "interview", "start", "--json"], fixture_dir)
        _write_answers(fixture_dir)
        run_required("harness interview answer", [cambrian, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json"], fixture_dir)
        run_required("harness engineer design", [cambrian, "harness", "engineer", "design", "--json"], fixture_dir)
        run_required("harness engineer review", [cambrian, "harness", "engineer", "review", "--json"], fixture_dir)
        run_required("harness engineer dry-run", [cambrian, "harness", "engineer", "dry-run", REQUEST_TEXT, "--json"], fixture_dir)
        run_required("workforce generate", [cambrian, "workforce", "generate", "--json"], fixture_dir)
        run_required("skill generate", [cambrian, "skill", "generate", "--json"], fixture_dir)
        run_required("harness install", [cambrian, "harness", "install", "--confirm", "--json"], fixture_dir)
        search = run_required("skill search", [cambrian, "skill", "search", "auth", "token", "--json"], fixture_dir)
        search_payload = _json_from_stdout(search)
        result_ids = [item.get("id") for item in search_payload.get("results", []) if isinstance(item, dict)]
        mark("skill search finds generated skill", "trace-auth-token-flow" in result_ids)
        if "trace-auth-token-flow" not in result_ids:
            raise RuntimeError("skill search did not find trace-auth-token-flow")
        fuse = run_required(
            "skill fuse",
            [
                cambrian,
                "skill",
                "fuse",
                "trace-auth-token-flow",
                "inspect-jest-auth-test",
                "--goal",
                FUSION_GOAL,
                "--json",
            ],
            fixture_dir,
        )
        fused_skill_id = str(_json_from_stdout(fuse).get("skill_id") or "")
        mark("skill fuse creates project skill", bool(fused_skill_id) and (fixture_dir / ".cambrian" / "skills" / f"{fused_skill_id}.yaml").exists())
        if not fused_skill_id:
            raise RuntimeError("skill fuse did not return skill_id")
        job = run_required("job start", [cambrian, "job", "start", REQUEST_TEXT, "--json"], fixture_dir)
        job_payload = _json_from_stdout(job)
        mark("job start selects agents and skills", bool(job_payload.get("selected_agents")) and bool(job_payload.get("selected_skills")))
        run_required(
            "job complete",
            [
                cambrian,
                "job",
                "complete",
                "latest",
                "--outcome",
                "partial",
                "--notes",
                "test command was wrong and refresh token path was missed",
                "--json",
            ],
            fixture_dir,
        )
        maturity = _expand_outcome_evidence(fixture_dir, python)
        commands.append(maturity)
        mark("evolution maturity evidence", maturity["exit_code"] == 0)
        if maturity["exit_code"] != 0:
            raise RuntimeError("evolution maturity evidence expansion failed")
        propose = run_required("evolve propose", [cambrian, "evolve", "propose", "--json"], fixture_dir)
        proposal_id = str(_json_from_stdout(propose).get("proposal_id") or "")
        if not proposal_id:
            raise RuntimeError("evolve propose did not return proposal_id")
        run_required("evolve preview", [cambrian, "evolve", "preview", proposal_id, "--json"], fixture_dir)
        run_required("evolve apply", [cambrian, "evolve", "apply", proposal_id, "--confirm", "--json"], fixture_dir)
        snapshot = run_required("company snapshot", [cambrian, "company", "snapshot", "--json"], fixture_dir)
        snapshot_payload = _json_from_stdout(snapshot)
        snapshot_body = snapshot_payload.get("snapshot", {}) if isinstance(snapshot_payload.get("snapshot"), dict) else {}
        privacy = snapshot_body.get("privacy_boundary", {}) if isinstance(snapshot_body.get("privacy_boundary"), dict) else {}
        marketplace = snapshot_body.get("marketplace", {}) if isinstance(snapshot_body.get("marketplace"), dict) else {}
        validation = snapshot_body.get("validation", {}) if isinstance(snapshot_body.get("validation"), dict) else {}
        snapshot_ref = str(snapshot_payload.get("snapshot_ref") or "")
        snapshot_ok = (
            validation.get("status") == "pass"
            and privacy.get("raw_private_project_data_included") is False
            and marketplace.get("sale_ready") is False
            and bool(snapshot_ref)
            and (fixture_dir / snapshot_ref).exists()
        )
        mark("company snapshot is private-safe artifact", snapshot_ok)
        if not snapshot_ok:
            raise RuntimeError("company snapshot did not validate as private-safe artifact")
        required_files = [
            ".cambrian/harness.yaml",
            ".cambrian/workforce.yaml",
            ".cambrian/agents/auth-flow-investigator.yaml",
            ".cambrian/skills/trace-auth-token-flow.yaml",
            ".cambrian/evolution/proposals",
            ".cambrian/company/snapshots",
        ]
        for relative in required_files:
            exists = (fixture_dir / relative).exists()
            mark(f"artifact exists: {relative}", exists)
            if not exists:
                raise RuntimeError(f"required artifact missing: {relative}")
    except Exception as exc:
        errors.append(str(exc))
        if not checks or checks[-1]["status"] != "failed":
            mark("current step", False)

    capabilities = {
        "ai_agents_created": any(check["name"] == "artifact exists: .cambrian/agents/auth-flow-investigator.yaml" and check["status"] == "passed" for check in checks),
        "skills_generated_searched_and_fused": any(check["name"] == "skill fuse creates project skill" and check["status"] == "passed" for check in checks),
        "harness_engineering_system_created": any(check["name"] == "harness engineer dry-run" and check["status"] == "passed" for check in checks),
        "evolution_proposed_previewed_and_applied": any(check["name"] == "evolve apply" and check["status"] == "passed" for check in checks),
        "company_snapshot_generated": any(check["name"] == "company snapshot is private-safe artifact" and check["status"] == "passed" for check in checks),
        "mcp_operability_verified": any(check["name"] == "mcp operability verify" and check["status"] == "passed" for check in checks),
    }
    status = "passed" if not errors and all(capabilities.values()) else "failed"
    local_receipt = {
        "schema_version": "cambrian_bundle_gold_path_receipt_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "safe_to_share": False,
        "shareable_receipt": "cambrian_gold_path_share_receipt.json",
        "privacy": {
            "absolute_paths_included": True,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "project_root": str(project_root),
        "fixture_root": str(fixture_dir),
        "steps": _safe_steps(commands),
        "debug_steps": commands,
        "checks": checks,
        "capabilities_verified": capabilities,
        "errors": errors,
    }
    local_path = project_root / "cambrian_gold_path_receipt.json"
    local_path.write_text(json.dumps(local_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    share_receipt = {
        "schema_version": "cambrian_bundle_gold_path_share_receipt_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "local_receipt_sha256": _sha256(local_path),
        "steps": _safe_steps(commands),
        "checks": {check["name"]: check["status"] == "passed" for check in checks},
        "capabilities_verified": capabilities,
        "proof_claim_allowed": False,
        "sale_ready": False,
        "do_not_share": [
            "cambrian_gold_path_receipt.json",
            ".env",
            "API keys",
            "raw private project data",
            "screenshots or raw user text",
            "mcp_operability_receipt.json",
        ],
    }
    share_path = project_root / "cambrian_gold_path_share_receipt.json"
    share_path.write_text(json.dumps(share_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not keep_fixture and status != "passed":
        shutil.rmtree(fixture_dir.parent, ignore_errors=True)
    print(json.dumps(share_receipt, ensure_ascii=False, indent=2, sort_keys=True))
    if status != "passed":
        raise SystemExit(1)
    return share_receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Cambrian AI Company Gold Path from an extracted release bundle install.")
    parser.add_argument("--project", type=Path, required=True, help="Project directory where INSTALL_CAMBRIAN_FROM_BUNDLE.py installed Cambrian.")
    parser.add_argument("--venv-name", default=".venv-cambrian", help="Cambrian venv directory name under the project.")
    parser.add_argument("--keep-fixture", action="store_true", help="Keep the generated fixture project even when the run fails.")
    args = parser.parse_args()
    run(args.project, args.venv_name, bool(args.keep_fixture))


if __name__ == "__main__":
    main()
'''


def _standalone_bundle_installer_text() -> str:
    return r'''from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any


INSTALL_KIT_DIR = "cambrian-install-kit"
RELEASE_BUNDLE_NAME = "cambrian-install-kit-release-bundle.zip"
VERIFIER_NAME = "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py"


def _find_install_kit_zip(root: Path) -> Path:
    candidates = sorted(
        path
        for path in root.glob("cambrian-install-kit-*.zip")
        if path.name != RELEASE_BUNDLE_NAME
    )
    for candidate in candidates:
        try:
            with zipfile.ZipFile(candidate) as archive:
                archive.getinfo("CAMBRIAN_INSTALL_KIT_MANIFEST.json")
        except (KeyError, zipfile.BadZipFile):
            continue
        return candidate
    raise SystemExit("Cambrian install kit ZIP was not found in the extracted release bundle directory.")


def _run(command: list[str], cwd: Path) -> int:
    completed = subprocess.run(command, cwd=str(cwd), text=True, check=False)
    return int(completed.returncode)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Cambrian from the extracted release bundle.")
    parser.add_argument("--project", type=Path, required=True, help="Target project directory where Cambrian will be installed.")
    parser.add_argument("--venv-name", default=".venv-cambrian", help="Project-local virtual environment directory name.")
    parser.add_argument("--online", action="store_true", help="Allow online pip resolution instead of offline wheelhouse-only install.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip release bundle hash-chain verification before install.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if not args.skip_verify:
        verifier = root / VERIFIER_NAME
        if not verifier.exists():
            raise SystemExit(f"{VERIFIER_NAME} was not found in the extracted release bundle directory.")
        code = _run([sys.executable, str(verifier)], cwd=root)
        if code != 0:
            raise SystemExit(code)

    kit_zip = _find_install_kit_zip(root)
    extract_dir = root / INSTALL_KIT_DIR
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(kit_zip) as archive:
        archive.extractall(extract_dir)
    install_script = extract_dir / "install_cambrian.py"
    if not install_script.exists():
        raise SystemExit("install_cambrian.py was not found inside the install kit ZIP.")
    command = [
        sys.executable,
        str(install_script),
        "--project",
        str(args.project),
        "--venv-name",
        args.venv_name,
    ]
    if not args.online:
        command.append("--offline")
    code = _run(command, cwd=extract_dir)
    if code != 0:
        raise SystemExit(code)

    project_root = args.project.resolve()
    receipt_path = project_root / "cambrian_install_receipt.json"
    share_receipt_path = project_root / "cambrian_install_share_receipt.json"
    mcp_receipt_path = project_root / "mcp_operability_receipt.json"
    receipt = _read_json(receipt_path)
    print(json.dumps({
        "status": "installed",
        "project": str(project_root),
        "receipt": str(receipt_path),
        "share_receipt": str(share_receipt_path),
        "mcp_operability_receipt": str(mcp_receipt_path),
        "cambrian_command": receipt.get("cambrian_command"),
        "cambrian_mcp_command": receipt.get("cambrian_mcp_command"),
        "next_commands": receipt.get("next_commands", []),
    }, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
'''
    return r'''from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path


INSTALL_KIT_DIR = "cambrian-install-kit"
RELEASE_BUNDLE_NAME = "cambrian-install-kit-release-bundle.zip"
VERIFIER_NAME = "VERIFY_CAMBRIAN_INSTALL_KIT_BUNDLE.py"


def _find_install_kit_zip(root: Path) -> Path:
    candidates = sorted(
        path
        for path in root.glob("cambrian-install-kit-*.zip")
        if path.name != RELEASE_BUNDLE_NAME
    )
    for candidate in candidates:
        try:
            with zipfile.ZipFile(candidate) as archive:
                archive.getinfo("CAMBRIAN_INSTALL_KIT_MANIFEST.json")
        except (KeyError, zipfile.BadZipFile):
            continue
        return candidate
    raise SystemExit("Cambrian install kit ZIP을 찾을 수 없습니다.")


def _run(command: list[str], cwd: Path) -> int:
    completed = subprocess.run(command, cwd=str(cwd), text=True, check=False)
    return int(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Cambrian from the extracted release bundle.")
    parser.add_argument("--project", type=Path, required=True, help="Cambrian을 설치할 대상 프로젝트 폴더")
    parser.add_argument("--venv-name", default=".venv-cambrian", help="대상 프로젝트에 만들 venv 폴더명")
    parser.add_argument("--online", action="store_true", help="offline wheelhouse 설치 대신 온라인 pip 경로를 허용")
    parser.add_argument("--skip-verify", action="store_true", help="bundle 내부 검증을 건너뛴다")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if not args.skip_verify:
        verifier = root / VERIFIER_NAME
        if not verifier.exists():
            raise SystemExit(f"{VERIFIER_NAME} 파일이 없습니다.")
        code = _run([sys.executable, str(verifier)], cwd=root)
        if code != 0:
            raise SystemExit(code)

    kit_zip = _find_install_kit_zip(root)
    extract_dir = root / INSTALL_KIT_DIR
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(kit_zip) as archive:
        archive.extractall(extract_dir)
    install_script = extract_dir / "install_cambrian.py"
    if not install_script.exists():
        raise SystemExit("install_cambrian.py를 찾을 수 없습니다.")
    command = [
        sys.executable,
        str(install_script),
        "--project",
        str(args.project),
        "--venv-name",
        args.venv_name,
    ]
    if not args.online:
        command.append("--offline")
    code = _run(command, cwd=extract_dir)
    if code != 0:
        raise SystemExit(code)
    receipt = args.project.resolve() / "cambrian_install_receipt.json"
    print(json.dumps({
        "status": "installed",
        "project": str(args.project.resolve()),
        "receipt": str(receipt),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
'''


def _bundle_installer_bat_text() -> str:
    return """@echo off
set SCRIPT_DIR=%~dp0
python "%SCRIPT_DIR%INSTALL_CAMBRIAN_FROM_BUNDLE.py" %*
"""


def _bundle_installer_sh_text() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/INSTALL_CAMBRIAN_FROM_BUNDLE.py" "$@"
"""


def _release_receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"release_receipt_body_sha256", "release_receipt_checks"}
    }
    import hashlib

    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _release_receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(ROOT)
    home = str(Path.home())
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    body_hash = payload.get("release_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == RELEASE_RECEIPT_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "status_pass": payload.get("status") == "pass",
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "raw_private_project_data_omitted": privacy.get("raw_private_project_data_included") is False,
        "secrets_omitted": privacy.get("secrets_included") is False,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "company_snapshot_help_verified": checks.get("company_snapshot_help_verified") is True,
        "manual_dispatch_required": checks.get("manual_dispatch_required") is True,
        "artifact_chain_complete": checks.get("artifact_chain_complete") is True,
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _release_receipt_body_sha256(payload),
    }


def _verify_release_receipt(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != RELEASE_RECEIPT_SCHEMA_VERSION:
        raise ValueError("install kit release receipt schema_version이 올바르지 않습니다.")
    receipt_checks = payload.get("release_receipt_checks") if isinstance(payload.get("release_receipt_checks"), dict) else {}
    if not receipt_checks:
        raise ValueError("install kit release receipt checks가 없습니다.")
    failed = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed:
        raise ValueError("install kit release receipt 검증 실패: " + ", ".join(failed))
    if payload.get("release_receipt_body_sha256") != _release_receipt_body_sha256(payload):
        raise ValueError("install kit release receipt 본문 해시가 일치하지 않습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian install kit release 패킷을 한 번에 준비한다.")
    parser.add_argument("--output-dir", type=Path, default=None, help="기본값은 dist")
    parser.add_argument("--no-dependency-wheels", action="store_true", help="dependency wheel 다운로드를 건너뛴다")
    parser.add_argument("--skip-build", action="store_true", help="기존 dist install kit ZIP을 재사용해 검증 체인만 갱신한다")
    parser.add_argument("--verify-release-receipt", type=Path, default=None, help="기존 install kit release receipt JSON만 검증한다")
    parser.add_argument("--verify-release-bundle", type=Path, default=None, help="기존 install kit release bundle ZIP만 검증한다")
    args = parser.parse_args()
    if args.verify_release_receipt:
        payload = verify_release_receipt_file(args.verify_release_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if args.verify_release_bundle:
        payload = verify_release_bundle_current_artifacts(args.verify_release_bundle)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    result = prepare_release(
        output_dir=args.output_dir,
        include_dependency_wheels=not bool(args.no_dependency_wheels),
        skip_build=bool(args.skip_build),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
