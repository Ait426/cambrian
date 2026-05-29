"""외부 알파 ZIP 릴리즈 산출물을 수령자 관점에서 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import (
    DISPATCH_EXECUTION_POLICY,
    FORBIDDEN_PATH_PARTS,
    INCLUDED_FILES,
    RELEASE_BOUNDARIES,
    RELEASE_SLUG,
    RELEASE_VERSION,
    TRUST_REPORT_NAME,
)

DEFAULT_ZIP = ROOT / "dist" / f"{RELEASE_SLUG}.zip"
DEFAULT_MANIFEST = ROOT / "dist" / f"{RELEASE_SLUG}.manifest.json"
BUNDLE_MANIFEST_NAME = "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json"
SUPPORT_PACKET_NAME = "EXTERNAL_ALPHA_SUPPORT_PACKET.md"
RECEIPT_SCHEMA_VERSION = "external_alpha_release_verification_receipt_v0_1"

logger = logging.getLogger(__name__)


class ReleaseVerificationError(Exception):
    """외부 알파 릴리즈 검증 실패."""


def verify_release(
    zip_path: Path = DEFAULT_ZIP,
    manifest_path: Path = DEFAULT_MANIFEST,
    extract_dir: Path | None = None,
    keep_extracted: bool = False,
    require_current_source_match: bool = True,
    current_source_root: Path = ROOT,
) -> dict[str, Any]:
    """ZIP, 외부 manifest, 압축 해제 후 자체 검증을 한 번에 수행한다."""
    resolved_zip = zip_path.resolve()
    resolved_manifest = manifest_path.resolve()
    manifest = _read_manifest(resolved_manifest)

    _verify_release_policy(manifest)
    _verify_manifest_archive_hash(manifest, resolved_zip)
    _verify_zip_entries(manifest, resolved_zip)

    if extract_dir is None:
        with tempfile.TemporaryDirectory(prefix="cambrian-alpha-verify-") as temp_root:
            extracted_root = _extract_and_verify(resolved_zip, Path(temp_root))
            _run_extracted_platform_verification(extracted_root)
            browser_wrapper = _run_extracted_browser_wrapper_help(extracted_root)
            diagnostics_summary = _run_extracted_diagnostics(extracted_root)
            batch_rehearsal = _run_extracted_windows_batch_rehearsal(extracted_root)
            current_source_manifest = (
                _verify_current_source_manifest(manifest, current_source_root)
                if require_current_source_match
                else _skipped_current_source_manifest()
            )
            return _summary(
                resolved_zip,
                resolved_manifest,
                extracted_root,
                manifest,
                kept=False,
                browser_wrapper=browser_wrapper,
                diagnostics_summary=diagnostics_summary,
                batch_rehearsal=batch_rehearsal,
                current_source_manifest=current_source_manifest,
            )

    target_root = extract_dir.resolve()
    if target_root.exists():
        if not keep_extracted:
            raise ReleaseVerificationError("지정한 extract_dir가 이미 존재합니다. 새 경로를 지정하세요.")
    else:
        target_root.mkdir(parents=True)

    extracted_root = _extract_and_verify(resolved_zip, target_root)
    _run_extracted_platform_verification(extracted_root)
    browser_wrapper = _run_extracted_browser_wrapper_help(extracted_root)
    diagnostics_summary = _run_extracted_diagnostics(extracted_root)
    batch_rehearsal = _run_extracted_windows_batch_rehearsal(extracted_root)
    current_source_manifest = (
        _verify_current_source_manifest(manifest, current_source_root)
        if require_current_source_match
        else _skipped_current_source_manifest()
    )
    if not keep_extracted:
        shutil.rmtree(target_root)
    return _summary(
        resolved_zip,
        resolved_manifest,
        extracted_root,
        manifest,
        kept=keep_extracted,
        browser_wrapper=browser_wrapper,
        diagnostics_summary=diagnostics_summary,
        batch_rehearsal=batch_rehearsal,
        current_source_manifest=current_source_manifest,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Cambrian Agent Platform 외부 알파 ZIP을 검증한다.")
    parser.add_argument("--zip", default=str(DEFAULT_ZIP), help="검증할 외부 알파 ZIP 경로")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="ZIP 밖 manifest JSON 경로")
    parser.add_argument("--extract-dir", default=None, help="검증용 압축 해제 폴더. 생략하면 임시 폴더를 쓴다.")
    parser.add_argument("--keep-extracted", action="store_true", help="--extract-dir 내용을 검증 후 보존한다.")
    parser.add_argument("--receipt", default=None, help="공유 가능한 검증 영수증 JSON 출력 경로")
    parser.add_argument("--verify-receipt", default=None, help="ZIP 없이 검증 영수증 JSON만 검증한다.")
    parser.add_argument(
        "--skip-current-source-check",
        action="store_true",
        help="standalone ZIP/manifest만 검증해야 할 때 현재 소스 allowlist 대조를 건너뛴다.",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            receipt = verify_shareable_receipt_file(Path(args.verify_receipt))
        except ReleaseVerificationError as exc:
            logger.error("[FAIL] external alpha receipt verification: %s", exc)
            return 1
        except Exception as exc:  # noqa: BLE001 - 예기치 못한 receipt 검증 실패도 로그로 남기고 종료한다.
            logger.exception("[FAIL] external alpha receipt verification crashed: %s", exc)
            return 1
        _log_receipt_success_summary(receipt)
        return 0

    receipt_path: Path | None = None
    try:
        result = verify_release(
            zip_path=Path(args.zip),
            manifest_path=Path(args.manifest),
            extract_dir=Path(args.extract_dir) if args.extract_dir else None,
            keep_extracted=args.keep_extracted,
            require_current_source_match=not args.skip_current_source_check,
        )
        if args.receipt:
            receipt_path = _write_shareable_receipt(Path(args.receipt), result)
    except ReleaseVerificationError as exc:
        logger.error("[FAIL] external alpha release verification: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - 예기치 못한 실패도 로그로 남기고 종료한다.
        logger.exception("[FAIL] external alpha release verification crashed: %s", exc)
        return 1

    _log_success_summary(result)
    if receipt_path is not None:
        logger.info("receipt : %s", receipt_path)
    return 0


def _log_success_summary(result: dict[str, Any]) -> None:
    """수령자가 검증 통과 근거를 한눈에 볼 수 있게 성공 요약을 출력한다."""
    batch_rehearsal = result.get("batch_rehearsal")
    batch_status = batch_rehearsal.get("status") if isinstance(batch_rehearsal, dict) else "unknown"
    browser_wrapper = result.get("browser_wrapper")
    browser_status = browser_wrapper.get("status") if isinstance(browser_wrapper, dict) else "unknown"
    extracted_state = "kept" if result.get("extracted_kept") else "temporary"

    logger.info("[PASS] external alpha release verification")
    logger.info("release : %s", result["release_version"])
    logger.info("zip     : %s", result["zip_path"])
    logger.info("manifest: %s", result["manifest_path"])
    logger.info("sha256  : %s", result["archive_sha256"])
    logger.info("files   : %s", result["file_count"])
    logger.info("policy  : %s boundaries verified", result["boundary_count"])
    logger.info("trust   : %s verified", result["trust_report"])
    logger.info("source  : current manifest matched=%s", result["release_sources_match_current_manifest"])
    logger.info("diag    : %s privacy-safe share-safe", result["diagnostics_status"])
    logger.info("share   : diagnostics safe_to_share=%s", result["diagnostics_safe_to_share"])
    logger.info("support : %s", result["diagnostics_next_action"])
    logger.info("browser : %s wrapper help", browser_status)
    logger.info("batch   : %s", batch_status)
    logger.info("extract : %s", extracted_state)


def _log_receipt_success_summary(receipt: dict[str, Any]) -> None:
    """검증 영수증 단독 검증 결과를 요약 출력한다."""
    release = receipt.get("release") if isinstance(receipt.get("release"), dict) else {}
    diagnostics = receipt.get("diagnostics") if isinstance(receipt.get("diagnostics"), dict) else {}
    browser_wrapper = receipt.get("browser_wrapper") if isinstance(receipt.get("browser_wrapper"), dict) else {}
    logger.info("[PASS] external alpha receipt verification")
    logger.info("release : %s", release.get("version"))
    logger.info("sha256  : %s", release.get("archive_sha256"))
    logger.info("receipt : %s", receipt.get("receipt_body_sha256"))
    logger.info("diag    : %s safe_to_share=%s", diagnostics.get("status"), diagnostics.get("safe_to_share"))
    logger.info("browser : %s", browser_wrapper.get("status"))
    logger.info("support : %s", diagnostics.get("next_action"))


def verify_shareable_receipt_file(path: Path) -> dict[str, Any]:
    """ZIP 없이 공유 영수증 JSON만 읽어 변조 여부와 공유 안전성을 검증한다."""
    receipt = _read_json_file(path, "검증 영수증")
    _verify_shareable_receipt(receipt)
    return receipt


def write_shareable_receipt(output_path: Path, result: dict[str, Any]) -> Path:
    """절대경로와 시크릿 없이 공유 가능한 릴리즈 검증 영수증을 저장한다."""
    resolved_output = output_path.resolve()
    receipt = _shareable_receipt(result)
    _verify_shareable_receipt(receipt)
    try:
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ReleaseVerificationError(f"검증 영수증을 쓸 수 없습니다: {resolved_output}") from exc
    return resolved_output


def _write_shareable_receipt(output_path: Path, result: dict[str, Any]) -> Path:
    """기존 내부 호출을 위한 공유 영수증 저장 래퍼."""
    return write_shareable_receipt(output_path, result)


def _shareable_receipt(result: dict[str, Any]) -> dict[str, Any]:
    """지원 요청에 첨부할 수 있는 최소 검증 결과만 추린다."""
    batch_rehearsal = result.get("batch_rehearsal") if isinstance(result.get("batch_rehearsal"), dict) else {}
    browser_wrapper = result.get("browser_wrapper") if isinstance(result.get("browser_wrapper"), dict) else {}
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status"),
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "environment_variables_collected": False,
            "secret_values_collected": False,
            "user_documents_collected": False,
        },
        "verified_checks": {
            "archive_sha256_matched": True,
            "manifest_files_sha256_matched": True,
            "bundle_manifest_policy_matched": True,
            "trust_report_verified": True,
            "release_boundaries_verified": True,
            "forbidden_paths_excluded": True,
            "platform_verification_passed": True,
            "diagnostics_privacy_verified": True,
            "diagnostics_share_safety_verified": True,
            "support_summary_verified": True,
            "browser_smoke_wrapper_checked": True,
            "batch_rehearsal_checked": True,
            "current_sources_match_release_manifest": result.get("release_sources_match_current_manifest") is True,
        },
        "release": {
            "version": result.get("release_version"),
            "archive_sha256": result.get("archive_sha256"),
            "file_count": result.get("file_count"),
            "boundary_count": result.get("boundary_count"),
            "trust_report": result.get("trust_report"),
            "release_sources_match_current_manifest": result.get("release_sources_match_current_manifest"),
        },
        "diagnostics": {
            "status": result.get("diagnostics_status"),
            "safe_to_share": result.get("diagnostics_safe_to_share"),
            "next_action": result.get("diagnostics_next_action"),
            "do_not_share": result.get("diagnostics_do_not_share"),
        },
        "batch_rehearsal": {
            "status": batch_rehearsal.get("status"),
        },
        "browser_wrapper": {
            "status": browser_wrapper.get("status"),
            "script": browser_wrapper.get("script"),
            "mode": browser_wrapper.get("mode"),
            "requires_playwright_for_full_run": browser_wrapper.get("requires_playwright_for_full_run"),
        },
        "support_summary": {
            "next_action": result.get("diagnostics_next_action"),
            "do_not_share": result.get("diagnostics_do_not_share"),
        },
    }
    receipt["receipt_body_sha256"] = _receipt_body_sha256(receipt)
    receipt["receipt_checks"] = _receipt_checks(receipt)
    return receipt


def _receipt_body_sha256(receipt: dict[str, Any]) -> str:
    """영수증의 검증 본문만 정규화해 sha256 해시를 계산한다."""
    body = {
        key: value
        for key, value in receipt.items()
        if key not in {"generated_at", "receipt_body_sha256", "receipt_checks"}
    }
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _receipt_checks(receipt: dict[str, Any]) -> dict[str, bool]:
    """영수증 자체가 공유 가능한 최소 정보만 담는지 점검한다."""
    serialized = json.dumps(receipt, ensure_ascii=False)
    home = str(Path.home())
    body_hash = receipt.get("receipt_body_sha256")
    verified_checks = receipt.get("verified_checks") if isinstance(receipt.get("verified_checks"), dict) else {}
    return {
        "schema_version_present": receipt.get("schema_version") == RECEIPT_SCHEMA_VERSION,
        "safe_to_share_true": receipt.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "archive_hash_present": isinstance(receipt.get("release", {}).get("archive_sha256"), str),
        "diagnostics_next_action_present": isinstance(receipt.get("diagnostics", {}).get("next_action"), str),
        "do_not_share_guidance_present": ".env" in receipt.get("support_summary", {}).get("do_not_share", []),
        "verified_checks_all_true": bool(verified_checks) and all(value is True for value in verified_checks.values()),
        "browser_wrapper_check_present": receipt.get("browser_wrapper", {}).get("status") == "pass",
        "receipt_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "receipt_body_hash_matched": body_hash == _receipt_body_sha256(receipt),
    }


def _verify_shareable_receipt(receipt: dict[str, Any]) -> None:
    """공유 영수증이 스스로 안전 기준을 만족하는지 확인한다."""
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ReleaseVerificationError("검증 영수증 schema_version이 올바르지 않습니다.")
    if receipt.get("status") != "pass":
        raise ReleaseVerificationError(f"검증 영수증 status가 pass가 아닙니다: {receipt.get('status')}")
    if receipt.get("safe_to_share") is not True:
        raise ReleaseVerificationError("검증 영수증 safe_to_share가 true가 아닙니다.")
    checks = receipt.get("receipt_checks") if isinstance(receipt.get("receipt_checks"), dict) else {}
    if not checks:
        raise ReleaseVerificationError("검증 영수증 receipt_checks가 없습니다.")
    failed_checks = [name for name, passed in checks.items() if passed is not True]
    if failed_checks:
        raise ReleaseVerificationError("검증 영수증 안전 점검 실패: " + ", ".join(failed_checks))
    verified_checks = receipt.get("verified_checks") if isinstance(receipt.get("verified_checks"), dict) else {}
    if not verified_checks:
        raise ReleaseVerificationError("검증 영수증 verified_checks가 없습니다.")
    failed_verified_checks = [name for name, passed in verified_checks.items() if passed is not True]
    if failed_verified_checks:
        raise ReleaseVerificationError("검증 영수증 verified_checks 실패: " + ", ".join(failed_verified_checks))
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    if privacy.get("absolute_paths_included") is not False:
        raise ReleaseVerificationError("검증 영수증에 절대경로 포함 가능성이 표시되었습니다.")
    browser_wrapper = receipt.get("browser_wrapper") if isinstance(receipt.get("browser_wrapper"), dict) else {}
    if (
        browser_wrapper.get("status") != "pass"
        or browser_wrapper.get("script") != "verify_agent_platform_browser_flow.py"
        or browser_wrapper.get("mode") != "help_only"
    ):
        raise ReleaseVerificationError("receipt browser_wrapper verification result is incomplete.")
    if receipt.get("receipt_body_sha256") != _receipt_body_sha256(receipt):
        raise ReleaseVerificationError("검증 영수증 본문 해시가 일치하지 않습니다.")


def _read_manifest(path: Path) -> dict[str, Any]:
    """외부 manifest JSON을 읽는다."""
    payload = _read_json_file(path, "manifest")
    return payload


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
    """UTF-8 JSON 객체 파일을 읽는다."""
    if not path.is_file():
        raise ReleaseVerificationError(f"{label} 파일이 없습니다: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"{label} JSON 파싱 실패: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseVerificationError(f"{label}는 JSON 객체여야 합니다.")
    return payload


def _verify_manifest_archive_hash(manifest: dict[str, Any], zip_path: Path) -> None:
    """ZIP 자체 해시가 외부 manifest와 일치하는지 확인한다."""
    if not zip_path.is_file():
        raise ReleaseVerificationError(f"ZIP 파일이 없습니다: {zip_path}")
    if manifest.get("release_name") != RELEASE_SLUG:
        raise ReleaseVerificationError(f"release_name이 다릅니다: {manifest.get('release_name')}")

    archive = manifest.get("archive") if isinstance(manifest.get("archive"), dict) else {}
    expected_hash = archive.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ReleaseVerificationError("manifest.archive.sha256이 올바르지 않습니다.")

    actual_hash = _sha256_file(zip_path)
    if actual_hash != expected_hash:
        raise ReleaseVerificationError(f"ZIP sha256 불일치: expected={expected_hash}, actual={actual_hash}")


def _verify_release_policy(manifest: dict[str, Any]) -> None:
    """외부 알파 릴리즈 정책 경계가 manifest에 고정되어 있는지 확인한다."""
    if manifest.get("release_version") != RELEASE_VERSION:
        raise ReleaseVerificationError(f"release_version이 다릅니다: {manifest.get('release_version')}")

    files = manifest.get("files")
    if not isinstance(files, list):
        raise ReleaseVerificationError("manifest.files는 배열이어야 합니다.")
    if manifest.get("file_count") != len(files):
        raise ReleaseVerificationError("manifest.file_count가 files 길이와 일치하지 않습니다.")

    bundle_manifest = manifest.get("bundle_manifest") if isinstance(manifest.get("bundle_manifest"), dict) else {}
    if bundle_manifest.get("path") != BUNDLE_MANIFEST_NAME:
        raise ReleaseVerificationError("bundle_manifest.path가 올바르지 않습니다.")
    if bundle_manifest.get("hash_policy") != "self_hash_omitted":
        raise ReleaseVerificationError("bundle_manifest.hash_policy는 self_hash_omitted여야 합니다.")

    boundaries = manifest.get("boundaries")
    if not isinstance(boundaries, list):
        raise ReleaseVerificationError("manifest.boundaries는 배열이어야 합니다.")
    missing_boundaries = [boundary for boundary in RELEASE_BOUNDARIES if boundary not in boundaries]
    if missing_boundaries:
        raise ReleaseVerificationError("릴리즈 경계 누락: " + " / ".join(missing_boundaries))

    _verify_dispatch_execution_policy(manifest)

    forbidden = manifest.get("forbidden_path_parts")
    if not isinstance(forbidden, list):
        raise ReleaseVerificationError("manifest.forbidden_path_parts는 배열이어야 합니다.")
    missing_forbidden = sorted(FORBIDDEN_PATH_PARTS - set(forbidden))
    if missing_forbidden:
        raise ReleaseVerificationError("금지 경로 정책 누락: " + ", ".join(missing_forbidden))

    file_paths = {_manifest_path(entry) for entry in files}
    if TRUST_REPORT_NAME not in file_paths:
        raise ReleaseVerificationError(f"신뢰 리포트가 manifest.files에 없습니다: {TRUST_REPORT_NAME}")


def _verify_dispatch_execution_policy(manifest: dict[str, Any]) -> None:
    """릴리즈 manifest의 외부 발송 실행 정책이 보수적으로 고정되어 있는지 확인한다."""
    policy = manifest.get("dispatch_execution_policy")
    if not isinstance(policy, dict):
        raise ReleaseVerificationError("manifest.dispatch_execution_policy가 없습니다.")
    mismatched = [
        key
        for key, expected in DISPATCH_EXECUTION_POLICY.items()
        if (
            (type(expected) is bool and policy.get(key) is not expected)
            or (type(expected) is int and policy.get(key) != expected)
        )
    ]
    if mismatched:
        raise ReleaseVerificationError("dispatch_execution_policy 불일치: " + ", ".join(sorted(set(mismatched))))


def _verify_zip_entries(manifest: dict[str, Any], zip_path: Path) -> None:
    """ZIP 내부 경로와 manifest 파일 목록을 검증한다."""
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ReleaseVerificationError("manifest.files는 배열이어야 합니다.")

    expected_entries = {f"{RELEASE_SLUG}/{_manifest_path(entry)}" for entry in files}
    expected_entries.add(f"{RELEASE_SLUG}/{BUNDLE_MANIFEST_NAME}")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = {info.filename for info in archive.infolist() if not info.is_dir()}
            for name in names:
                _validate_archive_name(name)
            missing = sorted(expected_entries - names)
            if missing:
                raise ReleaseVerificationError("ZIP 내부 파일 누락: " + ", ".join(missing))
            _verify_file_hashes(archive, manifest)
            _verify_bundle_manifest(archive, manifest)
            _verify_trust_report(archive)
            _verify_support_packet(archive)
    except zipfile.BadZipFile as exc:
        raise ReleaseVerificationError(f"ZIP 파일을 열 수 없습니다: {exc}") from exc


def _verify_current_source_manifest(
    manifest: dict[str, Any],
    source_root: Path = ROOT,
    included_files: tuple[str, ...] = INCLUDED_FILES,
) -> dict[str, Any]:
    """Ensure the built release still matches the current sender-side source allowlist."""
    result = _current_source_manifest_checks(manifest, source_root=source_root, included_files=included_files)
    failed_checks = result.get("failed_checks", [])
    if failed_checks:
        detail_parts = []
        for key in ("missing_manifest_entries", "missing_source_files", "byte_mismatches", "sha256_mismatches"):
            values = result.get(key, [])
            if values:
                detail_parts.append(f"{key}={', '.join(values[:5])}")
        details = "; ".join(detail_parts)
        suffix = f" ({details})" if details else ""
        raise ReleaseVerificationError(
            "current source manifest verification failed: " + ", ".join(failed_checks) + suffix
        )
    return result


def _current_source_manifest_checks(
    manifest: dict[str, Any],
    source_root: Path = ROOT,
    included_files: tuple[str, ...] = INCLUDED_FILES,
) -> dict[str, Any]:
    """Compare manifest file entries with the current release source allowlist."""
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    by_path = {
        item.get("path"): item
        for item in files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    missing_manifest_entries: list[str] = []
    missing_source_files: list[str] = []
    byte_mismatches: list[str] = []
    sha256_mismatches: list[str] = []

    for relative in included_files:
        normalized = relative.replace("\\", "/")
        entry = by_path.get(normalized)
        if not isinstance(entry, dict):
            missing_manifest_entries.append(normalized)
            continue

        source_path = source_root / relative
        if not source_path.is_file():
            missing_source_files.append(normalized)
            continue

        data = source_path.read_bytes()
        if entry.get("bytes") != len(data):
            byte_mismatches.append(normalized)
        if entry.get("sha256") != hashlib.sha256(data).hexdigest():
            sha256_mismatches.append(normalized)

    checks = {
        "current_source_manifest_checked": True,
        "included_files_present_in_manifest": not missing_manifest_entries,
        "included_source_files_present": not missing_source_files,
        "current_source_bytes_match_manifest": not byte_mismatches,
        "current_source_sha256_match_manifest": not sha256_mismatches,
    }
    return {
        "checked": True,
        "included_file_count": len(included_files),
        "missing_manifest_entries": missing_manifest_entries,
        "missing_source_files": missing_source_files,
        "byte_mismatches": byte_mismatches,
        "sha256_mismatches": sha256_mismatches,
        "mismatch_count": len(byte_mismatches) + len(sha256_mismatches),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if passed is not True],
    }


def _skipped_current_source_manifest() -> dict[str, Any]:
    """Represent an explicit standalone verification that did not inspect local sources."""
    return {
        "checked": False,
        "included_file_count": 0,
        "missing_manifest_entries": [],
        "missing_source_files": [],
        "byte_mismatches": [],
        "sha256_mismatches": [],
        "mismatch_count": 0,
        "checks": {"current_source_manifest_checked": False},
        "failed_checks": ["current_source_manifest_checked"],
    }


def _verify_file_hashes(archive: zipfile.ZipFile, manifest: dict[str, Any]) -> None:
    """manifest.files의 byte 크기와 sha256이 ZIP 내부 실제 파일과 일치하는지 확인한다."""
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ReleaseVerificationError("manifest.files는 배열이어야 합니다.")
    for entry in files:
        relative = _manifest_path(entry)
        if not isinstance(entry, dict):
            raise ReleaseVerificationError("manifest.files 항목은 객체여야 합니다.")
        expected_bytes = entry.get("bytes")
        expected_sha256 = entry.get("sha256")
        if not isinstance(expected_bytes, int) or expected_bytes < 0:
            raise ReleaseVerificationError(f"manifest.files.bytes가 올바르지 않습니다: {relative}")
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ReleaseVerificationError(f"manifest.files.sha256이 올바르지 않습니다: {relative}")

        data = archive.read(f"{RELEASE_SLUG}/{relative}")
        if len(data) != expected_bytes:
            raise ReleaseVerificationError(f"파일 byte 크기 불일치: {relative}")
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ReleaseVerificationError(f"파일 sha256 불일치: {relative}")


def _verify_bundle_manifest(archive: zipfile.ZipFile, external_manifest: dict[str, Any]) -> None:
    """ZIP 내부 bundle manifest가 외부 manifest와 같은 파일 목록을 가리키는지 확인한다."""
    bundle_name = f"{RELEASE_SLUG}/{BUNDLE_MANIFEST_NAME}"
    try:
        bundle_payload = json.loads(archive.read(bundle_name).decode("utf-8"))
    except KeyError as exc:
        raise ReleaseVerificationError("ZIP 내부 bundle manifest가 없습니다.") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"bundle manifest JSON 파싱 실패: {exc}") from exc

    if not isinstance(bundle_payload, dict):
        raise ReleaseVerificationError("bundle manifest는 JSON 객체여야 합니다.")
    if bundle_payload.get("release_name") != external_manifest.get("release_name"):
        raise ReleaseVerificationError("bundle manifest release_name이 외부 manifest와 다릅니다.")
    _verify_release_policy(bundle_payload)

    external_paths = {_manifest_path(entry) for entry in external_manifest.get("files", [])}
    bundle_paths = {_manifest_path(entry) for entry in bundle_payload.get("files", [])}
    if bundle_paths != external_paths:
        raise ReleaseVerificationError("bundle manifest 파일 목록이 외부 manifest와 다릅니다.")
    if "archive" in bundle_payload:
        raise ReleaseVerificationError("bundle manifest는 archive 해시를 직접 포함하면 안 됩니다.")


def _verify_trust_report(archive: zipfile.ZipFile) -> None:
    """ZIP 안의 사람이 읽는 신뢰 리포트가 정책 경계를 설명하는지 확인한다."""
    report_name = f"{RELEASE_SLUG}/{TRUST_REPORT_NAME}"
    try:
        text = archive.read(report_name).decode("utf-8")
    except KeyError as exc:
        raise ReleaseVerificationError("ZIP 내부 신뢰 리포트가 없습니다.") from exc
    for phrase in [
        "External Alpha Trust Report",
        "Defensible Alpha",
        "한국 시장",
        "verified promotion audit lineage",
        "proof boundary",
        "python scripts/verify_external_alpha_release.py",
        "python scripts/check_external_alpha_pilot_ready.py",
        "python scripts/check_external_alpha_pilot_evidence.py",
        "python scripts/check_external_alpha_pilot_decision.py",
        "python scripts/check_external_alpha_pilot_iteration.py",
        "python scripts/audit_external_alpha_operator_send_bypass.py",
        "python scripts/check_external_alpha_cloudflare_credentials.py",
        "python scripts/run_external_alpha_public_launch_sequence.py",
        "Dispatch Execution Policy",
        "script_sends_to_recipient: False",
        "manual_operator_dispatch_required: True",
        "max_recipients_per_record: 1",
        "records_private_sha256_only: True",
    ]:
        if phrase not in text:
            raise ReleaseVerificationError(f"신뢰 리포트 문구 누락: {phrase}")
    missing_boundaries = [boundary for boundary in RELEASE_BOUNDARIES if boundary not in text]
    if missing_boundaries:
        raise ReleaseVerificationError("신뢰 리포트 경계 누락: " + " / ".join(missing_boundaries))


def _verify_support_packet(archive: zipfile.ZipFile) -> None:
    """ZIP 안의 지원 패킷이 공유 가능 파일과 공유 금지 항목을 명확히 설명하는지 확인한다."""
    packet_name = f"{RELEASE_SLUG}/{SUPPORT_PACKET_NAME}"
    try:
        text = archive.read(packet_name).decode("utf-8")
    except KeyError as exc:
        raise ReleaseVerificationError("ZIP 내부 지원 패킷이 없습니다.") from exc
    for phrase in [
        "External Alpha Support Packet",
        "external_alpha_release_verification_receipt.json",
        "external_alpha_diagnostics.json",
        "external_alpha_builder_gold_path_share_receipt.json",
        "gold path receipt 다운로드",
        "safe_to_share: true",
        "redaction_checks",
        "docs/launch/PILOT_ISSUE_INTAKE.md",
        "docs/launch/PILOT_FEEDBACK_FORM.md",
        "Do Not Send",
        ".env",
        "raw AI reply",
        "private source code",
    ]:
        if phrase not in text:
            raise ReleaseVerificationError(f"지원 패킷 문구 누락: {phrase}")


def _verify_support_packet(archive: zipfile.ZipFile) -> None:
    """Verify the support packet is readable and names only share-safe evidence."""
    packet_name = f"{RELEASE_SLUG}/{SUPPORT_PACKET_NAME}"
    try:
        text = archive.read(packet_name).decode("utf-8")
    except KeyError as exc:
        raise ReleaseVerificationError("support packet is missing from the ZIP.") from exc
    for phrase in [
        "External Alpha Support Packet",
        "external_alpha_release_verification_receipt.json",
        "external_alpha_diagnostics.json",
        "external_alpha_builder_gold_path_share_receipt.json",
        "safe_to_share: true",
        "redaction_checks",
        "docs/launch/PILOT_ISSUE_INTAKE.md",
        "docs/launch/PILOT_FEEDBACK_FORM.md",
        "Do Not Send",
        ".env",
        "raw AI reply",
        "private source code",
    ]:
        if phrase not in text:
            raise ReleaseVerificationError(f"support packet phrase missing: {phrase}")
    if not text.isascii():
        raise ReleaseVerificationError("support packet must stay ASCII for first-recipient readability.")


def _extract_and_verify(zip_path: Path, target_root: Path) -> Path:
    """ZIP을 안전하게 풀고 추출된 루트를 반환한다."""
    resolved_target = target_root.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            _validate_archive_name(info.filename)
            target = (resolved_target / info.filename).resolve()
            if not target.is_relative_to(resolved_target):
                raise ReleaseVerificationError(f"ZIP 경로가 추출 폴더 밖을 가리킵니다: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)

    extracted_root = resolved_target / RELEASE_SLUG
    if not extracted_root.is_dir():
        raise ReleaseVerificationError(f"압축 해제 루트가 없습니다: {extracted_root}")
    return extracted_root


def _run_extracted_platform_verification(extracted_root: Path) -> None:
    """압축 해제된 묶음 안에서 플랫폼 자체 검증을 실행한다."""
    verify_script = extracted_root / "scripts" / "verify_platform_alpha.py"
    if not verify_script.is_file():
        raise ReleaseVerificationError(f"검증 스크립트가 없습니다: {verify_script}")

    result = subprocess.run(
        [sys.executable, str(verify_script)],
        cwd=extracted_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise ReleaseVerificationError(result.stdout + result.stderr)


def _run_extracted_browser_wrapper_help(extracted_root: Path) -> dict[str, Any]:
    """Verify the optional browser smoke wrapper is included and CLI-callable."""
    browser_script = extracted_root / "scripts" / "verify_agent_platform_browser_flow.py"
    if not browser_script.is_file():
        raise ReleaseVerificationError(f"browser smoke wrapper is missing: {browser_script}")

    result = subprocess.run(
        [sys.executable, str(browser_script), "--help"],
        cwd=extracted_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise ReleaseVerificationError(result.stdout + result.stderr)

    help_output = result.stdout + result.stderr
    for phrase in ["browser smoke tests", "--node-modules", "--single", "--install-deps"]:
        if phrase not in help_output:
            raise ReleaseVerificationError(f"browser smoke wrapper help is missing phrase: {phrase}")

    return {
        "status": "pass",
        "script": browser_script.name,
        "mode": "help_only",
        "requires_playwright_for_full_run": True,
    }


def _run_extracted_diagnostics(extracted_root: Path) -> dict[str, Any]:
    """압축 해제된 묶음 안에서 시크릿 없는 진단 리포트 생성까지 확인한다."""
    diagnostics_script = extracted_root / "scripts" / "collect_external_alpha_diagnostics.py"
    diagnostics_output = extracted_root / "external_alpha_diagnostics.verify.json"
    if not diagnostics_script.is_file():
        raise ReleaseVerificationError(f"진단 스크립트가 없습니다: {diagnostics_script}")

    result = subprocess.run(
        [sys.executable, str(diagnostics_script), "--output", str(diagnostics_output)],
        cwd=extracted_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise ReleaseVerificationError(result.stdout + result.stderr)
    if not diagnostics_output.is_file():
        raise ReleaseVerificationError("진단 리포트가 생성되지 않았습니다.")
    try:
        report = json.loads(diagnostics_output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"진단 리포트 JSON 파싱 실패: {exc}") from exc
    _verify_diagnostics_report(report, extracted_root)
    return _diagnostics_summary(report)


def _run_extracted_windows_batch_rehearsal(extracted_root: Path) -> dict[str, str]:
    """Windows에서 외부 사용자가 실행할 배치 파일 자체를 리허설한다."""
    if sys.platform != "win32":
        return {"status": "skipped", "reason": "not_windows"}
    if _skip_windows_batch_rehearsal_for_tests():
        return {"status": "skipped", "reason": "test_fast_path"}

    verify_batch = extracted_root / "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat"
    diagnostics_batch = extracted_root / "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat"
    diagnostics_output = extracted_root / "external_alpha_diagnostics.batch.verify.json"

    _run_batch_file(verify_batch, extracted_root, [])
    _run_batch_file(diagnostics_batch, extracted_root, ["--output", str(diagnostics_output)])

    if not diagnostics_output.is_file():
        raise ReleaseVerificationError("진단 배치 파일이 리포트를 생성하지 않았습니다.")
    try:
        report = json.loads(diagnostics_output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"진단 배치 리포트 JSON 파싱 실패: {exc}") from exc
    _verify_diagnostics_report(report, extracted_root)

    return {
        "status": "pass",
        "verify_batch": verify_batch.name,
        "diagnostics_batch": diagnostics_batch.name,
    }


def _skip_windows_batch_rehearsal_for_tests() -> bool:
    return os.environ.get("CAMBRIAN_EXTERNAL_ALPHA_SKIP_BATCH_REHEARSAL_FOR_TESTS") == "1"


def _run_batch_file(batch_path: Path, cwd: Path, args: list[str]) -> None:
    """배치 파일을 cmd로 실행하고 실패 출력을 검증 오류로 변환한다."""
    if not batch_path.is_file():
        raise ReleaseVerificationError(f"배치 파일이 없습니다: {batch_path.name}")
    result = subprocess.run(
        ["cmd", "/c", str(batch_path), *args],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise ReleaseVerificationError(result.stdout + result.stderr)


def _verify_diagnostics_report(report: Any, extracted_root: Path) -> None:
    """진단 리포트가 공유 가능한 privacy 경계를 지키는지 확인한다."""
    if not isinstance(report, dict):
        raise ReleaseVerificationError("진단 리포트는 JSON 객체여야 합니다.")
    if report.get("schema_version") != "external_alpha_diagnostics_v0_1":
        raise ReleaseVerificationError("진단 리포트 schema_version이 올바르지 않습니다.")
    if report.get("status") != "pass":
        raise ReleaseVerificationError(f"진단 리포트 status가 pass가 아닙니다: {report.get('status')}")
    privacy = report.get("privacy") if isinstance(report.get("privacy"), dict) else {}
    expected_false_flags = [
        "environment_variables_collected",
        "env_files_read",
        "secret_values_collected",
        "user_documents_collected",
    ]
    failed_flags = [name for name in expected_false_flags if privacy.get(name) is not False]
    if failed_flags:
        raise ReleaseVerificationError("진단 리포트 privacy 플래그가 안전하지 않습니다: " + ", ".join(failed_flags))

    if report.get("safe_to_share") is not True:
        raise ReleaseVerificationError("진단 리포트 safe_to_share가 true가 아닙니다.")
    redaction_checks = report.get("redaction_checks") if isinstance(report.get("redaction_checks"), dict) else {}
    expected_true_checks = [
        "bundle_root_path_redacted",
        "home_path_redacted",
        "environment_variables_omitted",
        "env_files_omitted",
        "secret_values_omitted",
        "user_documents_omitted",
    ]
    failed_checks = [name for name in expected_true_checks if redaction_checks.get(name) is not True]
    if failed_checks:
        raise ReleaseVerificationError("진단 리포트 redaction check가 안전하지 않습니다: " + ", ".join(failed_checks))

    support_summary = report.get("support_summary") if isinstance(report.get("support_summary"), dict) else {}
    if support_summary.get("safe_to_share") is not True:
        raise ReleaseVerificationError("진단 리포트 support_summary.safe_to_share가 true가 아닙니다.")
    if support_summary.get("status") != "pass":
        raise ReleaseVerificationError("진단 리포트 support_summary.status가 pass가 아닙니다.")
    if support_summary.get("platform_verification_status") not in {"pass", "skipped"}:
        raise ReleaseVerificationError("진단 리포트 support_summary의 platform verification 상태가 안전하지 않습니다.")
    if support_summary.get("missing_required_files") != []:
        raise ReleaseVerificationError("진단 리포트 support_summary에 누락 파일이 남아 있습니다.")
    if not isinstance(support_summary.get("next_action"), str) or not support_summary.get("next_action"):
        raise ReleaseVerificationError("진단 리포트 support_summary.next_action이 비어 있습니다.")
    do_not_share = support_summary.get("do_not_share")
    if not isinstance(do_not_share, list) or ".env" not in do_not_share or "raw AI reply" not in do_not_share:
        raise ReleaseVerificationError("진단 리포트 support_summary의 공유 금지 안내가 부족합니다.")

    serialized = json.dumps(report, ensure_ascii=False)
    if str(extracted_root) in serialized:
        raise ReleaseVerificationError("진단 리포트에 압축 해제 절대 경로가 포함되었습니다.")
    home = str(Path.home())
    if home and home in serialized:
        raise ReleaseVerificationError("진단 리포트에 사용자 홈 절대 경로가 포함되었습니다.")


def _diagnostics_summary(report: dict[str, Any]) -> dict[str, Any]:
    """검증된 진단 리포트에서 수령자에게 보여줄 안전한 요약만 추린다."""
    support_summary = report.get("support_summary") if isinstance(report.get("support_summary"), dict) else {}
    return {
        "status": str(report.get("status")),
        "safe_to_share": report.get("safe_to_share") is True,
        "support_next_action": support_summary.get("next_action"),
        "support_do_not_share": support_summary.get("do_not_share", []),
    }


def _validate_archive_name(name: str) -> None:
    """ZIP 내부 파일명이 외부 알파 루트 안의 안전한 상대 경로인지 확인한다."""
    path = PurePosixPath(name)
    parts = path.parts
    if not parts or parts[0] != RELEASE_SLUG:
        raise ReleaseVerificationError(f"ZIP 파일은 {RELEASE_SLUG}/ 아래에 있어야 합니다: {name}")
    if any(part in {"", ".", ".."} for part in parts):
        raise ReleaseVerificationError(f"안전하지 않은 ZIP 경로입니다: {name}")
    if any(part in FORBIDDEN_PATH_PARTS for part in parts):
        raise ReleaseVerificationError(f"금지된 경로가 ZIP에 포함되었습니다: {name}")


def _manifest_path(entry: Any) -> str:
    """manifest 파일 항목에서 상대 경로를 읽는다."""
    if not isinstance(entry, dict):
        raise ReleaseVerificationError("manifest.files 항목은 객체여야 합니다.")
    value = entry.get("path")
    if not isinstance(value, str) or not value:
        raise ReleaseVerificationError("manifest.files.path가 비어 있습니다.")
    return value.replace("\\", "/")


def _sha256_file(path: Path) -> str:
    """파일 sha256 해시를 계산한다."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary(
    zip_path: Path,
    manifest_path: Path,
    extracted_root: Path,
    manifest: dict[str, Any],
    kept: bool,
    browser_wrapper: dict[str, Any],
    diagnostics_summary: dict[str, Any],
    batch_rehearsal: dict[str, str],
    current_source_manifest: dict[str, Any],
) -> dict[str, Any]:
    """검증 결과 요약을 만든다."""
    archive = manifest.get("archive") if isinstance(manifest.get("archive"), dict) else {}
    return {
        "status": "pass",
        "zip_path": str(zip_path),
        "manifest_path": str(manifest_path),
        "extracted_root": str(extracted_root),
        "extracted_kept": kept,
        "archive_sha256": archive.get("sha256"),
        "file_count": manifest.get("file_count"),
        "release_version": manifest.get("release_version"),
        "boundary_count": len(manifest.get("boundaries", [])) if isinstance(manifest.get("boundaries"), list) else 0,
        "dispatch_execution_policy": manifest.get("dispatch_execution_policy")
        if isinstance(manifest.get("dispatch_execution_policy"), dict)
        else {},
        "trust_report": TRUST_REPORT_NAME,
        "release_sources_match_current_manifest": current_source_manifest.get("failed_checks") == [],
        "current_source_manifest": current_source_manifest,
        "browser_wrapper": browser_wrapper,
        "diagnostics_status": diagnostics_summary.get("status"),
        "diagnostics_safe_to_share": diagnostics_summary.get("safe_to_share"),
        "diagnostics_next_action": diagnostics_summary.get("support_next_action"),
        "diagnostics_do_not_share": diagnostics_summary.get("support_do_not_share"),
        "batch_rehearsal": batch_rehearsal,
    }


if __name__ == "__main__":
    raise SystemExit(main())
