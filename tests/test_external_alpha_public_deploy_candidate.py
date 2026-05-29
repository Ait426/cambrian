import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.check_external_alpha_send_ready import check_send_ready
from scripts.check_external_alpha_public_deploy_candidate import (
    PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
    PUBLIC_DEPLOY_CANDIDATE_SCHEMA_VERSION,
    PUBLIC_DEPLOY_CANDIDATE_VERDICT,
    PublicDeployCandidateError,
    _receipt_body_sha256,
    check_public_deploy_candidate,
    verify_public_deploy_candidate_receipt_file,
)
from scripts.package_external_alpha_public_download_site import (
    CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME,
    PUBLIC_SITE_PACKAGE_ZIP_NAME,
    PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME,
)
from scripts.prepare_external_alpha_public_download_site import NOJEKYLL_NAME, PUBLIC_HOSTING_RUNBOOK_NAME, ZIP_NAME


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_external_alpha_public_deploy_candidate.py"


def test_external_alpha_public_deploy_candidate_is_upload_ready(tmp_path: Path) -> None:
    check_send_ready(tmp_path)

    result = check_public_deploy_candidate(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == PUBLIC_DEPLOY_CANDIDATE_VERDICT
    assert receipt_path.name == PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME
    assert payload["schema_version"] == PUBLIC_DEPLOY_CANDIDATE_SCHEMA_VERSION
    assert payload["deploy_candidate"]["package_zip_file"] == PUBLIC_SITE_PACKAGE_ZIP_NAME
    assert payload["deploy_candidate"]["package_zip_file"] == "cambrian-public-site.zip"
    assert payload["deploy_candidate"]["canonical_package_zip_file"] == CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME
    assert payload["deploy_candidate"]["upload_root_directory"] == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
    assert "zip_file" in payload["deploy_candidate"]["upload_options"]
    assert "folder_contents" in payload["deploy_candidate"]["upload_options"]
    assert payload["deploy_candidate"]["external_sharing_allowed"] is False
    assert payload["release"]["public_download_zip_file"] == ZIP_NAME
    assert payload["package_receipt"]["verdict"] == "PUBLIC_DOWNLOAD_SITE_PACKAGE_READY"
    assert payload["package_receipt"]["upload_root_directory"] == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
    assert PUBLIC_HOSTING_RUNBOOK_NAME in payload["inspection"]["entries"]
    assert NOJEKYLL_NAME in payload["inspection"]["entries"]
    assert payload["inspection"]["runbook"]["mentions_final_gate"] is True
    assert payload["inspection"]["runbook"]["mentions_public_https_placeholder"] is True
    assert payload["inspection"]["runbook"]["mentions_external_share_allowed_true"] is True
    assert payload["inspection"]["runbook"]["mentions_rehearsal_share_false"] is True
    assert "finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL>" in payload["hosting"][
        "required_next_gate"
    ]
    assert payload["hosting"]["local_rehearsal_is_not_launch"] is True
    assert PUBLIC_SITE_PACKAGE_ZIP_NAME in payload["hosting"]["acceptable_upload_units"]
    assert f"{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}/ contents" in payload["hosting"]["acceptable_upload_units"]
    assert payload["policy"]["external_share_before_public_url_gate"] is False
    assert all(payload["checks"].values())
    assert verify_public_deploy_candidate_receipt_file(receipt_path)[
        "public_deploy_candidate_receipt_body_sha256"
    ] == payload["public_deploy_candidate_receipt_body_sha256"]


def test_external_alpha_public_deploy_candidate_cli_passes_and_verifies(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    receipt_path = tmp_path / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output-dir", str(tmp_path), "--receipt", str(receipt_path)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha public deploy candidate" in output
    assert PUBLIC_DEPLOY_CANDIDATE_VERDICT in output

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
    assert "[PASS] external alpha public deploy candidate receipt" in verify_output


def test_external_alpha_public_deploy_candidate_rejects_stale_receipt_checks(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_public_deploy_candidate(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["deploy_candidate"]["external_sharing_allowed"] = True
    payload["public_deploy_candidate_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PublicDeployCandidateError, match="checks are stale"):
        verify_public_deploy_candidate_receipt_file(receipt_path)


def test_external_alpha_public_deploy_candidate_rejects_stale_package_zip(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_public_deploy_candidate(tmp_path)
    package_zip = tmp_path / PUBLIC_SITE_PACKAGE_ZIP_NAME

    with zipfile.ZipFile(package_zip, "a") as archive:
        archive.writestr("extra.txt", "tamper")

    with pytest.raises(PublicDeployCandidateError, match="checks are stale"):
        verify_public_deploy_candidate_receipt_file(Path(result["receipt_json"]))


def test_external_alpha_public_deploy_candidate_rejects_stale_upload_root(tmp_path: Path) -> None:
    check_send_ready(tmp_path)
    result = check_public_deploy_candidate(tmp_path)
    upload_root = tmp_path / PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
    (upload_root / "extra.txt").write_text("tamper", encoding="utf-8")

    with pytest.raises(PublicDeployCandidateError, match="checks are stale"):
        verify_public_deploy_candidate_receipt_file(Path(result["receipt_json"]))
