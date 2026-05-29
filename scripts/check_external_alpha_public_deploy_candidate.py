"""Check the public download site package as the upload candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.package_external_alpha_public_download_site import (  # noqa: E402
    CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME,
    PACKAGE_VERDICT,
    PUBLIC_SITE_PACKAGE_RECEIPT_NAME,
    PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME,
    PUBLIC_SITE_PACKAGE_ZIP_NAME,
    package_public_download_site,
    verify_public_download_site_package_receipt_file,
)
from scripts.prepare_external_alpha_public_download_site import (  # noqa: E402
    INDEX_NAME,
    PUBLIC_HOSTING_RUNBOOK_NAME,
    REQUIRED_SITE_FILES,
    ZIP_NAME,
)


PUBLIC_DEPLOY_CANDIDATE_SCHEMA_VERSION = "external_alpha_public_deploy_candidate_v0_1"
PUBLIC_DEPLOY_CANDIDATE_VERDICT = "PUBLIC_DEPLOY_CANDIDATE_READY"
PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME = f"{RELEASE_SLUG}-public-deploy-candidate-receipt.json"

logger = logging.getLogger(__name__)


class PublicDeployCandidateError(RuntimeError):
    """Public deploy candidate check failed."""


def check_public_deploy_candidate(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Build and verify the ZIP that an operator should upload to static hosting."""
    output_dir = output_dir.resolve()
    package_result = package_public_download_site(output_dir)
    package_receipt = verify_public_download_site_package_receipt_file(Path(package_result["receipt_json"]))
    package_zip = Path(package_result["package_zip"]).resolve()
    inspection = _inspect_package_zip(package_zip)

    payload = _deploy_candidate_payload(
        package_result=package_result,
        package_receipt=package_receipt,
        inspection=inspection,
    )
    receipt_path = (receipt_path or output_dir / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_public_deploy_candidate_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "package_zip": package_result["package_zip"],
        "package_sha256": payload["deploy_candidate"]["package_sha256"],
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["public_deploy_candidate_receipt_body_sha256"],
    }


def verify_public_deploy_candidate_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_deploy_candidate_receipt_payload(payload, receipt_dir=path.resolve().parent)
    return payload


def verify_public_deploy_candidate_receipt_payload(
    payload: dict[str, Any],
    *,
    receipt_dir: Path | None = None,
) -> None:
    if payload.get("schema_version") != PUBLIC_DEPLOY_CANDIDATE_SCHEMA_VERSION:
        raise PublicDeployCandidateError("public deploy candidate schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != PUBLIC_DEPLOY_CANDIDATE_VERDICT:
        raise PublicDeployCandidateError("public deploy candidate did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PublicDeployCandidateError("public deploy candidate must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    package_zip = _package_zip_from_payload(payload, receipt_dir) if receipt_dir else None
    upload_root = _upload_root_from_payload(payload, receipt_dir) if receipt_dir else None
    recalculated = _candidate_checks(payload, package_zip=package_zip, upload_root=upload_root)
    if checks != recalculated:
        raise PublicDeployCandidateError("public deploy candidate checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicDeployCandidateError("public deploy candidate checks failed: " + ", ".join(failed))
    if payload.get("public_deploy_candidate_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PublicDeployCandidateError("public deploy candidate body hash mismatch.")


def _deploy_candidate_payload(
    *,
    package_result: dict[str, Any],
    package_receipt: dict[str, Any],
    inspection: dict[str, Any],
) -> dict[str, Any]:
    package = _dict(package_receipt, "package")
    upload_root = _dict(package_receipt, "upload_root")
    release = _dict(package_receipt, "release")
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_DEPLOY_CANDIDATE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": PUBLIC_DEPLOY_CANDIDATE_VERDICT,
        "safe_to_share": True,
        "deploy_candidate": {
            "package_zip_file": PUBLIC_SITE_PACKAGE_ZIP_NAME,
            "canonical_package_zip_file": CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME,
            "upload_root_directory": PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME,
            "package_sha256": package_result.get("package_sha256"),
            "package_bytes": package.get("bytes"),
            "package_entry_count": package.get("entry_count"),
            "upload_model": "upload_zip_or_unzipped_root_entries_to_static_host",
            "upload_options": ["zip_file", "folder_contents"],
            "external_sharing_allowed": False,
            "reason_external_sharing_blocked": "public_https_url_not_verified_yet",
        },
        "release": {
            "public_download_zip_file": ZIP_NAME,
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "package_receipt": {
            "file": PUBLIC_SITE_PACKAGE_RECEIPT_NAME,
            "verdict": package_receipt.get("verdict"),
            "receipt_body_sha256": package_receipt.get("public_download_site_package_receipt_body_sha256"),
            "upload_root_directory": upload_root.get("directory_name"),
        },
        "inspection": inspection,
        "hosting": {
            "acceptable_upload_units": [
                PUBLIC_SITE_PACKAGE_ZIP_NAME,
                f"{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}/ contents",
            ],
            "acceptable_host_classes": [
                "Cloudflare Pages direct upload",
                "Netlify manual deploy",
                "GitHub Pages static branch",
                "S3-compatible static website with HTTPS fronting",
            ],
            "required_next_gate": (
                "python scripts\\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> "
                f"--expected-archive-sha256 {release.get('archive_sha256')} "
                " --receipt dist\\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json"
            ),
            "local_rehearsal_is_not_launch": True,
        },
        "policy": {
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "external_share_before_public_url_gate": False,
        },
        "operator_next_action": (
            f"Upload {PUBLIC_SITE_PACKAGE_ZIP_NAME}, or upload the contents of {PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}/, "
            "to a static HTTPS host, then run the public launch URL gate. "
            "Do not share the URL until the final gate returns PUBLIC_LAUNCH_URL_READY."
        ),
    }
    payload["public_deploy_candidate_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _candidate_checks(
        payload,
        package_zip=Path(package_result["package_zip"]).resolve(),
        upload_root=Path(package_result["upload_root"]).resolve(),
    )
    return payload


def _candidate_checks(
    payload: dict[str, Any],
    *,
    package_zip: Path | None = None,
    upload_root: Path | None = None,
) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    candidate = _dict(payload, "deploy_candidate")
    release = _dict(payload, "release")
    package_receipt = _dict(payload, "package_receipt")
    inspection = _dict(payload, "inspection")
    hosting = _dict(payload, "hosting")
    policy = _dict(payload, "policy")
    entries = inspection.get("entries") if isinstance(inspection.get("entries"), list) else []
    upload_options = candidate.get("upload_options") if isinstance(candidate.get("upload_options"), list) else []
    acceptable_upload_units = (
        hosting.get("acceptable_upload_units") if isinstance(hosting.get("acceptable_upload_units"), list) else []
    )
    runbook = _dict(inspection, "runbook")
    body_hash = payload.get("public_deploy_candidate_receipt_body_sha256")
    current_package_hash = _sha256_file(package_zip) if package_zip and package_zip.is_file() else None
    current_inspection = _inspect_package_zip_for_check(package_zip) if package_zip else None
    current_zip_entries = _zip_entry_hashes(package_zip) if package_zip and package_zip.is_file() else None
    current_upload_root_entries = _folder_entry_hashes(upload_root) if upload_root else None
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_DEPLOY_CANDIDATE_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == PUBLIC_DEPLOY_CANDIDATE_VERDICT,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "package_file_named": candidate.get("package_zip_file") == PUBLIC_SITE_PACKAGE_ZIP_NAME,
        "canonical_package_file_recorded": candidate.get("canonical_package_zip_file")
        == CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME,
        "upload_root_directory_recorded": candidate.get("upload_root_directory") == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
        and package_receipt.get("upload_root_directory") == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME,
        "upload_options_recorded": {"zip_file", "folder_contents"}.issubset(set(str(item) for item in upload_options)),
        "package_hash_present": _looks_like_sha256(candidate.get("package_sha256")),
        "package_file_hash_matches_current_zip": package_zip is None
        or (package_zip.is_file() and candidate.get("package_sha256") == current_package_hash),
        "upload_root_matches_current_zip": upload_root is None
        or (
            upload_root.is_dir()
            and isinstance(current_zip_entries, dict)
            and current_upload_root_entries == current_zip_entries
        ),
        "package_bytes_present": isinstance(candidate.get("package_bytes"), int)
        and candidate.get("package_bytes", 0) > 0,
        "inspection_matches_current_zip": current_inspection is None or current_inspection == inspection,
        "package_entry_count_matches_inspection": candidate.get("package_entry_count") == inspection.get("entry_count"),
        "external_share_blocked_before_url_gate": candidate.get("external_sharing_allowed") is False
        and policy.get("external_share_before_public_url_gate") is False,
        "release_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "package_receipt_ready": package_receipt.get("verdict") == PACKAGE_VERDICT
        and _looks_like_sha256(package_receipt.get("receipt_body_sha256")),
        "zip_root_entries_only": inspection.get("root_entries_only") is True,
        "zip_has_required_site_files": set(REQUIRED_SITE_FILES).issubset(set(entries)),
        "zip_has_public_download": ZIP_NAME in entries,
        "zip_has_index": INDEX_NAME in entries,
        "zip_has_runbook": PUBLIC_HOSTING_RUNBOOK_NAME in entries,
        "zip_does_not_include_package_receipt": PUBLIC_SITE_PACKAGE_RECEIPT_NAME not in entries,
        "runbook_names_final_gate": runbook.get("mentions_final_gate") is True
        and runbook.get("mentions_public_https_placeholder") is True,
        "runbook_blocks_local_share": runbook.get("mentions_local_rehearsal") is True
        and runbook.get("mentions_external_share_allowed_true") is True
        and runbook.get("mentions_rehearsal_share_false") is True,
        "hosting_upload_units_recorded": PUBLIC_SITE_PACKAGE_ZIP_NAME in acceptable_upload_units
        and f"{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}/ contents" in acceptable_upload_units,
        "hosting_next_gate_present": isinstance(hosting.get("required_next_gate"), str)
        and "finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL>" in hosting.get("required_next_gate", "")
        and str(release.get("archive_sha256")) in hosting.get("required_next_gate", ""),
        "local_rehearsal_not_launch": hosting.get("local_rehearsal_is_not_launch") is True,
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and "PUBLIC_LAUNCH_URL_READY" in payload.get("operator_next_action", "")
        and PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME in payload.get("operator_next_action", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _inspect_package_zip(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            entries = sorted(name for name in names if not name.endswith("/"))
            if any(_bad_zip_entry_name(name) for name in entries):
                raise PublicDeployCandidateError("public deploy package has unsafe ZIP entries.")
            runbook_text = archive.read(PUBLIC_HOSTING_RUNBOOK_NAME).decode("utf-8")
    except KeyError as exc:
        raise PublicDeployCandidateError(f"public deploy package is missing {PUBLIC_HOSTING_RUNBOOK_NAME}.") from exc
    except zipfile.BadZipFile as exc:
        raise PublicDeployCandidateError("public deploy package ZIP cannot be opened.") from exc
    except OSError as exc:
        raise PublicDeployCandidateError(f"cannot read public deploy package ZIP: {path.name}") from exc
    except UnicodeDecodeError as exc:
        raise PublicDeployCandidateError(f"{PUBLIC_HOSTING_RUNBOOK_NAME} is not UTF-8.") from exc
    return {
        "entry_count": len(entries),
        "entries": entries,
        "root_entries_only": all("/" not in name and "\\" not in name for name in entries),
        "runbook": {
            "file": PUBLIC_HOSTING_RUNBOOK_NAME,
            "sha256": hashlib.sha256(runbook_text.encode("utf-8")).hexdigest(),
            "mentions_final_gate": "finalize_external_alpha_public_launch_url.py" in runbook_text,
            "mentions_public_https_placeholder": "<PUBLIC_HTTPS_URL>" in runbook_text,
            "mentions_local_rehearsal": "PUBLIC_LAUNCH_URL_REHEARSAL_READY" in runbook_text,
            "mentions_external_share_allowed_true": "external_sharing_allowed=true" in runbook_text,
            "mentions_rehearsal_share_false": "external_sharing_allowed=false" in runbook_text,
        },
    }


def _inspect_package_zip_for_check(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        return _inspect_package_zip(path)
    except PublicDeployCandidateError:
        return {}


def _zip_entry_hashes(path: Path | None) -> dict[str, dict[str, Any]] | None:
    if path is None:
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if any(name.endswith("/") or _bad_zip_entry_name(name) for name in names):
                return {}
            return {
                name: {
                    "bytes": len(data := archive.read(name)),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for name in names
            }
    except (OSError, zipfile.BadZipFile):
        return {}


def _folder_entry_hashes(path: Path | None) -> dict[str, dict[str, Any]] | None:
    if path is None:
        return None
    if not path.is_dir():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        name = file_path.relative_to(path).as_posix()
        if _bad_zip_entry_name(name):
            return {}
        data = file_path.read_bytes()
        result[name] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return result


def _bad_zip_entry_name(name: str) -> bool:
    if not name or "\\" in name:
        return True
    path = Path(name)
    return path.is_absolute() or ".." in path.parts


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicDeployCandidateError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicDeployCandidateError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicDeployCandidateError(f"JSON payload must be an object: {path.name}")
    return payload


def _package_zip_from_payload(payload: dict[str, Any], receipt_dir: Path | None) -> Path | None:
    if receipt_dir is None:
        return None
    candidate = _dict(payload, "deploy_candidate")
    package_file = candidate.get("package_zip_file")
    if not isinstance(package_file, str) or _bad_zip_entry_name(package_file):
        return None
    return receipt_dir / package_file


def _upload_root_from_payload(payload: dict[str, Any], receipt_dir: Path | None) -> Path | None:
    if receipt_dir is None:
        return None
    candidate = _dict(payload, "deploy_candidate")
    upload_root_directory = candidate.get("upload_root_directory")
    if not isinstance(upload_root_directory, str) or _bad_zip_entry_name(upload_root_directory):
        return None
    return receipt_dir / upload_root_directory


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_deploy_candidate_receipt_body_sha256", "checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the external alpha public deploy candidate package.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--verify-receipt", default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_public_deploy_candidate_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public deploy candidate receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha public deploy candidate receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("zip    : %s", payload["deploy_candidate"]["package_zip_file"])
        logger.info("sha256 : %s", payload["deploy_candidate"]["package_sha256"])
        logger.info("body   : %s", payload["public_deploy_candidate_receipt_body_sha256"])
        return 0

    try:
        result = check_public_deploy_candidate(
            Path(args.output_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing build failure.
        logger.error("[FAIL] external alpha public deploy candidate: %s", exc)
        return 1

    logger.info("[PASS] external alpha public deploy candidate")
    logger.info("verdict: %s", result["verdict"])
    logger.info("zip    : %s", result["package_zip"])
    logger.info("sha256 : %s", result["package_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
