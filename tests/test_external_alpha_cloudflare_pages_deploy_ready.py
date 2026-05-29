import json
import subprocess
from pathlib import Path

import pytest

from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (
    CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
    CLOUDFLARE_PAGES_DEPLOY_READY_SCHEMA_VERSION,
    CLOUDFLARE_PAGES_READY_VERDICT,
    CLOUDFLARE_PAGES_TOKEN_RUNBOOK,
    CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
    CloudflarePagesDeployReadyError,
    check_cloudflare_pages_deploy_ready,
    verify_cloudflare_pages_deploy_ready_receipt_file,
)
from scripts.check_external_alpha_public_deploy_candidate import (
    PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
    _receipt_body_sha256 as _candidate_receipt_body_sha256,
)
from scripts.check_external_alpha_send_ready import check_send_ready


ROOT = Path(__file__).resolve().parents[1]


def test_external_alpha_cloudflare_pages_preflight_blocks_until_api_token(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_cloudflare_pages_deploy_ready(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=False,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT
    assert receipt_path.name == CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME
    assert payload["schema_version"] == CLOUDFLARE_PAGES_DEPLOY_READY_SCHEMA_VERSION
    assert payload["safe_to_share"] is True
    assert payload["launch_state"]["external_sharing_allowed"] is False
    assert payload["wrangler"]["version_available"] is True
    assert payload["wrangler"]["authenticated"] is True
    assert payload["wrangler"]["noninteractive_api_token_present"] is False
    assert payload["wrangler"]["noninteractive_deploy_credential_ready"] is False
    assert payload["wrangler"]["account_id_required_for_direct_upload"] is True
    assert payload["wrangler"]["account_id_recommended_for_direct_upload"] is True
    assert payload["cloudflare_pages"]["required_account_env_var"] == "CLOUDFLARE_ACCOUNT_ID"
    assert payload["cloudflare_pages"]["required_credential_env_vars"] == [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    assert payload["cloudflare_pages"]["recommended_account_env_var"] == "CLOUDFLARE_ACCOUNT_ID"
    assert payload["cloudflare_pages"]["required_token_permission"] == "Account / Cloudflare Pages / Edit"
    assert payload["cloudflare_pages"]["api_permission_alias"] == "Pages Write"
    assert payload["cloudflare_pages"]["credential_runbook"] == CLOUDFLARE_PAGES_TOKEN_RUNBOOK
    assert payload["wrangler"]["raw_output_included"] is False
    assert payload["cloudflare_pages"]["login_command"] == "npx wrangler login"
    assert payload["cloudflare_pages"]["deploy_command"] == (
        "npx wrangler pages deploy dist\\cambrian-public-site --project-name cambrian-alpha --branch main"
    )
    assert "finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL>" in payload["cloudflare_pages"][
        "final_url_gate_command"
    ]
    assert payload["release"]["archive_sha256"] in payload["cloudflare_pages"]["final_url_gate_command"]
    assert all(payload["checks"].values())
    assert verify_cloudflare_pages_deploy_ready_receipt_file(receipt_path)[
        "cloudflare_pages_deploy_ready_body_sha256"
    ] == payload["cloudflare_pages_deploy_ready_body_sha256"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(Path.home()) not in serialized
    runbook = (ROOT / CLOUDFLARE_PAGES_TOKEN_RUNBOOK).read_text(encoding="utf-8")
    assert "CLOUDFLARE_API_TOKEN" in runbook
    assert "CLOUDFLARE_ACCOUNT_ID" in runbook
    assert "Account / Cloudflare Pages / Edit" in runbook


def test_external_alpha_cloudflare_pages_preflight_blocks_until_account_id(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_cloudflare_pages_deploy_ready(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=False,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT
    assert payload["wrangler"]["noninteractive_api_token_present"] is True
    assert payload["wrangler"]["account_id_env_var_present"] is False
    assert payload["wrangler"]["noninteractive_deploy_credential_ready"] is False
    assert "CLOUDFLARE_ACCOUNT_ID" in payload["operator_next_action"]
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_pages_preflight_blocks_until_wrangler_login(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_cloudflare_pages_deploy_ready(
        tmp_path,
        runner=_fake_wrangler_not_authenticated,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT
    assert payload["wrangler"]["version_available"] is True
    assert payload["wrangler"]["authenticated"] is False
    assert payload["wrangler"]["noninteractive_deploy_credential_ready"] is True
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_pages_preflight_ready_after_wrangler_auth(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_cloudflare_pages_deploy_ready(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == CLOUDFLARE_PAGES_READY_VERDICT
    assert payload["wrangler"]["authenticated"] is True
    assert payload["wrangler"]["account_id_env_var_present"] is True
    assert payload["cloudflare_pages"]["required_success_signal"] == (
        "wrangler pages deploy returns a public https://*.pages.dev URL"
    )
    assert payload["public_deploy_candidate"]["verdict"] == "PUBLIC_DEPLOY_CANDIDATE_READY"
    assert payload["public_deploy_candidate"]["receipt_file"] == PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_pages_preflight_blocks_when_wrangler_missing(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_cloudflare_pages_deploy_ready(
        tmp_path,
        runner=_fake_wrangler_missing,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT
    assert payload["wrangler"]["version_available"] is False
    assert payload["wrangler"]["auth_checked"] is False
    assert payload["wrangler"]["authenticated"] is False
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_pages_preflight_rejects_stale_candidate_receipt(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_cloudflare_pages_deploy_ready(
        tmp_path,
        runner=_fake_wrangler_authenticated,
        api_token_present=True,
        account_id_present=True,
    )
    candidate_receipt = tmp_path / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME
    candidate_payload = json.loads(candidate_receipt.read_text(encoding="utf-8"))
    candidate_payload["deploy_candidate"]["external_sharing_allowed"] = True
    candidate_payload["public_deploy_candidate_receipt_body_sha256"] = _candidate_receipt_body_sha256(
        candidate_payload
    )
    candidate_receipt.write_text(
        json.dumps(candidate_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CloudflarePagesDeployReadyError, match="public deploy candidate receipt invalid"):
        verify_cloudflare_pages_deploy_ready_receipt_file(Path(result["receipt_json"]))


def _fake_wrangler_not_authenticated(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return _fake_wrangler(command, authenticated=False, missing=False)


def _fake_wrangler_authenticated(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return _fake_wrangler(command, authenticated=True, missing=False)


def _fake_wrangler_missing(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return _fake_wrangler(command, authenticated=False, missing=True)


def _fake_wrangler(
    command: list[str],
    *,
    authenticated: bool,
    missing: bool,
) -> subprocess.CompletedProcess[str]:
    if command[-1] == "--version":
        if missing:
            return subprocess.CompletedProcess(command, 1, "", "wrangler unavailable")
        return subprocess.CompletedProcess(command, 0, "4.93.0\n", "")
    if command[-1] == "whoami":
        if authenticated:
            return subprocess.CompletedProcess(command, 0, "authenticated\n", "")
        return subprocess.CompletedProcess(command, 1, "", "not authenticated")
    raise AssertionError(f"unexpected command: {command!r}")
