import json
import subprocess
from pathlib import Path

from scripts.check_external_alpha_cloudflare_credentials import CLOUDFLARE_CREDENTIALS_READY_VERDICT
from scripts.check_external_alpha_cloudflare_pages_deploy_ready import CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT
from scripts.launch_external_alpha_cloudflare_pages import CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT
from scripts.run_external_alpha_public_launch_sequence import (
    PUBLIC_LAUNCH_SEQUENCE_BLOCKED_CREDENTIALS_VERDICT,
    PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT,
    PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT,
    PUBLIC_LAUNCH_SEQUENCE_RECEIPT_NAME,
    PUBLIC_LAUNCH_SEQUENCE_SCHEMA_VERSION,
    run_public_launch_sequence,
    verify_public_launch_sequence_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]


def test_external_alpha_public_launch_sequence_blocks_before_deploy_without_credentials(tmp_path: Path) -> None:
    deploy_calls: list[list[str]] = []

    result = run_public_launch_sequence(
        tmp_path,
        preflight_runner=_fake_wrangler_authenticated,
        deploy_runner=_recording_deploy_runner(deploy_calls),
        api_token_present=False,
        account_id_present=False,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == PUBLIC_LAUNCH_SEQUENCE_BLOCKED_CREDENTIALS_VERDICT
    assert receipt_path.name == PUBLIC_LAUNCH_SEQUENCE_RECEIPT_NAME
    assert payload["schema_version"] == PUBLIC_LAUNCH_SEQUENCE_SCHEMA_VERSION
    assert payload["stages"]["cloudflare_credentials"]["verdict"] == CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT
    assert payload["stages"]["cloudflare_credentials"]["missing_env_vars"] == [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    assert payload["stages"]["cloudflare_launch"]["attempted"] is False
    assert payload["launch_state"]["launch_attempted"] is False
    assert deploy_calls == []
    assert all(payload["checks"].values())
    assert verify_public_launch_sequence_receipt_file(receipt_path)[
        "public_launch_sequence_body_sha256"
    ] == payload["public_launch_sequence_body_sha256"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(Path.home()) not in serialized


def test_external_alpha_public_launch_sequence_blocks_on_launch_failure(tmp_path: Path) -> None:
    result = run_public_launch_sequence(
        tmp_path,
        credential_func=_ready_credential_gate,
        launch_func=_blocked_launch,
        doctor_func=_blocked_doctor,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert result["verdict"] == PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT
    assert payload["stages"]["cloudflare_credentials"]["verdict"] == CLOUDFLARE_CREDENTIALS_READY_VERDICT
    assert payload["stages"]["cloudflare_launch"]["attempted"] is True
    assert payload["stages"]["cloudflare_launch"]["verdict"] == CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT
    assert "Fix the deploy failure" in payload["operator_next_action"]
    assert all(payload["checks"].values())


def test_external_alpha_public_launch_sequence_ready_after_doctor_allows_external_share(tmp_path: Path) -> None:
    result = run_public_launch_sequence(
        tmp_path,
        credential_func=_ready_credential_gate,
        launch_func=_ready_launch,
        doctor_func=_ready_doctor,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT
    assert result["external_sharing_allowed"] is True
    assert payload["stages"]["cloudflare_launch"]["attempted"] is True
    assert payload["stages"]["public_launch_doctor"]["external_sharing_allowed"] is True
    assert payload["launch_state"]["external_sharing_allowed"] is True
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


def _ready_credential_gate(output_dir: Path, **kwargs: object) -> dict[str, object]:
    return {
        "status": "pass",
        "verdict": CLOUDFLARE_CREDENTIALS_READY_VERDICT,
        "receipt_json": str(output_dir / "cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json"),
        "missing_env_vars": [],
        "next_action": "run launch",
        "receipt_body_sha256": "c" * 64,
    }


def _blocked_launch(output_dir: Path, **kwargs: object) -> dict[str, object]:
    return {
        "status": "blocked",
        "verdict": CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT,
        "receipt_json": str(output_dir / "cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json"),
        "public_url": None,
        "external_sharing_allowed": False,
        "next_action": "Fix the deploy failure before rerunning the public launch sequence.",
        "receipt_body_sha256": "d" * 64,
    }


def _ready_launch(output_dir: Path, **kwargs: object) -> dict[str, object]:
    return {
        "status": "pass",
        "verdict": "CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY",
        "receipt_json": str(output_dir / "cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json"),
        "public_url": "https://cambrian-alpha.pages.dev/",
        "external_sharing_allowed": True,
        "next_action": "share packet",
        "receipt_body_sha256": "e" * 64,
    }


def _blocked_doctor(output_dir: Path, **kwargs: object) -> dict[str, object]:
    return {
        "status": "blocked",
        "verdict": "BLOCKED_CLOUDFLARE_LAUNCH",
        "receipt_json": str(output_dir / "cambrian-agent-platform-external-alpha-public-launch-doctor.json"),
        "next_action": "fix doctor",
        "external_sharing_allowed": False,
        "receipt_body_sha256": "f" * 64,
    }


def _ready_doctor(output_dir: Path, **kwargs: object) -> dict[str, object]:
    return {
        "status": "pass",
        "verdict": "PUBLIC_LAUNCH_SHARE_READY",
        "receipt_json": str(output_dir / "cambrian-agent-platform-external-alpha-public-launch-doctor.json"),
        "next_action": "review share packet",
        "external_sharing_allowed": True,
        "receipt_body_sha256": "1" * 64,
    }
