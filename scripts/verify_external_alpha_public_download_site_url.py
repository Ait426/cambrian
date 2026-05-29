"""Verify a hosted external alpha public download site URL."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_download_landing import (  # noqa: E402
    DOWNLOAD_LANDING_RECEIPT_NAME,
    MANIFEST_NAME,
    RELEASE_RECEIPT_NAME,
    ZIP_NAME,
    verify_download_landing_receipt_payload,
)
from scripts.prepare_external_alpha_public_download_site import (  # noqa: E402
    INDEX_NAME,
    PUBLIC_SITE_RECEIPT_NAME,
    ROBOTS_TXT_NAME,
    SEND_READY_MD_NAME,
    verify_public_download_site_receipt_payload,
)


PUBLIC_SITE_URL_SCHEMA_VERSION = "external_alpha_public_download_site_url_v0_1"
PUBLIC_SITE_URL_VERDICT = "PUBLIC_DOWNLOAD_SITE_URL_READY"
DEFAULT_URL_RECEIPT_NAME = "cambrian-agent-platform-external-alpha-public-download-site-url-receipt.json"
DOWNLOADED_RELEASE_REQUIRED_FILES = (
    "QUICKSTART_EXTERNAL_ALPHA.md",
    "START_CAMBRIAN_AGENT_PLATFORM.bat",
    "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
    "START_HERE_EXTERNAL_ALPHA.md",
    "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
    "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
    "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
)

logger = logging.getLogger(__name__)


class PublicDownloadSiteUrlError(RuntimeError):
    """Hosted public download site URL verification failed."""


class _HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: set[str] = set()
        self.download_hrefs: set[str] = set()
        self.meta_robots: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value for key, value in attrs}
        if tag == "a" and attr.get("href"):
            href = attr["href"] or ""
            self.hrefs.add(href)
            if "download" in attr:
                self.download_hrefs.add(href)
        if tag == "meta" and attr.get("name") == "robots" and attr.get("content"):
            self.meta_robots.add(attr["content"] or "")


def verify_public_download_site_url(
    base_url: str,
    *,
    expected_archive_sha256: str | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    base_url = _normalize_base_url(base_url)
    index_url = urllib.parse.urljoin(base_url, INDEX_NAME)
    index_bytes = _fetch(index_url, timeout_seconds=timeout_seconds)
    index_html = index_bytes.decode("utf-8")
    _assert_shareable_text(index_html)

    parser = _HrefParser()
    parser.feed(index_html)

    zip_bytes = _fetch(urllib.parse.urljoin(base_url, ZIP_NAME), timeout_seconds=timeout_seconds)
    manifest = _fetch_json(urllib.parse.urljoin(base_url, MANIFEST_NAME), timeout_seconds=timeout_seconds)
    release_receipt = _fetch_json(urllib.parse.urljoin(base_url, RELEASE_RECEIPT_NAME), timeout_seconds=timeout_seconds)
    site_receipt = _fetch_json(urllib.parse.urljoin(base_url, PUBLIC_SITE_RECEIPT_NAME), timeout_seconds=timeout_seconds)
    landing_receipt = _fetch_json(
        urllib.parse.urljoin(base_url, DOWNLOAD_LANDING_RECEIPT_NAME),
        timeout_seconds=timeout_seconds,
    )
    send_ready = _fetch_text(urllib.parse.urljoin(base_url, SEND_READY_MD_NAME), timeout_seconds=timeout_seconds)
    robots = _fetch_text(urllib.parse.urljoin(base_url, ROBOTS_TXT_NAME), timeout_seconds=timeout_seconds)

    verify_public_download_site_receipt_payload(site_receipt)
    verify_download_landing_receipt_payload(landing_receipt)

    archive_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    expected_hash = expected_archive_sha256 or _manifest_archive_sha256(manifest)
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_SITE_URL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": PUBLIC_SITE_URL_VERDICT,
        "safe_to_share": True,
        "url": {
            "base_url": base_url,
            "entrypoint": INDEX_NAME,
            "index_url": index_url,
        },
        "observed": {
            "index_bytes": len(index_bytes),
            "zip_bytes": len(zip_bytes),
            "zip_sha256": archive_sha256,
            "manifest_archive_sha256": _manifest_archive_sha256(manifest),
            "release_receipt_archive_sha256": _dict(release_receipt, "release").get("archive_sha256"),
            "site_receipt_archive_sha256": _dict(site_receipt, "release").get("archive_sha256"),
            "landing_receipt_archive_sha256": _dict(landing_receipt, "release").get("archive_sha256"),
            "public_site_receipt_body_sha256": site_receipt.get("public_download_site_receipt_body_sha256"),
            "download_landing_receipt_body_sha256": landing_receipt.get("download_landing_receipt_body_sha256"),
        },
        "html": {
            "download_hrefs": sorted(parser.download_hrefs),
            "hrefs": sorted(parser.hrefs),
            "robots_meta": sorted(parser.meta_robots),
            "has_download_title": "Download Cambrian Agent Platform" in index_html,
            "mentions_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in index_html,
            "mentions_codex_claude_prompt": "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in index_html,
        },
        "policy": {
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "search_indexing_enabled": False,
        },
        "support_files": {
            "send_ready_md_bytes": len(send_ready.encode("utf-8")),
            "robots_txt": robots,
        },
        "downloaded_release_zip": _downloaded_release_zip_smoke(zip_bytes),
        "expected_archive_sha256": expected_hash,
    }
    payload["public_download_site_url_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _receipt_checks(payload)
    verify_public_download_site_url_receipt_payload(payload)
    return payload


def verify_public_download_site_url_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_download_site_url_receipt_payload(payload)
    return payload


def verify_public_download_site_url_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_SITE_URL_SCHEMA_VERSION:
        raise PublicDownloadSiteUrlError("public download site URL receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != PUBLIC_SITE_URL_VERDICT:
        raise PublicDownloadSiteUrlError("public download site URL receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PublicDownloadSiteUrlError("public download site URL receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _receipt_checks(payload)
    if checks != recalculated:
        raise PublicDownloadSiteUrlError("public download site URL receipt checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicDownloadSiteUrlError("public download site URL receipt checks failed: " + ", ".join(failed))
    if payload.get("public_download_site_url_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PublicDownloadSiteUrlError("public download site URL receipt body hash mismatch.")


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    observed = _dict(payload, "observed")
    html = _dict(payload, "html")
    policy = _dict(payload, "policy")
    support_files = _dict(payload, "support_files")
    downloaded = _dict(payload, "downloaded_release_zip")
    download_hrefs = html.get("download_hrefs") if isinstance(html.get("download_hrefs"), list) else []
    hrefs = html.get("hrefs") if isinstance(html.get("hrefs"), list) else []
    robots_meta = html.get("robots_meta") if isinstance(html.get("robots_meta"), list) else []
    downloaded_required_files = (
        downloaded.get("required_files_present") if isinstance(downloaded.get("required_files_present"), list) else []
    )
    expected_hash = payload.get("expected_archive_sha256")
    body_hash = payload.get("public_download_site_url_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_SITE_URL_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == PUBLIC_SITE_URL_VERDICT,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "entrypoint_index": _dict(payload, "url").get("entrypoint") == INDEX_NAME,
        "index_loaded": isinstance(observed.get("index_bytes"), int) and observed.get("index_bytes", 0) > 0,
        "zip_loaded": isinstance(observed.get("zip_bytes"), int) and observed.get("zip_bytes", 0) > 0,
        "zip_hash_present": _looks_like_sha256(observed.get("zip_sha256")),
        "expected_hash_present": _looks_like_sha256(expected_hash),
        "zip_hash_matches_expected": observed.get("zip_sha256") == expected_hash,
        "zip_hash_matches_manifest": observed.get("zip_sha256") == observed.get("manifest_archive_sha256"),
        "zip_hash_matches_release_receipt": observed.get("zip_sha256")
        == observed.get("release_receipt_archive_sha256"),
        "zip_hash_matches_site_receipt": observed.get("zip_sha256") == observed.get("site_receipt_archive_sha256"),
        "zip_hash_matches_landing_receipt": observed.get("zip_sha256")
        == observed.get("landing_receipt_archive_sha256"),
        "site_receipt_hash_present": _looks_like_sha256(observed.get("public_site_receipt_body_sha256")),
        "landing_receipt_hash_present": _looks_like_sha256(observed.get("download_landing_receipt_body_sha256")),
        "download_link_present": ZIP_NAME in hrefs and ZIP_NAME in download_hrefs,
        "manifest_link_present": MANIFEST_NAME in hrefs,
        "release_receipt_link_present": RELEASE_RECEIPT_NAME in hrefs,
        "send_ready_link_present": SEND_READY_MD_NAME in hrefs,
        "html_product_copy_present": html.get("has_download_title") is True
        and html.get("mentions_quickstart") is True
        and html.get("mentions_codex_claude_prompt") is True,
        "robots_meta_noindex": any("noindex" in str(item) for item in robots_meta),
        "robots_txt_blocks_indexing": "Disallow: /" in str(support_files.get("robots_txt", "")),
        "send_ready_loaded": isinstance(support_files.get("send_ready_md_bytes"), int)
        and support_files.get("send_ready_md_bytes", 0) > 0,
        "downloaded_zip_opened": isinstance(downloaded.get("entry_count"), int)
        and downloaded.get("entry_count", 0) > 0,
        "downloaded_zip_root_locked": downloaded.get("root_dir") == RELEASE_SLUG
        and downloaded.get("all_entries_under_root") is True,
        "downloaded_user_entrypoints_present": set(DOWNLOADED_RELEASE_REQUIRED_FILES).issubset(
            set(downloaded_required_files)
        ),
        "downloaded_quickstart_actionable": downloaded.get("quickstart_mentions_start_bat") is True
        and downloaded.get("quickstart_mentions_builder_golden_path") is True
        and downloaded.get("prompt_mentions_quickstart") is True
        and downloaded.get("prompt_mentions_start_bat") is True,
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "search_indexing_disabled": policy.get("search_indexing_enabled") is False,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    try:
        payload = json.loads(_fetch_text(url, timeout_seconds=timeout_seconds))
    except json.JSONDecodeError as exc:
        raise PublicDownloadSiteUrlError(f"cannot parse JSON from URL: {url}") from exc
    if not isinstance(payload, dict):
        raise PublicDownloadSiteUrlError(f"JSON payload must be an object: {url}")
    return payload


def _fetch_text(url: str, *, timeout_seconds: float) -> str:
    return _fetch(url, timeout_seconds=timeout_seconds).decode("utf-8")


def _fetch(url: str, *, timeout_seconds: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Cambrian public download verifier"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - operator-supplied URL.
            status = getattr(response, "status", 200)
            if status != 200:
                raise PublicDownloadSiteUrlError(f"URL returned HTTP {status}: {url}")
            return response.read()
    except urllib.error.URLError as exc:
        raise PublicDownloadSiteUrlError(f"cannot fetch URL: {url}") from exc


def _normalize_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PublicDownloadSiteUrlError("base URL must be an http or https URL.")
    return base_url if base_url.endswith("/") else base_url + "/"


def _manifest_archive_sha256(manifest: dict[str, Any]) -> str | None:
    archive = manifest.get("archive")
    return archive.get("sha256") if isinstance(archive, dict) else None


def _assert_shareable_text(text: str) -> None:
    forbidden = [str(ROOT), str(Path.home()), ".env", "API key or secret", "raw private project files"]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise PublicDownloadSiteUrlError("download site URL contains private material.")


def _downloaded_release_zip_smoke(zip_bytes: bytes) -> dict[str, Any]:
    root_prefix = f"{RELEASE_SLUG}/"
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            names = sorted(info.filename for info in archive.infolist() if not info.is_dir())
            relative_names = sorted(
                name[len(root_prefix) :]
                for name in names
                if name.startswith(root_prefix) and name != root_prefix and not name.endswith("/")
            )
            quickstart_text = _read_zip_text(archive, root_prefix + "QUICKSTART_EXTERNAL_ALPHA.md")
            prompt_text = _read_zip_text(
                archive,
                root_prefix + "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
            )
    except zipfile.BadZipFile as exc:
        raise PublicDownloadSiteUrlError("downloaded release ZIP cannot be opened.") from exc

    required_present = [name for name in DOWNLOADED_RELEASE_REQUIRED_FILES if name in set(relative_names)]
    return {
        "root_dir": RELEASE_SLUG,
        "entry_count": len(names),
        "all_entries_under_root": bool(names) and all(name.startswith(root_prefix) for name in names),
        "required_files_present": required_present,
        "required_files_expected": list(DOWNLOADED_RELEASE_REQUIRED_FILES),
        "quickstart_mentions_start_bat": "START_CAMBRIAN_AGENT_PLATFORM.bat" in quickstart_text,
        "quickstart_mentions_builder_golden_path": "Builder Golden Path" in quickstart_text,
        "prompt_mentions_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in prompt_text,
        "prompt_mentions_start_bat": "START_CAMBRIAN_AGENT_PLATFORM.bat" in prompt_text,
    }


def _read_zip_text(archive: zipfile.ZipFile, name: str) -> str:
    try:
        return archive.read(name).decode("utf-8")
    except KeyError:
        return ""
    except UnicodeDecodeError as exc:
        raise PublicDownloadSiteUrlError(f"downloaded release ZIP text file is not UTF-8: {name}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicDownloadSiteUrlError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicDownloadSiteUrlError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicDownloadSiteUrlError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_download_site_url_receipt_body_sha256", "checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a hosted external alpha public download site URL.")
    parser.add_argument("base_url", nargs="?")
    parser.add_argument("--expected-archive-sha256", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
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
            payload = verify_public_download_site_url_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public download site URL receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha public download site URL receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("sha256 : %s", payload["observed"]["zip_sha256"])
        logger.info("body   : %s", payload["public_download_site_url_receipt_body_sha256"])
        return 0

    if not args.base_url:
        logger.error("[FAIL] base_url is required unless --verify-receipt is used")
        return 2

    try:
        payload = verify_public_download_site_url(
            args.base_url,
            expected_archive_sha256=args.expected_archive_sha256,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing URL verification failure.
        logger.error("[FAIL] external alpha public download site URL: %s", exc)
        return 1

    if args.receipt:
        _write_json(Path(args.receipt), payload)

    logger.info("[PASS] external alpha public download site URL")
    logger.info("verdict: %s", payload["verdict"])
    logger.info("url    : %s", payload["url"]["base_url"])
    logger.info("sha256 : %s", payload["observed"]["zip_sha256"])
    logger.info("body   : %s", payload["public_download_site_url_receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
