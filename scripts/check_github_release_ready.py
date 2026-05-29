from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_cambrian_install_kit_send_ready import (  # noqa: E402
    SEND_READY_JSON_NAME,
    verify_send_ready_file,
)
from scripts.check_final_commit_staging_handoff import (  # noqa: E402
    plan_all_worktree_slices,
    verify_staging_receipt_against_plan,
    verify_staging_receipt_file,
    verify_staging_receipt_pathspec_files,
)
from scripts.prepare_cambrian_install_kit_release import (  # noqa: E402
    RELEASE_BUNDLE_NAME,
    verify_release_bundle_current_artifacts,
)


GITHUB_RELEASE_READY_SCHEMA_VERSION = "cambrian_github_release_ready_v0_1"
GITHUB_RELEASE_READY_JSON_NAME = "github-release-ready.json"
GITHUB_RELEASE_READY_MD_NAME = "github-release-ready.md"
FINAL_STAGING_RECEIPT_NAME = "final-commit-staging-receipt.json"

_REQUIRED_GITIGNORE_LINES = [
    "dist/",
    "build/",
    ".env",
    ".env.*",
    ".cambrian/",
    "docs/release/NEXT_SESSION_HANDOFF.md",
]
_PRIVATE_TEXT_MARKERS = [
    "C:\\Users\\user",
    "C:/Users/user",
    "Desktop\\cambrain",
    "Desktop/cambrain",
    "AVE_MCP_CHECK",
]
_PUBLIC_TEXT_SCAN_FILES = [
    "README.md",
    "docs/release/CAMBRIAN_INSTALL_KIT.md",
    "docs/release/GITHUB_RELEASE_RUNBOOK.md",
    "docs/release/GITHUB_RELEASE_NOTES_0_3_0.md",
    "docs/release/MCP_EXTERNAL_CLIENT_CONNECT.md",
    "docs/release/RC_INSTALL_GUIDE.md",
    "docs/release/RC_VERIFICATION.md",
    "docs/release/PYPI_RELEASE.md",
    "docs/product/52_LOCAL_MCP_ADAPTER.md",
]


def check_github_release_ready(
    output_dir: Path | None = None,
    *,
    root: Path = ROOT,
    release_bundle: Path | None = None,
    send_ready_receipt: Path | None = None,
    final_staging_receipt: Path | None = None,
    require_staging_current: bool = True,
) -> dict[str, Any]:
    dist = (output_dir or root / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)
    release_bundle_path = (release_bundle or dist / RELEASE_BUNDLE_NAME).resolve()
    send_ready_path = (send_ready_receipt or dist / SEND_READY_JSON_NAME).resolve()
    final_staging_path = (final_staging_receipt or dist / FINAL_STAGING_RECEIPT_NAME).resolve()

    remote = _git_remote(root)
    readme_checks = _readme_checks(root / "README.md")
    gitignore_checks = _gitignore_checks(root / ".gitignore")
    public_text_scan = _public_text_scan(root)
    release_bundle_gate = _release_bundle_gate(release_bundle_path, output_dir=dist, root=root)
    send_ready_gate = _send_ready_gate(send_ready_path, root=root)
    staging_gate = _final_staging_gate(
        final_staging_path,
        root=root,
        require_current=require_staging_current,
    )

    payload = _github_release_ready_payload(
        root=root,
        remote=remote,
        readme_checks=readme_checks,
        gitignore_checks=gitignore_checks,
        public_text_scan=public_text_scan,
        release_bundle_gate=release_bundle_gate,
        send_ready_gate=send_ready_gate,
        staging_gate=staging_gate,
        require_staging_current=require_staging_current,
    )
    json_path = dist / GITHUB_RELEASE_READY_JSON_NAME
    md_path = dist / GITHUB_RELEASE_READY_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_github_release_ready_markdown(payload), encoding="utf-8")
    verify_github_release_ready_file(json_path)
    return {
        "status": "checked",
        "verdict": payload["verdict"],
        "github_release_ready_json": str(json_path),
        "github_release_ready_md": str(md_path),
        "github_release_ready_body_sha256": payload["github_release_ready_body_sha256"],
        "blocking_checks": payload["blocking_checks"],
    }


def verify_github_release_ready_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub release-ready JSON object expected.")
    if payload.get("schema_version") != GITHUB_RELEASE_READY_SCHEMA_VERSION:
        raise ValueError("GitHub release-ready schema_version mismatch.")
    checks = payload.get("github_release_ready_checks") if isinstance(payload.get("github_release_ready_checks"), dict) else {}
    if not checks:
        raise ValueError("GitHub release-ready checks missing.")
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise ValueError("GitHub release-ready verification failed: " + ", ".join(failed))
    if payload.get("github_release_ready_body_sha256") != _github_release_ready_body_sha256(payload):
        raise ValueError("GitHub release-ready body hash mismatch.")
    expected_blocking = sorted(name for name, passed in payload.get("checks", {}).items() if passed is not True)
    if payload.get("blocking_checks") != expected_blocking:
        raise ValueError("GitHub release-ready blocking checks mismatch.")
    if payload.get("verdict") == "GO" and expected_blocking:
        raise ValueError("GitHub release-ready GO verdict has blocking checks.")
    return payload


def _github_release_ready_payload(
    *,
    root: Path,
    remote: dict[str, Any],
    readme_checks: dict[str, bool],
    gitignore_checks: dict[str, bool],
    public_text_scan: dict[str, Any],
    release_bundle_gate: dict[str, Any],
    send_ready_gate: dict[str, Any],
    staging_gate: dict[str, Any],
    require_staging_current: bool,
) -> dict[str, Any]:
    checks = {
        "git_remote_origin_present": remote.get("status") == "present",
        "git_remote_origin_is_github": remote.get("is_github") is True,
        "git_remote_url_has_no_embedded_credentials": remote.get("has_embedded_credentials") is False,
        "readme_release_surface_ready": all(readme_checks.values()),
        "gitignore_release_safety_ready": all(gitignore_checks.values()),
        "public_text_has_no_private_markers": public_text_scan.get("finding_count") == 0,
        "release_bundle_verified": release_bundle_gate.get("status") == "verified",
        "release_bundle_safe_to_share": release_bundle_gate.get("safe_to_share") is True,
        "send_ready_receipt_verified": send_ready_gate.get("status") == "verified",
        "send_ready_verdict_go": send_ready_gate.get("verdict") == "GO",
        "final_staging_receipt_current": (
            staging_gate.get("status") == "verified" if require_staging_current else staging_gate.get("status") == "skipped"
        ),
        "no_remote_mutation_performed": True,
        "operator_upload_required": True,
    }
    blocking_checks = sorted(name for name, passed in checks.items() if passed is not True)
    verdict = "GO" if not blocking_checks else "BLOCKED"
    payload: dict[str, Any] = {
        "schema_version": GITHUB_RELEASE_READY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if verdict == "GO" else "blocked",
        "verdict": verdict,
        "safe_to_share": True,
        "repository": {
            "remote": "origin",
            "url": remote.get("url"),
            "repo_slug": remote.get("repo_slug"),
            "is_github": remote.get("is_github"),
        },
        "release_asset": release_bundle_gate,
        "send_ready_receipt": send_ready_gate,
        "final_staging_receipt": staging_gate,
        "readme_checks": readme_checks,
        "gitignore_checks": gitignore_checks,
        "public_text_scan": public_text_scan,
        "checks": checks,
        "blocking_checks": blocking_checks,
        "execution_policy": {
            "script_pushes_to_github": False,
            "script_creates_github_release": False,
            "script_uploads_release_asset": False,
            "script_uploads_dist_directory": False,
            "operator_must_commit_reviewed_slices": True,
            "operator_must_create_github_release": True,
            "operator_must_upload_release_asset": True,
        },
        "operator_steps": [
            "Commit the reviewed release slices manually.",
            "Create a GitHub Release only after the receipt verdict is GO.",
            f"Upload only {RELEASE_BUNDLE_NAME} as the external-user install asset.",
            "Do not claim PyPI availability until the PyPI lane separately verifies fresh install evidence.",
        ],
        "do_not_share": [
            ".env files",
            "raw private project data",
            "local operator session handoff notes",
            "PyPI or TestPyPI API tokens",
        ],
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    payload["github_release_ready_body_sha256"] = _github_release_ready_body_sha256(payload)
    payload["github_release_ready_checks"] = _github_release_ready_checks(payload, root=root)
    return payload


def _git_remote(root: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return {
            "status": "missing",
            "url": "",
            "repo_slug": "",
            "is_github": False,
            "has_embedded_credentials": False,
            "error": _safe_text(result.stderr or result.stdout, root=root),
        }
    raw_url = (result.stdout or "").strip()
    redacted = _redact_remote_url(raw_url)
    return {
        "status": "present",
        "url": redacted,
        "repo_slug": _github_repo_slug(raw_url),
        "is_github": "github.com" in raw_url.lower(),
        "has_embedded_credentials": _has_embedded_credentials(raw_url),
    }


def _readme_checks(path: Path) -> dict[str, bool]:
    text = _read_text(path)
    lowered = text.lower()
    return {
        "readme_present": path.exists(),
        "names_installable_ai_company_runtime": "installable AI company runtime" in text,
        "states_every_project_becomes_ai_company": "Every project becomes an AI company." in text,
        "github_release_asset_is_default": "GitHub Release asset" in text and RELEASE_BUNDLE_NAME in text,
        "standalone_bundle_install_command_present": "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in text,
        "gold_path_runner_present": "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py" in text,
        "pypi_lane_deferred": "PyPI remains a deferred distribution lane" in text
        and "not the current external-user release path" in text,
        "supervised_boundary_present": "does not automatically patch source code" in text
        and "does not call an AI provider" in text,
        "no_fake_autonomy_claim": "fully autonomous" not in lowered and "unsupervised 24/7" not in lowered,
    }


def _gitignore_checks(path: Path) -> dict[str, bool]:
    text = _read_text(path)
    lines = {line.strip() for line in text.splitlines()}
    return {f"gitignore_has_{item.replace('/', '_').replace('.', 'dot')}": item in lines for item in _REQUIRED_GITIGNORE_LINES}


def _public_text_scan(root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned: list[str] = []
    for rel in _PUBLIC_TEXT_SCAN_FILES:
        path = root / rel
        if not path.exists() or path.name == "NEXT_SESSION_HANDOFF.md":
            continue
        scanned.append(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in _PRIVATE_TEXT_MARKERS:
            if marker in text:
                findings.append({"file": rel, "marker": marker})
    return {
        "scanned_files": scanned,
        "finding_count": len(findings),
        "findings": findings[:20],
        "findings_truncated": len(findings) > 20,
    }


def _release_bundle_gate(path: Path, *, output_dir: Path, root: Path) -> dict[str, Any]:
    try:
        manifest = verify_release_bundle_current_artifacts(path, output_dir=output_dir)
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        payload_checks = manifest.get("payload_checks") if isinstance(manifest.get("payload_checks"), dict) else {}
        current_artifact_checks = (
            manifest.get("current_artifact_checks") if isinstance(manifest.get("current_artifact_checks"), dict) else {}
        )
        return {
            "status": "verified",
            "file": path.name,
            "sha256": _sha256(path),
            "file_count": len(files),
            "safe_to_share": True,
            "payload_checks_true": bool(payload_checks) and all(value is True for value in payload_checks.values()),
            "current_artifact_checks_true": bool(current_artifact_checks)
            and all(value is True for value in current_artifact_checks.values()),
        }
    except Exception as exc:  # pragma: no cover - exercised by integration checks
        return {
            "status": "failed",
            "file": path.name,
            "sha256": _sha256(path) if path.exists() else "",
            "safe_to_share": False,
            "error_type": exc.__class__.__name__,
            "error": _safe_text(str(exc), root=root),
        }


def _send_ready_gate(path: Path, *, root: Path) -> dict[str, Any]:
    try:
        payload = verify_send_ready_file(path)
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        return {
            "status": "verified",
            "file": path.name,
            "verdict": payload.get("verdict"),
            "safe_to_share": payload.get("safe_to_share"),
            "body_sha256": payload.get("send_ready_body_sha256"),
            "checks_true": bool(checks) and all(value is True for value in checks.values()),
        }
    except Exception as exc:  # pragma: no cover - exercised by integration checks
        return {
            "status": "failed",
            "file": path.name,
            "verdict": "UNKNOWN",
            "safe_to_share": False,
            "error_type": exc.__class__.__name__,
            "error": _safe_text(str(exc), root=root),
        }


def _final_staging_gate(path: Path, *, root: Path, require_current: bool) -> dict[str, Any]:
    if not require_current:
        return {
            "status": "skipped",
            "file": path.name,
            "reason": "staging receipt current check skipped by operator flag",
        }
    try:
        receipt = verify_staging_receipt_file(path)
        plan = plan_all_worktree_slices(root)
        if plan.get("status") != "all_slices_worktree_ready":
            raise ValueError(f"final staging worktree plan is not ready: {plan.get('status')}")
        current = verify_staging_receipt_against_plan(receipt, plan)
        pathspecs = verify_staging_receipt_pathspec_files(receipt, root)
        return {
            "status": "verified",
            "file": path.name,
            "body_sha256": receipt.get("receipt_body_sha256"),
            "total_candidate_paths": receipt.get("summary", {}).get("total_candidate_paths"),
            "current_status": current.get("status"),
            "pathspec_status": pathspecs.get("status"),
        }
    except Exception as exc:  # pragma: no cover - exercised by integration checks
        return {
            "status": "failed",
            "file": path.name,
            "error_type": exc.__class__.__name__,
            "error": _safe_text(str(exc), root=root),
        }


def _github_release_ready_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "github_release_ready_body_sha256", "github_release_ready_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _github_release_ready_checks(payload: dict[str, Any], *, root: Path) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    body_hash = payload.get("github_release_ready_body_sha256")
    policy = payload.get("execution_policy") if isinstance(payload.get("execution_policy"), dict) else {}
    expected_blocking = sorted(name for name, passed in payload.get("checks", {}).items() if passed is not True)
    return {
        "schema_version_present": payload.get("schema_version") == GITHUB_RELEASE_READY_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "verdict_known": payload.get("verdict") in {"GO", "BLOCKED"},
        "blocking_checks_match_checks": payload.get("blocking_checks") == expected_blocking,
        "execution_policy_blocks_remote_mutation": policy.get("script_pushes_to_github") is False
        and policy.get("script_creates_github_release") is False
        and policy.get("script_uploads_release_asset") is False,
        "operator_release_steps_present": bool(payload.get("operator_steps")),
        "absolute_paths_omitted": str(root) not in serialized and (not home or home not in serialized),
        "privacy_flags_false": payload.get("privacy", {}).get("absolute_paths_included") is False
        and payload.get("privacy", {}).get("raw_private_project_data_included") is False
        and payload.get("privacy", {}).get("secrets_included") is False,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _github_release_ready_body_sha256(payload),
    }


def _github_release_ready_markdown(payload: dict[str, Any]) -> str:
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(payload["operator_steps"], start=1))
    blocking = "\n".join(f"- `{item}`" for item in payload["blocking_checks"]) or "- none"
    return f"""# Cambrian GitHub Release Ready

## Verdict

`{payload["verdict"]}`

## Release Asset

- File: `{payload["release_asset"]["file"]}`
- SHA-256: `{payload["release_asset"].get("sha256", "")}`

## Blocking Checks

{blocking}

## Operator Steps

{steps}

## Boundary

This receipt is a local preflight only. It does not push to GitHub, create a GitHub Release, upload release assets, publish PyPI packages, or send files to external recipients.
"""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_text(value: str, *, root: Path) -> str:
    safe = value.replace(str(root), "<repo>")
    home = str(Path.home())
    if home:
        safe = safe.replace(home, "<home>")
    return safe


def _redact_remote_url(url: str) -> str:
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        rest = "<credentials>@" + rest.split("@", 1)[1]
    return f"{scheme}://{rest}"


def _has_embedded_credentials(url: str) -> bool:
    if "://" not in url:
        return False
    rest = url.split("://", 1)[1]
    return "@" in rest and "github.com" in rest.split("@", 1)[1].lower()


def _github_repo_slug(url: str) -> str:
    cleaned = url.strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if cleaned.startswith("git@github.com:"):
        return cleaned.split(":", 1)[1]
    marker = "github.com/"
    if marker in cleaned:
        return cleaned.split(marker, 1)[1]
    return ""


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Cambrian GitHub Release readiness without mutating GitHub.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--release-bundle", type=Path, default=None)
    parser.add_argument("--send-ready-receipt", type=Path, default=None)
    parser.add_argument("--final-staging-receipt", type=Path, default=None)
    parser.add_argument("--skip-staging-receipt-current", action="store_true")
    parser.add_argument("--verify-receipt", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.verify_receipt:
        payload = verify_github_release_ready_file(args.verify_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    result = check_github_release_ready(
        output_dir=args.output_dir,
        release_bundle=args.release_bundle,
        send_ready_receipt=args.send_ready_receipt,
        final_staging_receipt=args.final_staging_receipt,
        require_staging_current=not args.skip_staging_receipt_current,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
