import json
import subprocess
from pathlib import Path

from scripts.check_external_alpha_public_launch_doctor import (
    BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT,
    PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME,
    PUBLIC_LAUNCH_DOCTOR_SCHEMA_VERSION,
    READY_TO_RUN_CLOUDFLARE_LAUNCH_VERDICT,
    check_public_launch_doctor,
    verify_public_launch_doctor_receipt_file,
)
from scripts.check_external_alpha_public_deploy_candidate import check_public_deploy_candidate
from scripts.check_external_alpha_send_ready import check_send_ready


ROOT = Path(__file__).resolve().parents[1]


def test_external_alpha_public_launch_doctor_blocks_on_cloudflare_credentials(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    check_public_deploy_candidate(tmp_path)

    result = check_public_launch_doctor(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        api_token_present=False,
        account_id_present=False,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT
    assert receipt_path.name == PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME
    assert payload["schema_version"] == PUBLIC_LAUNCH_DOCTOR_SCHEMA_VERSION
    assert payload["launch_state"]["external_sharing_allowed"] is False
    assert payload["artifacts"]["cloudflare_credentials"]["verdict"] == "BLOCKED_API_TOKEN_REQUIRED"
    assert payload["artifacts"]["cloudflare_credentials"]["missing_env_vars"] == [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    assert payload["artifacts"]["cloudflare_credentials"]["does_not_deploy"] is True
    assert payload["artifacts"]["public_deploy_candidate"]["verdict"] == "PUBLIC_DEPLOY_CANDIDATE_READY"
    assert payload["artifacts"]["cloudflare_pages_preflight"]["verdict"] == "BLOCKED_API_TOKEN_REQUIRED"
    assert payload["artifacts"]["cloudflare_pages_preflight"]["api_token_present"] is False
    assert payload["artifacts"]["cloudflare_pages_preflight"]["missing_credential_env_vars"] == [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    assert payload["next_action"]["runbook"] == "docs\\release\\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md"
    assert payload["next_action"]["credential_receipt"] == (
        "cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json"
    )
    assert payload["next_action"]["required_env_vars"] == ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]
    assert payload["next_action"]["missing_env_vars"] == ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]
    assert "check_external_alpha_cloudflare_credentials.py" in payload["next_action"]["command"]
    assert all(payload["checks"].values())
    assert verify_public_launch_doctor_receipt_file(receipt_path)[
        "public_launch_doctor_body_sha256"
    ] == payload["public_launch_doctor_body_sha256"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(Path.home()) not in serialized


def test_external_alpha_public_launch_doctor_blocks_on_missing_account_id(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    check_public_deploy_candidate(tmp_path)

    result = check_public_launch_doctor(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=False,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT
    assert payload["artifacts"]["cloudflare_credentials"]["verdict"] == "BLOCKED_ACCOUNT_ID_REQUIRED"
    assert payload["artifacts"]["cloudflare_credentials"]["missing_env_vars"] == ["CLOUDFLARE_ACCOUNT_ID"]
    assert payload["artifacts"]["cloudflare_pages_preflight"]["verdict"] == "BLOCKED_ACCOUNT_ID_REQUIRED"
    assert payload["artifacts"]["cloudflare_pages_preflight"]["api_token_present"] is True
    assert payload["artifacts"]["cloudflare_pages_preflight"]["account_id_present"] is False
    assert payload["artifacts"]["cloudflare_pages_preflight"]["missing_credential_env_vars"] == [
        "CLOUDFLARE_ACCOUNT_ID"
    ]
    assert payload["next_action"]["missing_env_vars"] == ["CLOUDFLARE_ACCOUNT_ID"]
    assert "CLOUDFLARE_ACCOUNT_ID" in payload["next_action"]["command"]
    assert all(payload["checks"].values())


def test_external_alpha_public_launch_doctor_is_ready_to_run_cloudflare_launch(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    check_public_deploy_candidate(tmp_path)

    result = check_public_launch_doctor(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert result["verdict"] == READY_TO_RUN_CLOUDFLARE_LAUNCH_VERDICT
    assert payload["artifacts"]["cloudflare_credentials"]["verdict"] == "CLOUDFLARE_CREDENTIALS_READY"
    assert payload["artifacts"]["cloudflare_credentials"]["missing_env_vars"] == []
    assert payload["artifacts"]["cloudflare_pages_preflight"]["verdict"] == "READY_TO_DEPLOY_WITH_WRANGLER"
    assert payload["artifacts"]["cloudflare_pages_preflight"]["api_token_present"] is True
    assert payload["artifacts"]["cloudflare_pages_preflight"]["account_id_present"] is True
    assert "launch_external_alpha_cloudflare_pages.py" in payload["next_action"]["command"]
    assert payload["launch_state"]["external_sharing_allowed"] is False
    assert all(payload["checks"].values())


def _fake_wrangler_authenticated(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    if command[-1] == "--version":
        return subprocess.CompletedProcess(command, 0, "4.93.0\n", "")
    if command[-1] == "whoami":
        return subprocess.CompletedProcess(command, 0, "authenticated\n", "")
    raise AssertionError(f"unexpected command: {command!r}")
