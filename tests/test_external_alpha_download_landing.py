import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.prepare_external_alpha_download_landing import (
    CANONICAL_ZIP_NAME,
    DOWNLOAD_LANDING_HTML_NAME,
    DOWNLOAD_LANDING_PREVIEW_NAME,
    DOWNLOAD_LANDING_RECEIPT_NAME,
    DownloadLandingError,
    PUBLIC_DOWNLOAD_ZIP_NAME,
    _receipt_body_sha256,
    prepare_download_landing,
    verify_download_landing_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_external_alpha_download_landing.py"


def test_external_alpha_download_landing_writes_download_page_and_receipt(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = prepare_download_landing(tmp_path)
    html_path = Path(result["landing_html"])
    preview_path = Path(result["preview_png"])
    receipt_path = Path(result["receipt_json"])
    html = html_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "DOWNLOAD_PAGE_READY"
    assert html_path.name == DOWNLOAD_LANDING_HTML_NAME
    assert preview_path.name == DOWNLOAD_LANDING_PREVIEW_NAME
    assert receipt_path.name == DOWNLOAD_LANDING_RECEIPT_NAME
    assert preview_path.is_file()
    assert preview_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert f'href="{PUBLIC_DOWNLOAD_ZIP_NAME}" download' in html
    assert f"Download file: {PUBLIC_DOWNLOAD_ZIP_NAME}" in html
    assert f"ZIP sha256</strong><br />\n          {result['archive_sha256']}" in html
    assert "Download Cambrian Agent Platform" in html
    assert "Capability Contract" in html
    assert "Build AI Agents" in html
    assert "Create And Fuse Skills" in html
    assert "Run Harness Engineering" in html
    assert "Evolve With Receipts" in html
    assert '<meta name="robots" content="noindex,nofollow" />' in html
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in html
    assert "START_CAMBRIAN_AGENT_PLATFORM.bat" in html
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in html
    assert "does not collect email" in html
    assert "claim public success metrics" in html
    assert str(ROOT) not in html
    assert str(tmp_path) not in html

    assert receipt["schema_version"] == "external_alpha_download_landing_v0_1"
    assert receipt["safe_to_share"] is True
    assert receipt["release"]["archive_sha256"] == result["archive_sha256"]
    assert receipt["release"]["zip_file"] == CANONICAL_ZIP_NAME
    assert receipt["release"]["public_download_zip_file"] == PUBLIC_DOWNLOAD_ZIP_NAME
    assert receipt["download_page"]["html_file"] == DOWNLOAD_LANDING_HTML_NAME
    assert receipt["download_page"]["preview_asset"] == DOWNLOAD_LANDING_PREVIEW_NAME
    assert receipt["download_page"]["zip_download_href"] == PUBLIC_DOWNLOAD_ZIP_NAME
    assert (tmp_path / PUBLIC_DOWNLOAD_ZIP_NAME).is_file()
    assert receipt["policy"] == {
        "local_paths_included": False,
        "page_collects_email": False,
        "proof_or_success_claims": False,
        "raw_private_values_included": False,
        "requires_api_key": False,
        "script_sends_to_recipient": False,
    }
    assert all(receipt["checks"].values())
    assert verify_download_landing_receipt_file(receipt_path)[
        "download_landing_receipt_body_sha256"
    ] == receipt["download_landing_receipt_body_sha256"]


def test_external_alpha_download_landing_cli_passes_and_verifies(tmp_path: Path) -> None:
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
    assert "[PASS] external alpha download landing" in output
    assert "DOWNLOAD_PAGE_READY" in output
    assert (tmp_path / DOWNLOAD_LANDING_HTML_NAME).is_file()
    assert (tmp_path / DOWNLOAD_LANDING_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify-receipt",
            str(tmp_path / DOWNLOAD_LANDING_RECEIPT_NAME),
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha download landing verification" in verify_output


def test_external_alpha_download_landing_rejects_stale_receipt_checks(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = prepare_download_landing(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["download_page"]["zip_download_href"] = "wrong.zip"
    payload["download_landing_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(DownloadLandingError, match="checks are stale"):
        verify_download_landing_receipt_file(receipt_path)
