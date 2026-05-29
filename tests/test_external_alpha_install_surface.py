import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_DOC = ROOT / "START_HERE_EXTERNAL_ALPHA.md"
QUICKSTART_DOC = ROOT / "QUICKSTART_EXTERNAL_ALPHA.md"
PROMPT_DOC = ROOT / "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md"
SUPPORT_PACKET = ROOT / "EXTERNAL_ALPHA_SUPPORT_PACKET.md"
START_BAT = ROOT / "START_CAMBRIAN_AGENT_PLATFORM.bat"
VERIFY_BAT = ROOT / "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat"
DIAGNOSTICS_BAT = ROOT / "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_platform_alpha.py"
DIAGNOSTICS_SCRIPT = ROOT / "scripts" / "collect_external_alpha_diagnostics.py"
RC_INSTALL_GUIDE = ROOT / "docs" / "release" / "RC_INSTALL_GUIDE.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_ascii_readable(text: str) -> None:
    assert text.isascii()
    for marker in ["占", "嚥", "癒", "袁", "筌", "吏", "留", "?쒓", "?몃", "?꾨", "?뚰", "?뺤", "?ㅼ"]:
        assert marker not in text


def test_external_alpha_start_surface_exists() -> None:
    assert START_DOC.exists()
    assert QUICKSTART_DOC.exists()
    assert PROMPT_DOC.exists()
    assert SUPPORT_PACKET.exists()
    assert START_BAT.exists()
    assert VERIFY_BAT.exists()
    assert DIAGNOSTICS_BAT.exists()
    assert VERIFY_SCRIPT.exists()
    assert DIAGNOSTICS_SCRIPT.exists()

    start_doc = _read(START_DOC)
    quickstart_doc = _read(QUICKSTART_DOC)
    prompt_doc = _read(PROMPT_DOC)
    support_packet = _read(SUPPORT_PACKET)
    start_bat = _read(START_BAT)
    verify_bat = _read(VERIFY_BAT)
    diagnostics_bat = _read(DIAGNOSTICS_BAT)

    for doc in [quickstart_doc, start_doc, prompt_doc, support_packet]:
        _assert_ascii_readable(doc)

    for phrase in [
        "Cambrian External Alpha Quickstart",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "Builder Golden Path",
        "external_alpha_builder_gold_path_share_receipt.json",
        "safe_to_share: true",
        "Do not send",
        "Confirmed: opened Cambrian and completed the Builder Golden Path.",
    ]:
        assert phrase in quickstart_doc

    for phrase in [
        "Cambrian Agent Platform External Alpha",
        "QUICKSTART_EXTERNAL_ALPHA.md",
        "Defensible Alpha",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
        "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "Builder Golden Path",
        "manual_no_api",
        "manual_run_receipt_v0_1",
        "manual_review_only",
        "promotion audit record",
        "private_download_hub_to_manual_runner",
        "external_alpha_builder_gold_path_share_receipt.json",
        "safe_to_share: true",
        "proof_claim_allowed: false",
        "success_rate_claim_allowed: false",
        "sale_ready: false",
        "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
        ".venv\\Scripts\\python.exe -m pip install -e .",
        ".venv\\Scripts\\python.exe scripts/verify_platform_alpha.py",
        ".venv\\Scripts\\python.exe scripts/collect_external_alpha_diagnostics.py",
        "python scripts/verify_agent_platform_browser_flow.py",
        "npm install --prefix C:\\tmp\\cambrian-playwright-deps playwright",
        "python scripts/build_external_alpha_release.py",
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
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "python scripts/check_external_alpha_first_recipient_operator_status.py",
        "python scripts/check_external_alpha_first_recipient_pre_send_sequence.py",
        "python scripts/check_external_alpha_first_recipient_post_send_sequence.py",
        "CHECK_RELEASE_CHAIN",
        "release_sources_match_current_manifest",
        "--private-workspace-dir <private-workspace-dir>",
        "CONFIRMED",
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
        "web/platform/index.html",
        "web/assets/document-organizer.promoted.agent-pack.json",
        "web/assets/document-organizer.candidate-promotion-record.json",
        "localStorage",
        "redaction_checks",
    ]:
        assert phrase in start_doc

    assert "web\\platform\\index.html" in start_bat
    assert "scripts\\verify_platform_alpha.py" in verify_bat
    assert "scripts\\collect_external_alpha_diagnostics.py" in diagnostics_bat
    assert ".venv\\Scripts\\python.exe" in verify_bat
    assert ".venv\\Scripts\\python.exe" in diagnostics_bat
    assert "-m venv" in verify_bat
    assert "-m venv" in diagnostics_bat
    assert "-m pip install -e" in verify_bat
    assert "-m pip install -e" in diagnostics_bat
    assert "import jsonschema, yaml" in verify_bat
    assert "import jsonschema, yaml" in diagnostics_bat
    assert "%LOCALAPPDATA%\\Programs\\Python\\Python*" in verify_bat
    assert "%LOCALAPPDATA%\\Programs\\Python\\Python*" in diagnostics_bat
    assert "py -3 --version" in verify_bat
    assert "py -3 --version" in diagnostics_bat

    for phrase in [
        "Cambrian Agent Platform Prompt For Codex/Claude",
        "QUICKSTART_EXTERNAL_ALPHA.md",
        "START_HERE_EXTERNAL_ALPHA.md",
        ".venv\\Scripts\\python.exe -m pip install -e .",
        ".venv\\Scripts\\python.exe scripts/verify_platform_alpha.py",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "web/platform/index.html",
        "Builder Golden Path",
        "manual_no_api runner",
        "external_alpha_release_verification_receipt.json",
        "external_alpha_diagnostics.json",
        "external_alpha_builder_gold_path_share_receipt.json",
        "CONFIRMED",
        "Do not ask for API keys",
        "Treat this as a defensible alpha",
    ]:
        assert phrase in prompt_doc

    for phrase in [
        "External Alpha Support Packet",
        "external_alpha_release_verification_receipt.json",
        "external_alpha_diagnostics.json",
        "external_alpha_builder_gold_path_share_receipt.json",
        "safe_to_share: true",
        "redaction_checks",
        "docs/launch/PILOT_ISSUE_INTAKE.md",
        "docs/launch/PILOT_FEEDBACK_FORM.md",
        "Do Not Send",
        "raw AI replies",
    ]:
        assert phrase in support_packet


def test_external_alpha_install_guide_names_platform_path() -> None:
    guide = _read(RC_INSTALL_GUIDE)

    for phrase in [
        "Agent Platform External Alpha",
        "Defensible Alpha",
        "promotion audit lineage",
        "proof boundary",
        "START_HERE_EXTERNAL_ALPHA.md",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
        "START_CAMBRIAN_AGENT_PLATFORM.bat",
        "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
        "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
        "python scripts/verify_platform_alpha.py",
        "python scripts/collect_external_alpha_diagnostics.py",
        "python scripts/verify_agent_platform_browser_flow.py",
        "npm install --prefix C:\\tmp\\cambrian-playwright-deps playwright",
        "python scripts/build_external_alpha_release.py",
        "python scripts/smoke_external_alpha_release_bundle.py",
        "python scripts/smoke_external_alpha_manual_send_go_rehearsal.py",
        "READY_TO_MANUALLY_SEND_ONE",
        "python scripts/smoke_external_alpha_post_send_checkpoint.py",
        "python scripts/smoke_external_alpha_pilot_learning_loop.py",
        "python scripts/smoke_external_alpha_private_pilot_workspace.py",
        "python scripts/prepare_external_alpha_private_pilot_workspace.py",
        "python scripts/prepare_external_alpha_first_recipient_send_workspace.py",
        "python scripts/check_external_alpha_first_recipient_pre_send_sequence.py",
        "python scripts/check_external_alpha_first_recipient_operator_status.py",
        "CHECK_RELEASE_CHAIN",
        "release_sources_match_current_manifest",
        "controlled check IDs",
        "python scripts/check_external_alpha_first_recipient_post_send_sequence.py",
        "--private-workspace-dir <private-workspace-dir>",
        "python scripts/prepare_external_alpha_operator_dispatch_packet.py",
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
        "docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md",
        "cambrian-public-site.zip",
        "PUBLIC_LAUNCH_SEQUENCE_READY",
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
        "--receipt",
        "--verify-receipt",
        "--verify-send-ready",
        "--verify-pilot-ready",
        "--verify-dispatch-record",
        "--verify-recipient-checkpoint",
        "--verify-pilot-review",
        "--verify-pilot-evidence",
        "--verify-pilot-decision",
        "--verify-pilot-iteration",
        "dist/cambrian-agent-platform-external-alpha.zip",
        "dist/cambrian-agent-platform-external-alpha-handoff.md",
        "dist/cambrian-agent-platform-external-alpha-send-ready.md",
        "dist/cambrian-agent-platform-external-alpha-pilot-ready.md",
        "dist/cambrian-agent-platform-external-alpha-pilot-dispatch.md",
        "dist/cambrian-agent-platform-external-alpha-dispatch-record.md",
        "dist/cambrian-agent-platform-external-alpha-recipient-checkpoint.md",
        "dist/cambrian-agent-platform-external-alpha-pilot-review.md",
        "dist/cambrian-agent-platform-external-alpha-pilot-evidence.md",
        "dist/cambrian-agent-platform-external-alpha-pilot-decision.md",
        "dist/cambrian-agent-platform-external-alpha-pilot-iteration.md",
        "dist/cambrian-agent-platform-external-alpha-bundle-smoke-receipt.json",
        "dist/cambrian-agent-platform-external-alpha-private-workspace-rehearsal-receipt.json",
        "dist/cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json",
        "dist/cambrian-agent-platform-external-alpha-post-send-rehearsal-receipt.json",
        "dist/cambrian-agent-platform-external-alpha-pilot-learning-rehearsal-receipt.json",
        "dist/cambrian-agent-platform-external-alpha-operator-dispatch-packet.md",
        "dist/cambrian-agent-platform-external-alpha-operator-dispatch-packet.json",
        "docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md",
        "web/assets/document-organizer.promoted.agent-pack.json",
        "promotion audit record",
        "sale_ready: false",
        "proof_claim_allowed: false",
        "no_runtime_evidence",
        "safe_to_share: true",
        "redaction_checks: true",
        "support_summary",
    ]:
        assert phrase in guide


def test_external_alpha_verify_script_passes() -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cambrian Agent Platform alpha verification passed." in result.stdout
    assert "[PASS] required_files" in result.stdout
    assert "[PASS] agent_pack_samples" in result.stdout
    assert "[PASS] sidecar_samples" in result.stdout


def test_external_alpha_verify_batch_passes_on_windows() -> None:
    if os.name != "nt":
        return
    result = subprocess.run(
        ["cmd", "/c", str(VERIFY_BAT)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Cambrian Agent Platform alpha verification passed." in result.stdout


def test_external_alpha_diagnostics_batch_passes_on_windows(tmp_path: Path) -> None:
    if os.name != "nt":
        return
    output = tmp_path / "external_alpha_diagnostics.batch.json"
    result = subprocess.run(
        ["cmd", "/c", str(DIAGNOSTICS_BAT), "--output", str(output)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["safe_to_share"] is True
