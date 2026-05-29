import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.package_external_alpha_public_download_site import PUBLIC_SITE_PACKAGE_ZIP_NAME, package_public_download_site
from scripts.prepare_external_alpha_public_launch_handoff import (
    PUBLIC_LAUNCH_HANDOFF_JSON_NAME,
    PUBLIC_LAUNCH_HANDOFF_MD_NAME,
    PUBLIC_LAUNCH_HANDOFF_SCHEMA_VERSION,
    PUBLIC_LAUNCH_HANDOFF_VERDICT,
    PublicLaunchHandoffError,
    _handoff_body_sha256,
    prepare_public_launch_handoff,
    verify_public_launch_handoff_file,
)
from scripts.prepare_external_alpha_public_download_site import NOJEKYLL_NAME, PUBLIC_HOSTING_RUNBOOK_NAME, ZIP_NAME
from scripts.verify_external_alpha_public_download_site_url import DEFAULT_URL_RECEIPT_NAME


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_external_alpha_public_launch_handoff.py"


def test_external_alpha_public_launch_handoff_blocks_external_share_until_url_verified(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = prepare_public_launch_handoff(tmp_path)
    handoff_json = Path(result["handoff_json"])
    handoff_md = Path(result["handoff_md"])
    payload = json.loads(handoff_json.read_text(encoding="utf-8"))
    markdown = handoff_md.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["verdict"] == PUBLIC_LAUNCH_HANDOFF_VERDICT
    assert result["public_url_state"] == "PENDING_PUBLIC_URL"
    assert handoff_json.name == PUBLIC_LAUNCH_HANDOFF_JSON_NAME
    assert handoff_md.name == PUBLIC_LAUNCH_HANDOFF_MD_NAME
    assert payload["schema_version"] == PUBLIC_LAUNCH_HANDOFF_SCHEMA_VERSION
    assert payload["launch_state"]["external_sharing_state"] == "BLOCKED_UNTIL_PUBLIC_URL_VERIFIED"
    assert payload["public_url"]["share_allowed_before_verify"] is False
    assert "<PUBLIC_URL>" in payload["public_url"]["verify_command"]
    assert "verify_external_alpha_public_download_site_url.py" in payload["public_url"]["verify_command"]
    assert payload["release"]["archive_sha256"] in payload["public_url"]["verify_command"]
    assert payload["public_url"]["expected_url_receipt"] == f"dist\\{DEFAULT_URL_RECEIPT_NAME}"
    assert payload["package"]["zip_file"] == PUBLIC_SITE_PACKAGE_ZIP_NAME
    assert ZIP_NAME in payload["hosting"]["required_support_files"]
    assert NOJEKYLL_NAME in payload["hosting"]["required_support_files"]
    assert PUBLIC_HOSTING_RUNBOOK_NAME in payload["hosting"]["required_support_files"]
    assert payload["policy"]["fake_public_url_included"] is False
    assert payload["policy"]["manual_send_gate_replaced"] is False
    assert "Do not share the public URL externally" in markdown
    assert "PUBLIC_DOWNLOAD_SITE_URL_READY" in markdown
    assert ZIP_NAME in markdown
    assert str(ROOT) not in markdown
    assert str(tmp_path) not in markdown
    assert all(payload["checks"].values())
    assert verify_public_launch_handoff_file(handoff_json)[
        "public_launch_handoff_body_sha256"
    ] == payload["public_launch_handoff_body_sha256"]


def test_external_alpha_public_launch_handoff_cli_passes_and_verifies(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha public launch handoff" in output
    assert PUBLIC_LAUNCH_HANDOFF_VERDICT in output

    verify_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-handoff", str(tmp_path / PUBLIC_LAUNCH_HANDOFF_JSON_NAME)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha public launch handoff verification" in verify_output


def test_external_alpha_public_launch_handoff_reuses_verified_package_without_repackaging(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    package_result = package_public_download_site(tmp_path)

    result = prepare_public_launch_handoff(tmp_path)
    handoff_json = Path(result["handoff_json"])
    payload = json.loads(handoff_json.read_text(encoding="utf-8"))

    assert payload["package"]["zip_sha256"] == package_result["package_sha256"]
    assert result["package_sha256"] == package_result["package_sha256"]


def test_external_alpha_public_launch_handoff_rejects_fake_public_url(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = prepare_public_launch_handoff(tmp_path)
    handoff_json = Path(result["handoff_json"])
    payload = json.loads(handoff_json.read_text(encoding="utf-8"))
    payload["public_url"]["placeholder"] = "https://example.invalid/cambrian/"
    payload["public_launch_handoff_body_sha256"] = _handoff_body_sha256(payload)
    handoff_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicLaunchHandoffError, match="checks are stale"):
        verify_public_launch_handoff_file(handoff_json)


def test_external_alpha_public_launch_handoff_rejects_premature_share_allowed(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = prepare_public_launch_handoff(tmp_path)
    handoff_json = Path(result["handoff_json"])
    payload = json.loads(handoff_json.read_text(encoding="utf-8"))
    payload["public_url"]["share_allowed_before_verify"] = True
    payload["public_launch_handoff_body_sha256"] = _handoff_body_sha256(payload)
    handoff_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicLaunchHandoffError, match="checks are stale"):
        verify_public_launch_handoff_file(handoff_json)
