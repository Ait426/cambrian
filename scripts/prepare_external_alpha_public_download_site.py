"""Prepare a hostable static download site for the external alpha bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_download_landing import (  # noqa: E402
    CANONICAL_ZIP_NAME,
    DOWNLOAD_LANDING_HTML_NAME,
    DOWNLOAD_LANDING_PREVIEW_NAME,
    DOWNLOAD_LANDING_RECEIPT_NAME,
    PUBLIC_DOWNLOAD_ZIP_NAME,
    prepare_download_landing,
    verify_download_landing_receipt_file,
)


PUBLIC_SITE_SCHEMA_VERSION = "external_alpha_public_download_site_v0_1"
PUBLIC_SITE_DIR_NAME = f"{RELEASE_SLUG}-public-download-site"
PUBLIC_SITE_RECEIPT_NAME = f"{RELEASE_SLUG}-public-download-site-receipt.json"
PUBLIC_SITE_README_NAME = "README_HOSTING.md"
PUBLIC_HOSTING_RUNBOOK_NAME = "PUBLIC_HOSTING_RUNBOOK.md"
HOSTING_HEADERS_NAME = "_headers"
NOJEKYLL_NAME = ".nojekyll"
ROBOTS_TXT_NAME = "robots.txt"
NOT_FOUND_HTML_NAME = "404.html"
INDEX_NAME = "index.html"
ZIP_NAME = PUBLIC_DOWNLOAD_ZIP_NAME
MANIFEST_NAME = f"{RELEASE_SLUG}.manifest.json"
RELEASE_RECEIPT_NAME = "external_alpha_release_verification_receipt.json"
SEND_READY_MD_NAME = f"{RELEASE_SLUG}-send-ready.md"
SEND_READY_JSON_NAME = f"{RELEASE_SLUG}-send-ready.json"

REQUIRED_SITE_FILES = (
    INDEX_NAME,
    DOWNLOAD_LANDING_HTML_NAME,
    DOWNLOAD_LANDING_PREVIEW_NAME,
    ZIP_NAME,
    MANIFEST_NAME,
    RELEASE_RECEIPT_NAME,
    SEND_READY_MD_NAME,
    SEND_READY_JSON_NAME,
    DOWNLOAD_LANDING_RECEIPT_NAME,
    PUBLIC_SITE_README_NAME,
    PUBLIC_HOSTING_RUNBOOK_NAME,
    HOSTING_HEADERS_NAME,
    NOJEKYLL_NAME,
    ROBOTS_TXT_NAME,
    NOT_FOUND_HTML_NAME,
)

logger = logging.getLogger(__name__)


class PublicDownloadSiteError(RuntimeError):
    """Public download site generation or verification failed."""


def prepare_public_download_site(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    site_dir: Path | None = None,
) -> dict[str, Any]:
    """Create a self-contained static hosting directory."""
    output_dir = output_dir.resolve()
    landing_result = prepare_download_landing(output_dir)
    landing_receipt = verify_download_landing_receipt_file(output_dir / DOWNLOAD_LANDING_RECEIPT_NAME)
    release = _dict(landing_receipt, "release")
    site_dir = (site_dir or output_dir / PUBLIC_SITE_DIR_NAME).resolve()
    _reset_site_dir(site_dir)

    copied_files = _copy_site_files(output_dir, site_dir)
    readme_path = site_dir / PUBLIC_SITE_README_NAME
    readme_path.write_text(_hosting_readme(release), encoding="utf-8")
    copied_files[PUBLIC_SITE_README_NAME] = readme_path
    runbook_path = site_dir / PUBLIC_HOSTING_RUNBOOK_NAME
    runbook_path.write_text(_hosting_runbook(release), encoding="utf-8")
    copied_files[PUBLIC_HOSTING_RUNBOOK_NAME] = runbook_path
    headers_path = site_dir / HOSTING_HEADERS_NAME
    headers_path.write_text(_hosting_headers(), encoding="utf-8")
    copied_files[HOSTING_HEADERS_NAME] = headers_path
    nojekyll_path = site_dir / NOJEKYLL_NAME
    nojekyll_path.write_text("", encoding="utf-8")
    copied_files[NOJEKYLL_NAME] = nojekyll_path
    robots_path = site_dir / ROBOTS_TXT_NAME
    robots_path.write_text(_robots_txt(), encoding="utf-8")
    copied_files[ROBOTS_TXT_NAME] = robots_path
    not_found_path = site_dir / NOT_FOUND_HTML_NAME
    not_found_path.write_text(_not_found_html(release), encoding="utf-8")
    copied_files[NOT_FOUND_HTML_NAME] = not_found_path

    payload = _site_receipt_payload(
        site_dir=site_dir,
        copied_files=copied_files,
        landing_result=landing_result,
        landing_receipt=landing_receipt,
    )
    receipt_path = site_dir / PUBLIC_SITE_RECEIPT_NAME
    _write_json(receipt_path, payload)
    verify_public_download_site_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "site_dir": str(site_dir),
        "index_html": str(site_dir / INDEX_NAME),
        "receipt_json": str(receipt_path),
        "archive_sha256": release.get("archive_sha256"),
        "receipt_body_sha256": payload["public_download_site_receipt_body_sha256"],
    }


def verify_public_download_site_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_download_site_receipt_payload(payload)
    return payload


def verify_public_download_site_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_SITE_SCHEMA_VERSION:
        raise PublicDownloadSiteError("public download site receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "PUBLIC_DOWNLOAD_SITE_READY":
        raise PublicDownloadSiteError("public download site receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PublicDownloadSiteError("public download site receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _receipt_checks(payload)
    if checks != recalculated:
        raise PublicDownloadSiteError("public download site receipt checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicDownloadSiteError("public download site receipt checks failed: " + ", ".join(failed))
    if payload.get("public_download_site_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PublicDownloadSiteError("public download site receipt body hash mismatch.")


def _copy_site_files(output_dir: Path, site_dir: Path) -> dict[str, Path]:
    source_files = {
        DOWNLOAD_LANDING_HTML_NAME: output_dir / DOWNLOAD_LANDING_HTML_NAME,
        DOWNLOAD_LANDING_PREVIEW_NAME: output_dir / DOWNLOAD_LANDING_PREVIEW_NAME,
        ZIP_NAME: output_dir / ZIP_NAME,
        MANIFEST_NAME: output_dir / MANIFEST_NAME,
        RELEASE_RECEIPT_NAME: output_dir / RELEASE_RECEIPT_NAME,
        SEND_READY_MD_NAME: output_dir / SEND_READY_MD_NAME,
        SEND_READY_JSON_NAME: output_dir / SEND_READY_JSON_NAME,
        DOWNLOAD_LANDING_RECEIPT_NAME: output_dir / DOWNLOAD_LANDING_RECEIPT_NAME,
    }
    missing = [name for name, path in source_files.items() if not path.is_file()]
    if missing:
        raise PublicDownloadSiteError("download site source files are missing: " + ", ".join(missing))

    copied: dict[str, Path] = {}
    for name, source in source_files.items():
        target = site_dir / name
        shutil.copy2(source, target)
        copied[name] = target

    index_target = site_dir / INDEX_NAME
    shutil.copy2(source_files[DOWNLOAD_LANDING_HTML_NAME], index_target)
    copied[INDEX_NAME] = index_target
    return copied


def _reset_site_dir(site_dir: Path) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    for child in site_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _site_receipt_payload(
    *,
    site_dir: Path,
    copied_files: dict[str, Path],
    landing_result: dict[str, Any],
    landing_receipt: dict[str, Any],
) -> dict[str, Any]:
    release = _dict(landing_receipt, "release")
    files = [
        {
            "file": name,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for name, path in sorted(copied_files.items())
    ]
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_SITE_SCHEMA_VERSION,
        "generated_at": _stable_generated_at(landing_receipt),
        "status": "pass",
        "verdict": "PUBLIC_DOWNLOAD_SITE_READY",
        "safe_to_share": True,
        "site": {
            "directory_name": site_dir.name,
            "entrypoint": INDEX_NAME,
            "file_count": len(files),
            "hosting_model": "static_files_same_directory",
            "local_path_included": False,
        },
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "public_download": {
            "zip_file": ZIP_NAME,
            "canonical_zip_file": CANONICAL_ZIP_NAME,
        },
        "download_landing": {
            "verdict": landing_result.get("verdict"),
            "receipt_body_sha256": landing_result.get("receipt_body_sha256"),
            "html_sha256": landing_result.get("landing_html_sha256"),
        },
        "files": files,
        "policy": {
            "script_sends_to_recipient": False,
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "ready_for_static_hosting": True,
            "search_indexing_enabled": False,
            "security_headers_included": True,
            "jekyll_processing_disabled": True,
            "hosting_runbook_included": True,
        },
        "operator_next_action": (
            "Follow PUBLIC_HOSTING_RUNBOOK.md, upload every file in this directory to one static hosting "
            "location, then run the public launch URL gate before sharing."
        ),
    }
    payload["public_download_site_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _receipt_checks(payload)
    return payload


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    site = _dict(payload, "site")
    release = _dict(payload, "release")
    public_download = _dict(payload, "public_download")
    landing = _dict(payload, "download_landing")
    policy = _dict(payload, "policy")
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    by_file = {item.get("file"): item for item in files if isinstance(item, dict)}
    index = by_file.get(INDEX_NAME, {})
    landing_html = by_file.get(DOWNLOAD_LANDING_HTML_NAME, {})
    zip_file = by_file.get(ZIP_NAME, {})
    body_hash = payload.get("public_download_site_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_SITE_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == "PUBLIC_DOWNLOAD_SITE_READY",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "entrypoint_index": site.get("entrypoint") == INDEX_NAME,
        "hosting_model_static": site.get("hosting_model") == "static_files_same_directory",
        "local_path_omitted": site.get("local_path_included") is False,
        "required_files_present": set(REQUIRED_SITE_FILES).issubset(set(by_file)),
        "public_download_zip_named": public_download.get("zip_file") == ZIP_NAME
        and public_download.get("canonical_zip_file") == CANONICAL_ZIP_NAME,
        "file_hashes_present": bool(files)
        and all(_looks_like_sha256(item.get("sha256")) and isinstance(item.get("bytes"), int) for item in files),
        "index_matches_landing_html": index.get("sha256") == landing_html.get("sha256"),
        "index_matches_landing_receipt": index.get("sha256") == landing.get("html_sha256"),
        "zip_hash_matches_release": zip_file.get("sha256") == release.get("archive_sha256")
        and _looks_like_sha256(release.get("archive_sha256")),
        "download_landing_ready": landing.get("verdict") == "DOWNLOAD_PAGE_READY"
        and _looks_like_sha256(landing.get("receipt_body_sha256")),
        "manual_only_no_email_collection": policy.get("script_sends_to_recipient") is False
        and policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "static_hosting_ready": policy.get("ready_for_static_hosting") is True,
        "static_hosting_support_files_present": HOSTING_HEADERS_NAME in by_file
        and NOJEKYLL_NAME in by_file
        and ROBOTS_TXT_NAME in by_file
        and NOT_FOUND_HTML_NAME in by_file,
        "jekyll_processing_disabled": NOJEKYLL_NAME in by_file
        and policy.get("jekyll_processing_disabled") is True,
        "hosting_runbook_present": PUBLIC_HOSTING_RUNBOOK_NAME in by_file
        and policy.get("hosting_runbook_included") is True,
        "search_indexing_disabled": policy.get("search_indexing_enabled") is False,
        "security_headers_included": policy.get("security_headers_included") is True,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and "static hosting" in payload.get("operator_next_action", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _hosting_readme(release: dict[str, Any]) -> str:
    archive_sha256 = release.get("archive_sha256")
    return f"""# Cambrian Public Download Site

Upload every file in this folder to the same static hosting location.

Start URL:

```text
index.html
```

Primary public download:

```text
{ZIP_NAME}
```

Canonical internal release artifact:

```text
{CANONICAL_ZIP_NAME}
```

ZIP sha256:

```text
{archive_sha256}
```

Do not remove the verification receipt, manifest, send-ready note, preview image, `.nojekyll`, or `PUBLIC_HOSTING_RUNBOOK.md`. The landing page uses same-folder relative links.

The `_headers`, `.nojekyll`, `robots.txt`, and `404.html` files are host hardening helpers. Hosts that ignore `_headers` or `.nojekyll` can still serve the site, but hosts that support them will apply safer content, avoid Jekyll processing, and keep download defaults stable.

Read `PUBLIC_HOSTING_RUNBOOK.md` before sharing a URL. A local URL is only a rehearsal; the final external share requires the public launch URL gate to pass against a non-local HTTPS URL.

This folder does not collect email, run installation commands, contact recipients, require API keys, enable search indexing, or claim public proof/success metrics.
"""


def _hosting_runbook(release: dict[str, Any]) -> str:
    archive_sha256 = release.get("archive_sha256")
    return f"""# Cambrian Public Hosting Runbook

Purpose: publish the Cambrian external alpha download site without losing the checksum, receipt, or launch boundary.

## Publish Unit

Upload the contents of this folder as static files. The web root must contain:

- `index.html`
- `{ZIP_NAME}`
- `{MANIFEST_NAME}`
- `{RELEASE_RECEIPT_NAME}`
- `{PUBLIC_SITE_RECEIPT_NAME}`
- `{DOWNLOAD_LANDING_RECEIPT_NAME}`
- `{SEND_READY_MD_NAME}`
- `{SEND_READY_JSON_NAME}`
- `{PUBLIC_SITE_README_NAME}`
- `{PUBLIC_HOSTING_RUNBOOK_NAME}`
- `{HOSTING_HEADERS_NAME}`
- `{NOJEKYLL_NAME}`
- `{ROBOTS_TXT_NAME}`
- `{NOT_FOUND_HTML_NAME}`

The primary public download file is `{ZIP_NAME}`.

Expected ZIP sha256:

```text
{archive_sha256}
```

## Host Options

Use any static host that can serve same-folder files over HTTPS. Suitable examples:

- Cloudflare Pages direct upload
- Netlify manual deploy
- GitHub Pages from a dedicated release branch or repository
- Any S3-compatible static website fronted by HTTPS

Do not use a host that rewrites ZIP downloads, blocks `.json` files, requires a login to download, or serves the final URL only over plain HTTP.

Keep `{NOJEKYLL_NAME}` in the upload root. It disables GitHub Pages Jekyll processing so underscore-prefixed helper files remain predictable; other static hosts can ignore it safely.

## Required Operator Flow

1. Upload every file from this folder to one static hosting location.
2. Confirm `index.html` and `{ZIP_NAME}` are in the same web root.
3. Open the hosted landing page in a browser.
4. Run the final launch gate from the project root:

```text
python scripts\\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> --expected-archive-sha256 {archive_sha256} --receipt dist\\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json
```

5. Share the public URL only if the verdict is `PUBLIC_LAUNCH_URL_READY` and `external_sharing_allowed=true`.

## Local Rehearsal

Local URLs can only prove packaging and link behavior. They cannot be shared externally.

```text
python scripts\\finalize_external_alpha_public_launch_url.py http://127.0.0.1:8787/ --expected-archive-sha256 {archive_sha256} --allow-local-rehearsal --receipt dist\\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json
```

Expected local rehearsal verdict:

```text
PUBLIC_LAUNCH_URL_REHEARSAL_READY
```

Expected local rehearsal share state:

```text
external_sharing_allowed=false
```

## Boundaries

- Do not add email collection before this gate.
- Do not require an API key before this gate.
- Do not publish private recipient/channel values.
- Do not claim public traction or success metrics from this alpha page.
- Do not share a local or private-network URL as the launch URL.
"""


def _hosting_headers() -> str:
    return f"""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Frame-Options: DENY
  Permissions-Policy: camera=(), microphone=(), geolocation=()

/{ZIP_NAME}
  Content-Type: application/zip
  Content-Disposition: attachment; filename="{ZIP_NAME}"

/*.json
  Content-Type: application/json; charset=utf-8

/*.md
  Content-Type: text/markdown; charset=utf-8
"""


def _robots_txt() -> str:
    return """User-agent: *
Disallow: /
"""


def _not_found_html(release: dict[str, Any]) -> str:
    archive_sha256 = release.get("archive_sha256")
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow" />
  <title>Cambrian Download Not Found</title>
  <style>
    body {{
      background: #f6f8fb;
      color: #111827;
      font-family: "Aptos", "Malgun Gothic", "Segoe UI", sans-serif;
      letter-spacing: 0;
      margin: 0;
    }}
    main {{
      margin: 0 auto;
      max-width: 760px;
      padding: 80px 20px;
    }}
    h1 {{ font-size: 2rem; margin: 0 0 12px; }}
    p {{ color: #5b6472; line-height: 1.6; margin: 0 0 18px; }}
    a {{
      align-items: center;
      background: #2457d6;
      border-radius: 8px;
      color: #fff;
      display: inline-flex;
      font-weight: 900;
      min-height: 42px;
      padding: 10px 14px;
      text-decoration: none;
    }}
    code {{
      background: #eef2f7;
      border-radius: 6px;
      overflow-wrap: anywhere;
      padding: 2px 5px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Cambrian download page moved</h1>
    <p>Use the verified download entrypoint below. The current external alpha ZIP sha256 is <code>{archive_sha256}</code>.</p>
    <a href="{INDEX_NAME}">Open download page</a>
  </main>
</body>
</html>
"""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicDownloadSiteError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicDownloadSiteError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicDownloadSiteError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_download_site_receipt_body_sha256", "checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_generated_at(source: dict[str, Any]) -> str:
    generated_at = source.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        return generated_at
    return "1970-01-01T00:00:00+00:00"


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
    parser = argparse.ArgumentParser(description="Prepare a static public download site for external alpha.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--site-dir", default=None)
    parser.add_argument("--verify-receipt", default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_public_download_site_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public download site verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha public download site verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["public_download_site_receipt_body_sha256"])
        logger.info("entry  : %s", payload["site"]["entrypoint"])
        return 0

    try:
        result = prepare_public_download_site(
            Path(args.output_dir),
            site_dir=Path(args.site_dir) if args.site_dir else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing build failure.
        logger.error("[FAIL] external alpha public download site: %s", exc)
        return 1

    logger.info("[PASS] external alpha public download site")
    logger.info("verdict: %s", result["verdict"])
    logger.info("site   : %s", result["site_dir"])
    logger.info("index  : %s", result["index_html"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
