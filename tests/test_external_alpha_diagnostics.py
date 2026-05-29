import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.collect_external_alpha_diagnostics import (
    DO_NOT_SHARE,
    SHARE_GUIDANCE,
    SUPPORT_NEXT_ACTION,
    collect_diagnostics,
)


ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS_SCRIPT = ROOT / "scripts" / "collect_external_alpha_diagnostics.py"
DIAGNOSTICS_BAT = ROOT / "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat"


def test_external_alpha_diagnostics_script_writes_sanitized_report(tmp_path: Path) -> None:
    output = tmp_path / "diagnostics.json"
    report = collect_diagnostics(output)

    assert report["status"] == "pass"
    assert output.is_file()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_diagnostics_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["share_guidance"] == SHARE_GUIDANCE
    assert payload["privacy"]["environment_variables_collected"] is False
    assert payload["privacy"]["env_files_read"] is False
    assert payload["privacy"]["secret_values_collected"] is False
    assert payload["privacy"]["user_documents_collected"] is False
    assert payload["platform_verification"]["status"] == "pass"
    assert payload["redaction_checks"]["bundle_root_path_redacted"] is True
    assert payload["redaction_checks"]["home_path_redacted"] is True
    assert payload["redaction_checks"]["environment_variables_omitted"] is True
    assert payload["redaction_checks"]["env_files_omitted"] is True
    assert payload["redaction_checks"]["secret_values_omitted"] is True
    assert payload["redaction_checks"]["user_documents_omitted"] is True
    assert payload["support_summary"]["status"] == "pass"
    assert payload["support_summary"]["safe_to_share"] is True
    assert payload["support_summary"]["platform_verification_status"] == "pass"
    assert payload["support_summary"]["missing_required_files"] == []
    assert payload["support_summary"]["next_action"] == SUPPORT_NEXT_ACTION
    assert payload["support_summary"]["do_not_share"] == DO_NOT_SHARE
    for required_path in [
        "QUICKSTART_EXTERNAL_ALPHA.md",
        "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
        "scripts/smoke_external_alpha_release_bundle.py",
        "scripts/smoke_external_alpha_manual_send_go_rehearsal.py",
        "scripts/smoke_external_alpha_post_send_checkpoint.py",
        "scripts/smoke_external_alpha_pilot_learning_loop.py",
        "scripts/prepare_external_alpha_operator_dispatch_packet.py",
        "scripts/check_external_alpha_first_recipient_pre_send_sequence.py",
        "scripts/check_external_alpha_first_recipient_post_send_sequence.py",
        "scripts/check_external_alpha_first_recipient_operator_status.py",
    ]:
        assert any(item["path"] == required_path and item["exists"] is True for item in payload["required_files"])

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_diagnostics_cli_passes_without_secret_env(tmp_path: Path) -> None:
    output = tmp_path / "diagnostics-cli.json"
    env = dict(os.environ)
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, str(DIAGNOSTICS_SCRIPT), "--output", str(output)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "safe_to_share: True" in result.stdout + result.stderr
    assert f"support_summary: {SUPPORT_NEXT_ACTION}" in result.stdout + result.stderr
    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["safe_to_share"] is True
    assert payload["redaction_checks"]["secret_values_omitted"] is True
    assert payload["support_summary"]["safe_to_share"] is True
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in text


def test_external_alpha_diagnostics_batch_passes_on_windows(tmp_path: Path) -> None:
    if os.name != "nt":
        return
    output = tmp_path / "diagnostics-bat.json"
    result = subprocess.run(
        ["cmd", "/c", str(DIAGNOSTICS_BAT), "--output", str(output)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["safe_to_share"] is True
