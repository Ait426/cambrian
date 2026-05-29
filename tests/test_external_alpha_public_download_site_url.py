import contextlib
import functools
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterator

import pytest

from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.prepare_external_alpha_public_download_site import ZIP_NAME, prepare_public_download_site
from scripts.verify_external_alpha_public_download_site_url import (
    DEFAULT_URL_RECEIPT_NAME,
    DOWNLOADED_RELEASE_REQUIRED_FILES,
    PUBLIC_SITE_URL_SCHEMA_VERSION,
    PUBLIC_SITE_URL_VERDICT,
    PublicDownloadSiteUrlError,
    _receipt_body_sha256,
    verify_public_download_site_url,
    verify_public_download_site_url_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_external_alpha_public_download_site_url.py"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
        return


@contextlib.contextmanager
def serve_directory(path: Path) -> Iterator[str]:
    handler = functools.partial(QuietHandler, directory=str(path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_external_alpha_public_download_site_url_verifies_live_download(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        payload = verify_public_download_site_url(
            base_url,
            expected_archive_sha256=site_result["archive_sha256"],
        )

    assert payload["schema_version"] == PUBLIC_SITE_URL_SCHEMA_VERSION
    assert payload["verdict"] == PUBLIC_SITE_URL_VERDICT
    assert payload["observed"]["zip_sha256"] == site_result["archive_sha256"]
    assert ZIP_NAME in payload["html"]["download_hrefs"]
    assert any("noindex" in item for item in payload["html"]["robots_meta"])
    assert "Disallow: /" in payload["support_files"]["robots_txt"]
    assert payload["downloaded_release_zip"]["root_dir"] == RELEASE_SLUG
    assert set(DOWNLOADED_RELEASE_REQUIRED_FILES).issubset(
        set(payload["downloaded_release_zip"]["required_files_present"])
    )
    assert payload["downloaded_release_zip"]["quickstart_mentions_start_bat"] is True
    assert payload["downloaded_release_zip"]["quickstart_mentions_builder_golden_path"] is True
    assert payload["downloaded_release_zip"]["prompt_mentions_quickstart"] is True
    assert payload["downloaded_release_zip"]["prompt_mentions_start_bat"] is True
    assert all(payload["checks"].values())


def test_external_alpha_public_download_site_url_cli_writes_and_verifies_receipt(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)
    receipt = tmp_path / DEFAULT_URL_RECEIPT_NAME

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                base_url,
                "--expected-archive-sha256",
                str(site_result["archive_sha256"]),
                "--receipt",
                str(receipt),
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=120,
        )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha public download site URL" in output
    assert PUBLIC_SITE_URL_VERDICT in output

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
    assert "[PASS] external alpha public download site URL receipt" in verify_output


def test_external_alpha_public_download_site_url_rejects_wrong_expected_hash(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        with pytest.raises(PublicDownloadSiteUrlError, match="zip_hash_matches_expected"):
            verify_public_download_site_url(
                base_url,
                expected_archive_sha256="0" * 64,
            )


def test_external_alpha_public_download_site_url_rejects_stale_receipt_checks(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)
    receipt = tmp_path / DEFAULT_URL_RECEIPT_NAME

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        payload = verify_public_download_site_url(base_url)

    payload["policy"]["page_collects_email"] = True
    payload["public_download_site_url_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicDownloadSiteUrlError, match="checks are stale"):
        verify_public_download_site_url_receipt_file(receipt)
