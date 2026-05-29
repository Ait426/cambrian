import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.prepare_external_alpha_public_download_site import (
    CANONICAL_ZIP_NAME,
    HOSTING_HEADERS_NAME,
    INDEX_NAME,
    NOJEKYLL_NAME,
    NOT_FOUND_HTML_NAME,
    PUBLIC_HOSTING_RUNBOOK_NAME,
    PUBLIC_SITE_DIR_NAME,
    PUBLIC_SITE_RECEIPT_NAME,
    REQUIRED_SITE_FILES,
    ROBOTS_TXT_NAME,
    ZIP_NAME,
    PublicDownloadSiteError,
    _receipt_body_sha256,
    prepare_public_download_site,
    verify_public_download_site_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_external_alpha_public_download_site.py"


def test_external_alpha_public_download_site_is_hostable(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = prepare_public_download_site(tmp_path)
    site_dir = Path(result["site_dir"])
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    index_html = (site_dir / INDEX_NAME).read_text(encoding="utf-8")
    headers = (site_dir / HOSTING_HEADERS_NAME).read_text(encoding="utf-8")
    nojekyll = (site_dir / NOJEKYLL_NAME).read_text(encoding="utf-8")
    runbook = (site_dir / PUBLIC_HOSTING_RUNBOOK_NAME).read_text(encoding="utf-8")
    robots = (site_dir / ROBOTS_TXT_NAME).read_text(encoding="utf-8")
    not_found = (site_dir / NOT_FOUND_HTML_NAME).read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["verdict"] == "PUBLIC_DOWNLOAD_SITE_READY"
    assert site_dir.name == PUBLIC_SITE_DIR_NAME
    assert receipt_path.name == PUBLIC_SITE_RECEIPT_NAME
    assert set(REQUIRED_SITE_FILES).issubset({path.name for path in site_dir.iterdir() if path.is_file()})
    assert f'href="{ZIP_NAME}" download' in index_html
    assert "cambrian-agent-platform-external-alpha.zip" not in index_html
    assert "Download Cambrian Agent Platform" in index_html
    assert "Capability Contract" in index_html
    assert "Build AI Agents" in index_html
    assert "Create And Fuse Skills" in index_html
    assert "Run Harness Engineering" in index_html
    assert "Evolve With Receipts" in index_html
    assert '<meta name="robots" content="noindex,nofollow" />' in index_html
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in index_html
    assert "Content-Disposition: attachment" in headers
    assert f'filename="{ZIP_NAME}"' in headers
    assert "X-Content-Type-Options: nosniff" in headers
    assert nojekyll == ""
    assert "Cambrian Public Hosting Runbook" in runbook
    assert NOJEKYLL_NAME in runbook
    assert "PUBLIC_LAUNCH_URL_READY" in runbook
    assert "external_sharing_allowed=true" in runbook
    assert "PUBLIC_LAUNCH_URL_REHEARSAL_READY" in runbook
    assert "finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL>" in runbook
    assert "Disallow: /" in robots
    assert f'href="{INDEX_NAME}"' in not_found
    assert str(ROOT) not in index_html
    assert str(tmp_path) not in index_html
    assert str(ROOT) not in headers + runbook + robots + not_found
    assert str(tmp_path) not in headers + runbook + robots + not_found

    by_file = {item["file"]: item for item in payload["files"]}
    assert payload["schema_version"] == "external_alpha_public_download_site_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["site"]["entrypoint"] == INDEX_NAME
    assert payload["site"]["hosting_model"] == "static_files_same_directory"
    assert payload["policy"]["ready_for_static_hosting"] is True
    assert payload["policy"]["page_collects_email"] is False
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["proof_or_success_claims"] is False
    assert payload["policy"]["search_indexing_enabled"] is False
    assert payload["policy"]["security_headers_included"] is True
    assert payload["policy"]["jekyll_processing_disabled"] is True
    assert payload["policy"]["hosting_runbook_included"] is True
    assert payload["checks"]["jekyll_processing_disabled"] is True
    assert payload["checks"]["hosting_runbook_present"] is True
    assert payload["public_download"]["zip_file"] == ZIP_NAME
    assert payload["public_download"]["canonical_zip_file"] == CANONICAL_ZIP_NAME
    assert by_file[INDEX_NAME]["sha256"] == by_file["cambrian-agent-platform-external-alpha-download.html"]["sha256"]
    assert by_file[ZIP_NAME]["sha256"] == payload["release"]["archive_sha256"]
    assert all(payload["checks"].values())
    assert verify_public_download_site_receipt_file(receipt_path)[
        "public_download_site_receipt_body_sha256"
    ] == payload["public_download_site_receipt_body_sha256"]


def test_external_alpha_public_download_site_cli_passes_and_verifies(tmp_path: Path) -> None:
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
    assert "[PASS] external alpha public download site" in output
    assert "PUBLIC_DOWNLOAD_SITE_READY" in output

    receipt = tmp_path / PUBLIC_SITE_DIR_NAME / PUBLIC_SITE_RECEIPT_NAME
    verify_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-receipt", str(receipt)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha public download site verification" in verify_output


def test_external_alpha_public_download_site_rejects_stale_receipt_checks(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = prepare_public_download_site(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["page_collects_email"] = True
    payload["public_download_site_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicDownloadSiteError, match="checks are stale"):
        verify_public_download_site_receipt_file(receipt_path)


def test_external_alpha_public_download_site_removes_stale_canonical_zip_from_site_dir(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    stale_site_dir = tmp_path / PUBLIC_SITE_DIR_NAME
    stale_site_dir.mkdir()
    (stale_site_dir / CANONICAL_ZIP_NAME).write_text("stale", encoding="utf-8")

    result = prepare_public_download_site(tmp_path)
    site_dir = Path(result["site_dir"])

    assert not (site_dir / CANONICAL_ZIP_NAME).exists()
    assert (site_dir / ZIP_NAME).is_file()
