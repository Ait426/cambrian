import json
import subprocess
from pathlib import Path

from scripts.check_external_alpha_cloudflare_credentials import (
    CLOUDFLARE_CREDENTIALS_READY_VERDICT,
    CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
    CLOUDFLARE_CREDENTIALS_SCHEMA_VERSION,
    check_cloudflare_credentials,
    verify_cloudflare_credentials_receipt_file,
)
from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (
    CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT,
)


ROOT = Path(__file__).resolve().parents[1]


def test_external_alpha_cloudflare_credentials_blocks_until_token_and_account_id(tmp_path: Path) -> None:
    result = check_cloudflare_credentials(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=False,
        account_id_present=False,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT
    assert receipt_path.name == CLOUDFLARE_CREDENTIALS_RECEIPT_NAME
    assert payload["schema_version"] == CLOUDFLARE_CREDENTIALS_SCHEMA_VERSION
    assert payload["credentials"]["required_env_vars"] == ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]
    assert payload["credentials"]["missing_env_vars"] == ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]
    assert payload["credentials"]["api_token_present"] is False
    assert payload["credentials"]["account_id_present"] is False
    assert payload["policy"]["does_not_deploy"] is True
    assert payload["wrangler"]["raw_output_included"] is False
    assert all(payload["checks"].values())
    assert verify_cloudflare_credentials_receipt_file(receipt_path)[
        "cloudflare_credentials_body_sha256"
    ] == payload["cloudflare_credentials_body_sha256"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(Path.home()) not in serialized


def test_external_alpha_cloudflare_credentials_blocks_until_account_id(tmp_path: Path) -> None:
    result = check_cloudflare_credentials(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=False,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT
    assert payload["credentials"]["missing_env_vars"] == ["CLOUDFLARE_ACCOUNT_ID"]
    assert payload["credentials"]["api_token_present"] is True
    assert payload["credentials"]["account_id_present"] is False
    assert "CLOUDFLARE_ACCOUNT_ID" in payload["operator_next_action"]
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_credentials_blocks_until_wrangler_auth(tmp_path: Path) -> None:
    result = check_cloudflare_credentials(
        tmp_path,
        runner=_fake_wrangler_not_authenticated,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT
    assert payload["credentials"]["missing_env_vars"] == []
    assert payload["wrangler"]["authenticated"] is False
    assert "wrangler login" in payload["operator_next_action"]
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_credentials_ready_before_launch(tmp_path: Path) -> None:
    result = check_cloudflare_credentials(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == CLOUDFLARE_CREDENTIALS_READY_VERDICT
    assert payload["credentials"]["missing_env_vars"] == []
    assert payload["credentials"]["noninteractive_deploy_credential_ready"] is True
    assert payload["wrangler"]["authenticated"] is True
    assert "launch_external_alpha_cloudflare_pages.py" in payload["operator_next_action"]
    assert all(payload["checks"].values())


def _fake_wrangler_authenticated(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return _fake_wrangler(command, authenticated=True)


def _fake_wrangler_not_authenticated(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return _fake_wrangler(command, authenticated=False)


def _fake_wrangler(command: list[str], *, authenticated: bool) -> subprocess.CompletedProcess[str]:
    if command[-1] == "--version":
        return subprocess.CompletedProcess(command, 0, "4.93.0\n", "")
    if command[-1] == "whoami":
        if authenticated:
            return subprocess.CompletedProcess(command, 0, "authenticated\n", "")
        return subprocess.CompletedProcess(command, 1, "", "not authenticated")
    raise AssertionError(f"unexpected command: {command!r}")
