"""Build a public download landing page for the external alpha bundle."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import logging
import shutil
import struct
import sys
import zlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_send_ready import SEND_READY_JSON_NAME, verify_send_ready_file  # noqa: E402
from scripts.verify_external_alpha_release import RECEIPT_SCHEMA_VERSION, verify_shareable_receipt_file  # noqa: E402


DOWNLOAD_LANDING_SCHEMA_VERSION = "external_alpha_download_landing_v0_1"
DOWNLOAD_LANDING_HTML_NAME = f"{RELEASE_SLUG}-download.html"
DOWNLOAD_LANDING_RECEIPT_NAME = f"{RELEASE_SLUG}-download-landing-receipt.json"
DOWNLOAD_LANDING_PREVIEW_NAME = f"{RELEASE_SLUG}-download-preview.png"
RELEASE_RECEIPT_NAME = "external_alpha_release_verification_receipt.json"
MANIFEST_NAME = f"{RELEASE_SLUG}.manifest.json"
CANONICAL_ZIP_NAME = f"{RELEASE_SLUG}.zip"
PUBLIC_DOWNLOAD_ZIP_NAME = "cambrian-alpha.zip"
ZIP_NAME = PUBLIC_DOWNLOAD_ZIP_NAME

logger = logging.getLogger(__name__)


class DownloadLandingError(RuntimeError):
    """Download landing generation or verification failed."""


def prepare_download_landing(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Write the static download landing page and a share-safe receipt."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    send_ready = verify_send_ready_file(output_dir / SEND_READY_JSON_NAME)
    release_receipt = verify_shareable_receipt_file(output_dir / RELEASE_RECEIPT_NAME)
    manifest = _read_json(output_dir / MANIFEST_NAME)
    release = _release_summary(send_ready, release_receipt, manifest)
    _write_public_download_alias(output_dir, release)

    preview_path = output_dir / DOWNLOAD_LANDING_PREVIEW_NAME
    _write_preview_png(preview_path)

    html = _landing_html(release)
    html_path = output_dir / DOWNLOAD_LANDING_HTML_NAME
    html_path.write_text(html, encoding="utf-8")
    _assert_shareable_text(html)

    payload = _landing_receipt_payload(
        release=release,
        html_path=html_path,
        preview_path=preview_path,
        send_ready=send_ready,
        release_receipt=release_receipt,
    )
    receipt_path = output_dir / DOWNLOAD_LANDING_RECEIPT_NAME
    _write_json(receipt_path, payload)
    verify_download_landing_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "landing_html": str(html_path),
        "preview_png": str(preview_path),
        "receipt_json": str(receipt_path),
        "archive_sha256": release["archive_sha256"],
        "landing_html_sha256": payload["download_page"]["html_sha256"],
        "receipt_body_sha256": payload["download_landing_receipt_body_sha256"],
    }


def verify_download_landing_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_download_landing_receipt_payload(payload)
    return payload


def verify_download_landing_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != DOWNLOAD_LANDING_SCHEMA_VERSION:
        raise DownloadLandingError("download landing receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "DOWNLOAD_PAGE_READY":
        raise DownloadLandingError("download landing receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise DownloadLandingError("download landing receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _receipt_checks(payload)
    if checks != recalculated:
        raise DownloadLandingError("download landing receipt checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise DownloadLandingError("download landing receipt checks failed: " + ", ".join(failed))
    if payload.get("download_landing_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise DownloadLandingError("download landing receipt body hash mismatch.")


def _release_summary(
    send_ready: dict[str, Any],
    release_receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    send_release = _dict(send_ready, "release")
    receipt_release = _dict(release_receipt, "release")
    archive_sha256 = send_release.get("archive_sha256")
    if not _looks_like_sha256(archive_sha256):
        raise DownloadLandingError("send-ready release hash is missing.")
    if receipt_release.get("archive_sha256") != archive_sha256:
        raise DownloadLandingError("release receipt hash does not match send-ready hash.")
    if manifest.get("archive", {}).get("sha256") != archive_sha256:
        raise DownloadLandingError("manifest archive hash does not match send-ready hash.")
    return {
        "zip_file": CANONICAL_ZIP_NAME,
        "public_download_zip_file": PUBLIC_DOWNLOAD_ZIP_NAME,
        "archive_sha256": archive_sha256,
        "file_count": send_release.get("file_count"),
        "release_version": release_receipt.get("release_version"),
        "send_ready_body_sha256": send_ready.get("send_ready_body_sha256"),
        "release_receipt_body_sha256": release_receipt.get("receipt_body_sha256"),
    }


def _write_public_download_alias(output_dir: Path, release: dict[str, Any]) -> None:
    source = output_dir / CANONICAL_ZIP_NAME
    target = output_dir / PUBLIC_DOWNLOAD_ZIP_NAME
    if not source.is_file():
        raise DownloadLandingError(f"canonical release ZIP is missing: {CANONICAL_ZIP_NAME}")
    shutil.copy2(source, target)
    if _sha256_file(target) != release.get("archive_sha256"):
        raise DownloadLandingError("public download ZIP alias hash does not match release hash.")


def _landing_receipt_payload(
    *,
    release: dict[str, Any],
    html_path: Path,
    preview_path: Path,
    send_ready: dict[str, Any],
    release_receipt: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": DOWNLOAD_LANDING_SCHEMA_VERSION,
        "generated_at": _stable_generated_at(release_receipt),
        "status": "pass",
        "verdict": "DOWNLOAD_PAGE_READY",
        "safe_to_share": True,
        "release": {
            "zip_file": release["zip_file"],
            "public_download_zip_file": release["public_download_zip_file"],
            "archive_sha256": release["archive_sha256"],
            "file_count": release.get("file_count"),
            "release_version": release.get("release_version"),
        },
        "download_page": {
            "html_file": DOWNLOAD_LANDING_HTML_NAME,
            "preview_asset": DOWNLOAD_LANDING_PREVIEW_NAME,
            "html_sha256": _sha256_file(html_path),
            "zip_download_href": ZIP_NAME,
            "manifest_href": MANIFEST_NAME,
            "release_receipt_href": RELEASE_RECEIPT_NAME,
            "send_ready_href": f"{RELEASE_SLUG}-send-ready.md",
        },
        "evidence": {
            "send_ready_body_sha256": release.get("send_ready_body_sha256"),
            "release_receipt_body_sha256": release.get("release_receipt_body_sha256"),
            "send_ready_verdict": send_ready.get("verdict"),
            "release_receipt_schema": release_receipt.get("schema_version"),
        },
        "policy": {
            "script_sends_to_recipient": False,
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
        },
    }
    payload["download_landing_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _receipt_checks(payload)
    return payload


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    release = _dict(payload, "release")
    page = _dict(payload, "download_page")
    evidence = _dict(payload, "evidence")
    policy = _dict(payload, "policy")
    body_hash = payload.get("download_landing_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == DOWNLOAD_LANDING_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == "DOWNLOAD_PAGE_READY",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "zip_file_named": release.get("zip_file") == CANONICAL_ZIP_NAME,
        "public_zip_file_named": release.get("public_download_zip_file") == PUBLIC_DOWNLOAD_ZIP_NAME,
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "html_file_named": page.get("html_file") == DOWNLOAD_LANDING_HTML_NAME,
        "preview_asset_named": page.get("preview_asset") == DOWNLOAD_LANDING_PREVIEW_NAME,
        "download_link_points_to_zip": page.get("zip_download_href") == ZIP_NAME,
        "manifest_link_present": page.get("manifest_href") == MANIFEST_NAME,
        "release_receipt_link_present": page.get("release_receipt_href") == RELEASE_RECEIPT_NAME,
        "send_ready_link_present": page.get("send_ready_href") == f"{RELEASE_SLUG}-send-ready.md",
        "html_hash_present": _looks_like_sha256(page.get("html_sha256")),
        "send_ready_go": evidence.get("send_ready_verdict") == "GO",
        "release_receipt_verified": evidence.get("release_receipt_schema") == RECEIPT_SCHEMA_VERSION,
        "manual_only_no_email_collection": policy.get("script_sends_to_recipient") is False
        and policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _landing_html(release: dict[str, Any]) -> str:
    archive_sha256 = release["archive_sha256"]
    file_count = release.get("file_count") or "verified"
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow" />
  <title>Cambrian Agent Platform Download</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #5b6472;
      --line: #d9e2ef;
      --paper: #ffffff;
      --bg: #f6f8fb;
      --blue: #2457d6;
      --green: #0f766e;
      --amber: #a16207;
      --slate: #1f2937;
      --soft-blue: #edf3ff;
      --soft-green: #e9f8f4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      background: var(--bg);
      color: var(--ink);
      font-family: "Aptos", "Malgun Gothic", "Segoe UI", sans-serif;
      letter-spacing: 0;
      margin: 0;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .nav {{
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin: 0 auto;
      padding: 18px 0;
      width: min(1160px, calc(100% - 32px));
    }}
    .brand {{ align-items: center; display: flex; gap: 10px; font-weight: 900; }}
    .mark {{
      align-items: center;
      background: var(--slate);
      border-radius: 8px;
      color: #fff;
      display: inline-flex;
      height: 34px;
      justify-content: center;
      width: 34px;
    }}
    .nav-actions {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .nav a, .button {{
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      display: inline-flex;
      font-weight: 900;
      min-height: 42px;
      padding: 10px 14px;
    }}
    .button.primary {{ background: var(--blue); border-color: var(--blue); color: #fff; }}
    .button.dark {{ background: var(--slate); border-color: var(--slate); color: #fff; }}
    .hero {{
      background-image: linear-gradient(90deg, rgba(8, 13, 24, 0.84), rgba(8, 13, 24, 0.42)), url("{DOWNLOAD_LANDING_PREVIEW_NAME}");
      background-position: center;
      background-size: cover;
      color: #fff;
      min-height: min(760px, 86vh);
      position: relative;
    }}
    .hero-inner {{
      display: grid;
      min-height: min(760px, 86vh);
      padding: clamp(34px, 7vw, 86px) 0;
      place-items: center start;
      width: min(1160px, calc(100% - 32px));
      margin: 0 auto;
    }}
    .hero-copy {{ max-width: 760px; }}
    .eyebrow {{
      color: #c7f9e5;
      font-size: 0.78rem;
      font-weight: 900;
      text-transform: uppercase;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{
      font-size: clamp(2.35rem, 6vw, 5.5rem);
      line-height: 1.02;
      margin: 14px 0 18px;
    }}
    .lead {{
      color: #e8eef8;
      font-size: 1.08rem;
      line-height: 1.7;
      max-width: 720px;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }}
    .promise-row {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-top: 22px;
      max-width: 920px;
    }}
    .promise {{
      background: rgba(255,255,255,0.12);
      border: 1px solid rgba(255,255,255,0.24);
      border-radius: 8px;
      padding: 12px;
    }}
    .promise strong {{
      display: block;
      font-size: 0.94rem;
      margin-bottom: 4px;
    }}
    .promise span {{
      color: #d9e2ef;
      display: block;
      font-size: 0.86rem;
      line-height: 1.42;
    }}
    .checksum {{
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.24);
      border-radius: 8px;
      color: #f8fafc;
      font-family: "Cascadia Mono", "Consolas", monospace;
      line-height: 1.6;
      margin-top: 18px;
      max-width: 720px;
      overflow-wrap: anywhere;
      padding: 12px;
    }}
    .band {{
      padding: 34px 0;
    }}
    .wrap {{ margin: 0 auto; width: min(1160px, calc(100% - 32px)); }}
    .section-head {{
      align-items: end;
      display: flex;
      gap: 18px;
      justify-content: space-between;
      margin-bottom: 16px;
    }}
    .section-head p {{ color: var(--muted); line-height: 1.55; max-width: 680px; }}
    .grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }}
    .card h3 {{ font-size: 1.02rem; margin-bottom: 8px; }}
    .card p, li {{ color: var(--muted); line-height: 1.55; }}
    .contract-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }}
    .contract {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 180px;
      padding: 18px;
    }}
    .contract .number {{
      align-items: center;
      background: var(--soft-green);
      border: 1px solid #a3dfd3;
      border-radius: 8px;
      color: var(--green);
      display: inline-flex;
      font-weight: 900;
      height: 30px;
      justify-content: center;
      margin-bottom: 14px;
      width: 30px;
    }}
    .contract h3 {{ font-size: 1rem; margin-bottom: 8px; }}
    .contract p {{ color: var(--muted); line-height: 1.55; }}
    .meta {{
      color: var(--muted);
      font-size: 0.9rem;
      margin-top: 8px;
    }}
    .steps {{
      counter-reset: step;
      display: grid;
      gap: 10px;
      margin: 0;
      padding: 0;
    }}
    .steps li {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      list-style: none;
      padding: 16px 16px 16px 54px;
      position: relative;
    }}
    .steps li::before {{
      align-items: center;
      background: var(--soft-blue);
      border: 1px solid #bed0ff;
      border-radius: 8px;
      color: var(--blue);
      content: counter(step);
      counter-increment: step;
      display: inline-flex;
      font-weight: 900;
      height: 28px;
      justify-content: center;
      left: 16px;
      position: absolute;
      top: 16px;
      width: 28px;
    }}
    code {{
      background: #eef2f7;
      border-radius: 6px;
      color: #111827;
      font-family: "Cascadia Mono", "Consolas", monospace;
      padding: 2px 5px;
    }}
    .download-strip {{
      background: var(--slate);
      color: #fff;
    }}
    .download-strip .wrap {{
      align-items: center;
      display: flex;
      gap: 18px;
      justify-content: space-between;
    }}
    .download-strip p {{ color: #d9e2ef; line-height: 1.55; }}
    footer {{
      border-top: 1px solid var(--line);
      color: var(--muted);
      padding: 22px 0 40px;
    }}
    @media (max-width: 780px) {{
      .nav, .download-strip .wrap, .section-head {{ align-items: stretch; flex-direction: column; }}
      .grid, .contract-grid, .promise-row {{ grid-template-columns: 1fr; }}
      .hero, .hero-inner {{ min-height: 720px; }}
      .actions .button, .nav a {{ justify-content: center; width: 100%; }}
    }}
  </style>
</head>
<body>
  <nav class="nav" aria-label="Primary">
    <a class="brand" href="#top" aria-label="Cambrian home"><span class="mark">C</span><span>Cambrian Agent Platform</span></a>
    <div class="nav-actions">
      <a href="{RELEASE_RECEIPT_NAME}" download>Verification receipt</a>
      <a href="{MANIFEST_NAME}" download>Manifest</a>
      <a class="button primary" href="{ZIP_NAME}" download>Download ZIP</a>
    </div>
  </nav>

  <header class="hero" id="top">
    <div class="hero-inner">
      <div class="hero-copy">
        <div class="eyebrow">External alpha download</div>
        <h1>Download Cambrian Agent Platform</h1>
        <p class="lead">Cambrian is a local-first alpha for building AI agent packs, creating and fusing skills, running a manual no-API harness, and preserving share-safe evolution receipts. Download one ZIP, unzip it, and start from the included Quickstart.</p>
        <div class="actions">
          <a class="button primary" href="{ZIP_NAME}" download>Download Cambrian ZIP</a>
          <a class="button dark" href="{RELEASE_RECEIPT_NAME}" download>Download verification receipt</a>
          <a class="button" href="{RELEASE_SLUG}-send-ready.md" download>Read send-ready note</a>
        </div>
        <div class="promise-row" aria-label="Cambrian alpha promises">
          <div class="promise"><strong>Agents</strong><span>Create local agent packs from a guided builder path.</span></div>
          <div class="promise"><strong>Skills</strong><span>Generate, search, and fuse skill artifacts.</span></div>
          <div class="promise"><strong>Harness</strong><span>Run manual review gates without an API dependency.</span></div>
          <div class="promise"><strong>Evolution</strong><span>Keep receipts that show what changed and why.</span></div>
        </div>
        <div class="checksum" aria-label="Release checksum">
          <strong>ZIP sha256</strong><br />
          {archive_sha256}
        </div>
      </div>
    </div>
  </header>

  <main>
    <section class="band">
      <div class="wrap">
        <div class="section-head">
          <h2>Start Path</h2>
          <p>The ZIP contains the docs and launch scripts. A user should not need a package registry, API key, payment setup, or cloud account for this alpha path.</p>
        </div>
        <ol class="steps">
          <li>Unzip <code>{ZIP_NAME}</code>.</li>
          <li>Open <code>QUICKSTART_EXTERNAL_ALPHA.md</code> first.</li>
          <li>Run <code>START_CAMBRIAN_AGENT_PLATFORM.bat</code> and complete the Builder Golden Path.</li>
          <li>If using Codex or Claude, paste <code>RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md</code> exactly.</li>
        </ol>
      </div>
    </section>

    <section class="band">
      <div class="wrap">
        <div class="section-head">
          <h2>Capability Contract</h2>
          <p>This page promises only what the alpha path can prove locally. The point is not a broad marketplace claim yet; it is a repeatable path a real external user can run.</p>
        </div>
        <div class="contract-grid">
          <article class="contract">
            <div class="number">1</div>
            <h3>Build AI Agents</h3>
            <p>Create a named agent pack, keep the workspace local, and finish the Builder Golden Path with evidence.</p>
          </article>
          <article class="contract">
            <div class="number">2</div>
            <h3>Create And Fuse Skills</h3>
            <p>Turn a skill idea into local artifacts, search existing skill material, and combine candidates under review.</p>
          </article>
          <article class="contract">
            <div class="number">3</div>
            <h3>Run Harness Engineering</h3>
            <p>Use manual gates, diagnostics, and no-API runner receipts to inspect changes before promotion.</p>
          </article>
          <article class="contract">
            <div class="number">4</div>
            <h3>Evolve With Receipts</h3>
            <p>Record the before/after trail so future improvements can be reviewed instead of guessed.</p>
          </article>
        </div>
      </div>
    </section>

    <section class="band">
      <div class="wrap">
        <div class="section-head">
          <h2>What The Alpha Proves</h2>
          <p>Keep the promise narrow: this is a defensible local product path, not a public proof or marketplace claim.</p>
        </div>
        <div class="grid">
          <article class="card">
            <h3>Agent Builder</h3>
            <p>Create a local agent pack and keep raw project data in the user's workspace.</p>
          </article>
          <article class="card">
            <h3>Skill Flow</h3>
            <p>Generate, search, and fuse skill ideas through controlled local artifacts.</p>
          </article>
          <article class="card">
            <h3>Harness Engineering</h3>
            <p>Review and run a manual no-API path with receipts instead of opaque automation.</p>
          </article>
        </div>
      </div>
    </section>

    <section class="band download-strip">
      <div class="wrap">
        <div>
          <h2>Ready To Hand To A User</h2>
          <p>Attach only the ZIP. Use the checksum above to verify the exact file. If anything fails, ask for the safe receipt and diagnostics JSON named in the support packet.</p>
          <p class="meta">Download file: {PUBLIC_DOWNLOAD_ZIP_NAME} - Files in release bundle: {file_count}</p>
        </div>
        <a class="button primary" href="{ZIP_NAME}" download>Download ZIP</a>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">This page does not collect email, run installation commands, contact a recipient, or claim public success metrics. It only links to verified external alpha artifacts.</div>
  </footer>
</body>
</html>
"""


def _write_preview_png(path: Path) -> None:
    width, height = 1200, 720
    pixels = bytearray([246, 248, 251] * width * height)

    def rect(x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        for yy in range(y0, y1):
            row = (yy * width + x0) * 3
            for _ in range(x0, x1):
                pixels[row : row + 3] = bytes(color)
                row += 3

    def border(x: int, y: int, w: int, h: int, color: tuple[int, int, int], size: int = 2) -> None:
        rect(x, y, w, size, color)
        rect(x, y + h - size, w, size, color)
        rect(x, y, size, h, color)
        rect(x + w - size, y, size, h, color)

    rect(0, 0, width, height, (236, 243, 255))
    rect(62, 56, 1076, 608, (255, 255, 255))
    border(62, 56, 1076, 608, (205, 215, 229), 3)
    rect(62, 56, 1076, 64, (31, 41, 55))
    rect(94, 78, 130, 20, (148, 163, 184))
    rect(850, 76, 86, 24, (36, 87, 214))
    rect(952, 76, 116, 24, (15, 118, 110))

    rect(104, 166, 430, 54, (17, 24, 39))
    rect(104, 238, 520, 16, (91, 100, 115))
    rect(104, 268, 470, 16, (91, 100, 115))
    rect(104, 322, 160, 44, (36, 87, 214))
    rect(282, 322, 210, 44, (15, 118, 110))

    rect(704, 158, 322, 406, (248, 250, 252))
    border(704, 158, 322, 406, (210, 221, 235), 3)
    rect(736, 192, 178, 18, (31, 41, 55))
    rect(736, 232, 238, 14, (100, 116, 139))
    rect(736, 262, 214, 14, (100, 116, 139))
    rect(736, 314, 236, 54, (237, 243, 255))
    border(736, 314, 236, 54, (190, 208, 255), 2)
    rect(760, 334, 144, 14, (36, 87, 214))
    rect(736, 390, 236, 54, (233, 248, 244))
    border(736, 390, 236, 54, (163, 223, 211), 2)
    rect(760, 410, 156, 14, (15, 118, 110))
    rect(736, 466, 236, 54, (255, 247, 237))
    border(736, 466, 236, 54, (251, 191, 36), 2)
    rect(760, 486, 118, 14, (161, 98, 7))

    rect(104, 434, 170, 90, (237, 243, 255))
    border(104, 434, 170, 90, (190, 208, 255), 2)
    rect(306, 434, 170, 90, (233, 248, 244))
    border(306, 434, 170, 90, (163, 223, 211), 2)
    rect(508, 434, 170, 90, (255, 247, 237))
    border(508, 434, 170, 90, (251, 191, 36), 2)

    raw = b"".join(b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    data = b"\x89PNG\r\n\x1a\n"
    data += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _png_chunk(b"IDAT", zlib.compress(raw, 9))
    data += _png_chunk(b"IEND", b"")
    path.write_bytes(data)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def _assert_shareable_text(text: str) -> None:
    forbidden = [str(ROOT), str(Path.home()), ".env", "API key or secret", "raw private project files"]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise DownloadLandingError("download landing HTML contains private material.")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise DownloadLandingError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise DownloadLandingError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise DownloadLandingError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "download_landing_receipt_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Build the external alpha public download landing page.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--verify-receipt", default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_download_landing_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha download landing verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha download landing verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["download_landing_receipt_body_sha256"])
        logger.info("html   : %s", payload["download_page"]["html_file"])
        return 0

    try:
        result = prepare_download_landing(Path(args.output_dir))
    except Exception as exc:  # noqa: BLE001 - concise operator-facing build failure.
        logger.error("[FAIL] external alpha download landing: %s", exc)
        return 1

    logger.info("[PASS] external alpha download landing")
    logger.info("verdict: %s", result["verdict"])
    logger.info("html   : %s", result["landing_html"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
