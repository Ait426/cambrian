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
from scripts.finalize_external_alpha_public_launch_url import (
    PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
    PUBLIC_LAUNCH_URL_GATE_SCHEMA_VERSION,
    PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT,
    PublicLaunchUrlGateError,
    _receipt_body_sha256,
    finalize_public_launch_url,
    verify_public_launch_url_gate_receipt_file,
)
from scripts.prepare_external_alpha_public_download_site import PUBLIC_SITE_DIR_NAME, prepare_public_download_site


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "finalize_external_alpha_public_launch_url.py"


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


def test_external_alpha_public_launch_url_gate_local_rehearsal_passes(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        result = finalize_public_launch_url(
            base_url,
            tmp_path,
            expected_archive_sha256=site_result["archive_sha256"],
            allow_local_rehearsal=True,
        )

    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT
    assert result["external_sharing_allowed"] is False
    assert receipt_path.name == PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME
    assert payload["schema_version"] == PUBLIC_LAUNCH_URL_GATE_SCHEMA_VERSION
    assert payload["launch_state"]["mode"] == "local_rehearsal"
    assert payload["launch_state"]["external_sharing_state"] == "BLOCKED_LOCAL_REHEARSAL_ONLY"
    assert payload["url"]["is_local_or_private"] is True
    assert payload["downloaded_release_zip"]["quickstart_mentions_builder_golden_path"] is True
    assert payload["url_receipt"]["downloaded_release_zip"]["root_dir"] == "cambrian-agent-platform-external-alpha"
    assert all(payload["checks"].values())
    assert verify_public_launch_url_gate_receipt_file(receipt_path)[
        "public_launch_url_gate_receipt_body_sha256"
    ] == payload["public_launch_url_gate_receipt_body_sha256"]


def test_external_alpha_public_launch_url_gate_rejects_localhost_without_rehearsal_flag(
    tmp_path: Path,
) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        with pytest.raises(PublicLaunchUrlGateError, match="allow-local-rehearsal"):
            finalize_public_launch_url(
                base_url,
                tmp_path,
                expected_archive_sha256=site_result["archive_sha256"],
            )


def test_external_alpha_public_launch_url_gate_cli_writes_and_verifies_local_rehearsal(
    tmp_path: Path,
) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)
    receipt_path = tmp_path / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                base_url,
                "--output-dir",
                str(tmp_path),
                "--expected-archive-sha256",
                str(site_result["archive_sha256"]),
                "--allow-local-rehearsal",
                "--receipt",
                str(receipt_path),
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
    assert "[PASS] external alpha public launch URL gate" in output
    assert PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT in output

    verify_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-receipt", str(receipt_path)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha public launch URL gate receipt" in verify_output


def test_external_alpha_public_launch_url_gate_rejects_stale_receipt_checks(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)

    with serve_directory(Path(site_result["site_dir"])) as base_url:
        result = finalize_public_launch_url(
            base_url,
            tmp_path,
            expected_archive_sha256=site_result["archive_sha256"],
            allow_local_rehearsal=True,
        )

    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["launch_state"]["external_sharing_allowed"] = True
    payload["public_launch_url_gate_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicLaunchUrlGateError, match="checks are stale"):
        verify_public_launch_url_gate_receipt_file(receipt_path)
