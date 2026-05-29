"""Package the external alpha public download site as an upload-ready ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_public_download_site import (  # noqa: E402
    INDEX_NAME,
    MANIFEST_NAME,
    PUBLIC_SITE_DIR_NAME,
    PUBLIC_SITE_RECEIPT_NAME,
    RELEASE_RECEIPT_NAME,
    REQUIRED_SITE_FILES,
    SEND_READY_JSON_NAME,
    SEND_READY_MD_NAME,
    ZIP_NAME,
    prepare_public_download_site,
    verify_public_download_site_receipt_file,
)


PUBLIC_SITE_PACKAGE_SCHEMA_VERSION = "external_alpha_public_download_site_package_v0_1"
CANONICAL_PUBLIC_SITE_PACKAGE_ZIP_NAME = f"{PUBLIC_SITE_DIR_NAME}.zip"
PUBLIC_SITE_PACKAGE_ZIP_NAME = "cambrian-public-site.zip"
PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME = "cambrian-public-site"
PUBLIC_SITE_PACKAGE_RECEIPT_NAME = f"{PUBLIC_SITE_DIR_NAME}-package-receipt.json"
PACKAGE_VERDICT = "PUBLIC_DOWNLOAD_SITE_PACKAGE_READY"
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

logger = logging.getLogger(__name__)


class PublicDownloadSitePackageError(RuntimeError):
    """Public download site package generation or verification failed."""


def package_public_download_site(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    site_dir: Path | None = None,
    package_zip: Path | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Create an upload-ready ZIP for the static public download site."""
    output_dir = output_dir.resolve()
    result = prepare_public_download_site(output_dir, site_dir=site_dir)
    site_root = Path(result["site_dir"]).resolve()
    site_receipt_path = site_root / PUBLIC_SITE_RECEIPT_NAME
    site_receipt = verify_public_download_site_receipt_file(site_receipt_path)
    upload_root = (output_dir / PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME).resolve()
    _refresh_upload_root(site_root, upload_root)

    package_zip = (package_zip or output_dir / PUBLIC_SITE_PACKAGE_ZIP_NAME).resolve()
    receipt_path = (receipt_path or output_dir / PUBLIC_SITE_PACKAGE_RECEIPT_NAME).resolve()
    _assert_not_inside(package_zip, site_root, "package ZIP")
    _assert_not_inside(package_zip, upload_root, "package ZIP")
    _assert_not_inside(receipt_path, site_root, "package receipt")
    _assert_not_inside(receipt_path, upload_root, "package receipt")

    package_zip.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    entries = _write_package_zip(upload_root, package_zip)

    payload = _package_receipt_payload(
        package_zip=package_zip,
        upload_root=upload_root,
        site_receipt=site_receipt,
        entries=entries,
    )
    _write_json(receipt_path, payload)
    verify_public_download_site_package_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "upload_root": str(upload_root),
        "package_zip": str(package_zip),
        "receipt_json": str(receipt_path),
        "package_sha256": payload["package"]["sha256"],
        "public_site_receipt_body_sha256": payload["public_site"]["receipt_body_sha256"],
        "receipt_body_sha256": payload["public_download_site_package_receipt_body_sha256"],
    }


def verify_public_download_site_package_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_download_site_package_receipt_payload(payload, receipt_dir=path.resolve().parent)
    return payload


def verify_public_download_site_package_receipt_payload(
    payload: dict[str, Any],
    *,
    receipt_dir: Path | None = None,
) -> None:
    if payload.get("schema_version") != PUBLIC_SITE_PACKAGE_SCHEMA_VERSION:
        raise PublicDownloadSitePackageError("public download site package receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != PACKAGE_VERDICT:
        raise PublicDownloadSitePackageError("public download site package receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PublicDownloadSitePackageError("public download site package receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    package_zip = _package_zip_from_payload(payload, receipt_dir) if receipt_dir else None
    recalculated = _receipt_checks(payload, package_zip=package_zip)
    if checks != recalculated:
        raise PublicDownloadSitePackageError("public download site package receipt checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicDownloadSitePackageError(
            "public download site package receipt checks failed: " + ", ".join(failed)
        )
    if payload.get("public_download_site_package_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PublicDownloadSitePackageError("public download site package receipt body hash mismatch.")


def _write_package_zip(site_root: Path, package_zip: Path) -> list[dict[str, Any]]:
    files = sorted(path for path in site_root.rglob("*") if path.is_file())
    if not files:
        raise PublicDownloadSitePackageError("public download site directory has no files to package.")

    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(package_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            arcname = path.relative_to(site_root).as_posix()
            if _bad_zip_entry_name(arcname):
                raise PublicDownloadSitePackageError(f"unsafe package ZIP entry name: {arcname}")
            info = zipfile.ZipInfo(arcname, ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = path.read_bytes()
            archive.writestr(info, data)
            entries.append(
                {
                    "file": arcname,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return entries


def _refresh_upload_root(site_root: Path, upload_root: Path) -> None:
    if site_root == upload_root:
        raise PublicDownloadSitePackageError("upload root must be separate from the canonical public site directory.")
    if upload_root.exists():
        if upload_root.is_dir():
            shutil.rmtree(upload_root)
        else:
            upload_root.unlink()
    upload_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(path for path in site_root.rglob("*") if path.is_file()):
        relative = source.relative_to(site_root)
        target = upload_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _package_receipt_payload(
    *,
    package_zip: Path,
    upload_root: Path,
    site_receipt: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    site = _dict(site_receipt, "site")
    release = _dict(site_receipt, "release")
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_SITE_PACKAGE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": PACKAGE_VERDICT,
        "safe_to_share": True,
        "package": {
            "file": package_zip.name,
            "bytes": package_zip.stat().st_size,
            "sha256": _sha256_file(package_zip),
            "entry_count": len(entries),
            "entrypoint": INDEX_NAME,
            "root_entries_only": True,
            "includes_package_receipt": False,
            "local_path_included": False,
        },
        "upload_root": {
            "directory_name": upload_root.name,
            "entrypoint": INDEX_NAME,
            "mirrors_public_site_directory": site.get("directory_name"),
            "root_entries_only": True,
            "includes_package_receipt": False,
        },
        "public_site": {
            "directory_name": site.get("directory_name"),
            "receipt_file": PUBLIC_SITE_RECEIPT_NAME,
            "receipt_body_sha256": site_receipt.get("public_download_site_receipt_body_sha256"),
            "verdict": site_receipt.get("verdict"),
            "entrypoint": site.get("entrypoint"),
        },
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "entries": entries,
        "policy": {
            "script_sends_to_recipient": False,
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "ready_for_static_hosting": True,
            "short_upload_root_included": True,
            "receipt_outside_package": True,
        },
        "operator_next_action": (
            f"Upload {PUBLIC_SITE_PACKAGE_ZIP_NAME}, or upload the unzipped {PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME} "
            "folder contents to the chosen static host, then run the public launch URL gate."
        ),
    }
    payload["public_download_site_package_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _receipt_checks(payload, package_zip=package_zip)
    return payload


def _receipt_checks(payload: dict[str, Any], *, package_zip: Path | None = None) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    package = _dict(payload, "package")
    upload_root = _dict(payload, "upload_root")
    public_site = _dict(payload, "public_site")
    release = _dict(payload, "release")
    policy = _dict(payload, "policy")
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    by_file = {item.get("file"): item for item in entries if isinstance(item, dict)}
    package_file = package.get("file")
    body_hash = payload.get("public_download_site_package_receipt_body_sha256")
    package_zip_hash = _sha256_file(package_zip) if package_zip and package_zip.is_file() else None
    zip_entries = _zip_entry_hashes(package_zip) if package_zip and package_zip.is_file() else None
    expected_names = sorted(item.get("file") for item in entries if isinstance(item, dict))
    actual_names = sorted(zip_entries) if isinstance(zip_entries, dict) else None
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_SITE_PACKAGE_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == PACKAGE_VERDICT,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "package_file_named": isinstance(package_file, str) and package_file == PUBLIC_SITE_PACKAGE_ZIP_NAME,
        "package_zip_extension": isinstance(package_file, str) and package_file.endswith(".zip"),
        "package_hash_present": _looks_like_sha256(package.get("sha256")),
        "package_bytes_present": isinstance(package.get("bytes"), int) and package.get("bytes", 0) > 0,
        "entry_count_matches": package.get("entry_count") == len(entries),
        "entrypoint_index": package.get("entrypoint") == INDEX_NAME,
        "upload_root_named": upload_root.get("directory_name") == PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME
        and upload_root.get("entrypoint") == INDEX_NAME,
        "upload_root_mirrors_public_site": upload_root.get("mirrors_public_site_directory")
        == public_site.get("directory_name"),
        "upload_root_package_receipt_excluded": upload_root.get("includes_package_receipt") is False
        and upload_root.get("root_entries_only") is True,
        "root_entries_only": package.get("root_entries_only") is True
        and all(isinstance(item.get("file"), str) and "/" not in item["file"] for item in entries if isinstance(item, dict)),
        "package_receipt_excluded": package.get("includes_package_receipt") is False
        and PUBLIC_SITE_PACKAGE_RECEIPT_NAME not in by_file,
        "local_path_omitted": package.get("local_path_included") is False,
        "required_site_files_present": set(REQUIRED_SITE_FILES).issubset(set(by_file)),
        "site_receipt_present": PUBLIC_SITE_RECEIPT_NAME in by_file,
        "index_present": INDEX_NAME in by_file,
        "manifest_present": MANIFEST_NAME in by_file,
        "release_receipt_present": RELEASE_RECEIPT_NAME in by_file,
        "send_ready_files_present": SEND_READY_MD_NAME in by_file and SEND_READY_JSON_NAME in by_file,
        "release_zip_present": ZIP_NAME in by_file,
        "entry_hashes_present": bool(entries)
        and all(_looks_like_sha256(item.get("sha256")) and isinstance(item.get("bytes"), int) for item in entries if isinstance(item, dict)),
        "release_zip_hash_matches_release": by_file.get(ZIP_NAME, {}).get("sha256") == release.get("archive_sha256")
        and _looks_like_sha256(release.get("archive_sha256")),
        "public_site_ready": public_site.get("verdict") == "PUBLIC_DOWNLOAD_SITE_READY"
        and public_site.get("entrypoint") == INDEX_NAME
        and public_site.get("receipt_file") == PUBLIC_SITE_RECEIPT_NAME
        and _looks_like_sha256(public_site.get("receipt_body_sha256")),
        "manual_only_no_email_collection": policy.get("script_sends_to_recipient") is False
        and policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "static_hosting_ready": policy.get("ready_for_static_hosting") is True,
        "short_upload_root_included": policy.get("short_upload_root_included") is True,
        "receipt_outside_package": policy.get("receipt_outside_package") is True,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME in payload.get("operator_next_action", "")
        and "public launch URL gate" in payload.get("operator_next_action", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
        "package_hash_matches_file": package_zip is None or package.get("sha256") == package_zip_hash,
        "zip_entries_match_payload": zip_entries is None
        or (
            actual_names == expected_names
            and all(
                isinstance(item, dict)
                and isinstance(item.get("file"), str)
                and zip_entries.get(item["file"], {}).get("sha256") == item.get("sha256")
                and zip_entries.get(item["file"], {}).get("bytes") == item.get("bytes")
                for item in entries
            )
        ),
    }


def _zip_entry_hashes(path: Path) -> dict[str, dict[str, Any]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if any(name.endswith("/") or _bad_zip_entry_name(name) for name in names):
                return {}
            result: dict[str, dict[str, Any]] = {}
            for name in names:
                data = archive.read(name)
                result[name] = {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            return result
    except (OSError, zipfile.BadZipFile):
        return {}


def _package_zip_from_payload(payload: dict[str, Any], receipt_dir: Path) -> Path | None:
    package = _dict(payload, "package")
    package_file = package.get("file")
    if not isinstance(package_file, str) or _bad_zip_entry_name(package_file):
        return None
    return receipt_dir / package_file


def _bad_zip_entry_name(name: str) -> bool:
    if not name or "\\" in name:
        return True
    path = Path(name)
    return path.is_absolute() or ".." in path.parts


def _assert_not_inside(path: Path, directory: Path, label: str) -> None:
    try:
        path.relative_to(directory)
    except ValueError:
        return
    raise PublicDownloadSitePackageError(f"{label} must be outside the public download site directory.")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicDownloadSitePackageError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicDownloadSitePackageError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicDownloadSitePackageError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_download_site_package_receipt_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Package the external alpha public download site for hosting upload.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--site-dir", default=None)
    parser.add_argument("--package-zip", default=None)
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
            payload = verify_public_download_site_package_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public download site package verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha public download site package verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("zip    : %s", payload["package"]["file"])
        logger.info("sha256 : %s", payload["package"]["sha256"])
        logger.info("body   : %s", payload["public_download_site_package_receipt_body_sha256"])
        return 0

    try:
        result = package_public_download_site(
            Path(args.output_dir),
            site_dir=Path(args.site_dir) if args.site_dir else None,
            package_zip=Path(args.package_zip) if args.package_zip else None,
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing build failure.
        logger.error("[FAIL] external alpha public download site package: %s", exc)
        return 1

    logger.info("[PASS] external alpha public download site package")
    logger.info("verdict: %s", result["verdict"])
    logger.info("root   : %s", result["upload_root"])
    logger.info("zip    : %s", result["package_zip"])
    logger.info("sha256 : %s", result["package_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
