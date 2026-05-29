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
    PUBLIC_LAUNCH_URL_READY_VERDICT,
    _gate_checks,
    _receipt_body_sha256 as _gate_body_sha256,
    finalize_public_launch_url,
    verify_public_launch_url_gate_receipt_file,
)
from scripts.prepare_external_alpha_public_download_site import (
    INDEX_NAME,
    ZIP_NAME,
    prepare_public_download_site,
)
from scripts.prepare_external_alpha_public_share_packet import (
    PUBLIC_SHARE_PACKET_JSON_NAME,
    PUBLIC_SHARE_PACKET_MD_NAME,
    PUBLIC_SHARE_PACKET_SCHEMA_VERSION,
    PUBLIC_SHARE_PACKET_VERDICT,
    PublicSharePacketError,
    _packet_body_sha256,
    prepare_public_share_packet,
    verify_public_share_packet_file,
)
from scripts.verify_external_alpha_public_download_site_url import (
    _receipt_body_sha256 as _url_receipt_body_sha256,
    _receipt_checks as _url_receipt_checks,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_external_alpha_public_share_packet.py"
PUBLIC_TEST_URL = "https://download.example.com/cambrian/"


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


def _write_local_launch_gate_receipt(tmp_path: Path) -> Path:
    check_send_ready(tmp_path)
    site_result = prepare_public_download_site(tmp_path)
    receipt_path = tmp_path / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME
    with serve_directory(Path(site_result["site_dir"])) as base_url:
        finalize_public_launch_url(
            base_url,
            tmp_path,
            expected_archive_sha256=site_result["archive_sha256"],
            allow_local_rehearsal=True,
            receipt_path=receipt_path,
        )
    return receipt_path


def _write_public_launch_gate_receipt(tmp_path: Path) -> Path:
    receipt_path = _write_local_launch_gate_receipt(tmp_path)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    url_receipt = payload["url_receipt"]
    url_receipt["url"]["base_url"] = PUBLIC_TEST_URL
    url_receipt["url"]["index_url"] = PUBLIC_TEST_URL + INDEX_NAME
    url_receipt["public_download_site_url_receipt_body_sha256"] = _url_receipt_body_sha256(url_receipt)
    url_receipt["checks"] = _url_receipt_checks(url_receipt)

    payload["verdict"] = PUBLIC_LAUNCH_URL_READY_VERDICT
    payload["launch_state"] = {
        "mode": "public_url",
        "public_url_ready": True,
        "local_rehearsal_ready": False,
        "external_sharing_allowed": True,
        "external_sharing_state": "PUBLIC_URL_VERIFIED",
    }
    payload["url"] = {
        "base_url": PUBLIC_TEST_URL,
        "entrypoint": INDEX_NAME,
        "scheme": "https",
        "host": "download.example.com",
        "is_local_or_private": False,
        "allow_local_rehearsal": False,
    }
    payload["url_receipt_summary"]["body_sha256"] = url_receipt["public_download_site_url_receipt_body_sha256"]
    payload["public_launch_url_gate_receipt_body_sha256"] = _gate_body_sha256(payload)
    payload["checks"] = _gate_checks(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_public_launch_url_gate_receipt_file(receipt_path)
    return receipt_path


def test_external_alpha_public_share_packet_requires_public_verified_url(tmp_path: Path) -> None:
    gate_receipt = _write_public_launch_gate_receipt(tmp_path)

    result = prepare_public_share_packet(tmp_path, gate_receipt=gate_receipt)
    packet_json = Path(result["packet_json"])
    packet_md = Path(result["packet_md"])
    payload = json.loads(packet_json.read_text(encoding="utf-8"))
    markdown = packet_md.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["verdict"] == PUBLIC_SHARE_PACKET_VERDICT
    assert result["public_url"] == PUBLIC_TEST_URL
    assert packet_json.name == PUBLIC_SHARE_PACKET_JSON_NAME
    assert packet_md.name == PUBLIC_SHARE_PACKET_MD_NAME
    assert payload["schema_version"] == PUBLIC_SHARE_PACKET_SCHEMA_VERSION
    assert payload["source_gate"]["verdict"] == PUBLIC_LAUNCH_URL_READY_VERDICT
    assert payload["source_gate"]["external_sharing_allowed"] is True
    assert payload["url"]["public_url"] == PUBLIC_TEST_URL
    assert payload["url"]["url_receipt_base_url"] == PUBLIC_TEST_URL
    assert payload["download"]["public_zip_file"] == ZIP_NAME
    assert payload["download"]["archive_sha256"] == payload["download"]["downloaded_zip_sha256"]
    assert PUBLIC_TEST_URL in payload["copy_paste"]["message"]
    assert payload["download"]["archive_sha256"] in payload["copy_paste"]["message"]
    assert "external alpha" in payload["copy_paste"]["message"].lower()
    assert "production ready" not in payload["copy_paste"]["message"].lower()
    assert PUBLIC_TEST_URL in markdown
    assert str(ROOT) not in markdown
    assert str(tmp_path) not in markdown
    assert all(payload["checks"].values())
    assert verify_public_share_packet_file(packet_json)[
        "public_share_packet_body_sha256"
    ] == payload["public_share_packet_body_sha256"]


def test_external_alpha_public_share_packet_rejects_local_rehearsal_gate(tmp_path: Path) -> None:
    local_gate_receipt = _write_local_launch_gate_receipt(tmp_path)

    with pytest.raises(PublicSharePacketError, match="PUBLIC_LAUNCH_URL_READY"):
        prepare_public_share_packet(tmp_path, gate_receipt=local_gate_receipt)


def test_external_alpha_public_share_packet_cli_passes_and_verifies(tmp_path: Path) -> None:
    gate_receipt = _write_public_launch_gate_receipt(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(tmp_path), "--gate-receipt", str(gate_receipt)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha public share packet" in output
    assert PUBLIC_SHARE_PACKET_VERDICT in output

    verify_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-packet", str(tmp_path / PUBLIC_SHARE_PACKET_JSON_NAME)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha public share packet verification" in verify_output


def test_external_alpha_public_share_packet_rejects_stale_checks(tmp_path: Path) -> None:
    gate_receipt = _write_public_launch_gate_receipt(tmp_path)
    result = prepare_public_share_packet(tmp_path, gate_receipt=gate_receipt)
    packet_json = Path(result["packet_json"])
    payload = json.loads(packet_json.read_text(encoding="utf-8"))
    payload["copy_paste"]["contains_public_url"] = False
    payload["public_share_packet_body_sha256"] = _packet_body_sha256(payload)
    packet_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicSharePacketError, match="checks are stale"):
        verify_public_share_packet_file(packet_json)


def test_external_alpha_public_share_packet_default_gate_path_blocks_before_public_url(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    prepare_public_download_site(tmp_path)

    with pytest.raises(PublicSharePacketError, match=PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME):
        prepare_public_share_packet(tmp_path)
