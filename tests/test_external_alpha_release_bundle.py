import json
import os
import subprocess
import sys
import zipfile
import hashlib
from pathlib import Path

import pytest

from scripts.collect_external_alpha_diagnostics import DO_NOT_SHARE, SUPPORT_NEXT_ACTION
from scripts.build_external_alpha_release import (
    DISPATCH_EXECUTION_POLICY,
    FORBIDDEN_PATH_PARTS,
    INCLUDED_FILES,
    RELEASE_BOUNDARIES,
    RELEASE_SLUG,
    TRUST_REPORT_NAME,
    build_release,
)
from scripts.verify_external_alpha_release import (
    ReleaseVerificationError,
    SUPPORT_PACKET_NAME,
    _current_source_manifest_checks,
    _receipt_body_sha256,
    _verify_current_source_manifest,
    _verify_diagnostics_report,
    _verify_shareable_receipt,
    verify_shareable_receipt_file,
    verify_release,
)


ROOT = Path(__file__).resolve().parents[1]
RELEASE_MANIFEST_DOC = ROOT / "docs" / "release" / "EXTERNAL_ALPHA_RELEASE_MANIFEST.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_external_alpha_release_manifest_doc_exists() -> None:
    text = _read(RELEASE_MANIFEST_DOC)

    for phrase in [
        "External Alpha Release Manifest",
        "Defensible Alpha",
        "한국 시장",
        "verified promotion audit lineage",
        "verified linked",
        "python scripts/build_external_alpha_release.py",
        "python scripts/verify_external_alpha_release.py",
        "python scripts/smoke_external_alpha_release_bundle.py",
        "python scripts/smoke_external_alpha_manual_send_go_rehearsal.py",
        "READY_TO_MANUALLY_SEND_ONE",
        "python scripts/smoke_external_alpha_post_send_checkpoint.py",
        "python scripts/smoke_external_alpha_pilot_learning_loop.py",
        "python scripts/smoke_external_alpha_private_pilot_workspace.py",
        "scripts/external_alpha_operator_note_template.py",
        "python scripts/prepare_external_alpha_private_pilot_workspace.py",
        "python scripts/prepare_external_alpha_first_recipient_send_workspace.py",
        "python scripts/check_external_alpha_first_recipient_send_preflight.py",
        "python scripts/check_external_alpha_first_recipient_manual_send_go.py",
        "python scripts/check_external_alpha_first_recipient_pre_send_sequence.py",
        "python scripts/check_external_alpha_first_recipient_operator_status.py",
        "CHECK_RELEASE_CHAIN",
        "release_sources_match_current_manifest",
        "controlled check IDs",
        "python scripts/check_external_alpha_first_recipient_post_send_sequence.py",
        "--private-workspace-dir <private-workspace-dir>",
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "python scripts/verify_agent_platform_browser_flow.py",
        "npm install --prefix C:\\tmp\\cambrian-playwright-deps playwright",
        "python scripts/prepare_external_alpha_handoff.py",
        "python scripts/check_external_alpha_send_ready.py",
        "python scripts/check_external_alpha_pilot_ready.py",
        "python scripts/check_external_alpha_dispatch_record.py",
        "python scripts/check_external_alpha_recipient_checkpoint.py",
        "python scripts/check_external_alpha_pilot_review.py",
        "python scripts/check_external_alpha_pilot_evidence.py",
        "python scripts/check_external_alpha_pilot_decision.py",
        "python scripts/check_external_alpha_pilot_iteration.py",
        "python scripts/audit_external_alpha_send_chain.py",
        "python scripts/audit_external_alpha_operator_send_bypass.py",
        "--verify-pilot-ready",
        "--verify-dispatch-record",
        "--verify-recipient-checkpoint",
        "--verify-pilot-review",
        "--verify-pilot-evidence",
        "--verify-pilot-decision",
        "--verify-pilot-iteration",
        "cambrian-agent-platform-external-alpha-pilot-ready.md",
        "cambrian-agent-platform-external-alpha-pilot-ready.json",
        "cambrian-agent-platform-external-alpha-pilot-dispatch.md",
        "cambrian-agent-platform-external-alpha-dispatch-record.md",
        "cambrian-agent-platform-external-alpha-dispatch-record.json",
        "cambrian-agent-platform-external-alpha-recipient-checkpoint.md",
        "cambrian-agent-platform-external-alpha-recipient-checkpoint.json",
        "cambrian-agent-platform-external-alpha-pilot-review.md",
        "cambrian-agent-platform-external-alpha-pilot-review.json",
        "cambrian-agent-platform-external-alpha-pilot-evidence.md",
        "cambrian-agent-platform-external-alpha-pilot-evidence.json",
        "cambrian-agent-platform-external-alpha-pilot-decision.md",
        "cambrian-agent-platform-external-alpha-pilot-decision.json",
        "cambrian-agent-platform-external-alpha-pilot-iteration.md",
        "cambrian-agent-platform-external-alpha-pilot-iteration.json",
        "cambrian-agent-platform-external-alpha-bundle-smoke-receipt.json",
        "cambrian-agent-platform-external-alpha-private-workspace-rehearsal-receipt.json",
        "cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json",
        "cambrian-agent-platform-external-alpha-post-send-rehearsal-receipt.json",
        "cambrian-agent-platform-external-alpha-pilot-learning-rehearsal-receipt.json",
        "cambrian-agent-platform-external-alpha-operator-dispatch-packet.md",
        "cambrian-agent-platform-external-alpha-operator-dispatch-packet.json",
        "cambrian-agent-platform-external-alpha-operator-send-bypass-audit.json",
        "--receipt",
        "--verify-receipt",
        "--verify-send-ready",
        "cambrian-agent-platform-external-alpha-handoff.md",
        "cambrian-agent-platform-external-alpha-handoff.json",
        "cambrian-agent-platform-external-alpha-send-ready.md",
        "cambrian-agent-platform-external-alpha-send-ready.json",
        "dist/cambrian-agent-platform-external-alpha.zip",
        "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json",
        "EXTERNAL_ALPHA_TRUST_REPORT.md",
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
        "external_alpha_builder_gold_path_share_receipt.json",
        "gold path receipt 다운로드",
        "dispatch_execution_policy",
        "script_sends_to_recipient=false",
        "manual_operator_dispatch_required=true",
        "release version",
        "boundaries",
        "forbidden_path_parts",
        "manifest.files의 byte/sha256",
        "진단 privacy 플래그",
        "safe_to_share",
        "redaction_checks",
        "support_summary",
        "verified_checks",
        "browser_smoke_wrapper_checked",
        "browser_wrapper",
        "generated_at",
        "browser : pass wrapper help",
        "receipt_body_sha256",
        "repeated receipt generation",
        "handoff_receipt_body_matches_current_receipt",
        "receipt_checks",
        "docs/launch/PILOT_ISSUE_INTAKE.md",
        "docs/launch/PILOT_FEEDBACK_FORM.md",
        "docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md",
        "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
        "python scripts/prepare_external_alpha_download_landing.py",
        "python scripts/prepare_external_alpha_public_download_site.py",
        "python scripts/package_external_alpha_public_download_site.py",
        "python scripts/check_external_alpha_public_deploy_candidate.py",
        "python scripts/check_external_alpha_cloudflare_pages_deploy_ready.py",
        "python scripts/check_external_alpha_cloudflare_credentials.py",
        "python scripts/launch_external_alpha_cloudflare_pages.py",
        "python scripts/check_external_alpha_public_launch_doctor.py",
        "python scripts/run_external_alpha_public_launch_sequence.py",
        "python scripts/finalize_external_alpha_public_launch_url.py",
        "python scripts/verify_external_alpha_public_download_site_url.py",
        "python scripts/prepare_external_alpha_public_share_packet.py",
        "python scripts/prepare_external_alpha_public_launch_handoff.py",
        "cambrian-public-site.zip",
        "PUBLIC_LAUNCH_SEQUENCE_READY",
        ".env",
        ".cambrian",
        "proof, 성능, 성공률",
        "python -m pip install -e .",
    ]:
        assert phrase in text


def test_external_alpha_release_allowlist_is_safe() -> None:
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in INCLUDED_FILES
    assert "START_HERE_EXTERNAL_ALPHA.md" in INCLUDED_FILES
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in INCLUDED_FILES
    assert SUPPORT_PACKET_NAME in INCLUDED_FILES
    assert "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat" in INCLUDED_FILES
    assert "docs/launch/PILOT_ISSUE_INTAKE.md" in INCLUDED_FILES
    assert "docs/launch/PILOT_FEEDBACK_FORM.md" in INCLUDED_FILES
    assert "docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md" in INCLUDED_FILES
    assert "web/platform/index.html" in INCLUDED_FILES
    assert "scripts/verify_platform_alpha.py" in INCLUDED_FILES
    assert "scripts/verify_external_alpha_release.py" in INCLUDED_FILES
    assert "scripts/verify_agent_platform_browser_flow.py" in INCLUDED_FILES
    assert "scripts/smoke_external_alpha_release_bundle.py" in INCLUDED_FILES
    assert "scripts/smoke_external_alpha_manual_send_go_rehearsal.py" in INCLUDED_FILES
    assert "scripts/smoke_external_alpha_post_send_checkpoint.py" in INCLUDED_FILES
    assert "scripts/smoke_external_alpha_pilot_learning_loop.py" in INCLUDED_FILES
    assert "scripts/smoke_external_alpha_private_pilot_workspace.py" in INCLUDED_FILES
    assert "scripts/external_alpha_operator_note_template.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_private_pilot_workspace.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_first_recipient_send_workspace.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_first_recipient_send_preflight.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_first_recipient_manual_send_go.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_first_recipient_pre_send_sequence.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_first_recipient_post_send_sequence.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_first_recipient_operator_status.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_operator_dispatch_packet.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_handoff.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_send_ready.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_pilot_ready.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_dispatch_record.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_recipient_checkpoint.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_pilot_review.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_pilot_evidence.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_pilot_decision.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_pilot_iteration.py" in INCLUDED_FILES
    assert "scripts/audit_external_alpha_send_chain.py" in INCLUDED_FILES
    assert "scripts/audit_external_alpha_operator_send_bypass.py" in INCLUDED_FILES
    assert "scripts/collect_external_alpha_diagnostics.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_download_landing.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_public_download_site.py" in INCLUDED_FILES
    assert "scripts/package_external_alpha_public_download_site.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_public_deploy_candidate.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_cloudflare_pages_deploy_ready.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_cloudflare_credentials.py" in INCLUDED_FILES
    assert "scripts/launch_external_alpha_cloudflare_pages.py" in INCLUDED_FILES
    assert "scripts/check_external_alpha_public_launch_doctor.py" in INCLUDED_FILES
    assert "scripts/run_external_alpha_public_launch_sequence.py" in INCLUDED_FILES
    assert "scripts/finalize_external_alpha_public_launch_url.py" in INCLUDED_FILES
    assert "scripts/verify_external_alpha_public_download_site_url.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_public_share_packet.py" in INCLUDED_FILES
    assert "scripts/prepare_external_alpha_public_launch_handoff.py" in INCLUDED_FILES
    assert "docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md" in INCLUDED_FILES

    for relative in INCLUDED_FILES:
        assert (ROOT / relative).is_file(), relative
        parts = set(Path(relative).parts)
        assert not parts.intersection(FORBIDDEN_PATH_PARTS), relative


def test_external_alpha_release_bundle_builds_and_verifies(tmp_path: Path) -> None:
    result = build_release(tmp_path)
    staging_root = Path(result["staging_root"])
    zip_path = Path(result["zip_path"])
    manifest_path = Path(result["manifest_path"])

    assert result["status"] == "pass"
    assert staging_root.is_dir()
    assert zip_path.is_file()
    assert manifest_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in manifest["files"]}

    assert manifest["release_name"] == RELEASE_SLUG
    assert set(RELEASE_BOUNDARIES).issubset(set(manifest["boundaries"]))
    assert manifest["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    assert set(FORBIDDEN_PATH_PARTS).issubset(set(manifest["forbidden_path_parts"]))
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in paths
    assert "START_HERE_EXTERNAL_ALPHA.md" in paths
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in paths
    assert SUPPORT_PACKET_NAME in paths
    assert "docs/launch/PILOT_ISSUE_INTAKE.md" in paths
    assert "docs/launch/PILOT_FEEDBACK_FORM.md" in paths
    assert "docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md" in paths
    assert "web/platform/index.html" in paths
    assert "scripts/verify_agent_platform_browser_flow.py" in paths
    assert "scripts/smoke_external_alpha_release_bundle.py" in paths
    assert "scripts/smoke_external_alpha_manual_send_go_rehearsal.py" in paths
    assert "scripts/smoke_external_alpha_post_send_checkpoint.py" in paths
    assert "scripts/smoke_external_alpha_pilot_learning_loop.py" in paths
    assert "scripts/smoke_external_alpha_private_pilot_workspace.py" in paths
    assert "scripts/external_alpha_operator_note_template.py" in paths
    assert "scripts/prepare_external_alpha_private_pilot_workspace.py" in paths
    assert "scripts/prepare_external_alpha_first_recipient_send_workspace.py" in paths
    assert "scripts/check_external_alpha_first_recipient_send_preflight.py" in paths
    assert "scripts/check_external_alpha_first_recipient_manual_send_go.py" in paths
    assert "scripts/check_external_alpha_first_recipient_pre_send_sequence.py" in paths
    assert "scripts/check_external_alpha_first_recipient_post_send_sequence.py" in paths
    assert "scripts/check_external_alpha_first_recipient_operator_status.py" in paths
    assert "scripts/prepare_external_alpha_operator_dispatch_packet.py" in paths
    assert "scripts/audit_external_alpha_send_chain.py" in paths
    assert "scripts/audit_external_alpha_operator_send_bypass.py" in paths
    assert "scripts/prepare_external_alpha_download_landing.py" in paths
    assert "scripts/prepare_external_alpha_public_download_site.py" in paths
    assert "scripts/package_external_alpha_public_download_site.py" in paths
    assert "scripts/check_external_alpha_public_deploy_candidate.py" in paths
    assert "scripts/check_external_alpha_cloudflare_pages_deploy_ready.py" in paths
    assert "scripts/check_external_alpha_cloudflare_credentials.py" in paths
    assert "scripts/launch_external_alpha_cloudflare_pages.py" in paths
    assert "scripts/check_external_alpha_public_launch_doctor.py" in paths
    assert "scripts/run_external_alpha_public_launch_sequence.py" in paths
    assert "scripts/finalize_external_alpha_public_launch_url.py" in paths
    assert "scripts/verify_external_alpha_public_download_site_url.py" in paths
    assert "scripts/prepare_external_alpha_public_share_packet.py" in paths
    assert "scripts/prepare_external_alpha_public_launch_handoff.py" in paths
    assert manifest["bundle_manifest"]["path"] == "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json"
    assert manifest["bundle_manifest"]["hash_policy"] == "self_hash_omitted"
    assert manifest["archive"]["sha256"] == result["archive_sha256"]
    assert TRUST_REPORT_NAME in paths

    for path in paths:
        parts = set(Path(path).parts)
        assert not parts.intersection(FORBIDDEN_PATH_PARTS), path

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        assert f"{RELEASE_SLUG}/QUICKSTART_EXTERNAL_ALPHA.md" in names
        assert f"{RELEASE_SLUG}/START_HERE_EXTERNAL_ALPHA.md" in names
        assert f"{RELEASE_SLUG}/RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in names
        assert f"{RELEASE_SLUG}/{SUPPORT_PACKET_NAME}" in names
        assert f"{RELEASE_SLUG}/web/platform/index.html" in names
        assert f"{RELEASE_SLUG}/scripts/verify_agent_platform_browser_flow.py" in names
        assert f"{RELEASE_SLUG}/scripts/smoke_external_alpha_release_bundle.py" in names
        assert f"{RELEASE_SLUG}/scripts/smoke_external_alpha_manual_send_go_rehearsal.py" in names
        assert f"{RELEASE_SLUG}/scripts/smoke_external_alpha_post_send_checkpoint.py" in names
        assert f"{RELEASE_SLUG}/scripts/smoke_external_alpha_pilot_learning_loop.py" in names
        assert f"{RELEASE_SLUG}/scripts/smoke_external_alpha_private_pilot_workspace.py" in names
        assert f"{RELEASE_SLUG}/scripts/external_alpha_operator_note_template.py" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_private_pilot_workspace.py" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_first_recipient_send_workspace.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_first_recipient_send_preflight.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_first_recipient_manual_send_go.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_first_recipient_pre_send_sequence.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_first_recipient_post_send_sequence.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_first_recipient_operator_status.py" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_operator_dispatch_packet.py" in names
        assert f"{RELEASE_SLUG}/scripts/audit_external_alpha_send_chain.py" in names
        assert f"{RELEASE_SLUG}/scripts/audit_external_alpha_operator_send_bypass.py" in names
        assert f"{RELEASE_SLUG}/docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_download_landing.py" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_public_download_site.py" in names
        assert f"{RELEASE_SLUG}/scripts/package_external_alpha_public_download_site.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_public_deploy_candidate.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_cloudflare_pages_deploy_ready.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_cloudflare_credentials.py" in names
        assert f"{RELEASE_SLUG}/scripts/launch_external_alpha_cloudflare_pages.py" in names
        assert f"{RELEASE_SLUG}/scripts/check_external_alpha_public_launch_doctor.py" in names
        assert f"{RELEASE_SLUG}/scripts/run_external_alpha_public_launch_sequence.py" in names
        assert f"{RELEASE_SLUG}/scripts/finalize_external_alpha_public_launch_url.py" in names
        assert f"{RELEASE_SLUG}/scripts/verify_external_alpha_public_download_site_url.py" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_public_share_packet.py" in names
        assert f"{RELEASE_SLUG}/scripts/prepare_external_alpha_public_launch_handoff.py" in names
        assert f"{RELEASE_SLUG}/EXTERNAL_ALPHA_BUNDLE_MANIFEST.json" in names
        assert f"{RELEASE_SLUG}/{TRUST_REPORT_NAME}" in names
        assert not any("/.env" in name or "/.cambrian/" in name or "/.pytest_tmp/" in name for name in names)
        trust_report = archive.read(f"{RELEASE_SLUG}/{TRUST_REPORT_NAME}").decode("utf-8")
        assert "External Alpha Trust Report" in trust_report
        assert "Defensible Alpha" in trust_report
        assert "verified promotion audit lineage" in trust_report
        assert "Dispatch Execution Policy" in trust_report
        assert "script_sends_to_recipient: False" in trust_report
        assert "manual_operator_dispatch_required: True" in trust_report
        assert "max_recipients_per_record: 1" in trust_report
        assert "python scripts/audit_external_alpha_operator_send_bypass.py" in trust_report
        assert "python scripts/check_external_alpha_cloudflare_credentials.py" in trust_report
        assert "python scripts/run_external_alpha_public_launch_sequence.py" in trust_report
        assert "python scripts/check_external_alpha_first_recipient_operator_status.py" in trust_report
        bundle_manifest = json.loads(archive.read(f"{RELEASE_SLUG}/EXTERNAL_ALPHA_BUNDLE_MANIFEST.json").decode("utf-8"))
        assert bundle_manifest["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    verify_result = subprocess.run(
        [sys.executable, "scripts/verify_platform_alpha.py"],
        cwd=staging_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert verify_result.returncode == 0, verify_result.stdout + verify_result.stderr
    assert "Cambrian Agent Platform alpha verification passed." in verify_result.stdout


def test_external_alpha_release_zip_verifier_passes(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    verify_result = verify_release(
        zip_path=Path(build_result["zip_path"]),
        manifest_path=Path(build_result["manifest_path"]),
    )

    assert verify_result["status"] == "pass"
    assert verify_result["archive_sha256"] == build_result["archive_sha256"]
    assert verify_result["release_version"] == "0.1.0-alpha"
    assert verify_result["release_sources_match_current_manifest"] is True
    assert verify_result["current_source_manifest"]["checked"] is True
    assert verify_result["current_source_manifest"]["failed_checks"] == []
    assert verify_result["boundary_count"] >= len(RELEASE_BOUNDARIES)
    assert verify_result["trust_report"] == TRUST_REPORT_NAME
    assert verify_result["diagnostics_status"] == "pass"
    assert verify_result["diagnostics_safe_to_share"] is True
    assert verify_result["diagnostics_next_action"] == SUPPORT_NEXT_ACTION
    assert ".env" in verify_result["diagnostics_do_not_share"]
    assert "raw AI reply" in verify_result["diagnostics_do_not_share"]
    assert verify_result["browser_wrapper"]["status"] == "pass"
    assert verify_result["browser_wrapper"]["script"] == "verify_agent_platform_browser_flow.py"
    assert verify_result["browser_wrapper"]["mode"] == "help_only"
    assert verify_result["browser_wrapper"]["requires_playwright_for_full_run"] is True
    if sys.platform == "win32":
        assert verify_result["batch_rehearsal"]["status"] == "pass"
        assert verify_result["batch_rehearsal"]["verify_batch"] == "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat"
        assert (
            verify_result["batch_rehearsal"]["diagnostics_batch"]
            == "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat"
        )
    else:
        assert verify_result["batch_rehearsal"]["status"] == "skipped"


def test_external_alpha_release_verifier_detects_current_source_manifest_drift(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    relative = "scripts/example.py"
    source_file = source_root / relative
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"current source\n")
    stale_data = b"stale release\n"
    manifest = {
        "files": [
            {
                "path": relative,
                "bytes": len(stale_data),
                "sha256": hashlib.sha256(stale_data).hexdigest(),
            }
        ]
    }

    checks = _current_source_manifest_checks(manifest, source_root=source_root, included_files=(relative,))

    assert checks["checks"]["current_source_manifest_checked"] is True
    assert checks["checks"]["current_source_bytes_match_manifest"] is False
    assert checks["checks"]["current_source_sha256_match_manifest"] is False
    assert checks["byte_mismatches"] == [relative]
    assert checks["sha256_mismatches"] == [relative]
    with pytest.raises(ReleaseVerificationError, match="current source manifest verification failed"):
        _verify_current_source_manifest(manifest, source_root=source_root, included_files=(relative,))


def test_external_alpha_release_verifier_rejects_broken_browser_wrapper_help(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    source_zip = Path(build_result["zip_path"])
    source_manifest = Path(build_result["manifest_path"])
    tampered_zip = tmp_path / "tampered-browser-wrapper.zip"
    tampered_manifest = tmp_path / "tampered-browser-wrapper.manifest.json"
    wrapper_path = "scripts/verify_agent_platform_browser_flow.py"
    wrapper_entry = f"{RELEASE_SLUG}/{wrapper_path}"
    broken_wrapper = b"print('broken browser smoke wrapper')\n"

    with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.is_dir():
                continue
            data = broken_wrapper if info.filename == wrapper_entry else source.read(info.filename)
            target.writestr(info, data)

    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == wrapper_path:
            entry["bytes"] = len(broken_wrapper)
            entry["sha256"] = hashlib.sha256(broken_wrapper).hexdigest()
            break
    else:
        raise AssertionError(f"missing manifest entry: {wrapper_path}")

    archive_data = tampered_zip.read_bytes()
    manifest["archive"]["path"] = tampered_zip.name
    manifest["archive"]["bytes"] = len(archive_data)
    manifest["archive"]["sha256"] = hashlib.sha256(archive_data).hexdigest()
    tampered_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="browser smoke wrapper help"):
        verify_release(zip_path=tampered_zip, manifest_path=tampered_manifest)


def test_external_alpha_release_verifier_requires_share_safe_diagnostics(tmp_path: Path) -> None:
    report = {
        "schema_version": "external_alpha_diagnostics_v0_1",
        "status": "pass",
        "safe_to_share": False,
        "privacy": {
            "environment_variables_collected": False,
            "env_files_read": False,
            "secret_values_collected": False,
            "user_documents_collected": False,
        },
        "redaction_checks": {
            "bundle_root_path_redacted": True,
            "home_path_redacted": True,
            "environment_variables_omitted": True,
            "env_files_omitted": True,
            "secret_values_omitted": True,
            "user_documents_omitted": True,
        },
        "support_summary": {
            "status": "pass",
            "safe_to_share": True,
            "platform_verification_status": "pass",
            "missing_required_files": [],
            "present_forbidden_top_level_paths": [],
            "next_action": SUPPORT_NEXT_ACTION,
            "do_not_share": DO_NOT_SHARE,
        },
    }

    with pytest.raises(ReleaseVerificationError, match="safe_to_share"):
        _verify_diagnostics_report(report, tmp_path)

    report["safe_to_share"] = True
    report["redaction_checks"]["secret_values_omitted"] = False

    with pytest.raises(ReleaseVerificationError, match="redaction check"):
        _verify_diagnostics_report(report, tmp_path)


def test_external_alpha_release_verifier_requires_support_summary(tmp_path: Path) -> None:
    report = {
        "schema_version": "external_alpha_diagnostics_v0_1",
        "status": "pass",
        "safe_to_share": True,
        "privacy": {
            "environment_variables_collected": False,
            "env_files_read": False,
            "secret_values_collected": False,
            "user_documents_collected": False,
        },
        "redaction_checks": {
            "bundle_root_path_redacted": True,
            "home_path_redacted": True,
            "environment_variables_omitted": True,
            "env_files_omitted": True,
            "secret_values_omitted": True,
            "user_documents_omitted": True,
        },
        "support_summary": {
            "status": "fail",
            "safe_to_share": True,
            "platform_verification_status": "pass",
            "missing_required_files": [],
            "present_forbidden_top_level_paths": [],
            "next_action": SUPPORT_NEXT_ACTION,
            "do_not_share": DO_NOT_SHARE,
        },
    }

    with pytest.raises(ReleaseVerificationError, match="support_summary.status"):
        _verify_diagnostics_report(report, tmp_path)

    report["support_summary"]["status"] = "pass"
    report["support_summary"]["missing_required_files"] = ["web/platform/index.html"]

    with pytest.raises(ReleaseVerificationError, match="누락 파일"):
        _verify_diagnostics_report(report, tmp_path)

    report["support_summary"]["missing_required_files"] = []
    report["support_summary"]["next_action"] = ""

    with pytest.raises(ReleaseVerificationError, match="next_action"):
        _verify_diagnostics_report(report, tmp_path)

    report["support_summary"]["next_action"] = SUPPORT_NEXT_ACTION
    report["support_summary"]["do_not_share"] = ["browser localStorage"]

    with pytest.raises(ReleaseVerificationError, match="공유 금지 안내"):
        _verify_diagnostics_report(report, tmp_path)


def test_external_alpha_release_cli_prints_trust_summary(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    receipt_path = tmp_path / "release-verification-receipt.json"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_external_alpha_release.py",
            "--zip",
            build_result["zip_path"],
            "--manifest",
            build_result["manifest_path"],
            "--receipt",
            str(receipt_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=90,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert receipt_path.is_file()
    assert "[PASS] external alpha release verification" in output
    assert "release : 0.1.0-alpha" in output
    assert f"policy  : {len(RELEASE_BOUNDARIES)} boundaries verified" in output
    assert f"trust   : {TRUST_REPORT_NAME} verified" in output
    assert "source  : current manifest matched=True" in output
    assert "diag    : pass privacy-safe share-safe" in output
    assert "share   : diagnostics safe_to_share=True" in output
    assert f"support : {SUPPORT_NEXT_ACTION}" in output
    assert "browser : pass wrapper help" in output
    assert f"receipt : {receipt_path.resolve()}" in output
    if sys.platform == "win32":
        assert "batch   : pass" in output
    else:
        assert "batch   : skipped" in output
    assert "extract : temporary" in output

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "external_alpha_release_verification_receipt_v0_1"
    assert receipt["status"] == "pass"
    assert receipt["safe_to_share"] is True
    assert receipt["privacy"]["absolute_paths_included"] is False
    assert isinstance(receipt["receipt_body_sha256"], str)
    assert len(receipt["receipt_body_sha256"]) == 64
    assert receipt["receipt_body_sha256"] == _receipt_body_sha256(receipt)
    assert all(receipt["receipt_checks"].values())
    assert all(receipt["verified_checks"].values())
    assert receipt["verified_checks"]["archive_sha256_matched"] is True
    assert receipt["verified_checks"]["manifest_files_sha256_matched"] is True
    assert receipt["verified_checks"]["trust_report_verified"] is True
    assert receipt["verified_checks"]["current_sources_match_release_manifest"] is True
    assert receipt["verified_checks"]["diagnostics_share_safety_verified"] is True
    assert receipt["verified_checks"]["browser_smoke_wrapper_checked"] is True
    assert receipt["receipt_checks"]["absolute_paths_omitted"] is True
    assert receipt["receipt_checks"]["do_not_share_guidance_present"] is True
    assert receipt["receipt_checks"]["browser_wrapper_check_present"] is True
    assert receipt["receipt_checks"]["receipt_body_hash_matched"] is True
    assert receipt["receipt_checks"]["verified_checks_all_true"] is True
    assert receipt["release"]["version"] == "0.1.0-alpha"
    assert receipt["release"]["archive_sha256"] == build_result["archive_sha256"]
    assert receipt["release"]["release_sources_match_current_manifest"] is True
    assert receipt["diagnostics"]["safe_to_share"] is True
    assert receipt["diagnostics"]["next_action"] == SUPPORT_NEXT_ACTION
    assert receipt["browser_wrapper"]["status"] == "pass"
    assert receipt["browser_wrapper"]["script"] == "verify_agent_platform_browser_flow.py"
    assert receipt["browser_wrapper"]["mode"] == "help_only"
    assert receipt["browser_wrapper"]["requires_playwright_for_full_run"] is True
    assert ".env" in receipt["diagnostics"]["do_not_share"]
    assert "raw AI reply" in receipt["support_summary"]["do_not_share"]
    timestamp_changed_receipt = json.loads(json.dumps(receipt, ensure_ascii=False))
    timestamp_changed_receipt["generated_at"] = "2099-01-01T00:00:00+00:00"
    assert _receipt_body_sha256(timestamp_changed_receipt) == receipt["receipt_body_sha256"]
    serialized_receipt = json.dumps(receipt, ensure_ascii=False)
    assert str(ROOT) not in serialized_receipt
    assert str(tmp_path) not in serialized_receipt

    tampered_receipt = json.loads(json.dumps(receipt, ensure_ascii=False))
    tampered_receipt["release"]["file_count"] = 0
    tampered_receipt["receipt_checks"] = {
        **tampered_receipt["receipt_checks"],
        "receipt_body_hash_matched": tampered_receipt["receipt_body_sha256"]
        == _receipt_body_sha256(tampered_receipt),
    }
    with pytest.raises(ReleaseVerificationError, match="영수증 안전 점검 실패"):
        _verify_shareable_receipt(tampered_receipt)

    tampered_browser_receipt = json.loads(json.dumps(receipt, ensure_ascii=False))
    tampered_browser_receipt["browser_wrapper"]["status"] = "fail"
    tampered_browser_receipt["receipt_body_sha256"] = _receipt_body_sha256(tampered_browser_receipt)
    with pytest.raises(ReleaseVerificationError, match="browser_wrapper verification"):
        _verify_shareable_receipt(tampered_browser_receipt)


def test_external_alpha_receipt_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    receipt_path = tmp_path / "release-verification-receipt.json"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    create_result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_external_alpha_release.py",
            "--zip",
            build_result["zip_path"],
            "--manifest",
            build_result["manifest_path"],
            "--receipt",
            str(receipt_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=90,
    )
    assert create_result.returncode == 0, create_result.stdout + create_result.stderr

    receipt = verify_shareable_receipt_file(receipt_path)
    assert receipt["status"] == "pass"

    verify_result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_external_alpha_release.py",
            "--verify-receipt",
            str(receipt_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )
    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha receipt verification" in verify_output
    assert "receipt :" in verify_output
    assert "browser : pass" in verify_output
    assert f"support : {SUPPORT_NEXT_ACTION}" in verify_output

    tampered_path = tmp_path / "tampered-receipt.json"
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["release"]["archive_sha256"] = "0" * 64
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_external_alpha_release.py",
            "--verify-receipt",
            str(tampered_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert tampered_result.returncode == 1
    assert "본문 해시가 일치하지 않습니다" in tampered_result.stdout + tampered_result.stderr


def test_external_alpha_release_verifier_rejects_missing_policy_boundary(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    zip_path = Path(build_result["zip_path"])
    manifest_path = Path(build_result["manifest_path"])
    tampered_path = tmp_path / "tampered.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["boundaries"] = [
        boundary for boundary in manifest["boundaries"] if boundary != "단순 MVP가 아니라 Defensible Alpha다."
    ]
    tampered_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="릴리즈 경계 누락"):
        verify_release(zip_path=zip_path, manifest_path=tampered_path)


def test_external_alpha_release_verifier_rejects_dispatch_policy_tampering(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    zip_path = Path(build_result["zip_path"])
    manifest_path = Path(build_result["manifest_path"])
    tampered_path = tmp_path / "tampered-dispatch-policy.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    tampered_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="dispatch_execution_policy 불일치"):
        verify_release(zip_path=zip_path, manifest_path=tampered_path)


def test_external_alpha_release_verifier_rejects_file_hash_mismatch(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    source_zip = Path(build_result["zip_path"])
    source_manifest = Path(build_result["manifest_path"])
    tampered_zip = tmp_path / "tampered-file-hash.zip"
    tampered_manifest = tmp_path / "tampered-file-hash.manifest.json"

    with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.is_dir():
                continue
            data = source.read(info.filename)
            if info.filename == f"{RELEASE_SLUG}/START_HERE_EXTERNAL_ALPHA.md":
                data = data + b"\n# tampered\n"
            target.writestr(info, data)

    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    archive_data = tampered_zip.read_bytes()
    manifest["archive"]["path"] = tampered_zip.name
    manifest["archive"]["bytes"] = len(archive_data)
    manifest["archive"]["sha256"] = hashlib.sha256(archive_data).hexdigest()
    tampered_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="파일 byte 크기 불일치|파일 sha256 불일치"):
        verify_release(zip_path=tampered_zip, manifest_path=tampered_manifest)


def test_external_alpha_release_verifier_rejects_tampered_trust_report(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    source_zip = Path(build_result["zip_path"])
    source_manifest = Path(build_result["manifest_path"])
    tampered_zip = tmp_path / "tampered-trust-report.zip"
    tampered_manifest = tmp_path / "tampered-trust-report.manifest.json"

    with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.is_dir():
                continue
            data = source.read(info.filename)
            if info.filename == f"{RELEASE_SLUG}/{TRUST_REPORT_NAME}":
                data = b"# tampered\n"
            target.writestr(info, data)

    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    tampered_report = b"# tampered\n"
    for entry in manifest["files"]:
        if entry["path"] == TRUST_REPORT_NAME:
            entry["bytes"] = len(tampered_report)
            entry["sha256"] = hashlib.sha256(tampered_report).hexdigest()
    archive_data = tampered_zip.read_bytes()
    manifest["archive"]["path"] = tampered_zip.name
    manifest["archive"]["bytes"] = len(archive_data)
    manifest["archive"]["sha256"] = hashlib.sha256(archive_data).hexdigest()
    tampered_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="신뢰 리포트 문구 누락"):
        verify_release(zip_path=tampered_zip, manifest_path=tampered_manifest)


def test_external_alpha_release_verifier_rejects_tampered_support_packet(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    source_zip = Path(build_result["zip_path"])
    source_manifest = Path(build_result["manifest_path"])
    tampered_zip = tmp_path / "tampered-support-packet.zip"
    tampered_manifest = tmp_path / "tampered-support-packet.manifest.json"

    with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(tampered_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.is_dir():
                continue
            data = source.read(info.filename)
            if info.filename == f"{RELEASE_SLUG}/{SUPPORT_PACKET_NAME}":
                data = b"# tampered\n"
            target.writestr(info, data)

    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    tampered_packet = b"# tampered\n"
    for entry in manifest["files"]:
        if entry["path"] == SUPPORT_PACKET_NAME:
            entry["bytes"] = len(tampered_packet)
            entry["sha256"] = hashlib.sha256(tampered_packet).hexdigest()
    archive_data = tampered_zip.read_bytes()
    manifest["archive"]["path"] = tampered_zip.name
    manifest["archive"]["bytes"] = len(archive_data)
    manifest["archive"]["sha256"] = hashlib.sha256(archive_data).hexdigest()
    tampered_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ReleaseVerificationError, match="support packet phrase missing"):
        verify_release(zip_path=tampered_zip, manifest_path=tampered_manifest)
