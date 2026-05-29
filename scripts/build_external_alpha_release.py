"""Cambrian Agent Platform 외부 알파 릴리즈 묶음을 만든다."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELEASE_SLUG = "cambrian-agent-platform-external-alpha"
RELEASE_VERSION = "0.1.0-alpha"
DEFAULT_OUTPUT_DIR = ROOT / "dist"
TRUST_REPORT_NAME = "EXTERNAL_ALPHA_TRUST_REPORT.md"

INCLUDED_FILES = (
    "QUICKSTART_EXTERNAL_ALPHA.md",
    "START_HERE_EXTERNAL_ALPHA.md",
    "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
    "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
    "START_CAMBRIAN_AGENT_PLATFORM.bat",
    "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
    "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
    "README.md",
    "README_EN.md",
    "LICENSE",
    "pyproject.toml",
    "docs/platform/00_AGENT_PLATFORM_FOUNDATION.md",
    "docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md",
    "docs/release/RC_INSTALL_GUIDE.md",
    "docs/release/RC_VERIFICATION.md",
    "docs/release/CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md",
    "docs/launch/DEMO_SCRIPT.md",
    "docs/launch/LAUNCH_GOLDEN_PATH.md",
    "docs/launch/PILOT_ISSUE_INTAKE.md",
    "docs/launch/PILOT_FEEDBACK_FORM.md",
    "scripts/verify_platform_alpha.py",
    "scripts/verify_agent_platform_browser_flow.py",
    "scripts/build_external_alpha_release.py",
    "scripts/verify_external_alpha_release.py",
    "scripts/smoke_external_alpha_release_bundle.py",
    "scripts/smoke_external_alpha_manual_send_go_rehearsal.py",
    "scripts/smoke_external_alpha_post_send_checkpoint.py",
    "scripts/smoke_external_alpha_pilot_learning_loop.py",
    "scripts/smoke_external_alpha_private_pilot_workspace.py",
    "scripts/external_alpha_operator_note_template.py",
    "scripts/prepare_external_alpha_private_pilot_workspace.py",
    "scripts/prepare_external_alpha_first_recipient_send_workspace.py",
    "scripts/check_external_alpha_first_recipient_send_preflight.py",
    "scripts/check_external_alpha_first_recipient_manual_send_go.py",
    "scripts/check_external_alpha_first_recipient_pre_send_sequence.py",
    "scripts/check_external_alpha_first_recipient_post_send_sequence.py",
    "scripts/check_external_alpha_first_recipient_operator_status.py",
    "scripts/prepare_external_alpha_operator_dispatch_packet.py",
    "scripts/prepare_external_alpha_handoff.py",
    "scripts/check_external_alpha_send_ready.py",
    "scripts/check_external_alpha_pilot_ready.py",
    "scripts/check_external_alpha_dispatch_record.py",
    "scripts/check_external_alpha_recipient_checkpoint.py",
    "scripts/check_external_alpha_pilot_review.py",
    "scripts/check_external_alpha_pilot_evidence.py",
    "scripts/check_external_alpha_pilot_decision.py",
    "scripts/check_external_alpha_pilot_iteration.py",
    "scripts/audit_external_alpha_send_chain.py",
    "scripts/audit_external_alpha_operator_send_bypass.py",
    "scripts/collect_external_alpha_diagnostics.py",
    "scripts/prepare_external_alpha_download_landing.py",
    "scripts/prepare_external_alpha_public_download_site.py",
    "scripts/package_external_alpha_public_download_site.py",
    "scripts/check_external_alpha_public_deploy_candidate.py",
    "scripts/check_external_alpha_cloudflare_pages_deploy_ready.py",
    "scripts/check_external_alpha_cloudflare_credentials.py",
    "scripts/launch_external_alpha_cloudflare_pages.py",
    "scripts/check_external_alpha_public_launch_doctor.py",
    "scripts/run_external_alpha_public_launch_sequence.py",
    "scripts/finalize_external_alpha_public_launch_url.py",
    "scripts/verify_external_alpha_public_download_site_url.py",
    "scripts/prepare_external_alpha_public_share_packet.py",
    "scripts/prepare_external_alpha_public_launch_handoff.py",
    "schemas/agent_contract_v0_1.schema.json",
    "schemas/agent_pack_bundle_v0_1.schema.json",
    "schemas/candidate_diff_report_v0_1.schema.json",
    "schemas/candidate_promotion_record_v0_1.schema.json",
    "schemas/evolution_review_decision_v0_1.schema.json",
    "schemas/evolution_suggestion_v0_1.schema.json",
    "schemas/manual_run_receipt_v0_1.schema.json",
    "tools/generate_candidate_diff_report.py",
    "tools/generate_candidate_pack.py",
    "tools/generate_evolution_suggestion.py",
    "tools/promote_candidate_pack.py",
    "tools/validate_agent_pack.py",
    "tools/validate_candidate_diff_report.py",
    "tools/validate_candidate_promotion_record.py",
    "tools/validate_evolution_review_decision.py",
    "tools/validate_evolution_suggestion.py",
    "tools/validate_manual_run_receipt.py",
    "tools/verify_promotion_audit_link.py",
    "web/index.html",
    "web/platform/index.html",
    "web/runner/index.html",
    "web/evolution/index.html",
    "web/studio/index.html",
    "web/packs/index.html",
    "web/packs/auth-bug-core.html",
    "web/packs/typescript-jest-auth-core.html",
    "web/assets/catalog.json",
    "web/assets/auth-bug-core.cambrian-pack.yaml",
    "web/assets/typescript-jest-auth-core.cambrian-pack.yaml",
    "web/assets/document-organizer.agent-pack.json",
    "web/assets/document-organizer.candidate.agent-pack.json",
    "web/assets/document-organizer.candidate-diff-report.json",
    "web/assets/document-organizer.candidate-promotion-record.json",
    "web/assets/document-organizer.evolution-review-decision.json",
    "web/assets/document-organizer.evolution-suggestion.json",
    "web/assets/document-organizer.manual-run-receipt.json",
    "web/assets/document-organizer.promoted.agent-pack.json",
)

FORBIDDEN_PATH_PARTS = {
    ".env",
    ".git",
    ".cambrian",
    ".pytest_tmp",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
}

RELEASE_BOUNDARIES = (
    "단순 MVP가 아니라 Defensible Alpha다.",
    "한국 시장 선점 대상은 에이전트 쇼핑몰 UI가 아니라 agent contract, preflight, verified promotion audit lineage, proof boundary 표준이다.",
    "브라우저 localStorage 외 저장소를 만들지 않는다.",
    "서버, 공개 마켓, Cambrian Runtime으로 데이터를 전송하지 않는다.",
    "API key, secret, 비밀번호를 수집하지 않는다.",
    "proof, 성능, 성공률, 판매 가능 상태를 주장하지 않는다.",
    "promotion audit record는 원문 입력이 아니라 해시와 수동 gate만 저장한다.",
    "promotion audit record는 promoted pack 본문 해시까지 맞을 때만 verified linked로 인정한다.",
)

DISPATCH_EXECUTION_POLICY = {
    "script_sends_to_recipient": False,
    "script_sends_copy_paste_message": False,
    "manual_operator_dispatch_required": True,
    "max_recipients_per_record": 1,
    "records_private_sha256_only": True,
    "raw_private_content_included": False,
    "cohort_scaling_allowed": False,
    "sent_recorded_by_private_hashes_only": False,
}


def build_release(output_dir: Path = DEFAULT_OUTPUT_DIR, skip_verify: bool = False) -> dict[str, Any]:
    """허용 목록 기반으로 외부 알파 ZIP과 해시 매니페스트를 생성한다."""
    output_dir = output_dir.resolve()
    staging_root = output_dir / RELEASE_SLUG
    zip_path = output_dir / f"{RELEASE_SLUG}.zip"
    manifest_path = output_dir / f"{RELEASE_SLUG}.manifest.json"

    if not skip_verify:
        _run_platform_verification()

    _validate_file_list()
    _prepare_output_dir(output_dir)
    _reset_staging_root(staging_root, output_dir)

    entries: list[dict[str, Any]] = []
    for relative in INCLUDED_FILES:
        source = ROOT / relative
        target = staging_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.append(_file_entry(relative, target))

    manifest = {
        "release_name": RELEASE_SLUG,
        "release_version": RELEASE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root_folder": RELEASE_SLUG,
        "zip_file": zip_path.name,
        "file_count": len(entries),
        "bundle_manifest": {
            "path": "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json",
            "hash_policy": "self_hash_omitted",
            "reason": "ZIP 내부 매니페스트는 자기 자신과 ZIP archive 해시를 순환 참조하지 않는다.",
        },
        "boundaries": list(RELEASE_BOUNDARIES),
        "dispatch_execution_policy": dict(DISPATCH_EXECUTION_POLICY),
        "forbidden_path_parts": sorted(FORBIDDEN_PATH_PARTS),
        "files": entries,
    }
    trust_report = staging_root / TRUST_REPORT_NAME
    trust_report.write_text(_trust_report_text(manifest), encoding="utf-8")
    manifest["files"].append(_file_entry(TRUST_REPORT_NAME, trust_report))
    manifest["file_count"] = len(manifest["files"])

    bundle_manifest = staging_root / "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json"
    _write_json(bundle_manifest, manifest)
    _write_zip(staging_root, zip_path)

    archive_entry = _archive_entry(zip_path)
    external_manifest = dict(manifest)
    external_manifest["archive"] = archive_entry
    _write_json(manifest_path, external_manifest)

    return {
        "status": "pass",
        "staging_root": str(staging_root),
        "zip_path": str(zip_path),
        "manifest_path": str(manifest_path),
        "archive_sha256": archive_entry["sha256"],
        "file_count": external_manifest["file_count"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Cambrian Agent Platform 외부 알파 ZIP을 생성한다.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="릴리즈 산출물을 생성할 폴더. 기본값은 dist",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="이미 검증한 경우에만 사전 검증을 건너뛴다.",
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    try:
        result = build_release(Path(args.output_dir), skip_verify=args.skip_verify)
    except Exception as exc:  # noqa: BLE001 - 릴리즈 빌드는 실패 원인을 사용자에게 직접 보여준다.
        print(f"[FAIL] external alpha release build: {exc}")
        return 1

    print("[PASS] external alpha release build")
    print(f"staging : {result['staging_root']}")
    print(f"zip     : {result['zip_path']}")
    print(f"manifest: {result['manifest_path']}")
    print(f"sha256  : {result['archive_sha256']}")
    return 0


def _run_platform_verification() -> None:
    """릴리즈를 만들기 전에 외부 알파 자체 검증을 통과시킨다."""
    script = ROOT / "scripts" / "verify_platform_alpha.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)


def _validate_file_list() -> None:
    """허용 목록의 누락 파일과 금지 경로 포함 여부를 확인한다."""
    missing = [relative for relative in INCLUDED_FILES if not (ROOT / relative).is_file()]
    if missing:
        raise FileNotFoundError("릴리즈 허용 목록 파일 누락: " + ", ".join(missing))

    blocked = [relative for relative in INCLUDED_FILES if _has_forbidden_part(Path(relative))]
    if blocked:
        raise ValueError("릴리즈에 포함할 수 없는 경로: " + ", ".join(blocked))


def _prepare_output_dir(output_dir: Path) -> None:
    """출력 폴더를 만들고 실제 디렉터리인지 확인한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise NotADirectoryError(str(output_dir))


def _reset_staging_root(staging_root: Path, output_dir: Path) -> None:
    """출력 폴더 내부의 이전 스테이징 결과만 안전하게 지운다."""
    resolved_staging = staging_root.resolve()
    resolved_output = output_dir.resolve()
    if resolved_staging == ROOT or resolved_staging == resolved_output:
        raise ValueError("스테이징 폴더가 너무 넓습니다.")
    if not resolved_staging.is_relative_to(resolved_output):
        raise ValueError("스테이징 폴더가 출력 폴더 밖에 있습니다.")
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True)


def _file_entry(relative: str, path: Path) -> dict[str, Any]:
    """매니페스트에 기록할 파일 항목을 만든다."""
    data = path.read_bytes()
    return {
        "path": relative.replace("\\", "/"),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _archive_entry(zip_path: Path) -> dict[str, Any]:
    """ZIP 자체 해시를 만든다."""
    data = zip_path.read_bytes()
    return {
        "path": zip_path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _trust_report_text(manifest: dict[str, Any]) -> str:
    """외부 알파 수령자가 먼저 읽을 신뢰 리포트를 만든다."""
    files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    boundaries = manifest.get("boundaries") if isinstance(manifest.get("boundaries"), list) else []
    dispatch_policy = (
        manifest.get("dispatch_execution_policy")
        if isinstance(manifest.get("dispatch_execution_policy"), dict)
        else {}
    )
    forbidden = manifest.get("forbidden_path_parts") if isinstance(manifest.get("forbidden_path_parts"), list) else []
    boundary_lines = "\n".join(f"- {item}" for item in boundaries)
    dispatch_policy_lines = "\n".join(f"- {key}: {value}" for key, value in dispatch_policy.items())
    forbidden_lines = "\n".join(f"- {item}" for item in forbidden)
    return f"""# External Alpha Trust Report

## Release

- name: {manifest.get("release_name")}
- version: {manifest.get("release_version")}
- status: Defensible Alpha
- root folder: {manifest.get("root_folder")}
- packaged files before this report: {len(files)}

## Position

이 릴리즈는 단순 MVP가 아니라 Defensible Alpha입니다.
한국 시장 선점 대상은 에이전트 쇼핑몰 UI가 아니라 agent contract, preflight, verified promotion audit lineage, proof boundary 표준입니다.

## Boundaries

{boundary_lines}

## Dispatch Execution Policy

{dispatch_policy_lines}

## Forbidden Path Policy

{forbidden_lines}

## Verification

```bash
python scripts/verify_platform_alpha.py
python scripts/verify_external_alpha_release.py
python scripts/check_external_alpha_pilot_ready.py
python scripts/check_external_alpha_pilot_review.py
python scripts/check_external_alpha_pilot_evidence.py
python scripts/check_external_alpha_pilot_decision.py
python scripts/check_external_alpha_pilot_iteration.py
python scripts/smoke_external_alpha_private_pilot_workspace.py
python scripts/smoke_external_alpha_manual_send_go_rehearsal.py
python scripts/prepare_external_alpha_private_pilot_workspace.py --workspace-dir <private-workspace-dir>
python scripts/prepare_external_alpha_first_recipient_send_workspace.py --workspace-dir <private-workspace-dir> --operator-packet dist\\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
python scripts/check_external_alpha_first_recipient_send_preflight.py --workspace-dir <private-workspace-dir> --operator-packet dist\\cambrian-agent-platform-external-alpha-operator-dispatch-packet.json
python scripts/check_external_alpha_first_recipient_manual_send_go.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_first_recipient_pre_send_sequence.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>
python scripts/audit_external_alpha_operator_send_bypass.py --workspace-dir <private-workspace-dir>
python scripts/check_external_alpha_cloudflare_credentials.py --receipt dist\\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json
python scripts/run_external_alpha_public_launch_sequence.py --receipt dist\\cambrian-agent-platform-external-alpha-public-launch-sequence-receipt.json
```

ZIP 자체 sha256은 ZIP 밖 manifest의 `archive.sha256`에 기록됩니다.
이 리포트는 사람이 읽는 신뢰 요약이고, 최종 판정은 검증 스크립트와 JSON manifest가 함께 수행합니다.
"""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON 파일을 안정적인 순서로 쓴다."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_zip(staging_root: Path, zip_path: Path) -> None:
    """스테이징 폴더 전체를 ZIP으로 묶는다."""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging_root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(staging_root).as_posix()
                archive.write(path, f"{RELEASE_SLUG}/{relative}")


def _has_forbidden_part(path: Path) -> bool:
    """금지된 내부 경로 조각이 포함되어 있는지 확인한다."""
    return any(part in FORBIDDEN_PATH_PARTS for part in path.parts)


if __name__ == "__main__":
    raise SystemExit(main())
