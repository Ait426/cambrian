import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.package_external_alpha_public_download_site import (
    CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME,
    PACKAGE_VERDICT,
    PUBLIC_SITE_PACKAGE_RECEIPT_NAME,
    PUBLIC_SITE_PACKAGE_SCHEMA_VERSION,
    PUBLIC_SITE_PACKAGE_ZIP_NAME,
    PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME,
    PublicDownloadSitePackageError,
    _receipt_body_sha256,
    _sha256_file,
    package_public_download_site,
    verify_public_download_site_package_receipt_file,
)
from scripts.prepare_external_alpha_public_download_site import (
    DOWNLOAD_LANDING_RECEIPT_NAME,
    HOSTING_HEADERS_NAME,
    INDEX_NAME,
    MANIFEST_NAME,
    NOJEKYLL_NAME,
    NOT_FOUND_HTML_NAME,
    PUBLIC_HOSTING_RUNBOOK_NAME,
    PUBLIC_SITE_RECEIPT_NAME,
    RELEASE_RECEIPT_NAME,
    ROBOTS_TXT_NAME,
    SEND_READY_JSON_NAME,
    SEND_READY_MD_NAME,
    ZIP_NAME,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "package_external_alpha_public_download_site.py"


def test_external_alpha_public_download_site_package_is_upload_ready(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = package_public_download_site(tmp_path)
    package_zip = Path(result["package_zip"])
    upload_root = Path(result["upload_root"])
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == PACKAGE_VERDICT
    assert package_zip.name == PUBLIC_SITE_PACKAGE_ZIP_NAME
    assert package_zip.name == "cambrian-public-site.zip"
    assert package_zip.name != CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME
    assert upload_root.name == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
    assert (upload_root / INDEX_NAME).is_file()
    assert (upload_root / ZIP_NAME).is_file()
    assert (upload_root / NOJEKYLL_NAME).is_file()
    assert not (upload_root / PUBLIC_SITE_PACKAGE_RECEIPT_NAME).exists()
    assert receipt_path.name == PUBLIC_SITE_PACKAGE_RECEIPT_NAME
    assert payload["schema_version"] == PUBLIC_SITE_PACKAGE_SCHEMA_VERSION
    assert payload["safe_to_share"] is True
    assert payload["package"]["sha256"] == _sha256_file(package_zip)
    assert payload["package"]["includes_package_receipt"] is False
    assert payload["package"]["root_entries_only"] is True
    assert payload["upload_root"]["directory_name"] == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
    assert payload["upload_root"]["entrypoint"] == INDEX_NAME
    assert payload["upload_root"]["includes_package_receipt"] is False
    assert payload["policy"]["receipt_outside_package"] is True
    assert payload["policy"]["short_upload_root_included"] is True
    assert payload["policy"]["page_collects_email"] is False
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["proof_or_success_claims"] is False

    with zipfile.ZipFile(package_zip) as archive:
        names = archive.namelist()
        assert INDEX_NAME in names
        assert ZIP_NAME in names
        assert "cambrian-agent-platform-external-alpha.zip" not in names
        assert MANIFEST_NAME in names
        assert RELEASE_RECEIPT_NAME in names
        assert SEND_READY_MD_NAME in names
        assert SEND_READY_JSON_NAME in names
        assert PUBLIC_SITE_RECEIPT_NAME in names
        assert HOSTING_HEADERS_NAME in names
        assert NOJEKYLL_NAME in names
        assert PUBLIC_HOSTING_RUNBOOK_NAME in names
        assert ROBOTS_TXT_NAME in names
        assert NOT_FOUND_HTML_NAME in names
        assert "PUBLIC_LAUNCH_URL_READY" in archive.read(PUBLIC_HOSTING_RUNBOOK_NAME).decode("utf-8")
        assert PUBLIC_SITE_PACKAGE_RECEIPT_NAME not in names
        assert all(not Path(name).is_absolute() for name in names)
        assert all("/" not in name and "\\" not in name for name in names)

    by_entry = {item["file"]: item for item in payload["entries"]}
    assert set(by_entry) == {path.name for path in upload_root.iterdir() if path.is_file()}
    assert by_entry[ZIP_NAME]["sha256"] == payload["release"]["archive_sha256"]
    assert all(payload["checks"].values())
    assert verify_public_download_site_package_receipt_file(receipt_path)[
        "public_download_site_package_receipt_body_sha256"
    ] == payload["public_download_site_package_receipt_body_sha256"]


def test_external_alpha_public_download_site_package_is_deterministic(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    first = package_public_download_site(tmp_path)
    first_zip_sha = _sha256_file(Path(first["package_zip"]))
    first_payload = verify_public_download_site_package_receipt_file(Path(first["receipt_json"]))
    first_upload_root = Path(first["upload_root"])
    first_landing_receipt = json.loads((first_upload_root / DOWNLOAD_LANDING_RECEIPT_NAME).read_text(encoding="utf-8"))
    first_site_receipt = json.loads((first_upload_root / PUBLIC_SITE_RECEIPT_NAME).read_text(encoding="utf-8"))

    second = package_public_download_site(tmp_path)
    second_zip_sha = _sha256_file(Path(second["package_zip"]))
    second_payload = verify_public_download_site_package_receipt_file(Path(second["receipt_json"]))
    second_upload_root = Path(second["upload_root"])
    second_landing_receipt = json.loads((second_upload_root / DOWNLOAD_LANDING_RECEIPT_NAME).read_text(encoding="utf-8"))
    second_site_receipt = json.loads((second_upload_root / PUBLIC_SITE_RECEIPT_NAME).read_text(encoding="utf-8"))

    assert second_zip_sha == first_zip_sha
    assert second_payload["package"]["sha256"] == first_payload["package"]["sha256"]
    assert (
        second_payload["public_download_site_package_receipt_body_sha256"]
        == first_payload["public_download_site_package_receipt_body_sha256"]
    )
    assert second_landing_receipt["generated_at"] == first_landing_receipt["generated_at"]
    assert second_site_receipt["generated_at"] == first_site_receipt["generated_at"]


def test_external_alpha_public_download_site_package_cli_passes_and_verifies(tmp_path: Path) -> None:
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
    assert "[PASS] external alpha public download site package" in output
    assert PACKAGE_VERDICT in output

    receipt = tmp_path / PUBLIC_SITE_PACKAGE_RECEIPT_NAME
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
    assert "[PASS] external alpha public download site package verification" in verify_output


def test_external_alpha_public_download_site_package_rejects_stale_receipt_checks(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = package_public_download_site(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["page_collects_email"] = True
    payload["public_download_site_package_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicDownloadSitePackageError, match="checks are stale"):
        verify_public_download_site_package_receipt_file(receipt_path)


def test_external_alpha_public_download_site_package_rejects_tampered_zip(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = package_public_download_site(tmp_path)
    package_zip = Path(result["package_zip"])

    with zipfile.ZipFile(package_zip, "a") as archive:
        archive.writestr("extra.txt", "tamper")

    with pytest.raises(PublicDownloadSitePackageError, match="checks are stale"):
        verify_public_download_site_package_receipt_file(Path(result["receipt_json"]))
