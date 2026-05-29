"""최종 commit staging 전에 worktree를 slice 단위로 점검한다."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "final_commit_staging_handoff_audit_v0_1"
RECEIPT_SCHEMA_VERSION = "final_commit_staging_receipt_v0_1"
RECEIPT_JSON_NAME = "final-commit-staging-receipt.json"
RECEIPT_MD_NAME = "final-commit-staging-receipt.md"
RECEIPT_RUNBOOK_NAME = "final-commit-staging-runbook.md"
RECEIPT_PATHSPEC_DIR_NAME = "final-commit-staging-pathspecs"
TEST_GATE_EVIDENCE_SCHEMA_VERSION = "final_commit_test_gate_evidence_v0_1"
TEST_GATE_EVIDENCE_DIR_NAME = "final-commit-test-gate-evidence"
TEST_GATE_LOG_DIR_NAME = "final-commit-test-gate-logs"
GIT_STATUS_ARGS = ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all")
RECEIPT_EXCLUDED_SAMPLE_LIMIT = 50

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SliceRule:
    """commit slice 후보를 판정하는 경로 규칙."""

    slice_id: str
    label: str
    patterns: tuple[str, ...]


SLICE_RULES: tuple[SliceRule, ...] = (
    SliceRule(
        "slice_1_packaging_rc_runtime",
        "Slice 1: Packaging RC Runtime",
        (
            "pyproject.toml",
            "engine/_data_path.py",
            "engine/_data/packs/*",
            "engine/project_pack_catalog.py",
            "engine/project_pack_dependencies.py",
            "engine/project_pack_readiness.py",
            "engine/project_pack_install.py",
            "engine/demo_project.py",
            "scripts/smoke_installed_wheel.py",
            "tests/test_installed_wheel_pack_rc.py",
            "tests/test_alpha_packaging.py",
            "tests/test_pack_catalog.py",
            "tests/test_pack_install.py",
            "tests/test_pack_readiness.py",
            "tests/test_launch_golden_path.py",
            "tests/test_launch_surface.py",
            "tests/test_packaging_slice_ready.py",
            "docs/release/PACKAGING_SLICE_READY.md",
        ),
    ),
    SliceRule(
        "slice_2_ai_company_auto_runtime",
        "Slice 2: AI Company Auto Runtime",
        (
            "engine/project_authority.py",
            "engine/project_auto_mode.py",
            "engine/project_bridge.py",
            "engine/project_company_layer.py",
            "engine/project_mission.py",
            "engine/project_mode.py",
            "tests/test_authority_mode.py",
            "tests/test_auto_mode_state.py",
            "tests/test_auto_boardroom.py",
            "tests/test_auto_plan.py",
            "tests/test_auto_run_limits.py",
            "tests/test_auto_cycle.py",
            "tests/test_auto_input_required_gate.py",
            "tests/test_auto_release_gate.py",
            "tests/test_auto_result_quality_scoring.py",
            "tests/test_auto_done_gate.py",
            "tests/test_auto_next_iteration.py",
            "tests/test_role_specific_auto_directives.py",
            "tests/test_role_specific_result_compliance.py",
            "tests/test_quality_aware_auto_plan_selection.py",
            "tests/test_auto_loop_dogfood.py",
            "tests/test_auto_mission_control.py",
            "tests/test_auto_worker_bridge.py",
            "tests/test_bridge*.py",
            "tests/test_company_layer.py",
            "tests/test_company_snapshot.py",
            "tests/test_mission_company.py",
            "tests/test_project_mode.py",
            "tests/test_auto_runtime_slice_ready.py",
            "docs/release/AUTO_RUNTIME_SLICE_READY.md",
        ),
    ),
    SliceRule(
        "slice_3_harness_workforce_skill",
        "Slice 3: Conversational Harness, Workforce, Skill System",
        (
            "HARNESS_ARTIFACT_SYSTEM.md",
            "docs/product/12_HARNESS_ENGINEERING_SYSTEM.md",
            "docs/product/18_AI_REPLY_INGEST_CONTRACT.md",
            "docs/product/19_JOB_VALIDATE_TRUST_GATE.md",
            "docs/product/46_TRUE_HARNESS_CONTRACT.md",
            "docs/product/47_PERFECT_HARNESS_RESEARCH.md",
            "docs/product/48_AI_EVOLUTION_RESEARCH.md",
            "docs/product/49_META_HARNESS_CAMBRIAN_DIFFERENTIATION.md",
            "docs/product/50_CAMBRIAN_EVOLUTION_RESEARCH_PROGRAM.md",
            "docs/product/51_HARNESS_FIRST_REALITY_CHECK.md",
            "ai_boardroom_reply.yaml",
            "ai_reply_patch_candidate.yaml",
            "engine/project_harness_*.py",
            "engine/project_custom_harness.py",
            "engine/project_workforce_builder.py",
            "engine/project_skill_builder.py",
            "engine/project_agent_dispatch.py",
            "engine/project_evidence.py",
            "engine/project_evolution.py",
            "docs/product/21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md",
            "docs/product/22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md",
            "docs/product/23_EVOLUTION_APPLY_AUDIT_CONTRACT.md",
            "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md",
            "tests/test_project_harness_profile.py",
            "tests/test_project_harness_plan.py",
            "tests/test_project_agent_dispatch.py",
            "tests/test_typescript_jest_auth_harness.py",
            "tests/test_harness_*.py",
            "tests/test_custom_harness_from_answers.py",
            "tests/test_workforce_builder.py",
            "tests/test_agent_generation.py",
            "tests/test_skill_generation.py",
            "tests/test_job_start_*.py",
            "tests/test_dispatch_on_demand.py",
            "tests/test_preset_as_optional_seed.py",
            "tests/test_job_complete_evidence.py",
            "tests/test_evolution*.py",
            "tests/test_skill_evolution.py",
            "tests/test_ai_company_bootstrap.py",
            "tests/fixtures/one_good_harness/*",
            "tests/test_one_good_harness_fixture.py",
            "tests/test_harness_workforce_skill_slice_ready.py",
            "docs/release/HARNESS_WORKFORCE_SKILL_SLICE_READY.md",
        ),
    ),
    SliceRule(
        "slice_4_pack_template_benchmark",
        "Slice 4: Pack, Template, Benchmark Advanced Surfaces",
        (
            "packs/*",
            "schemas/*",
            "engine/cli.py",
            "engine/project_pack_*.py",
            "engine/project_template_*.py",
            "engine/project_benchmark*.py",
            "tools/generate_candidate_pack.py",
            "tools/generate_candidate_diff_report.py",
            "tools/generate_evolution_suggestion.py",
            "tools/promote_candidate_pack.py",
            "tools/validate_*.py",
            "tools/verify_promotion_audit_link.py",
            "tests/test_pack_*.py",
            "tests/test_template_*.py",
            "tests/test_benchmark*.py",
            "tests/test_agent_pack_validator.py",
            "tests/test_agent_platform*.py",
            "tests/test_candidate_*.py",
            "tests/test_manual_run_receipt_validator.py",
            "tests/test_promotion_audit_link.py",
            "tests/test_evolution_suggestion.py",
            "tests/test_evolution_review_decision.py",
            "tests/test_pack_template_benchmark_slice_ready.py",
            "docs/release/PACK_TEMPLATE_BENCHMARK_SLICE_READY.md",
        ),
    ),
    SliceRule(
        "slice_5_launch_pilot_release_docs",
        "Slice 5: Launch, Pilot, Release Docs",
        (
            "START_HERE_EXTERNAL_ALPHA.md",
            "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
            "START_CAMBRIAN_AGENT_PLATFORM.bat",
            "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
            "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
            ".gitignore",
            "CONTEXT_INDEX.md",
            "PROJECT_BRIEF.md",
            "QUICKSTART_EXTERNAL_ALPHA.md",
            "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
            "README.md",
            "TODO.md",
            "demo/*",
            "docs/launch/*",
            "docs/product/00_INDEX.md",
            "docs/product/14_PRODUCT_CONSTITUTION.md",
            "docs/product/42_TEN_YEAR_ARCHITECTURE.md",
            "docs/product/43_AGENT_MARKETPLACE_FUTURE.md",
            "docs/product/45_AI_COMPANY_OS_TASK_BACKLOG.md",
            "docs/product/52_LOCAL_MCP_ADAPTER.md",
            "docs/platform/*",
            "docs/release/*",
            "engine/project_llm_assist.py",
            "engine/project_mcp_server.py",
            "engine/project_mcp_verify.py",
            "scripts/audit_cambrian_install_kit_operator_send_bypass.py",
            "scripts/audit_external_alpha_operator_send_bypass.py",
            "scripts/audit_external_alpha_send_chain.py",
            "scripts/build_cambrian_install_kit.py",
            "scripts/build_external_alpha_release.py",
            "scripts/check_cambrian_install_kit_*.py",
            "scripts/check_external_alpha_*.py",
            "scripts/check_github_release_ready.py",
            "scripts/check_pypi_publish_ready.py",
            "scripts/collect_external_alpha_diagnostics.py",
            "scripts/dogfood_auth_bug_run.py",
            "scripts/external_alpha_operator_note_template.py",
            "scripts/finalize_external_alpha_public_launch_url.py",
            "scripts/launch_external_alpha_cloudflare_pages.py",
            "scripts/package_external_alpha_public_download_site.py",
            "scripts/prepare_cambrian_install_kit_*.py",
            "scripts/prepare_external_alpha_*.py",
            "scripts/prepare_external_alpha_handoff.py",
            "scripts/prepare_pypi_release.py",
            "scripts/run_external_alpha_public_launch_sequence.py",
            "scripts/smoke_ai_company_gold_path.py",
            "scripts/smoke_cambrian_install_kit_*.py",
            "scripts/smoke_external_alpha_*.py",
            "scripts/smoke_one_good_harness_fixture.py",
            "scripts/verify_agent_platform_browser_flow.py",
            "scripts/verify_cambrian_install_kit.py",
            "scripts/verify_external_alpha_release.py",
            "scripts/verify_external_alpha_public_download_site_url.py",
            "scripts/verify_mcp_operability.py",
            "scripts/verify_platform_alpha.py",
            "scripts/verify_pypi_install.py",
            "tests/test_ai_company_gold_path.py",
            "tests/test_ai_company_gold_path_snapshot.py",
            "tests/test_ai_company_os_task_backlog.py",
            "tests/test_cambrian_install_kit.py",
            "scripts/check_final_commit_staging_handoff.py",
            "tests/test_external_alpha_*.py",
            "tests/test_github_release_ready.py",
            "tests/test_launch_*.py",
            "tests/test_pilot_*.py",
            "tests/test_project_mcp_server.py",
            "tests/test_pypi_release.py",
            "tests/test_public_demo_kit.py",
            "tests/test_product_docs.py",
            "tests/test_product_identity_ai_company.py",
            "tests/test_split_run_regression_gate.py",
            "tests/test_worktree_release_handoff.py",
            "tests/test_commit_slicing_plan.py",
            "tests/test_dogfood_runbook.py",
            "tests/test_final_commit_staging_handoff.py",
            "tests/conftest.py",
            "tests/test_cli_help.py",
            "tests/test_win_lane.py",
        ),
    ),
    SliceRule(
        "slice_6_web_and_tools",
        "Slice 6: Web And Tools",
        (
            "web/*",
            "tools/generate_web_catalog.py",
            "tools/run_launch_demo.py",
            "tests/test_web_catalog.py",
            "tests/test_web_tools_slice_ready.py",
            "docs/release/WEB_TOOLS_SLICE_READY.md",
        ),
    ),
    SliceRule(
        "slice_7_runtime_evidence_archive",
        "Slice 7: Runtime Evidence Archive summary",
        (
            "docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md",
            "docs/release/RC_CHECKLIST.md",
            "tests/test_runtime_evidence_archive_slice_ready.py",
        ),
    ),
)

SUGGESTED_COMMIT_MESSAGES = {
    "slice_1_packaging_rc_runtime": "fix(packaging): 설치형 wheel pack catalog 경로 안정화",
    "slice_2_ai_company_auto_runtime": "feat(auto): 권한 모드와 AI 회사 auto loop 추가",
    "slice_3_harness_workforce_skill": "feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가",
    "slice_4_pack_template_benchmark": "feat(pack): pack template qualification surfaces 추가",
    "slice_5_launch_pilot_release_docs": "docs(launch): launch pilot release 운영 문서 정리",
    "slice_6_web_and_tools": "feat(web): launch surface and local tooling 정리",
    "slice_7_runtime_evidence_archive": "docs(evidence): Cambrian auto loop evidence archive 요약 추가",
}

SUGGESTED_TEST_GATE_COMMANDS: dict[str, tuple[str, ...]] = {
    "slice_1_packaging_rc_runtime": (
        "python scripts/smoke_installed_wheel.py",
        "python -m pytest -q tests/test_installed_wheel_pack_rc.py tests/test_alpha_packaging.py tests/test_pack_catalog.py tests/test_pack_install.py tests/test_pack_readiness.py tests/test_launch_golden_path.py tests/test_launch_surface.py tests/test_packaging_slice_ready.py",
    ),
    "slice_2_ai_company_auto_runtime": (
        "python -m pytest -q tests/test_authority_mode.py tests/test_auto_mode_state.py tests/test_auto_boardroom.py tests/test_auto_plan.py tests/test_auto_run_limits.py tests/test_auto_cycle.py tests/test_auto_input_required_gate.py tests/test_auto_release_gate.py tests/test_auto_result_quality_scoring.py tests/test_auto_done_gate.py tests/test_auto_next_iteration.py tests/test_role_specific_auto_directives.py tests/test_role_specific_result_compliance.py tests/test_quality_aware_auto_plan_selection.py tests/test_auto_loop_dogfood.py tests/test_auto_runtime_slice_ready.py",
    ),
    "slice_3_harness_workforce_skill": (
        "python -m pytest -q tests/test_project_harness_profile.py tests/test_project_harness_plan.py tests/test_project_agent_dispatch.py tests/test_pack_compatibility.py tests/test_typescript_jest_auth_harness.py tests/test_harness_interview.py tests/test_custom_harness_from_answers.py tests/test_harness_install_requires_approval.py tests/test_harness_engineer_design.py tests/test_harness_engineer_review.py tests/test_harness_engineer_dry_run.py tests/test_harness_install_requires_engineering_gate.py tests/test_workforce_builder.py tests/test_agent_generation.py tests/test_skill_generation.py tests/test_job_start_selects_agents_and_skills.py tests/test_job_start_runtime_contract.py tests/test_dispatch_on_demand.py tests/test_preset_as_optional_seed.py tests/test_job_complete_evidence.py tests/test_evolution_review.py tests/test_evolution_proposal.py tests/test_evolution_apply_requires_confirm.py tests/test_skill_evolution.py tests/test_ai_company_bootstrap.py tests/test_harness_workforce_skill_slice_ready.py",
    ),
    "slice_4_pack_template_benchmark": (
        "python -m pytest -q tests/test_pack_*.py",
        "python -m pytest -q tests/test_template_*.py",
        "python -m pytest -q tests/test_benchmark*.py",
        "python -m pytest -q tests/test_pack_template_benchmark_slice_ready.py",
    ),
    "slice_5_launch_pilot_release_docs": (
        "python -m pytest -q tests/test_public_demo_kit.py tests/test_launch_assets.py tests/test_pilot_outreach_kit.py tests/test_pilot_learning_board.py tests/test_launch_go_no_go.py tests/test_product_docs.py tests/test_split_run_regression_gate.py tests/test_worktree_release_handoff.py tests/test_commit_slicing_plan.py tests/test_dogfood_runbook.py tests/test_launch_pilot_release_docs_slice_ready.py tests/test_github_release_ready.py",
    ),
    "slice_6_web_and_tools": (
        "python tools/generate_web_catalog.py",
        "python -m pytest -q tests/test_web_catalog.py tests/test_web_tools_slice_ready.py",
    ),
    "slice_7_runtime_evidence_archive": (
        "python -m pytest -q tests/test_runtime_evidence_archive_slice_ready.py tests/test_web_tools_slice_ready.py tests/test_launch_pilot_release_docs_slice_ready.py tests/test_pack_template_benchmark_slice_ready.py tests/test_harness_workforce_skill_slice_ready.py tests/test_auto_runtime_slice_ready.py tests/test_packaging_slice_ready.py tests/test_commit_slicing_plan.py tests/test_worktree_release_handoff.py tests/test_split_run_regression_gate.py",
    ),
}

FORBIDDEN_EXACT_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "id_rsa",
    "id_dsa",
}
FORBIDDEN_SUFFIXES = (".pem", ".p12", ".pfx", ".key")
NOISY_PARTS = {"__pycache__", ".pytest_cache", ".pytest_tmp", ".mypy_cache", ".ruff_cache"}
NOISY_PART_PREFIXES = (".pytest-basetemp",)
RAW_REPLY_MARKERS = ("raw_ai_reply", "external_ai_reply", "browser_localstorage")


def audit_worktree(root: Path = ROOT) -> dict[str, Any]:
    """git status 기반으로 최종 staging 전 점검 결과를 만든다."""
    status_entries = _git_status(root)
    return audit_paths([entry["path"] for entry in status_entries], status_entries=status_entries)


def audit_staged_slice(
    slice_id: str,
    root: Path = ROOT,
    expected_paths_sha256: str | None = None,
) -> dict[str, Any]:
    """현재 staged diff가 지정 slice만 담았는지 점검한다."""
    return validate_slice_paths(
        slice_id=slice_id,
        paths=_git_staged_paths(root),
        source="staged_diff",
        expected_paths_sha256=expected_paths_sha256,
    )


def plan_worktree_slice(slice_id: str, root: Path = ROOT) -> dict[str, Any]:
    """현재 worktree에서 지정 slice의 stage 후보 경로를 산출한다."""
    status_entries = _git_status(root)
    return plan_slice_paths(
        slice_id=slice_id,
        paths=[entry["path"] for entry in status_entries],
        status_entries=status_entries,
    )


def plan_all_worktree_slices(root: Path = ROOT) -> dict[str, Any]:
    """현재 worktree를 모든 commit slice 후보 목록으로 나눈다."""
    status_entries = _git_status(root)
    paths = [entry["path"] for entry in status_entries]
    return plan_all_slice_paths(paths=paths, status_entries=status_entries)


def write_staging_receipt(output_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    """전체 slice plan을 검토 가능한 JSON/Markdown receipt로 저장한다."""
    plan = plan_all_worktree_slices(root)
    return write_staging_receipt_from_plan(output_dir=output_dir, plan=plan)


def write_staging_receipt_from_plan(output_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """계산된 전체 slice plan을 JSON/Markdown receipt로 저장한다."""
    receipt = _receipt_payload(plan, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pathspec_dir = _write_receipt_pathspec_files(output_dir, receipt)
    evidence_template_dir = _write_test_gate_evidence_templates(output_dir, receipt)
    json_path = output_dir / RECEIPT_JSON_NAME
    md_path = output_dir / RECEIPT_MD_NAME
    runbook_path = output_dir / RECEIPT_RUNBOOK_NAME
    json_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_receipt_markdown(receipt), encoding="utf-8")
    runbook_path.write_text(_receipt_runbook_markdown(receipt, output_dir), encoding="utf-8")
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": receipt["status"],
        "verdict": receipt["verdict"],
        "receipt_json": str(json_path),
        "receipt_md": str(md_path),
        "receipt_runbook": str(runbook_path),
        "pathspec_dir": str(pathspec_dir),
        "test_gate_evidence_template_dir": str(evidence_template_dir),
        "receipt_body_sha256": _json_body_sha256(receipt),
        "active_slice_ids": receipt["active_slice_ids"],
        "safe_to_stage_all": receipt["safe_to_stage_all"],
    }


def verify_staging_receipt_file(path: Path) -> dict[str, Any]:
    """저장된 staging receipt JSON을 단독 검증한다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("receipt JSON은 객체여야 합니다.")
    _verify_staging_receipt_payload(payload)
    return payload


def verify_staging_receipt_against_plan(receipt: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """receipt가 현재 worktree plan과 동일한 slice 후보를 가리키는지 검증한다."""
    _verify_staging_receipt_payload(receipt)
    expected_active_slice_ids = list(plan.get("active_slice_ids") or [])
    actual_active_slice_ids = list(receipt.get("active_slice_ids") or [])
    slice_checks: dict[str, dict[str, Any]] = {}
    for slice_id in sorted(set(expected_active_slice_ids) | set(actual_active_slice_ids)):
        receipt_item = _receipt_slice_by_id(receipt, slice_id)
        plan_item = plan.get("slice_plans", {}).get(slice_id) if isinstance(plan.get("slice_plans"), dict) else None
        receipt_digest = receipt_item.get("candidate_paths_sha256") if isinstance(receipt_item, dict) else None
        plan_digest = plan_item.get("candidate_paths_sha256") if isinstance(plan_item, dict) else None
        receipt_count = receipt_item.get("candidate_count") if isinstance(receipt_item, dict) else None
        plan_count = plan_item.get("candidate_count") if isinstance(plan_item, dict) else None
        slice_checks[slice_id] = {
            "present_in_receipt": receipt_item is not None,
            "present_in_plan": plan_item is not None and plan_count > 0,
            "candidate_count_matched": receipt_count == plan_count,
            "candidate_paths_sha256_matched": receipt_digest == plan_digest,
            "receipt_candidate_count": receipt_count,
            "plan_candidate_count": plan_count,
            "receipt_candidate_paths_sha256": receipt_digest,
            "plan_candidate_paths_sha256": plan_digest,
        }
    checks = {
        "receipt_self_verified": True,
        "active_slice_ids_matched": actual_active_slice_ids == expected_active_slice_ids,
        "slice_candidate_counts_matched": all(item["candidate_count_matched"] for item in slice_checks.values()),
        "slice_candidate_digests_matched": all(item["candidate_paths_sha256_matched"] for item in slice_checks.values()),
    }
    status = "receipt_current" if all(checks.values()) else "receipt_stale"
    verdict = "GO" if status == "receipt_current" else "NO_GO"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": verdict,
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "active_slice_ids": actual_active_slice_ids,
        "current_active_slice_ids": expected_active_slice_ids,
        "slice_checks": slice_checks,
        "safe_to_stage_all": False,
    }


def verify_staging_receipt_pathspec_files(receipt: dict[str, Any], base_dir: Path = ROOT) -> dict[str, Any]:
    """receipt가 가리키는 per-slice pathspec 파일이 후보 경로와 일치하는지 검증한다."""
    _verify_staging_receipt_payload(receipt)
    pathspec_checks: dict[str, dict[str, Any]] = {}
    for item in receipt["slice_receipts"]:
        slice_id = item["slice_id"]
        pathspec_file = str(item["pathspec_file"])
        pathspec_path = _resolve_receipt_path(pathspec_file, base_dir)
        expected_paths = list(item["candidate_paths"])
        actual_paths = _read_pathspec_paths(pathspec_path) if pathspec_path.exists() else []
        expected_sha = str(item["candidate_paths_sha256"])
        actual_sha = _paths_sha256(actual_paths)
        pathspec_checks[slice_id] = {
            "pathspec_file": pathspec_file,
            "pathspec_file_exists": pathspec_path.exists(),
            "candidate_count_matched": len(actual_paths) == item["candidate_count"],
            "candidate_paths_matched": actual_paths == expected_paths,
            "candidate_paths_sha256_matched": actual_sha == expected_sha,
            "receipt_candidate_count": item["candidate_count"],
            "pathspec_candidate_count": len(actual_paths),
            "receipt_candidate_paths_sha256": expected_sha,
            "pathspec_candidate_paths_sha256": actual_sha,
        }

    checks = {
        "receipt_self_verified": True,
        "all_pathspec_files_exist": all(item["pathspec_file_exists"] for item in pathspec_checks.values()),
        "all_pathspec_counts_matched": all(item["candidate_count_matched"] for item in pathspec_checks.values()),
        "all_pathspec_paths_matched": all(item["candidate_paths_matched"] for item in pathspec_checks.values()),
        "all_pathspec_digests_matched": all(
            item["candidate_paths_sha256_matched"] for item in pathspec_checks.values()
        ),
    }
    status = "receipt_pathspec_files_current" if all(checks.values()) else "receipt_pathspec_files_stale"
    verdict = "GO" if status == "receipt_pathspec_files_current" else "NO_GO"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": verdict,
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "active_slice_ids": receipt["active_slice_ids"],
        "pathspec_checks": pathspec_checks,
        "safe_to_stage_all": False,
    }


def verify_staging_receipt_runbook(receipt: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """receipt에서 재생성한 runbook과 저장된 runbook 파일이 일치하는지 검증한다."""
    _verify_staging_receipt_payload(receipt)
    runbook_path = output_dir / RECEIPT_RUNBOOK_NAME
    expected = _receipt_runbook_markdown(receipt, output_dir)
    actual = runbook_path.read_text(encoding="utf-8") if runbook_path.exists() else ""
    checks = {
        "receipt_self_verified": True,
        "runbook_file_exists": runbook_path.exists(),
        "runbook_body_matched": actual == expected,
        "runbook_sha256_matched": _text_sha256(actual) == _text_sha256(expected),
    }
    status = "receipt_runbook_current" if all(checks.values()) else "receipt_runbook_stale"
    verdict = "GO" if status == "receipt_runbook_current" else "NO_GO"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": verdict,
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "receipt_runbook": str(runbook_path),
        "expected_runbook_sha256": _text_sha256(expected),
        "actual_runbook_sha256": _text_sha256(actual),
        "active_slice_ids": receipt["active_slice_ids"],
        "safe_to_stage_all": False,
    }


def verify_test_gate_evidence_templates(receipt: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """receipt에서 재생성한 test gate evidence template과 저장된 template 파일을 비교 검증한다."""
    _verify_staging_receipt_payload(receipt)
    template_checks: dict[str, dict[str, Any]] = {}
    for item in receipt["slice_receipts"]:
        slice_id = item["slice_id"]
        template_path = output_dir / TEST_GATE_EVIDENCE_DIR_NAME / f"{slice_id}.template.json"
        expected = json.dumps(
            _test_gate_evidence_template_payload(receipt, item),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        actual = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
        template_checks[slice_id] = {
            "template_file": _output_file_display_path(template_path),
            "template_file_exists": template_path.exists(),
            "template_body_matched": actual == expected,
            "template_sha256_matched": _text_sha256(actual) == _text_sha256(expected),
            "expected_template_sha256": _text_sha256(expected),
            "actual_template_sha256": _text_sha256(actual),
        }

    checks = {
        "receipt_self_verified": True,
        "all_template_files_exist": all(item["template_file_exists"] for item in template_checks.values()),
        "all_template_bodies_matched": all(item["template_body_matched"] for item in template_checks.values()),
        "all_template_digests_matched": all(item["template_sha256_matched"] for item in template_checks.values()),
    }
    status = "receipt_test_gate_evidence_templates_current" if all(checks.values()) else "receipt_test_gate_evidence_templates_stale"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": "GO" if status == "receipt_test_gate_evidence_templates_current" else "NO_GO",
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "active_slice_ids": receipt["active_slice_ids"],
        "template_checks": template_checks,
        "safe_to_stage_all": False,
    }


def verify_staging_receipt_all_artifacts(
    receipt: dict[str, Any],
    receipt_path: Path,
    current_plan: dict[str, Any],
    base_dir: Path = ROOT,
) -> dict[str, Any]:
    """receipt, current worktree, pathspec, runbook을 한 번에 검증한다."""
    current_check = verify_staging_receipt_against_plan(receipt, current_plan)
    pathspec_check = verify_staging_receipt_pathspec_files(receipt, base_dir)
    runbook_check = verify_staging_receipt_runbook(receipt, receipt_path.parent)
    evidence_template_check = verify_test_gate_evidence_templates(receipt, receipt_path.parent)
    checks = {
        "receipt_self_verified": True,
        "receipt_current": current_check["verdict"] == "GO",
        "pathspec_files_current": pathspec_check["verdict"] == "GO",
        "runbook_current": runbook_check["verdict"] == "GO",
        "test_gate_evidence_templates_current": evidence_template_check["verdict"] == "GO",
    }
    status = "receipt_all_artifacts_current" if all(checks.values()) else "receipt_verification_blocked"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": "GO" if status == "receipt_all_artifacts_current" else "NO_GO",
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "active_slice_ids": receipt["active_slice_ids"],
        "current_check": current_check,
        "pathspec_check": pathspec_check,
        "runbook_check": runbook_check,
        "evidence_template_check": evidence_template_check,
        "safe_to_stage_all": False,
    }


def verify_slice_prestage_ready(
    receipt: dict[str, Any],
    slice_id: str,
    staged_paths: list[str],
    current_plan: dict[str, Any],
    base_dir: Path = ROOT,
) -> dict[str, Any]:
    """선택한 slice를 stage하기 직전 index와 receipt/pathspec 상태를 검증한다."""
    _verify_staging_receipt_payload(receipt)
    receipt_item = _receipt_slice_by_id(receipt, slice_id)
    current_check = verify_staging_receipt_against_plan(receipt, current_plan)
    pathspec_check = verify_staging_receipt_pathspec_files(receipt, base_dir)
    slice_pathspec = (
        pathspec_check["pathspec_checks"].get(slice_id)
        if isinstance(pathspec_check.get("pathspec_checks"), dict)
        else None
    )
    checks = {
        "receipt_current": current_check["verdict"] == "GO",
        "pathspec_files_current": pathspec_check["verdict"] == "GO",
        "slice_present_in_receipt": receipt_item is not None,
        "slice_has_candidate_paths": bool(receipt_item and receipt_item.get("candidate_count", 0) > 0),
        "slice_pathspec_current": bool(
            isinstance(slice_pathspec, dict)
            and slice_pathspec["pathspec_file_exists"]
            and slice_pathspec["candidate_count_matched"]
            and slice_pathspec["candidate_paths_matched"]
            and slice_pathspec["candidate_paths_sha256_matched"]
        ),
        "staged_diff_empty": not staged_paths,
    }
    status = "slice_prestage_ready" if all(checks.values()) else "slice_prestage_blocked"
    verdict = "GO" if status == "slice_prestage_ready" else "NO_GO"
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": verdict,
        "slice_id": slice_id,
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "receipt_candidate_count": receipt_item.get("candidate_count") if isinstance(receipt_item, dict) else None,
        "receipt_candidate_paths_sha256": (
            receipt_item.get("candidate_paths_sha256") if isinstance(receipt_item, dict) else None
        ),
        "pathspec_file": receipt_item.get("pathspec_file") if isinstance(receipt_item, dict) else None,
        "stage_command_from_pathspec": (
            receipt_item.get("stage_command_from_pathspec") if isinstance(receipt_item, dict) else None
        ),
        "suggested_commit_message": (
            receipt_item.get("suggested_commit_message") if isinstance(receipt_item, dict) else None
        ),
        "test_gate_commands": (
            receipt_item.get("test_gate_commands") if isinstance(receipt_item, dict) else []
        ),
        "test_gate_commands_sha256": (
            receipt_item.get("test_gate_commands_sha256") if isinstance(receipt_item, dict) else None
        ),
        "commit_command": _commit_command(
            str(receipt_item.get("suggested_commit_message") or "") if isinstance(receipt_item, dict) else ""
        ),
        "verify_command_with_digest": (
            receipt_item.get("verify_command_with_digest") if isinstance(receipt_item, dict) else None
        ),
        "receipt_backed_staged_verify_command": (
            f"python scripts/check_final_commit_staging_handoff.py "
            f"--verify-staged-from-receipt dist/final-commit-staging-receipt.json --slice {slice_id}"
        ),
        "existing_staged_paths": staged_paths,
        "current_check": current_check,
        "pathspec_check": pathspec_check,
        "safe_to_stage_all": False,
    }


def verify_test_gate_evidence_against_receipt(
    receipt: dict[str, Any],
    slice_id: str,
    evidence: dict[str, Any],
    base_dir: Path = ROOT,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """수동 test gate 실행 증거가 receipt와 같은 slice를 가리키는지 검증한다."""
    _verify_staging_receipt_payload(receipt)
    receipt_item = _receipt_slice_by_id(receipt, slice_id)
    if receipt_item is None:
        raise ValueError(f"receipt에 slice가 없습니다: {slice_id}")
    if not isinstance(evidence, dict):
        raise ValueError("test gate evidence JSON은 객체여야 합니다.")

    expected_commands = list(receipt_item.get("test_gate_commands") or [])
    expected_evidence_file = str(receipt_item.get("test_gate_evidence_file") or "")
    actual_evidence_file = _output_file_display_path(evidence_path) if evidence_path is not None else None
    command_results = evidence.get("command_results")
    command_checks: list[dict[str, Any]] = []
    if isinstance(command_results, list):
        for index, command in enumerate(expected_commands):
            result = command_results[index] if index < len(command_results) else None
            matched = isinstance(result, dict) and result.get("command") == command
            passed = matched and result.get("status") == "PASS" and result.get("exit_code") == 0
            evidence_ref = result.get("evidence_ref") if isinstance(result, dict) else None
            evidence_ref_present = isinstance(evidence_ref, str) and bool(evidence_ref.strip())
            normalized_evidence_ref = _normalize(evidence_ref.strip()) if isinstance(evidence_ref, str) else None
            evidence_sha = result.get("evidence_sha256") if isinstance(result, dict) else None
            evidence_file_check = _check_evidence_ref_file(evidence_ref, evidence_sha, command, base_dir)
            command_checks.append(
                {
                    "command": command,
                    "matched": matched,
                    "passed": passed,
                    "evidence_ref_present": evidence_ref_present,
                    "evidence_ref": evidence_ref if isinstance(evidence_ref, str) else None,
                    "evidence_ref_normalized": normalized_evidence_ref,
                    **evidence_file_check,
                    "status": result.get("status") if isinstance(result, dict) else None,
                    "exit_code": result.get("exit_code") if isinstance(result, dict) else None,
                }
            )

    checks = {
        "receipt_self_verified": True,
        "schema_version_matched": evidence.get("schema_version") == TEST_GATE_EVIDENCE_SCHEMA_VERSION,
        "status_pass": evidence.get("status") == "PASS",
        "verdict_go": evidence.get("verdict") == "GO",
        "slice_id_matched": evidence.get("slice_id") == slice_id,
        "receipt_body_sha256_matched": evidence.get("receipt_body_sha256") == receipt["receipt_body_sha256"],
        "candidate_paths_sha256_matched": (
            evidence.get("candidate_paths_sha256") == receipt_item.get("candidate_paths_sha256")
        ),
        "test_gate_evidence_path_matched": (
            actual_evidence_file is None or actual_evidence_file == expected_evidence_file
        ),
        "test_gate_commands_sha256_matched": (
            evidence.get("test_gate_commands_sha256") == receipt_item.get("test_gate_commands_sha256")
        ),
        "test_gate_commands_matched": evidence.get("test_gate_commands") == expected_commands,
        "command_results_present": isinstance(command_results, list)
        and len(command_results) == len(expected_commands),
        "command_results_matched": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["matched"] for item in command_checks),
        "all_command_results_passed": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["passed"] for item in command_checks),
        "all_command_results_have_evidence_ref": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_ref_present"] for item in command_checks),
        "all_evidence_refs_unique": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item.get("evidence_ref_normalized") for item in command_checks)
        and len({item.get("evidence_ref_normalized") for item in command_checks}) == len(command_checks),
        "all_command_results_have_evidence_sha256": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_sha256_present"] for item in command_checks),
        "all_evidence_refs_are_local_files": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_ref_local_file"] for item in command_checks),
        "all_evidence_refs_are_portable": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_ref_portable"] for item in command_checks),
        "all_evidence_refs_use_log_dir": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_ref_allowed_log_dir"] for item in command_checks),
        "all_evidence_refs_are_safe": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_ref_safe"] for item in command_checks),
        "all_evidence_files_exist": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_file_exists"] for item in command_checks),
        "all_evidence_sha256_matched": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_sha256_matched"] for item in command_checks),
        "all_evidence_files_contain_command": bool(command_checks)
        and len(command_checks) == len(expected_commands)
        and all(item["evidence_file_contains_command"] for item in command_checks),
    }
    status = "test_gate_evidence_ready" if all(checks.values()) else "test_gate_evidence_blocked"
    return {
        "schema_version": TEST_GATE_EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "verdict": "GO" if status == "test_gate_evidence_ready" else "NO_GO",
        "slice_id": slice_id,
        "checks": checks,
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "candidate_paths_sha256": receipt_item.get("candidate_paths_sha256"),
        "test_gate_evidence_file": expected_evidence_file,
        "actual_test_gate_evidence_file": actual_evidence_file,
        "test_gate_commands_sha256": receipt_item.get("test_gate_commands_sha256"),
        "test_gate_commands": expected_commands,
        "command_checks": command_checks,
        "safe_to_stage_all": False,
    }


def verify_staged_slice_against_receipt(
    receipt: dict[str, Any],
    slice_id: str,
    staged_paths: list[str],
    source: str = "receipt_staged_diff",
) -> dict[str, Any]:
    """receipt에 잠긴 slice digest로 staged 경로 목록을 검증한다."""
    _verify_staging_receipt_payload(receipt)
    receipt_item = _receipt_slice_by_id(receipt, slice_id)
    if receipt_item is None:
        raise ValueError(f"receipt에 slice가 없습니다: {slice_id}")
    expected_paths_sha = str(receipt_item.get("candidate_paths_sha256") or "")
    result = validate_slice_paths(
        slice_id=slice_id,
        paths=staged_paths,
        source=source,
        expected_paths_sha256=expected_paths_sha,
    )
    result["receipt_body_sha256"] = receipt["receipt_body_sha256"]
    result["receipt_candidate_count"] = receipt_item.get("candidate_count")
    result["receipt_candidate_paths_sha256"] = expected_paths_sha
    result["suggested_commit_message"] = receipt_item.get("suggested_commit_message")
    result["test_gate_commands"] = receipt_item.get("test_gate_commands")
    result["test_gate_commands_sha256"] = receipt_item.get("test_gate_commands_sha256")
    result["test_gate_required_before_commit"] = True
    result["commit_command"] = _commit_command(str(receipt_item.get("suggested_commit_message") or ""))
    result["status"] = "receipt_staged_slice_ready" if result["verdict"] == "GO" else "receipt_staged_slice_blocked"
    return result


def verify_slice_commit_ready_against_receipt(
    receipt: dict[str, Any],
    slice_id: str,
    staged_paths: list[str],
) -> dict[str, Any]:
    """receipt와 staged diff가 맞을 때 commit 직전 상태와 추천 메시지를 반환한다."""
    result = verify_staged_slice_against_receipt(
        receipt=receipt,
        slice_id=slice_id,
        staged_paths=staged_paths,
        source="receipt_commit_ready_staged_diff",
    )
    checks = {
        "receipt_staged_slice_ready": result["verdict"] == "GO",
        "staged_paths_present": bool(result["accepted_paths"]),
        "suggested_commit_message_present": bool(result.get("suggested_commit_message")),
        "test_gate_commands_present": bool(result.get("test_gate_commands")),
    }
    status = "slice_commit_ready" if all(checks.values()) else "slice_commit_blocked"
    return {
        **result,
        "status": status,
        "verdict": "GO" if status == "slice_commit_ready" else "NO_GO",
        "checks": {**result["checks"], **checks},
        "next_required_commands": [
            *(result.get("test_gate_commands") or []),
            result.get("commit_command") or "",
        ],
    }


def verify_slice_final_commit_gate_against_receipt(
    receipt: dict[str, Any],
    slice_id: str,
    staged_paths: list[str],
    evidence: dict[str, Any],
    receipt_artifacts_check: dict[str, Any],
    base_dir: Path = ROOT,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    """커밋 직전 staged slice와 test gate evidence를 하나의 GO/NO_GO로 묶어 검증한다."""
    commit_ready = verify_slice_commit_ready_against_receipt(receipt, slice_id, staged_paths)
    test_gate_evidence = verify_test_gate_evidence_against_receipt(
        receipt=receipt,
        slice_id=slice_id,
        evidence=evidence,
        base_dir=base_dir,
        evidence_path=evidence_path,
    )
    checks = {
        "receipt_all_artifacts_current": receipt_artifacts_check.get("verdict") == "GO"
        and receipt_artifacts_check.get("status") == "receipt_all_artifacts_current",
        "slice_commit_ready": commit_ready["verdict"] == "GO",
        "test_gate_evidence_ready": test_gate_evidence["verdict"] == "GO",
        "same_slice_id": commit_ready.get("slice_id") == test_gate_evidence.get("slice_id") == slice_id,
        "same_candidate_paths_sha256": commit_ready.get("receipt_candidate_paths_sha256")
        == test_gate_evidence.get("candidate_paths_sha256"),
        "same_test_gate_commands_sha256": commit_ready.get("test_gate_commands_sha256")
        == test_gate_evidence.get("test_gate_commands_sha256"),
    }
    status = "slice_final_commit_gate_ready" if all(checks.values()) else "slice_final_commit_gate_blocked"
    blocking_reasons = _final_commit_gate_blocking_reasons(checks)
    blocking_details = _final_commit_gate_blocking_details(
        checks=checks,
        receipt_artifacts_check=receipt_artifacts_check,
        commit_ready=commit_ready,
        test_gate_evidence=test_gate_evidence,
    )
    recovery_commands = _final_commit_gate_recovery_commands(
        checks=checks,
        receipt=receipt,
        slice_id=slice_id,
    )
    recovery_command_plan = _final_commit_gate_recovery_command_plan(recovery_commands)
    recovery_command_summary = _recovery_command_summary(recovery_command_plan)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": status,
        "verdict": "GO" if status == "slice_final_commit_gate_ready" else "NO_GO",
        "slice_id": slice_id,
        "checks": checks,
        "blocking_reasons": blocking_reasons,
        "blocking_details": blocking_details,
        "recovery_commands": recovery_commands,
        "recovery_command_plan": recovery_command_plan,
        "recovery_command_summary": recovery_command_summary,
        "recovery_execution_policy": _final_commit_gate_recovery_execution_policy(),
        "next_action": "사용자 확인 후 git commit 실행" if not blocking_reasons else "blocking_reasons를 해결한 뒤 최종 통합 게이트를 재실행",
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "accepted_paths": commit_ready.get("accepted_paths") or [],
        "accepted_paths_sha256": commit_ready.get("accepted_paths_sha256"),
        "candidate_paths_sha256": test_gate_evidence.get("candidate_paths_sha256"),
        "test_gate_commands_sha256": test_gate_evidence.get("test_gate_commands_sha256"),
        "test_gate_evidence_file": test_gate_evidence.get("test_gate_evidence_file"),
        "actual_test_gate_evidence_file": test_gate_evidence.get("actual_test_gate_evidence_file"),
        "suggested_commit_message": commit_ready.get("suggested_commit_message"),
        "commit_command": commit_ready.get("commit_command"),
        "receipt_artifacts_check": receipt_artifacts_check,
        "commit_ready": commit_ready,
        "test_gate_evidence": test_gate_evidence,
        "manual_commit_requires_user_confirmation": True,
        "safe_to_stage_all": False,
    }


def _final_commit_gate_blocking_reasons(checks: dict[str, bool]) -> list[str]:
    reasons: list[str] = []
    if not checks.get("receipt_all_artifacts_current"):
        reasons.append("receipt/pathspec/runbook/evidence template 최신성 검증 실패")
    if not checks.get("slice_commit_ready"):
        reasons.append("staged slice가 receipt candidate digest와 일치하지 않음")
    if not checks.get("test_gate_evidence_ready"):
        reasons.append("test gate evidence JSON 또는 참조 로그 검증 실패")
    if not checks.get("same_slice_id"):
        reasons.append("staged slice와 test gate evidence의 slice_id 불일치")
    if not checks.get("same_candidate_paths_sha256"):
        reasons.append("staged candidate digest와 evidence candidate digest 불일치")
    if not checks.get("same_test_gate_commands_sha256"):
        reasons.append("commit-ready test gate digest와 evidence test gate digest 불일치")
    return reasons


def _final_commit_gate_blocking_details(
    checks: dict[str, bool],
    receipt_artifacts_check: dict[str, Any],
    commit_ready: dict[str, Any],
    test_gate_evidence: dict[str, Any],
) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    if not checks.get("receipt_all_artifacts_current"):
        details["receipt_artifacts"] = _failed_payload_check_names(receipt_artifacts_check)
    if not checks.get("slice_commit_ready"):
        details["commit_ready"] = _failed_payload_check_names(commit_ready)
    if not checks.get("test_gate_evidence_ready"):
        details["test_gate_evidence"] = _failed_payload_check_names(test_gate_evidence)
    integrated_failures = _failed_check_names(checks)
    if integrated_failures:
        details["integrated"] = integrated_failures
    return details


def _final_commit_gate_recovery_commands(
    checks: dict[str, bool],
    receipt: dict[str, Any],
    slice_id: str,
) -> list[str]:
    if all(checks.values()):
        return []
    receipt_item = _receipt_slice_by_id(receipt, slice_id) or {}
    commands: list[str] = []
    if not checks.get("receipt_all_artifacts_current"):
        commands.extend(
            [
                "python scripts/check_final_commit_staging_handoff.py --write-receipt-dir dist",
                "python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json",
            ]
        )
    if not checks.get("slice_commit_ready"):
        commands.extend(
            [
                f"python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt dist/final-commit-staging-receipt.json --slice {slice_id}",
                str(receipt_item.get("stage_command_from_pathspec") or ""),
                str(receipt_item.get("verify_command_with_digest") or ""),
                f"python scripts/check_final_commit_staging_handoff.py --verify-staged-from-receipt dist/final-commit-staging-receipt.json --slice {slice_id}",
                f"python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt dist/final-commit-staging-receipt.json --slice {slice_id}",
                "git diff --cached --stat",
                "git diff --cached --name-only",
            ]
        )
    if not checks.get("test_gate_evidence_ready"):
        commands.extend(str(command) for command in receipt_item.get("test_gate_commands") or [])
        commands.append(str(receipt_item.get("verify_test_gate_evidence_command") or ""))
    final_gate_command = str(receipt_item.get("verify_final_commit_gate_command") or "")
    if final_gate_command:
        commands.append(final_gate_command)
    return _dedupe_non_empty(commands)


def _final_commit_gate_recovery_command_plan(commands: list[str]) -> list[dict[str, Any]]:
    return [_recovery_command_step(command) for command in commands]


def _recovery_command_summary(plan: list[dict[str, Any]]) -> dict[str, Any]:
    phase_counts: dict[str, int] = {}
    command_kind_counts: dict[str, int] = {}
    for step in plan:
        phase = str(step.get("phase") or "unknown")
        command_kind = str(step.get("command_kind") or "unknown")
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        command_kind_counts[command_kind] = command_kind_counts.get(command_kind, 0) + 1
    index_mutation_count = sum(1 for step in plan if step.get("mutates_git_index") is True)
    dist_write_count = sum(1 for step in plan if step.get("command_kind") == "writes_dist_artifacts")
    test_run_count = sum(1 for step in plan if step.get("command_kind") == "runs_tests")
    manual_review_count = sum(1 for step in plan if step.get("requires_manual_review") is True)
    return {
        "total_count": len(plan),
        "phase_counts": phase_counts,
        "command_kind_counts": command_kind_counts,
        "mutates_git_index_count": index_mutation_count,
        "writes_dist_artifacts_count": dist_write_count,
        "runs_tests_count": test_run_count,
        "requires_manual_review_count": manual_review_count,
        "has_index_mutations": index_mutation_count > 0,
        "has_dist_artifact_writes": dist_write_count > 0,
        "has_test_runs": test_run_count > 0,
    }


def _final_commit_gate_recovery_execution_policy() -> dict[str, bool]:
    return {
        "recovery_commands_are_suggestions_only": True,
        "script_executes_recovery_commands": False,
        "script_executes_git_add": False,
        "script_executes_git_commit": False,
        "script_executes_git_push": False,
        "index_mutation_requires_manual_user_confirmation": True,
        "dist_artifact_write_requires_manual_review": True,
        "commit_requires_user_confirmation": True,
    }


def _recovery_command_step(command: str) -> dict[str, Any]:
    phase = "manual_review"
    command_kind = "read_only_verify"
    if "--write-receipt-dir" in command:
        phase = "receipt_artifacts"
        command_kind = "writes_dist_artifacts"
    elif "--verify-all-artifacts" in command:
        phase = "receipt_artifacts"
    elif "--verify-prestage-from-receipt" in command:
        phase = "prestage"
    elif command.startswith("git add "):
        phase = "stage"
        command_kind = "mutates_git_index"
    elif "--staged --slice" in command or "--verify-staged-from-receipt" in command:
        phase = "stage_verify"
    elif "--verify-commit-ready-from-receipt" in command:
        phase = "commit_ready"
    elif command.startswith("git diff --cached"):
        phase = "stage_review"
    elif "--verify-test-gate-evidence-from-receipt" in command:
        phase = "test_gate_evidence"
    elif "--verify-final-commit-from-receipt" in command:
        phase = "final_gate"
    elif "pytest" in command or "smoke_installed_wheel" in command:
        phase = "test_gate"
        command_kind = "runs_tests"
    return {
        "phase": phase,
        "command_kind": command_kind,
        "command": command,
        "mutates_git_index": command_kind == "mutates_git_index",
        "requires_manual_review": command_kind in {"mutates_git_index", "writes_dist_artifacts"},
    }


def _dedupe_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def _failed_payload_check_names(payload: dict[str, Any]) -> list[str]:
    failed = _failed_check_names(payload.get("checks") if isinstance(payload, dict) else None)
    if failed:
        return failed
    status = payload.get("status") if isinstance(payload, dict) else None
    verdict = payload.get("verdict") if isinstance(payload, dict) else None
    if verdict != "GO" and status:
        return [str(status)]
    if verdict != "GO":
        return ["verdict_not_go"]
    return []


def _failed_check_names(checks: Any) -> list[str]:
    if not isinstance(checks, dict):
        return []
    return [name for name, passed in checks.items() if passed is not True]


def audit_paths(paths: list[str], status_entries: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """테스트와 CLI가 공유하는 경로 분류 로직."""
    entries = [_classify_path(path) for path in paths]
    blockers = [entry for entry in entries if entry["risk"] == "forbidden"]
    excluded = [entry for entry in entries if entry["risk"] == "excluded_by_default"]
    manual_review = [entry for entry in entries if entry["risk"] == "manual_review"]
    slice_ids = sorted({entry["primary_slice"] for entry in entries if entry.get("primary_slice")})
    slice_counts = {
        rule.slice_id: sum(1 for entry in entries if entry.get("primary_slice") == rule.slice_id)
        for rule in SLICE_RULES
    }
    slice_counts = {key: value for key, value in slice_counts.items() if value}

    checks = {
        "no_forbidden_sensitive_paths": not blockers,
        "slice_candidates_present": bool(slice_ids),
        "stage_all_is_not_safe": len(slice_ids) > 1 or bool(excluded) or bool(manual_review),
        "runtime_evidence_excluded_by_default": any(
            entry["category"] == "runtime_evidence" for entry in excluded
        ),
        "manual_review_paths_named": True,
    }
    status = "ready_for_manual_slice_staging" if checks["no_forbidden_sensitive_paths"] else "blocked"
    verdict = "GO" if status == "ready_for_manual_slice_staging" else "NO_GO"
    next_action = (
        "slice 하나를 고른 뒤 해당 slice 경로만 stage하고 git diff --cached를 확인한다."
        if verdict == "GO"
        else "금지 또는 민감 경로를 worktree/staging 범위에서 제거한 뒤 다시 실행한다."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "verdict": verdict,
        "safe_to_stage_all": False,
        "next_action": next_action,
        "checks": checks,
        "total_paths": len(entries),
        "slice_ids": slice_ids,
        "slice_counts": slice_counts,
        "blockers": blockers,
        "excluded_by_default": excluded,
        "manual_review": manual_review,
        "entries": entries,
        "git_status_entries": status_entries or [],
    }


def validate_slice_paths(
    slice_id: str,
    paths: list[str],
    source: str = "paths",
    expected_paths_sha256: str | None = None,
) -> dict[str, Any]:
    """경로 목록이 특정 commit slice 범위 안에만 있는지 검증한다."""
    known_slice_ids = {rule.slice_id for rule in SLICE_RULES}
    if slice_id not in known_slice_ids:
        raise ValueError(f"알 수 없는 slice_id입니다: {slice_id}")

    entries = [_classify_path(path) for path in paths]
    blockers = [entry for entry in entries if entry["risk"] == "forbidden"]
    excluded = [entry for entry in entries if entry["risk"] == "excluded_by_default"]
    manual_review = [entry for entry in entries if entry["risk"] == "manual_review"]
    wrong_slice = [
        entry
        for entry in entries
        if entry["risk"] == "candidate" and entry.get("primary_slice") != slice_id
    ]
    accepted = [
        entry
        for entry in entries
        if entry["risk"] == "candidate" and entry.get("primary_slice") == slice_id
    ]
    accepted_paths = [entry["path"] for entry in accepted]
    accepted_paths_sha256 = _paths_sha256(accepted_paths)
    expected_sha = str(expected_paths_sha256 or "").strip()
    checks = {
        "slice_id_known": True,
        "paths_present": bool(entries),
        "no_forbidden_sensitive_paths": not blockers,
        "no_excluded_default_paths": not excluded,
        "no_manual_review_paths": not manual_review,
        "no_cross_slice_paths": not wrong_slice,
        "expected_paths_sha256_matched": not expected_sha or accepted_paths_sha256 == expected_sha,
    }
    status = "slice_stage_ready" if all(checks.values()) else "slice_stage_blocked"
    verdict = "GO" if status == "slice_stage_ready" else "NO_GO"
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "slice_id": slice_id,
        "status": status,
        "verdict": verdict,
        "checks": checks,
        "total_paths": len(entries),
        "accepted_paths": accepted_paths,
        "accepted_paths_sha256": accepted_paths_sha256,
        "expected_paths_sha256": expected_sha or None,
        "blockers": blockers,
        "excluded_by_default": excluded,
        "manual_review": manual_review,
        "wrong_slice": wrong_slice,
        "entries": entries,
    }


def plan_slice_paths(
    slice_id: str,
    paths: list[str],
    status_entries: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """특정 slice에 stage할 후보 경로와 제외/타 slice 경로를 분리한다."""
    known_slice_ids = {rule.slice_id for rule in SLICE_RULES}
    if slice_id not in known_slice_ids:
        raise ValueError(f"알 수 없는 slice_id입니다: {slice_id}")

    entries = [_classify_path(path) for path in paths]
    blockers = [entry for entry in entries if entry["risk"] == "forbidden"]
    excluded = [entry for entry in entries if entry["risk"] == "excluded_by_default"]
    manual_review = [entry for entry in entries if entry["risk"] == "manual_review"]
    candidate_entries = [
        entry
        for entry in entries
        if entry["risk"] == "candidate" and entry.get("primary_slice") == slice_id
    ]
    candidate_paths = [entry["path"] for entry in candidate_entries]
    other_slice_entries = [
        entry
        for entry in entries
        if entry["risk"] == "candidate" and entry.get("primary_slice") != slice_id
    ]
    other_slice_counts: dict[str, int] = {}
    for entry in other_slice_entries:
        other_slice = str(entry.get("primary_slice") or "unknown")
        other_slice_counts[other_slice] = other_slice_counts.get(other_slice, 0) + 1

    checks = {
        "slice_id_known": True,
        "candidate_paths_present": bool(candidate_entries),
        "no_forbidden_sensitive_paths": not blockers,
        "no_manual_review_paths": not manual_review,
    }
    status = "slice_worktree_ready" if all(checks.values()) else "slice_worktree_blocked"
    verdict = "GO" if status == "slice_worktree_ready" else "NO_GO"
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "worktree",
        "slice_id": slice_id,
        "status": status,
        "verdict": verdict,
        "checks": checks,
        "total_paths": len(entries),
        "candidate_paths": candidate_paths,
        "candidate_paths_sha256": _paths_sha256(candidate_paths),
        "candidate_count": len(candidate_entries),
        "other_slice_counts": other_slice_counts,
        "blockers": blockers,
        "excluded_by_default": excluded,
        "manual_review": manual_review,
        "entries": entries,
        "git_status_entries": status_entries or [],
        "stage_command_preview": _stage_command_preview(candidate_paths),
        "verify_command": f"python scripts/check_final_commit_staging_handoff.py --staged --slice {slice_id}",
        "verify_command_with_digest": (
            "python scripts/check_final_commit_staging_handoff.py "
            f"--staged --slice {slice_id} --expect-paths-sha256 {_paths_sha256(candidate_paths)}"
        ),
    }


def plan_all_slice_paths(
    paths: list[str],
    status_entries: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """모든 slice별 stage 후보 목록을 한 번에 만든다."""
    entries = [_classify_path(path) for path in paths]
    blockers = [entry for entry in entries if entry["risk"] == "forbidden"]
    excluded = [entry for entry in entries if entry["risk"] == "excluded_by_default"]
    manual_review = [entry for entry in entries if entry["risk"] == "manual_review"]
    slice_plans: dict[str, dict[str, Any]] = {}
    for rule in SLICE_RULES:
        candidate_paths = [
            entry["path"]
            for entry in entries
            if entry["risk"] == "candidate" and entry.get("primary_slice") == rule.slice_id
        ]
        slice_plans[rule.slice_id] = {
            "label": rule.label,
            "candidate_count": len(candidate_paths),
            "candidate_paths": candidate_paths,
            "candidate_paths_sha256": _paths_sha256(candidate_paths),
            "stage_command_preview": _stage_command_preview(candidate_paths),
            "verify_command": f"python scripts/check_final_commit_staging_handoff.py --staged --slice {rule.slice_id}",
            "verify_command_with_digest": (
                "python scripts/check_final_commit_staging_handoff.py "
                f"--staged --slice {rule.slice_id} --expect-paths-sha256 {_paths_sha256(candidate_paths)}"
            ),
        }

    active_slice_ids = [
        slice_id for slice_id, plan in slice_plans.items() if plan["candidate_count"] > 0
    ]
    worktree_clean = not entries
    checks = {
        "no_forbidden_sensitive_paths": not blockers,
        "no_manual_review_paths": not manual_review,
        "active_slice_candidates_present": bool(active_slice_ids) or worktree_clean,
        "excluded_default_paths_named": True,
    }
    if worktree_clean and checks["no_forbidden_sensitive_paths"] and checks["no_manual_review_paths"]:
        status = "all_slices_worktree_complete"
    else:
        status = "all_slices_worktree_ready" if all(checks.values()) else "all_slices_worktree_blocked"
    verdict = "GO" if status in {"all_slices_worktree_ready", "all_slices_worktree_complete"} else "NO_GO"
    next_action = (
        "No slice candidates remain; final staging is complete."
        if status == "all_slices_worktree_complete"
        else "한 slice를 골라 candidate_paths만 stage한 뒤 --staged --slice 검증을 실행한다."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "worktree",
        "status": status,
        "verdict": verdict,
        "safe_to_stage_all": False,
        "checks": checks,
        "total_paths": len(entries),
        "active_slice_ids": active_slice_ids,
        "slice_plans": slice_plans,
        "blockers": blockers,
        "excluded_by_default": excluded,
        "manual_review": manual_review,
        "entries": entries,
        "git_status_entries": status_entries or [],
        "next_action": next_action,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="최종 commit staging handoff를 slice 단위로 점검한다.")
    parser.add_argument("--json", action="store_true", help="점검 결과를 JSON으로 출력한다.")
    parser.add_argument("--paths-json", default=None, help="테스트용 경로 배열 JSON 파일을 사용한다.")
    parser.add_argument("--slice", dest="slice_id", default=None, help="지정 slice만 포함하는지 검증한다.")
    parser.add_argument("--staged", action="store_true", help="현재 staged diff를 대상으로 --slice 검증을 실행한다.")
    parser.add_argument("--worktree", action="store_true", help="현재 worktree에서 --slice 후보 경로를 산출한다.")
    parser.add_argument("--all-slices", action="store_true", help="현재 worktree의 모든 slice 후보 경로를 산출한다.")
    parser.add_argument("--expect-paths-sha256", default=None, help="staged 경로 목록이 계획 digest와 일치하는지 검증한다.")
    parser.add_argument("--write-receipt-dir", default=None, help="전체 slice staging receipt를 지정 폴더에 저장한다.")
    parser.add_argument("--verify-receipt", default=None, help="저장된 staging receipt JSON을 단독 검증한다.")
    parser.add_argument("--verify-all-artifacts", default=None, help="receipt/current worktree/pathspec/runbook을 한 번에 검증한다.")
    parser.add_argument("--verify-pathspec-files", action="store_true", help="receipt가 가리키는 per-slice pathspec 파일을 검증한다.")
    parser.add_argument("--verify-runbook", action="store_true", help="receipt에서 재생성한 runbook과 저장된 runbook 파일을 비교 검증한다.")
    parser.add_argument("--verify-prestage-from-receipt", default=None, help="receipt 기준으로 선택 slice를 stage하기 직전 상태를 검증한다.")
    parser.add_argument("--verify-staged-from-receipt", default=None, help="receipt digest로 현재 staged slice를 검증한다.")
    parser.add_argument("--verify-commit-ready-from-receipt", default=None, help="receipt digest로 현재 staged slice의 commit 직전 상태를 검증한다.")
    parser.add_argument("--verify-test-gate-evidence-from-receipt", default=None, help="receipt digest로 slice test gate evidence JSON을 검증한다.")
    parser.add_argument("--verify-final-commit-from-receipt", default=None, help="receipt digest로 staged slice와 test gate evidence를 함께 검증한다.")
    parser.add_argument("--test-gate-evidence", default=None, help="검증할 slice test gate evidence JSON 경로.")
    parser.add_argument("--against-current-worktree", action="store_true", help="receipt가 현재 worktree slice plan과 일치하는지 검증한다.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if args.verify_all_artifacts and (
            args.verify_receipt
            or args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.paths_json
            or args.slice_id
            or args.verify_pathspec_files
            or args.verify_runbook
            or args.verify_prestage_from_receipt
            or args.verify_staged_from_receipt
            or args.verify_commit_ready_from_receipt
            or args.verify_test_gate_evidence_from_receipt
            or args.verify_final_commit_from_receipt
            or args.test_gate_evidence
            or args.against_current_worktree
        ):
            raise ValueError("--verify-all-artifacts는 단독으로 사용해야 합니다.")
        if args.against_current_worktree and not args.verify_receipt:
            raise ValueError("--against-current-worktree는 --verify-receipt와 함께 사용해야 합니다.")
        if args.verify_pathspec_files and not args.verify_receipt:
            raise ValueError("--verify-pathspec-files는 --verify-receipt와 함께 사용해야 합니다.")
        if args.verify_runbook and not args.verify_receipt:
            raise ValueError("--verify-runbook은 --verify-receipt와 함께 사용해야 합니다.")
        if args.verify_prestage_from_receipt and (
            args.verify_receipt
            or args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.paths_json
            or args.verify_pathspec_files
            or args.against_current_worktree
            or args.verify_staged_from_receipt
            or args.verify_commit_ready_from_receipt
            or args.verify_test_gate_evidence_from_receipt
            or args.verify_final_commit_from_receipt
            or args.test_gate_evidence
        ):
            raise ValueError("--verify-prestage-from-receipt는 --slice와 단독으로 사용해야 합니다.")
        if args.verify_prestage_from_receipt and not args.slice_id:
            raise ValueError("--verify-prestage-from-receipt는 --slice와 함께 사용해야 합니다.")
        if args.verify_staged_from_receipt and (
            args.verify_receipt
            or args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.paths_json
            or args.verify_commit_ready_from_receipt
            or args.verify_test_gate_evidence_from_receipt
            or args.verify_final_commit_from_receipt
            or args.test_gate_evidence
        ):
            raise ValueError("--verify-staged-from-receipt는 --slice와 단독으로 사용해야 합니다.")
        if args.verify_staged_from_receipt and not args.slice_id:
            raise ValueError("--verify-staged-from-receipt는 --slice와 함께 사용해야 합니다.")
        if args.verify_commit_ready_from_receipt and (
            args.verify_receipt
            or args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.paths_json
            or args.verify_staged_from_receipt
            or args.verify_test_gate_evidence_from_receipt
            or args.verify_final_commit_from_receipt
            or args.test_gate_evidence
        ):
            raise ValueError("--verify-commit-ready-from-receipt는 --slice와 단독으로 사용해야 합니다.")
        if args.verify_commit_ready_from_receipt and not args.slice_id:
            raise ValueError("--verify-commit-ready-from-receipt는 --slice와 함께 사용해야 합니다.")
        if args.verify_test_gate_evidence_from_receipt and (
            args.verify_receipt
            or args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.paths_json
            or args.verify_staged_from_receipt
            or args.verify_commit_ready_from_receipt
            or args.verify_final_commit_from_receipt
        ):
            raise ValueError("--verify-test-gate-evidence-from-receipt는 --slice와 --test-gate-evidence만 함께 사용할 수 있습니다.")
        if args.verify_test_gate_evidence_from_receipt and (not args.slice_id or not args.test_gate_evidence):
            raise ValueError("--verify-test-gate-evidence-from-receipt는 --slice와 --test-gate-evidence가 필요합니다.")
        if args.verify_final_commit_from_receipt and (
            args.verify_receipt
            or args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.paths_json
            or args.verify_staged_from_receipt
            or args.verify_commit_ready_from_receipt
            or args.verify_test_gate_evidence_from_receipt
        ):
            raise ValueError("--verify-final-commit-from-receipt는 --slice와 --test-gate-evidence만 함께 사용할 수 있습니다.")
        if args.verify_final_commit_from_receipt and (not args.slice_id or not args.test_gate_evidence):
            raise ValueError("--verify-final-commit-from-receipt는 --slice와 --test-gate-evidence가 필요합니다.")
        if args.test_gate_evidence and not (
            args.verify_test_gate_evidence_from_receipt or args.verify_final_commit_from_receipt
        ):
            raise ValueError("--test-gate-evidence는 test gate evidence 검증 명령과 함께 사용해야 합니다.")
        if args.verify_receipt and (
            args.write_receipt_dir
            or args.staged
            or args.worktree
            or args.slice_id
            or args.paths_json
            or args.verify_final_commit_from_receipt
            or args.test_gate_evidence
        ):
            raise ValueError("--verify-receipt는 다른 검증 모드와 동시에 사용할 수 없습니다.")
        if args.write_receipt_dir and (
            args.staged
            or args.worktree
            or args.slice_id
            or args.paths_json
            or args.verify_final_commit_from_receipt
            or args.test_gate_evidence
        ):
            raise ValueError("--write-receipt-dir는 다른 검증 모드와 동시에 사용할 수 없습니다.")
        if args.staged and args.worktree:
            raise ValueError("--staged와 --worktree는 동시에 사용할 수 없습니다.")
        if args.all_slices and not args.worktree:
            raise ValueError("--all-slices는 --worktree와 함께 사용해야 합니다.")
        if args.all_slices and args.slice_id:
            raise ValueError("--all-slices와 --slice는 동시에 사용할 수 없습니다.")
        if args.verify_all_artifacts:
            receipt_path = Path(args.verify_all_artifacts)
            receipt = verify_staging_receipt_file(receipt_path)
            payload = verify_staging_receipt_all_artifacts(
                receipt=receipt,
                receipt_path=receipt_path,
                current_plan=plan_all_worktree_slices(ROOT),
                base_dir=ROOT,
            )
        elif args.verify_prestage_from_receipt:
            receipt = verify_staging_receipt_file(Path(args.verify_prestage_from_receipt))
            payload = verify_slice_prestage_ready(
                receipt=receipt,
                slice_id=args.slice_id,
                staged_paths=_git_staged_paths(ROOT),
                current_plan=plan_all_worktree_slices(ROOT),
                base_dir=ROOT,
            )
        elif args.verify_staged_from_receipt:
            receipt = verify_staging_receipt_file(Path(args.verify_staged_from_receipt))
            payload = verify_staged_slice_against_receipt(receipt, args.slice_id, _git_staged_paths(ROOT))
        elif args.verify_commit_ready_from_receipt:
            receipt = verify_staging_receipt_file(Path(args.verify_commit_ready_from_receipt))
            payload = verify_slice_commit_ready_against_receipt(receipt, args.slice_id, _git_staged_paths(ROOT))
        elif args.verify_test_gate_evidence_from_receipt:
            receipt = verify_staging_receipt_file(Path(args.verify_test_gate_evidence_from_receipt))
            evidence_path = Path(args.test_gate_evidence)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            payload = verify_test_gate_evidence_against_receipt(
                receipt,
                args.slice_id,
                evidence,
                base_dir=ROOT,
                evidence_path=evidence_path,
            )
            payload["test_gate_evidence"] = str(evidence_path)
        elif args.verify_final_commit_from_receipt:
            receipt_path = Path(args.verify_final_commit_from_receipt)
            receipt = verify_staging_receipt_file(receipt_path)
            evidence_path = Path(args.test_gate_evidence)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            receipt_artifacts_check = verify_staging_receipt_all_artifacts(
                receipt=receipt,
                receipt_path=receipt_path,
                current_plan=plan_all_worktree_slices(ROOT),
                base_dir=ROOT,
            )
            payload = verify_slice_final_commit_gate_against_receipt(
                receipt=receipt,
                slice_id=args.slice_id,
                staged_paths=_git_staged_paths(ROOT),
                evidence=evidence,
                receipt_artifacts_check=receipt_artifacts_check,
                base_dir=ROOT,
                evidence_path=evidence_path,
            )
            payload["test_gate_evidence_path"] = str(evidence_path)
        elif args.verify_receipt:
            receipt_path = Path(args.verify_receipt)
            receipt = verify_staging_receipt_file(receipt_path)
            if args.against_current_worktree and args.verify_pathspec_files:
                current_check = verify_staging_receipt_against_plan(receipt, plan_all_worktree_slices(ROOT))
                pathspec_check = verify_staging_receipt_pathspec_files(receipt, ROOT)
                runbook_check = verify_staging_receipt_runbook(receipt, receipt_path.parent) if args.verify_runbook else None
                checks = {
                    "receipt_self_verified": True,
                    "receipt_current": current_check["verdict"] == "GO",
                    "pathspec_files_current": pathspec_check["verdict"] == "GO",
                }
                if runbook_check is not None:
                    checks["runbook_current"] = runbook_check["verdict"] == "GO"
                combined_status = (
                    "receipt_current_with_pathspecs_and_runbook"
                    if runbook_check is not None
                    else "receipt_current_with_pathspecs"
                )
                payload = {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "status": combined_status if all(checks.values()) else "receipt_verification_blocked",
                    "verdict": "GO" if all(checks.values()) else "NO_GO",
                    "checks": checks,
                    "receipt_body_sha256": receipt["receipt_body_sha256"],
                    "active_slice_ids": receipt["active_slice_ids"],
                    "current_check": current_check,
                    "pathspec_check": pathspec_check,
                    "runbook_check": runbook_check,
                    "safe_to_stage_all": False,
                }
            elif args.against_current_worktree:
                payload = verify_staging_receipt_against_plan(receipt, plan_all_worktree_slices(ROOT))
            elif args.verify_pathspec_files and args.verify_runbook:
                pathspec_check = verify_staging_receipt_pathspec_files(receipt, ROOT)
                runbook_check = verify_staging_receipt_runbook(receipt, receipt_path.parent)
                checks = {
                    "receipt_self_verified": True,
                    "pathspec_files_current": pathspec_check["verdict"] == "GO",
                    "runbook_current": runbook_check["verdict"] == "GO",
                }
                payload = {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "status": "receipt_pathspecs_and_runbook_current" if all(checks.values()) else "receipt_verification_blocked",
                    "verdict": "GO" if all(checks.values()) else "NO_GO",
                    "checks": checks,
                    "receipt_body_sha256": receipt["receipt_body_sha256"],
                    "active_slice_ids": receipt["active_slice_ids"],
                    "pathspec_check": pathspec_check,
                    "runbook_check": runbook_check,
                    "safe_to_stage_all": False,
                }
            elif args.verify_pathspec_files:
                payload = verify_staging_receipt_pathspec_files(receipt, ROOT)
            elif args.verify_runbook:
                payload = verify_staging_receipt_runbook(receipt, receipt_path.parent)
            else:
                payload = {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "status": "receipt_verified",
                    "verdict": receipt["verdict"],
                    "receipt_json": str(Path(args.verify_receipt)),
                    "receipt_body_sha256": receipt["receipt_body_sha256"],
                    "active_slice_ids": receipt["active_slice_ids"],
                    "safe_to_stage_all": receipt["safe_to_stage_all"],
                }
        elif args.write_receipt_dir:
            payload = write_staging_receipt(Path(args.write_receipt_dir), ROOT)
        elif args.staged:
            if not args.slice_id:
                raise ValueError("--staged는 --slice와 함께 사용해야 합니다.")
            payload = audit_staged_slice(args.slice_id, ROOT, expected_paths_sha256=args.expect_paths_sha256)
        elif args.worktree and args.all_slices:
            payload = plan_all_worktree_slices(ROOT)
        elif args.worktree:
            if not args.slice_id:
                raise ValueError("--worktree는 --slice와 함께 사용해야 합니다.")
            payload = plan_worktree_slice(args.slice_id, ROOT)
        elif args.slice_id and args.paths_json:
            paths = json.loads(Path(args.paths_json).read_text(encoding="utf-8"))
            if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
                raise ValueError("--paths-json은 문자열 배열 JSON이어야 합니다.")
            payload = validate_slice_paths(args.slice_id, paths, source="paths_json")
        elif args.slice_id:
            raise ValueError("--slice 검증은 --staged 또는 --paths-json과 함께 사용해야 합니다.")
        elif args.paths_json:
            paths = json.loads(Path(args.paths_json).read_text(encoding="utf-8"))
            if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
                raise ValueError("--paths-json은 문자열 배열 JSON이어야 합니다.")
            payload = audit_paths(paths)
        else:
            payload = audit_worktree(ROOT)
    except Exception as exc:  # noqa: BLE001 - 운영 점검은 실패 원인을 한 줄로 남긴다.
        logger.error("[FAIL] final commit staging handoff audit: %s", exc)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.write_receipt_dir or args.verify_receipt or args.verify_all_artifacts:
        _log_receipt_summary(payload)
    elif args.worktree and args.all_slices:
        _log_all_worktree_slices_summary(payload)
    elif args.verify_prestage_from_receipt:
        _log_prestage_summary(payload)
    elif args.verify_staged_from_receipt:
        _log_slice_summary(payload)
    elif args.verify_commit_ready_from_receipt:
        _log_commit_ready_summary(payload)
    elif args.verify_test_gate_evidence_from_receipt:
        _log_test_gate_evidence_summary(payload)
    elif args.verify_final_commit_from_receipt:
        _log_final_commit_gate_summary(payload)
    elif args.slice_id:
        if args.worktree:
            _log_worktree_slice_summary(payload)
        else:
            _log_slice_summary(payload)
    else:
        _log_summary(payload)
    return 0 if payload["verdict"] == "GO" else 1


def _receipt_payload(plan: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    slice_receipts = []
    for slice_id in plan["active_slice_ids"]:
        slice_plan = plan["slice_plans"][slice_id]
        pathspec_file = _pathspec_file_display_path(output_dir, slice_id)
        receipt_path = _output_file_display_path(output_dir / RECEIPT_JSON_NAME)
        test_gate_evidence_file = _test_gate_evidence_file_display_path(output_dir, slice_id)
        test_gate_evidence_template_file = _test_gate_evidence_template_display_path(output_dir, slice_id)
        suggested_commit_message = _suggested_commit_message(slice_id)
        test_gate_commands = _suggested_test_gate_commands(slice_id)
        slice_receipts.append(
            {
                "slice_id": slice_id,
                "label": slice_plan["label"],
                "suggested_commit_message": suggested_commit_message,
                "candidate_count": slice_plan["candidate_count"],
                "candidate_paths_sha256": slice_plan["candidate_paths_sha256"],
                "candidate_paths": slice_plan["candidate_paths"],
                "pathspec_file": pathspec_file,
                "stage_command_preview": slice_plan["stage_command_preview"],
                "stage_command_from_pathspec": f"git add --pathspec-from-file={pathspec_file}",
                "commit_command": _commit_command(suggested_commit_message),
                "verify_command_with_digest": slice_plan["verify_command_with_digest"],
                "test_gate_commands": test_gate_commands,
                "test_gate_commands_sha256": _strings_sha256(test_gate_commands),
                "test_gate_evidence_file": test_gate_evidence_file,
                "test_gate_evidence_template_file": test_gate_evidence_template_file,
                "verify_test_gate_evidence_command": (
                    "python scripts/check_final_commit_staging_handoff.py "
                    f"--verify-test-gate-evidence-from-receipt {receipt_path} "
                    f"--slice {slice_id} --test-gate-evidence {test_gate_evidence_file}"
                ),
                "verify_final_commit_gate_command": (
                    "python scripts/check_final_commit_staging_handoff.py "
                    f"--verify-final-commit-from-receipt {receipt_path} "
                    f"--slice {slice_id} --test-gate-evidence {test_gate_evidence_file}"
                ),
            }
        )
    excluded_compact = _compact_entries(plan["excluded_by_default"], RECEIPT_EXCLUDED_SAMPLE_LIMIT)
    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source_schema_version": plan["schema_version"],
        "status": (
            "receipt_complete"
            if plan.get("status") == "all_slices_worktree_complete"
            else "receipt_ready"
            if plan["verdict"] == "GO"
            else "receipt_blocked"
        ),
        "verdict": plan["verdict"],
        "safe_to_stage_all": False,
        "total_paths": plan["total_paths"],
        "active_slice_ids": plan["active_slice_ids"],
        "slice_receipts": slice_receipts,
        "excluded_by_default_count": excluded_compact["count"],
        "excluded_by_default_summary": excluded_compact["summary"],
        "excluded_by_default_truncated": excluded_compact["truncated"],
        "excluded_by_default": excluded_compact["samples"],
        "blockers": [
            {"path": entry["path"], "category": entry["category"], "reasons": entry["reasons"]}
            for entry in plan["blockers"]
        ],
        "manual_review": [
            {"path": entry["path"], "category": entry["category"], "reasons": entry["reasons"]}
            for entry in plan["manual_review"]
        ],
        "next_action": plan["next_action"],
        "receipt_policy": {
            "read_only": True,
            "does_not_run_git_add": True,
            "stage_all_forbidden": True,
            "untracked_paths": "file_level",
            "default_output_excluded_from_source_commit": "dist/",
            "excluded_by_default_sample_limit": RECEIPT_EXCLUDED_SAMPLE_LIMIT,
            "pathspec_files": "per_slice_line_delimited",
            "test_gate_commands": "per_slice_receipt_locked",
            "test_gate_evidence": "per_slice_manual_pass_receipt",
            "test_gate_evidence_refs": f"portable_relative_under_{TEST_GATE_LOG_DIR_NAME}",
            "test_gate_evidence_ref_uniqueness": "per_command_unique",
            "test_gate_evidence_log_content": "contains_expected_command",
        },
    }
    payload["receipt_body_sha256"] = _json_body_sha256(payload)
    return payload


def _verify_staging_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("receipt schema_version이 일치하지 않습니다.")
    if payload.get("status") not in {"receipt_ready", "receipt_complete", "receipt_blocked"}:
        raise ValueError("receipt status가 알 수 없는 값입니다.")
    if payload.get("verdict") not in {"GO", "NO_GO"}:
        raise ValueError("receipt verdict가 알 수 없는 값입니다.")
    if payload.get("safe_to_stage_all") is not False:
        raise ValueError("receipt safe_to_stage_all은 false여야 합니다.")
    expected_body_sha = str(payload.get("receipt_body_sha256") or "")
    if not _looks_like_sha256(expected_body_sha):
        raise ValueError("receipt_body_sha256이 유효하지 않습니다.")
    if _json_body_sha256(payload) != expected_body_sha:
        raise ValueError("receipt_body_sha256이 본문과 일치하지 않습니다.")

    policy = payload.get("receipt_policy")
    if not isinstance(policy, dict):
        raise ValueError("receipt_policy가 없습니다.")
    if policy.get("read_only") is not True:
        raise ValueError("receipt_policy.read_only는 true여야 합니다.")
    if policy.get("does_not_run_git_add") is not True:
        raise ValueError("receipt_policy.does_not_run_git_add는 true여야 합니다.")
    if policy.get("stage_all_forbidden") is not True:
        raise ValueError("receipt_policy.stage_all_forbidden은 true여야 합니다.")
    if policy.get("untracked_paths") != "file_level":
        raise ValueError("receipt_policy.untracked_paths는 file_level이어야 합니다.")
    if policy.get("default_output_excluded_from_source_commit") != "dist/":
        raise ValueError("receipt_policy.default_output_excluded_from_source_commit은 dist/여야 합니다.")
    if policy.get("excluded_by_default_sample_limit") != RECEIPT_EXCLUDED_SAMPLE_LIMIT:
        raise ValueError("receipt_policy.excluded_by_default_sample_limit이 일치하지 않습니다.")
    if policy.get("pathspec_files") != "per_slice_line_delimited":
        raise ValueError("receipt_policy.pathspec_files는 per_slice_line_delimited여야 합니다.")
    if policy.get("test_gate_commands") != "per_slice_receipt_locked":
        raise ValueError("receipt_policy.test_gate_commands는 per_slice_receipt_locked여야 합니다.")
    if policy.get("test_gate_evidence") != "per_slice_manual_pass_receipt":
        raise ValueError("receipt_policy.test_gate_evidence는 per_slice_manual_pass_receipt여야 합니다.")
    if policy.get("test_gate_evidence_refs") != f"portable_relative_under_{TEST_GATE_LOG_DIR_NAME}":
        raise ValueError("receipt_policy.test_gate_evidence_refs가 전용 로그 디렉터리 정책과 일치하지 않습니다.")
    if policy.get("test_gate_evidence_ref_uniqueness") != "per_command_unique":
        raise ValueError("receipt_policy.test_gate_evidence_ref_uniqueness는 per_command_unique여야 합니다.")
    if policy.get("test_gate_evidence_log_content") != "contains_expected_command":
        raise ValueError("receipt_policy.test_gate_evidence_log_content는 contains_expected_command여야 합니다.")

    active_slice_ids = payload.get("active_slice_ids")
    slice_receipts = payload.get("slice_receipts")
    if not isinstance(active_slice_ids, list) or not all(isinstance(item, str) for item in active_slice_ids):
        raise ValueError("active_slice_ids는 문자열 배열이어야 합니다.")
    if not isinstance(slice_receipts, list):
        raise ValueError("slice_receipts는 배열이어야 합니다.")
    if [item.get("slice_id") for item in slice_receipts if isinstance(item, dict)] != active_slice_ids:
        raise ValueError("slice_receipts 순서가 active_slice_ids와 일치하지 않습니다.")

    known_slice_ids = {rule.slice_id for rule in SLICE_RULES}
    for item in slice_receipts:
        if not isinstance(item, dict):
            raise ValueError("slice_receipts 항목은 객체여야 합니다.")
        slice_id = str(item.get("slice_id") or "")
        if slice_id not in known_slice_ids:
            raise ValueError(f"알 수 없는 slice_id입니다: {slice_id}")
        suggested_commit_message = item.get("suggested_commit_message")
        if suggested_commit_message != _suggested_commit_message(slice_id):
            raise ValueError(f"{slice_id} suggested_commit_message가 slice 정책과 일치하지 않습니다.")
        commit_command = str(item.get("commit_command") or "")
        if commit_command != _commit_command(str(suggested_commit_message)):
            raise ValueError(f"{slice_id} commit_command가 suggested_commit_message와 일치하지 않습니다.")
        test_gate_commands = item.get("test_gate_commands")
        if not isinstance(test_gate_commands, list) or not all(
            isinstance(command, str) and command for command in test_gate_commands
        ):
            raise ValueError(f"{slice_id} test_gate_commands는 비어 있지 않은 문자열 배열이어야 합니다.")
        if test_gate_commands != _suggested_test_gate_commands(slice_id):
            raise ValueError(f"{slice_id} test_gate_commands가 slice 정책과 일치하지 않습니다.")
        test_gate_commands_sha = str(item.get("test_gate_commands_sha256") or "")
        if not _looks_like_sha256(test_gate_commands_sha):
            raise ValueError(f"{slice_id} test_gate_commands_sha256이 유효하지 않습니다.")
        if _strings_sha256(test_gate_commands) != test_gate_commands_sha:
            raise ValueError(f"{slice_id} test_gate_commands_sha256이 test_gate_commands와 일치하지 않습니다.")
        evidence_file = str(item.get("test_gate_evidence_file") or "")
        if not evidence_file.endswith(f"{slice_id}.json"):
            raise ValueError(f"{slice_id} test_gate_evidence_file이 slice 전용 파일명이 아닙니다.")
        evidence_template_file = str(item.get("test_gate_evidence_template_file") or "")
        if not evidence_template_file.endswith(f"{slice_id}.template.json"):
            raise ValueError(f"{slice_id} test_gate_evidence_template_file이 slice 전용 파일명이 아닙니다.")
        evidence_verify_command = str(item.get("verify_test_gate_evidence_command") or "")
        if "--verify-test-gate-evidence-from-receipt" not in evidence_verify_command:
            raise ValueError(f"{slice_id} verify_test_gate_evidence_command가 없습니다.")
        if f"--slice {slice_id}" not in evidence_verify_command or evidence_file not in evidence_verify_command:
            raise ValueError(f"{slice_id} verify_test_gate_evidence_command가 slice/evidence 경로와 일치하지 않습니다.")
        final_gate_command = str(item.get("verify_final_commit_gate_command") or "")
        if "--verify-final-commit-from-receipt" not in final_gate_command:
            raise ValueError(f"{slice_id} verify_final_commit_gate_command가 없습니다.")
        if f"--slice {slice_id}" not in final_gate_command or evidence_file not in final_gate_command:
            raise ValueError(f"{slice_id} verify_final_commit_gate_command가 slice/evidence 경로와 일치하지 않습니다.")
        candidate_paths = item.get("candidate_paths")
        if not isinstance(candidate_paths, list) or not all(isinstance(path, str) for path in candidate_paths):
            raise ValueError(f"{slice_id} candidate_paths는 문자열 배열이어야 합니다.")
        if item.get("candidate_count") != len(candidate_paths):
            raise ValueError(f"{slice_id} candidate_count가 candidate_paths 길이와 일치하지 않습니다.")
        expected_paths_sha = str(item.get("candidate_paths_sha256") or "")
        if not _looks_like_sha256(expected_paths_sha):
            raise ValueError(f"{slice_id} candidate_paths_sha256이 유효하지 않습니다.")
        if _paths_sha256(candidate_paths) != expected_paths_sha:
            raise ValueError(f"{slice_id} candidate_paths_sha256이 candidate_paths와 일치하지 않습니다.")
        pathspec_file = str(item.get("pathspec_file") or "")
        if not pathspec_file.endswith(f"{slice_id}.pathspec"):
            raise ValueError(f"{slice_id} pathspec_file이 slice 전용 파일명이 아닙니다.")
        stage_command = str(item.get("stage_command_from_pathspec") or "")
        if "git add --pathspec-from-file=" not in stage_command:
            raise ValueError(f"{slice_id} stage_command_from_pathspec에 pathspec staging 명령이 없습니다.")
        if pathspec_file not in stage_command:
            raise ValueError(f"{slice_id} stage_command_from_pathspec에 pathspec 파일 경로가 없습니다.")
        verify_command = str(item.get("verify_command_with_digest") or "")
        if f"--staged --slice {slice_id}" not in verify_command:
            raise ValueError(f"{slice_id} verify_command_with_digest에 slice 검증 명령이 없습니다.")
        if expected_paths_sha not in verify_command:
            raise ValueError(f"{slice_id} verify_command_with_digest에 candidate digest가 없습니다.")

    excluded_count = payload.get("excluded_by_default_count")
    if not isinstance(excluded_count, int) or excluded_count < 0:
        raise ValueError("excluded_by_default_count는 0 이상 정수여야 합니다.")
    excluded_samples = payload.get("excluded_by_default")
    if not isinstance(excluded_samples, list):
        raise ValueError("excluded_by_default는 배열이어야 합니다.")
    if len(excluded_samples) > RECEIPT_EXCLUDED_SAMPLE_LIMIT:
        raise ValueError("excluded_by_default sample이 너무 많습니다.")
    if excluded_count < len(excluded_samples):
        raise ValueError("excluded_by_default_count가 sample 수보다 작습니다.")
    if payload.get("excluded_by_default_truncated") != (excluded_count > len(excluded_samples)):
        raise ValueError("excluded_by_default_truncated 값이 count/sample과 일치하지 않습니다.")
    excluded_summary = payload.get("excluded_by_default_summary")
    if not isinstance(excluded_summary, dict):
        raise ValueError("excluded_by_default_summary는 객체여야 합니다.")
    if not all(isinstance(key, str) and isinstance(value, int) and value >= 0 for key, value in excluded_summary.items()):
        raise ValueError("excluded_by_default_summary는 category별 0 이상 정수 map이어야 합니다.")
    if sum(excluded_summary.values()) != excluded_count:
        raise ValueError("excluded_by_default_summary 합계가 count와 일치하지 않습니다.")
    for item in excluded_samples:
        if not isinstance(item, dict):
            raise ValueError("excluded_by_default sample 항목은 객체여야 합니다.")
        if not isinstance(item.get("path"), str) or not isinstance(item.get("category"), str):
            raise ValueError("excluded_by_default sample은 path/category 문자열을 가져야 합니다.")
        reasons = item.get("reasons")
        if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
            raise ValueError("excluded_by_default sample reasons는 문자열 배열이어야 합니다.")

    for key in ["blockers", "manual_review"]:
        value = payload.get(key)
        if not isinstance(value, list):
            raise ValueError(f"{key}는 배열이어야 합니다.")


def _receipt_slice_by_id(receipt: dict[str, Any], slice_id: str) -> dict[str, Any] | None:
    slice_receipts = receipt.get("slice_receipts")
    if not isinstance(slice_receipts, list):
        return None
    for item in slice_receipts:
        if isinstance(item, dict) and item.get("slice_id") == slice_id:
            return item
    return None


def _classify_path(path: str) -> dict[str, Any]:
    normalized = _normalize(path)
    parts = tuple(part for part in normalized.split("/") if part)
    name = parts[-1] if parts else normalized

    risk = "candidate"
    category = "source_candidate"
    reasons: list[str] = []

    if _is_forbidden_sensitive(parts, name, normalized):
        risk = "forbidden"
        category = "sensitive_or_forbidden"
        reasons.append("secret/env/key/raw-reply 경로는 stage 금지")
    elif (
        any(part in NOISY_PARTS or part.startswith(NOISY_PART_PREFIXES) for part in parts)
        or name.endswith((".pyc", ".pyo"))
    ):
        risk = "excluded_by_default"
        category = "noisy_generated"
        reasons.append("캐시/임시 산출물은 기본 stage 제외")
    elif ".cambrian" in parts:
        risk = "excluded_by_default"
        category = "runtime_evidence"
        reasons.append(".cambrian runtime evidence는 기본 stage 제외")
    elif parts and parts[0] == "dist":
        risk = "excluded_by_default"
        category = "release_artifact"
        reasons.append("dist 릴리즈 산출물은 source commit에서 기본 제외")

    matched = _matching_slices(normalized)
    if risk == "candidate" and not matched:
        risk = "manual_review"
        category = "unmapped"
        reasons.append("commit slicing plan에 명시 매핑이 없어 수동 검토 필요")

    return {
        "path": normalized,
        "risk": risk,
        "category": category,
        "primary_slice": matched[0]["slice_id"] if matched else None,
        "matched_slices": matched,
        "reasons": reasons,
    }


def _matching_slices(path: str) -> list[dict[str, str]]:
    ranked: list[tuple[int, int, SliceRule]] = []
    for index, rule in enumerate(SLICE_RULES):
        matched = [pattern for pattern in rule.patterns if _matches(path, pattern)]
        if matched:
            ranked.append((max(_pattern_specificity(pattern) for pattern in matched), -index, rule))
    ranked.sort(reverse=True)
    return [{"slice_id": rule.slice_id, "label": rule.label} for _score, _index, rule in ranked]


def _suggested_commit_message(slice_id: str) -> str:
    return SUGGESTED_COMMIT_MESSAGES.get(slice_id, f"docs(release): {slice_id} 정리")


def _suggested_test_gate_commands(slice_id: str) -> list[str]:
    return list(SUGGESTED_TEST_GATE_COMMANDS.get(slice_id, ()))


def _commit_command(message: str) -> str:
    return f'git commit -m "{message}"' if message else ""


def _pattern_specificity(pattern: str) -> int:
    normalized = _normalize(pattern)
    wildcard_penalty = normalized.count("*") * 1000 + normalized.count("?") * 1000
    exact_bonus = 10000 if "*" not in normalized and "?" not in normalized else 0
    return exact_bonus + len(normalized) - wildcard_penalty


def _matches(path: str, pattern: str) -> bool:
    normalized_pattern = _normalize(pattern)
    return fnmatch.fnmatchcase(path, normalized_pattern)


def _is_forbidden_sensitive(parts: tuple[str, ...], name: str, path: str) -> bool:
    lower_name = name.lower()
    lower_path = path.lower()
    if lower_name in FORBIDDEN_EXACT_NAMES:
        return True
    if lower_name.endswith(FORBIDDEN_SUFFIXES):
        return True
    if lower_name.startswith("secret.") or lower_name.startswith("secrets."):
        return True
    if lower_name.startswith("credential.") or lower_name.startswith("credentials."):
        return True
    if any(marker in lower_path for marker in RAW_REPLY_MARKERS):
        return True
    return any(part.lower() == ".env" for part in parts)


def _git_status(root: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        list(GIT_STATUS_ARGS),
        cwd=root,
        text=False,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git status 실패: {stderr}")
    return _parse_porcelain_z(result.stdout)


def _git_staged_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=root,
        text=False,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git diff --cached 실패: {stderr}")
    return [_normalize(chunk) for chunk in result.stdout.decode("utf-8", errors="replace").split("\0") if chunk]


def _parse_porcelain_z(payload: bytes) -> list[dict[str, str]]:
    chunks = [chunk for chunk in payload.decode("utf-8", errors="replace").split("\0") if chunk]
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(chunks):
        item = chunks[index]
        if len(item) < 4:
            index += 1
            continue
        status = item[:2]
        path = item[3:]
        original_path = ""
        if "R" in status or "C" in status:
            original_path = path
            index += 1
            if index < len(chunks):
                path = chunks[index]
        entries.append({"status": status, "path": _normalize(path), "original_path": _normalize(original_path)})
        index += 1
    return entries


def _normalize(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _compact_entries(entries: list[dict[str, Any]], sample_limit: int) -> dict[str, Any]:
    summary: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    for entry in entries:
        category = str(entry.get("category") or "unknown")
        summary[category] = summary.get(category, 0) + 1
        if len(samples) < sample_limit:
            reasons = entry.get("reasons")
            samples.append(
                {
                    "path": str(entry.get("path") or ""),
                    "category": category,
                    "reasons": [str(reason) for reason in reasons] if isinstance(reasons, list) else [],
                }
            )
    return {
        "count": len(entries),
        "summary": dict(sorted(summary.items())),
        "truncated": len(entries) > len(samples),
        "samples": samples,
    }


def _pathspec_file_display_path(output_dir: Path, slice_id: str) -> str:
    path = output_dir / RECEIPT_PATHSPEC_DIR_NAME / f"{slice_id}.pathspec"
    return _output_file_display_path(path)


def _test_gate_evidence_file_display_path(output_dir: Path, slice_id: str) -> str:
    path = output_dir / TEST_GATE_EVIDENCE_DIR_NAME / f"{slice_id}.json"
    return _output_file_display_path(path)


def _test_gate_evidence_template_display_path(output_dir: Path, slice_id: str) -> str:
    path = output_dir / TEST_GATE_EVIDENCE_DIR_NAME / f"{slice_id}.template.json"
    return _output_file_display_path(path)


def _output_file_display_path(path: Path) -> str:
    try:
        display_path = path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        display_path = path.resolve()
    return _normalize(str(display_path))


def _resolve_receipt_path(path: str, base_dir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def _read_pathspec_paths(path: Path) -> list[str]:
    return [_normalize(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_receipt_pathspec_files(output_dir: Path, receipt: dict[str, Any]) -> Path:
    pathspec_dir = output_dir / RECEIPT_PATHSPEC_DIR_NAME
    pathspec_dir.mkdir(parents=True, exist_ok=True)
    for item in receipt["slice_receipts"]:
        slice_id = item["slice_id"]
        paths = item["candidate_paths"]
        body = "\n".join(paths)
        if body:
            body += "\n"
        (pathspec_dir / f"{slice_id}.pathspec").write_text(body, encoding="utf-8")
    return pathspec_dir


def _write_test_gate_evidence_templates(output_dir: Path, receipt: dict[str, Any]) -> Path:
    evidence_dir = output_dir / TEST_GATE_EVIDENCE_DIR_NAME
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for item in receipt["slice_receipts"]:
        slice_id = item["slice_id"]
        template = _test_gate_evidence_template_payload(receipt, item)
        (evidence_dir / f"{slice_id}.template.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return evidence_dir


def _test_gate_evidence_template_payload(receipt: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": TEST_GATE_EVIDENCE_SCHEMA_VERSION,
        "status": "PENDING",
        "verdict": "NO_GO",
        "slice_id": item["slice_id"],
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "candidate_paths_sha256": item["candidate_paths_sha256"],
        "test_gate_commands_sha256": item["test_gate_commands_sha256"],
        "test_gate_commands": item["test_gate_commands"],
        "command_results": [
            {
                "command": command,
                "status": "PENDING",
                "exit_code": None,
                "evidence_ref": f"dist/{TEST_GATE_LOG_DIR_NAME}/{item['slice_id']}-{index}.log",
                "evidence_sha256": "",
            }
            for index, command in enumerate(item["test_gate_commands"])
        ],
        "notes": "",
    }


def _stage_command_preview(paths: list[str]) -> str:
    if not paths:
        return ""
    quoted = " ".join(f'"{path}"' for path in paths)
    return f"git add -- {quoted}"


def _paths_sha256(paths: list[str]) -> str:
    normalized = sorted(_normalize(path) for path in paths)
    body = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _strings_sha256(values: list[str]) -> str:
    body = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_evidence_ref_file(
    evidence_ref: Any,
    evidence_sha256: Any,
    expected_command: str,
    base_dir: Path,
) -> dict[str, Any]:
    normalized_ref = _normalize(str(evidence_ref).strip()) if isinstance(evidence_ref, str) else ""
    expected_sha = str(evidence_sha256 or "").strip() if isinstance(evidence_sha256, str) else ""
    result: dict[str, Any] = {
        "evidence_sha256": expected_sha or None,
        "evidence_sha256_present": _looks_like_sha256(expected_sha),
        "evidence_ref_local_file": False,
        "evidence_ref_portable": False,
        "evidence_ref_allowed_log_dir": False,
        "evidence_ref_safe": False,
        "evidence_file_exists": False,
        "evidence_file": None,
        "actual_evidence_sha256": None,
        "evidence_sha256_matched": False,
        "evidence_file_contains_command": False,
    }
    if not normalized_ref:
        return result
    if normalized_ref.startswith(("http://", "https://")):
        return result
    if Path(normalized_ref).is_absolute():
        return result
    result["evidence_ref_portable"] = True
    result["evidence_ref_allowed_log_dir"] = _is_allowed_test_gate_log_ref(normalized_ref)
    if not result["evidence_ref_allowed_log_dir"]:
        return result

    evidence_path = _resolve_receipt_path(normalized_ref, base_dir)
    try:
        resolved_base = base_dir.resolve()
        resolved_path = evidence_path.resolve()
        resolved_path.relative_to(resolved_base)
    except ValueError:
        result["evidence_file"] = str(evidence_path)
        return result

    path_entry = _classify_path(normalized_ref)
    result["evidence_ref_local_file"] = True
    result["evidence_ref_safe"] = path_entry["risk"] != "forbidden"
    result["evidence_file"] = _normalize(str(resolved_path))
    if not result["evidence_ref_safe"] or not evidence_path.is_file():
        return result

    result["evidence_file_exists"] = True
    actual_sha = _file_sha256(evidence_path)
    result["actual_evidence_sha256"] = actual_sha
    result["evidence_sha256_matched"] = result["evidence_sha256_present"] and actual_sha == expected_sha
    result["evidence_file_contains_command"] = _file_contains_text(evidence_path, expected_command)
    return result


def _file_contains_text(path: Path, expected_text: str) -> bool:
    if not expected_text:
        return False
    try:
        return expected_text in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _is_allowed_test_gate_log_ref(path: str) -> bool:
    parts = tuple(part for part in _normalize(path).split("/") if part)
    if not parts:
        return False
    return parts[0] == TEST_GATE_LOG_DIR_NAME or parts[:2] == ("dist", TEST_GATE_LOG_DIR_NAME)


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _json_body_sha256(payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.pop("receipt_body_sha256", None)
    serialized = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _receipt_markdown(receipt: dict[str, Any]) -> str:
    lines = [
        "# Final Commit Staging Receipt",
        "",
        "## Summary",
        "",
        f"- schema: `{receipt['schema_version']}`",
        f"- status: `{receipt['status']}`",
        f"- verdict: `{receipt['verdict']}`",
        f"- safe_to_stage_all: `{receipt['safe_to_stage_all']}`",
        f"- total_paths: `{receipt['total_paths']}`",
        f"- receipt_body_sha256: `{receipt['receipt_body_sha256']}`",
        "",
        "## Slice Receipts",
        "",
    ]
    for item in receipt["slice_receipts"]:
        lines.extend(
            [
                f"### {item['slice_id']}",
                "",
                f"- label: {item['label']}",
                f"- suggested_commit_message: `{item['suggested_commit_message']}`",
                f"- candidate_count: `{item['candidate_count']}`",
                f"- candidate_paths_sha256: `{item['candidate_paths_sha256']}`",
                f"- test_gate_commands_sha256: `{item['test_gate_commands_sha256']}`",
                f"- pathspec_file: `{item['pathspec_file']}`",
                f"- test_gate_evidence_template_file: `{item['test_gate_evidence_template_file']}`",
                f"- test_gate_evidence_file: `{item['test_gate_evidence_file']}`",
                f"- verify_final_commit_gate_command: `{item['verify_final_commit_gate_command']}`",
                "- stage from pathspec:",
                "",
                "```bash",
                item["stage_command_from_pathspec"],
                "```",
                "",
                "- verify:",
                "",
                "```bash",
                item["verify_command_with_digest"],
                "```",
                "",
                "- test gate before commit:",
                "",
                "```bash",
                *item["test_gate_commands"],
                "```",
                "",
                "- verify test gate evidence before commit:",
                "",
                "```bash",
                item["verify_test_gate_evidence_command"],
                "```",
                "",
                "- verify final commit integrated gate:",
                "",
                "```bash",
                item["verify_final_commit_gate_command"],
                "```",
                "",
                "- commit after staged verification:",
                "",
                "```bash",
                item["commit_command"],
                "```",
                "",
                "- candidate_paths:",
                "",
            ]
        )
        for path in item["candidate_paths"]:
            lines.append(f"  - `{path}`")
        lines.append("")
    lines.extend(
        [
            "## Excluded By Default",
            "",
            f"- total_count: `{receipt['excluded_by_default_count']}`",
            f"- sample_count: `{len(receipt['excluded_by_default'])}`",
            f"- sample_limit: `{receipt['receipt_policy']['excluded_by_default_sample_limit']}`",
            f"- truncated: `{receipt['excluded_by_default_truncated']}`",
            "- summary:",
            "",
        ]
    )
    if receipt["excluded_by_default_summary"]:
        for category, count in receipt["excluded_by_default_summary"].items():
            lines.append(f"  - `{category}`: `{count}`")
    else:
        lines.append("  - none")
    lines.extend(["", "- samples:", ""])
    if receipt["excluded_by_default"]:
        for item in receipt["excluded_by_default"]:
            lines.append(f"  - `{item['path']}` ({item['category']})")
    else:
        lines.append("  - none")
    lines.extend(
        [
            "",
            "## Blockers",
            "",
        ]
    )
    if receipt["blockers"]:
        for item in receipt["blockers"]:
            lines.append(f"- `{item['path']}` ({item['category']})")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Manual Review",
            "",
        ]
    )
    if receipt["manual_review"]:
        for item in receipt["manual_review"]:
            lines.append(f"- `{item['path']}` ({item['category']})")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Next Action",
            "",
            receipt["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def _receipt_runbook_markdown(receipt: dict[str, Any], output_dir: Path) -> str:
    receipt_path = _output_file_display_path(output_dir / RECEIPT_JSON_NAME)
    lines = [
        "# Final Commit Staging Runbook",
        "",
        "## Guardrails",
        "",
        "- 이 runbook은 명령 순서를 기록할 뿐 `git add`, `git commit`, `git push`를 실행하지 않는다.",
        "- 한 번에 하나의 slice만 stage한다.",
        "- 각 slice의 `slice_prestage_ready`가 PASS일 때만 pathspec staging을 진행한다.",
        "- 각 commit 전에 `receipt_staged_slice_ready`와 `git diff --cached --name-only`를 확인한다.",
        "- 각 commit 전에 receipt에 잠긴 slice별 `test_gate_commands`를 실행한다.",
        "- 각 commit 전에 slice별 test gate evidence JSON을 PASS 상태로 검증한다.",
        "- final commit integrated gate must return `slice_final_commit_gate_ready` before commit.",
        "",
        "## Global Preflight",
        "",
        "```bash",
        f"python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts {receipt_path}",
        f"python scripts/check_final_commit_staging_handoff.py --verify-receipt {receipt_path}",
        f"python scripts/check_final_commit_staging_handoff.py --verify-receipt {receipt_path} --verify-pathspec-files",
        f"python scripts/check_final_commit_staging_handoff.py --verify-receipt {receipt_path} --against-current-worktree --verify-pathspec-files",
        "```",
        "",
        "## Slice Commands",
        "",
    ]
    for item in receipt["slice_receipts"]:
        slice_id = item["slice_id"]
        lines.extend(
            [
                f"### {slice_id}",
                "",
                f"- label: {item['label']}",
                f"- suggested_commit_message: `{item['suggested_commit_message']}`",
                f"- candidate_count: `{item['candidate_count']}`",
                f"- candidate_paths_sha256: `{item['candidate_paths_sha256']}`",
                f"- test_gate_commands_sha256: `{item['test_gate_commands_sha256']}`",
                f"- test_gate_evidence_template_file: `{item['test_gate_evidence_template_file']}`",
                f"- test_gate_evidence_file: `{item['test_gate_evidence_file']}`",
                "",
                "```bash",
                f"python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt {receipt_path} --slice {slice_id}",
                item["stage_command_from_pathspec"],
                item["verify_command_with_digest"],
                f"python scripts/check_final_commit_staging_handoff.py --verify-staged-from-receipt {receipt_path} --slice {slice_id}",
                f"python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt {receipt_path} --slice {slice_id}",
                "git diff --cached --stat",
                "git diff --cached --name-only",
                *item["test_gate_commands"],
                item["verify_test_gate_evidence_command"],
                item["verify_final_commit_gate_command"],
                item["commit_command"],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Stop Conditions",
            "",
            "- `slice_prestage_ready`, `slice_stage_ready`, or `receipt_staged_slice_ready`가 아니면 commit하지 않는다.",
            "- slice별 `test_gate_commands`가 실패하면 commit하지 않는다.",
            "- slice별 test gate evidence가 `test_gate_evidence_ready`가 아니면 commit하지 않는다.",
            "- staged diff에 `.env`, secret, raw external AI reply, private data, 또는 의도하지 않은 `.cambrian/` 파일이 있으면 중단한다.",
            "- receipt가 `receipt_all_artifacts_current`가 아니면 receipt와 pathspec을 재생성한다.",
            "",
        ]
    )
    return "\n".join(lines)


def _log_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit staging handoff audit" if payload["verdict"] == "GO" else "[FAIL] final commit staging handoff audit")
    logger.info("status          : %s", payload["status"])
    logger.info("total paths     : %s", payload["total_paths"])
    logger.info("slice groups    : %s", ", ".join(payload["slice_ids"]) or "none")
    logger.info("blockers        : %s", len(payload["blockers"]))
    logger.info("excluded default: %s", len(payload["excluded_by_default"]))
    logger.info("manual review   : %s", len(payload["manual_review"]))
    logger.info("safe to stage all: %s", payload["safe_to_stage_all"])
    logger.info("next action     : %s", payload["next_action"])


def _log_slice_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit slice stage audit" if payload["verdict"] == "GO" else "[FAIL] final commit slice stage audit")
    logger.info("slice           : %s", payload["slice_id"])
    logger.info("status          : %s", payload["status"])
    logger.info("total paths     : %s", payload["total_paths"])
    logger.info("accepted paths  : %s", len(payload["accepted_paths"]))
    logger.info("accepted sha256 : %s", payload["accepted_paths_sha256"])
    if payload.get("expected_paths_sha256"):
        logger.info("expected sha256 : %s", payload["expected_paths_sha256"])
    logger.info("blockers        : %s", len(payload["blockers"]))
    logger.info("excluded default: %s", len(payload["excluded_by_default"]))
    logger.info("manual review   : %s", len(payload["manual_review"]))
    logger.info("wrong slice     : %s", len(payload["wrong_slice"]))


def _log_prestage_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit slice prestage audit" if payload["verdict"] == "GO" else "[FAIL] final commit slice prestage audit")
    logger.info("slice           : %s", payload["slice_id"])
    logger.info("status          : %s", payload["status"])
    logger.info("candidate paths : %s", payload["receipt_candidate_count"])
    logger.info("candidate sha256: %s", payload["receipt_candidate_paths_sha256"])
    logger.info("pathspec file   : %s", payload["pathspec_file"])
    logger.info("staged existing : %s", len(payload["existing_staged_paths"]))
    logger.info("stage command   : %s", payload["stage_command_from_pathspec"])
    logger.info("verify command  : %s", payload["receipt_backed_staged_verify_command"])
    logger.info("test gate sha256: %s", payload["test_gate_commands_sha256"])


def _log_commit_ready_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit slice commit-ready audit" if payload["verdict"] == "GO" else "[FAIL] final commit slice commit-ready audit")
    logger.info("slice           : %s", payload["slice_id"])
    logger.info("status          : %s", payload["status"])
    logger.info("accepted paths  : %s", len(payload["accepted_paths"]))
    logger.info("accepted sha256 : %s", payload["accepted_paths_sha256"])
    logger.info("test gate sha256: %s", payload["test_gate_commands_sha256"])
    for command in payload.get("test_gate_commands") or []:
        logger.info("test gate cmd   : %s", command)
    logger.info("commit message  : %s", payload["suggested_commit_message"])
    logger.info("commit command  : %s", payload["commit_command"])


def _log_test_gate_evidence_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit test gate evidence" if payload["verdict"] == "GO" else "[FAIL] final commit test gate evidence")
    logger.info("slice           : %s", payload["slice_id"])
    logger.info("status          : %s", payload["status"])
    logger.info("body sha256     : %s", payload["receipt_body_sha256"])
    logger.info("test gate sha256: %s", payload["test_gate_commands_sha256"])
    if payload.get("test_gate_evidence"):
        logger.info("evidence       : %s", payload["test_gate_evidence"])
    logger.info("commands        : %s", len(payload["test_gate_commands"]))


def _log_final_commit_gate_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit integrated gate" if payload["verdict"] == "GO" else "[FAIL] final commit integrated gate")
    logger.info("slice           : %s", payload["slice_id"])
    logger.info("status          : %s", payload["status"])
    logger.info("accepted paths  : %s", len(payload["accepted_paths"]))
    logger.info("accepted sha256 : %s", payload["accepted_paths_sha256"])
    logger.info("test gate sha256: %s", payload["test_gate_commands_sha256"])
    logger.info("evidence file   : %s", payload["actual_test_gate_evidence_file"])
    logger.info("commit message  : %s", payload["suggested_commit_message"])
    logger.info("commit command  : %s", payload["commit_command"])
    logger.info("user confirm    : %s", payload["manual_commit_requires_user_confirmation"])
    policy = payload.get("recovery_execution_policy") or {}
    logger.info(
        "recovery policy: suggestions_only=%s executes_git_add=%s executes_git_commit=%s executes_git_push=%s",
        policy.get("recovery_commands_are_suggestions_only"),
        policy.get("script_executes_git_add"),
        policy.get("script_executes_git_commit"),
        policy.get("script_executes_git_push"),
    )
    for reason in payload.get("blocking_reasons") or []:
        logger.info("blocking reason: %s", reason)
    for section, failed_checks in (payload.get("blocking_details") or {}).items():
        logger.info("blocking detail: %s=%s", section, ", ".join(failed_checks))
    summary = payload.get("recovery_command_summary") or {}
    logger.info(
        "recovery summary: total=%s index_mutations=%s dist_writes=%s test_runs=%s",
        summary.get("total_count", 0),
        summary.get("mutates_git_index_count", 0),
        summary.get("writes_dist_artifacts_count", 0),
        summary.get("runs_tests_count", 0),
    )
    for step in payload.get("recovery_command_plan") or []:
        logger.info(
            "recovery step  : %s/%s%s",
            step["phase"],
            step["command_kind"],
            " index-mutating" if step["mutates_git_index"] else "",
        )
    for command in payload.get("recovery_commands") or []:
        logger.info("recovery cmd   : %s", command)
    logger.info("next action     : %s", payload["next_action"])


def _log_worktree_slice_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit worktree slice plan" if payload["verdict"] == "GO" else "[FAIL] final commit worktree slice plan")
    logger.info("slice           : %s", payload["slice_id"])
    logger.info("status          : %s", payload["status"])
    logger.info("candidate paths : %s", payload["candidate_count"])
    logger.info("candidate sha256: %s", payload["candidate_paths_sha256"])
    logger.info("blockers        : %s", len(payload["blockers"]))
    logger.info("excluded default: %s", len(payload["excluded_by_default"]))
    logger.info("manual review   : %s", len(payload["manual_review"]))
    logger.info("other slices    : %s", payload["other_slice_counts"])
    logger.info("verify command  : %s", payload["verify_command"])
    logger.info("verify digest   : %s", payload["verify_command_with_digest"])


def _log_all_worktree_slices_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit all-slices worktree plan" if payload["verdict"] == "GO" else "[FAIL] final commit all-slices worktree plan")
    logger.info("status          : %s", payload["status"])
    logger.info("total paths     : %s", payload["total_paths"])
    logger.info("active slices   : %s", ", ".join(payload["active_slice_ids"]) or "none")
    logger.info("blockers        : %s", len(payload["blockers"]))
    logger.info("excluded default: %s", len(payload["excluded_by_default"]))
    logger.info("manual review   : %s", len(payload["manual_review"]))
    logger.info("safe to stage all: %s", payload["safe_to_stage_all"])
    for slice_id in payload["active_slice_ids"]:
        plan = payload["slice_plans"][slice_id]
        logger.info("%s: %s candidate paths sha256=%s", slice_id, plan["candidate_count"], plan["candidate_paths_sha256"])
    logger.info("next action     : %s", payload["next_action"])


def _log_receipt_summary(payload: dict[str, Any]) -> None:
    logger.info("[PASS] final commit staging receipt" if payload["verdict"] == "GO" else "[FAIL] final commit staging receipt")
    logger.info("status          : %s", payload["status"])
    if payload.get("receipt_json"):
        logger.info("json            : %s", payload["receipt_json"])
    if payload.get("receipt_md"):
        logger.info("markdown        : %s", payload["receipt_md"])
    if payload.get("receipt_runbook"):
        logger.info("runbook         : %s", payload["receipt_runbook"])
    if payload.get("pathspec_dir"):
        logger.info("pathspec dir    : %s", payload["pathspec_dir"])
    if payload.get("test_gate_evidence_template_dir"):
        logger.info("evidence tpl dir: %s", payload["test_gate_evidence_template_dir"])
    logger.info("body sha256     : %s", payload["receipt_body_sha256"])
    logger.info("active slices   : %s", ", ".join(payload["active_slice_ids"]) or "none")
    if payload.get("current_active_slice_ids"):
        logger.info("current slices  : %s", ", ".join(payload["current_active_slice_ids"]) or "none")
    if payload.get("pathspec_checks"):
        matched_count = sum(
            1
            for item in payload["pathspec_checks"].values()
            if item["pathspec_file_exists"]
            and item["candidate_count_matched"]
            and item["candidate_paths_matched"]
            and item["candidate_paths_sha256_matched"]
        )
        logger.info("pathspec files  : %s/%s current", matched_count, len(payload["pathspec_checks"]))
    if payload.get("pathspec_check"):
        logger.info("pathspec status : %s", payload["pathspec_check"]["status"])
    if payload.get("runbook_check"):
        logger.info("runbook status  : %s", payload["runbook_check"]["status"])
    elif payload.get("receipt_runbook") and payload.get("actual_runbook_sha256"):
        logger.info("runbook sha256  : %s", payload["actual_runbook_sha256"])
    if payload.get("evidence_template_check"):
        logger.info("evidence status : %s", payload["evidence_template_check"]["status"])
    logger.info("safe to stage all: %s", payload["safe_to_stage_all"])


if __name__ == "__main__":
    raise SystemExit(main())
