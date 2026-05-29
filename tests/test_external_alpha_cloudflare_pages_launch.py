import json
import subprocess
from pathlib import Path

from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (
    CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
)
from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.finalize_external_alpha_public_launch_url import PUBLIC_LAUNCH_URL_READY_VERDICT
from scripts.launch_external_alpha_cloudflare_pages import (
    CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT,
    CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT,
    CLOUDFLARE_PAGES_LAUNCH_PROJECT_CREATE_FAILED_VERDICT,
    CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT,
    CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME,
    CLOUDFLARE_PAGES_LAUNCH_SCHEMA_VERSION,
    launch_cloudflare_pages,
    verify_cloudflare_pages_launch_receipt_file,
)
from scripts.prepare_external_alpha_public_share_packet import PUBLIC_SHARE_PACKET_VERDICT


ROOT = Path(__file__).resolve().parents[1]


def test_external_alpha_cloudflare_pages_launch_blocks_before_deploy_without_api_token(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    deploy_calls: list[list[str]] = []

    result = launch_cloudflare_pages(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        deploy_runner=_recording_deploy_runner(deploy_calls),
        api_token_present=False,
        account_id_present=False,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT
    assert receipt_path.name == CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME
    assert payload["schema_version"] == CLOUDFLARE_PAGES_LAUNCH_SCHEMA_VERSION
    assert payload["preflight"]["verdict"] == CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT
    assert payload["preflight_blocker"]["missing_credential_env_vars"] == [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    assert payload["preflight_blocker"]["required_credential_env_vars"] == [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    assert payload["preflight_blocker"]["api_token_present"] is False
    assert payload["preflight_blocker"]["account_id_present"] is False
    assert "CLOUDFLARE_API_TOKEN" in payload["operator_next_action"]
    assert "CLOUDFLARE_ACCOUNT_ID" in payload["operator_next_action"]
    assert payload["deploy_result"]["attempted"] is False
    assert payload["launch_state"]["external_sharing_allowed"] is False
    assert deploy_calls == []
    assert all(payload["checks"].values())
    assert verify_cloudflare_pages_launch_receipt_file(receipt_path)[
        "cloudflare_pages_launch_receipt_body_sha256"
    ] == payload["cloudflare_pages_launch_receipt_body_sha256"]


def test_external_alpha_cloudflare_pages_launch_names_missing_account_id(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = launch_cloudflare_pages(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        deploy_runner=_failed_deploy_runner_after_project_ready,
        api_token_present=True,
        account_id_present=False,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT
    assert payload["preflight"]["verdict"] == CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT
    assert payload["preflight_blocker"]["missing_credential_env_vars"] == ["CLOUDFLARE_ACCOUNT_ID"]
    assert payload["preflight_blocker"]["api_token_present"] is True
    assert payload["preflight_blocker"]["account_id_present"] is False
    assert payload["deploy_result"]["attempted"] is False
    assert "CLOUDFLARE_ACCOUNT_ID" in payload["operator_next_action"]
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_pages_launch_runs_deploy_and_url_gate(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    public_url = "https://cambrian-alpha.pages.dev/"
    calls: list[list[str]] = []

    result = launch_cloudflare_pages(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        deploy_runner=_successful_cloudflare_runner(public_url, calls=calls, project_exists=False),
        api_token_present=True,
        account_id_present=True,
        finalize_func=_successful_url_gate(public_url),
        share_packet_func=_successful_share_packet(public_url),
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
    assert result["public_url"] == public_url
    assert result["external_sharing_allowed"] is True
    assert payload["deploy_result"]["attempted"] is True
    assert payload["deploy_result"]["exit_code"] == 0
    assert payload["deploy_result"]["output_redacted"] is True
    assert payload["project"]["project_present_before"] is False
    assert payload["project"]["create_attempted"] is True
    assert payload["project"]["project_ready"] is True
    assert payload["url_gate"]["verdict"] == PUBLIC_LAUNCH_URL_READY_VERDICT
    assert payload["share_packet"]["verdict"] == PUBLIC_SHARE_PACKET_VERDICT
    assert payload["share_packet"]["json_file"] == "cambrian-agent-platform-external-alpha-public-share-packet.json"
    assert payload["share_packet"]["md_file"] == "cambrian-agent-platform-external-alpha-public-share-packet.md"
    assert payload["launch_state"]["external_sharing_state"] == "PUBLIC_URL_VERIFIED"
    assert [call[:4] for call in calls] == [
        ["npx", "wrangler", "pages", "project"],
        ["npx", "wrangler", "pages", "project"],
        ["npx", "wrangler", "pages", "deploy"],
    ]
    assert all(payload["checks"].values())
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(Path.home()) not in serialized


def test_external_alpha_cloudflare_pages_launch_redacts_failed_deploy_output(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = launch_cloudflare_pages(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        deploy_runner=_failed_deploy_runner_after_project_ready,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT
    assert payload["deploy_result"]["attempted"] is True
    assert payload["deploy_result"]["exit_code"] == 1
    assert payload["deploy_result"]["output_redacted"] is True
    assert payload["public_url"]["base_url"] is None
    assert payload["launch_state"]["external_sharing_allowed"] is False
    assert "private account detail" not in json.dumps(payload, ensure_ascii=False)
    assert all(payload["checks"].values())


def test_external_alpha_cloudflare_pages_launch_blocks_when_project_create_fails(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = launch_cloudflare_pages(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        deploy_runner=_project_create_failed_runner,
        api_token_present=True,
        account_id_present=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == CLOUDFLARE_PAGES_LAUNCH_PROJECT_CREATE_FAILED_VERDICT
    assert payload["project"]["project_present_before"] is False
    assert payload["project"]["create_attempted"] is True
    assert payload["project"]["create_exit_code"] == 1
    assert payload["deploy_result"]["attempted"] is False
    assert payload["launch_state"]["external_sharing_allowed"] is False
    assert all(payload["checks"].values())


def _fake_wrangler_authenticated(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    if command[-1] == "--version":
        return subprocess.CompletedProcess(command, 0, "4.93.0\n", "")
    if command[-1] == "whoami":
        return subprocess.CompletedProcess(command, 0, "authenticated\n", "")
    raise AssertionError(f"unexpected preflight command: {command!r}")


def _recording_deploy_runner(calls: list[list[str]]):
    def runner(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "https://cambrian-alpha.pages.dev/\n", "")

    return runner


def _successful_cloudflare_runner(public_url: str, *, calls: list[list[str]], project_exists: bool):
    def runner(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:5] == ["npx", "wrangler", "pages", "project", "list"]:
            payload = [{"name": "cambrian-alpha"}] if project_exists else []
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[:5] == ["npx", "wrangler", "pages", "project", "create"]:
            return subprocess.CompletedProcess(command, 0, "created\n", "")
        return subprocess.CompletedProcess(command, 0, f"Deployment complete: {public_url}\n", "")

    return runner


def _failed_deploy_runner_after_project_ready(
    command: list[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    if command[:5] == ["npx", "wrangler", "pages", "project", "list"]:
        return subprocess.CompletedProcess(command, 0, json.dumps([{"name": "cambrian-alpha"}]), "")
    return subprocess.CompletedProcess(command, 1, "", "private account detail should be redacted")


def _project_create_failed_runner(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    if command[:5] == ["npx", "wrangler", "pages", "project", "list"]:
        return subprocess.CompletedProcess(command, 0, "[]", "")
    if command[:5] == ["npx", "wrangler", "pages", "project", "create"]:
        return subprocess.CompletedProcess(command, 1, "", "private account detail should be redacted")
    raise AssertionError(f"deploy should not run after failed project create: {command!r}")


def _successful_url_gate(public_url: str):
    def finalize(base_url: str, output_dir: Path, **kwargs: object) -> dict[str, object]:
        assert base_url == public_url
        return {
            "status": "pass",
            "verdict": PUBLIC_LAUNCH_URL_READY_VERDICT,
            "receipt_json": str(output_dir / "cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json"),
            "url": public_url,
            "external_sharing_allowed": True,
            "receipt_body_sha256": "a" * 64,
        }

    return finalize


def _successful_share_packet(public_url: str):
    def prepare(output_dir: Path, **kwargs: object) -> dict[str, object]:
        return {
            "status": "pass",
            "verdict": PUBLIC_SHARE_PACKET_VERDICT,
            "packet_json": str(output_dir / "cambrian-agent-platform-external-alpha-public-share-packet.json"),
            "packet_md": str(output_dir / "cambrian-agent-platform-external-alpha-public-share-packet.md"),
            "public_url": public_url,
            "receipt_body_sha256": "b" * 64,
        }

    return prepare
