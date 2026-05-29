import hashlib
import json
from pathlib import Path

from scripts.check_final_commit_staging_handoff import (
    GIT_STATUS_ARGS,
    RECEIPT_EXCLUDED_SAMPLE_LIMIT,
    audit_paths,
    plan_all_slice_paths,
    plan_slice_paths,
    validate_slice_paths,
    verify_slice_final_commit_gate_against_receipt,
    verify_slice_commit_ready_against_receipt,
    verify_slice_prestage_ready,
    verify_staged_slice_against_receipt,
    verify_test_gate_evidence_against_receipt,
    verify_staging_receipt_against_plan,
    verify_staging_receipt_all_artifacts,
    verify_staging_receipt_file,
    verify_staging_receipt_pathspec_files,
    verify_staging_receipt_runbook,
    verify_test_gate_evidence_templates,
    write_staging_receipt_from_plan,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _receipt_body_sha256(payload: dict) -> str:
    body = dict(payload)
    body.pop("receipt_body_sha256", None)
    serialized = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_final_commit_staging_handoff_exists_and_lists_all_slices() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "Final Commit Staging Handoff",
        "Slice 1: Packaging RC Runtime",
        "Slice 2: AI Company Auto Runtime",
        "Slice 3: Conversational Harness, Workforce, Skill System",
        "Slice 4: Pack, Template, Benchmark Advanced Surfaces",
        "Slice 5: Launch, Pilot, Release Docs",
        "Slice 6: Web And Tools",
        "Slice 7: Runtime Evidence Archive summary",
    ]:
        assert phrase in text


def test_final_commit_staging_handoff_records_latest_release_gate_and_policy() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "release-gate-20260513-142945",
        "Verdict: GO",
        "Do not stage all files at once.",
        "python scripts/check_final_commit_staging_handoff.py --json",
        "python scripts/check_final_commit_staging_handoff.py --worktree --all-slices --json",
        "python scripts/check_final_commit_staging_handoff.py --write-receipt-dir dist",
        "python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json",
        "python scripts/check_final_commit_staging_handoff.py --verify-receipt",
        "python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --verify-pathspec-files",
        "python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --verify-runbook",
        "python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --against-current-worktree",
        "python scripts/check_final_commit_staging_handoff.py --verify-receipt dist/final-commit-staging-receipt.json --against-current-worktree --verify-pathspec-files --verify-runbook",
        "python scripts/check_final_commit_staging_handoff.py --verify-prestage-from-receipt",
        "python scripts/check_final_commit_staging_handoff.py --verify-staged-from-receipt",
        "python scripts/check_final_commit_staging_handoff.py --verify-commit-ready-from-receipt",
        "python scripts/check_final_commit_staging_handoff.py --verify-test-gate-evidence-from-receipt",
        "python scripts/check_final_commit_staging_handoff.py --verify-final-commit-from-receipt",
        "blocking_reasons",
        "blocking_details",
        "recovery_commands",
        "recovery_command_plan",
        "recovery_command_summary",
        "recovery_execution_policy",
        "script_executes_recovery_commands",
        "script_executes_git_add",
        "index_mutation_requires_manual_user_confirmation",
        "python scripts/check_final_commit_staging_handoff.py --worktree --slice",
        "python scripts/check_final_commit_staging_handoff.py --staged --slice",
        "dist/final-commit-staging-runbook.md",
        "dist/final-commit-test-gate-evidence/",
        "receipt_test_gate_evidence_templates_current",
        "test_gate_evidence_ready",
        "test_gate_evidence_file",
        "evidence_ref",
        "evidence_sha256",
        "dist/final-commit-test-gate-logs/",
        "git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec",
        "--untracked-files=all",
        "excluded_by_default_count",
        "excluded_by_default_summary",
        "git diff --cached --stat",
        "release_gate_go",
        "Do not create a tag from this handoff alone.",
        "Final staging receipt body sha256: b7917cffb0416a2e2d84a7c3fc68e82ca7b53f80f6539fe7a53acd907706f2e2",
        "Manual review entries: 0",
        "Excluded-by-default entries: 0",
    ]:
        assert phrase in text


def test_final_commit_staging_handoff_has_slice_specific_gates() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "python scripts/smoke_installed_wheel.py",
        "tests/test_auto_runtime_slice_ready.py",
        "tests/test_harness_workforce_skill_slice_ready.py",
        "tests/test_pack_template_benchmark_slice_ready.py",
        "tests/test_dogfood_runbook.py",
        "tests/test_launch_pilot_release_docs_slice_ready.py",
        "tests/test_web_tools_slice_ready.py",
        "tests/test_runtime_evidence_archive_slice_ready.py",
    ]:
        assert phrase in text


def test_final_commit_staging_handoff_excludes_sensitive_and_noisy_files() -> None:
    text = _read("docs/release/FINAL_COMMIT_STAGING_HANDOFF.md")

    for phrase in [
        "full `.cambrian/` runtime tree",
        "raw external AI replies",
        "private project paths",
        ".env or secret files",
        "pycache directories",
        "tools/__pycache__/",
    ]:
        assert phrase in text


def test_final_commit_staging_uses_file_level_untracked_status() -> None:
    assert GIT_STATUS_ARGS == ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all")


def test_rc_checklist_links_final_commit_staging_handoff_gate() -> None:
    checklist = _read("docs/release/RC_CHECKLIST.md")

    for phrase in [
        "Final Commit Staging Handoff Gate",
        "docs/release/FINAL_COMMIT_STAGING_HANDOFF.md",
        "stage and commit one slice at a time",
        "latest auto release gate is GO",
        "compacts `excluded_by_default`",
        "dist/final-commit-staging-pathspecs/",
        "receipt_pathspec_files_current",
        "receipt_runbook_current",
        "receipt_all_artifacts_current",
        "receipt_current_with_pathspecs_and_runbook",
        "slice_prestage_ready",
        "slice_commit_ready",
        "slice_final_commit_gate_ready",
        "blocking_reasons",
        "blocking_details",
        "recovery_commands",
        "recovery_command_plan",
        "recovery_command_summary",
        "recovery_execution_policy",
        "script_executes_recovery_commands",
        "script_executes_git_add",
        "index_mutation_requires_manual_user_confirmation",
        "receipt-locked suggested commit message",
        "slice-specific prestage, stage, staged-verify, and test gate commands",
        "test_gate_commands",
        "receipt_test_gate_evidence_templates_current",
        "test_gate_evidence_ready",
        "slice_final_commit_gate_ready",
        "test_gate_evidence_file",
        "evidence_ref",
        "evidence_sha256",
        "dist/final-commit-test-gate-logs/",
        "git add --pathspec-from-file=dist/final-commit-staging-pathspecs/<slice_id>.pathspec",
        "git diff --cached --stat",
    ]:
        assert phrase in checklist


def test_final_commit_staging_audit_classifies_slices_and_exclusions() -> None:
    payload = audit_paths(
        [
            "engine/project_evolution.py",
            "docs/product/12_HARNESS_ENGINEERING_SYSTEM.md",
            "engine/cli.py",
            "demo/src/example.py",
            "tests/test_agent_platform.py",
            "tests/test_bridge.py",
            "engine/project_bridge.py",
            "engine/project_company_layer.py",
            "engine/project_mission.py",
            "engine/project_mode.py",
            "tests/test_auto_mission_control.py",
            "tests/test_company_layer.py",
            "tests/test_project_mode.py",
            "docs/product/18_AI_REPLY_INGEST_CONTRACT.md",
            "docs/product/19_JOB_VALIDATE_TRUST_GATE.md",
            "docs/product/46_TRUE_HARNESS_CONTRACT.md",
            "ai_reply_patch_candidate.yaml",
            "tests/fixtures/one_good_harness/python_auth_service/src/auth_service.py",
            "CONTEXT_INDEX.md",
            "scripts/check_cambrian_install_kit_send_ready.py",
            "scripts/dogfood_auth_bug_run.py",
            "scripts/prepare_pypi_release.py",
            "tests/test_cambrian_install_kit.py",
            "tests/test_dogfood_runbook.py",
            "README.md",
            ".gitignore",
            "tests/conftest.py",
            "web/index.html",
            "docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md",
            ".cambrian/auto/report.yaml",
            "tools/__pycache__/generate_web_catalog.cpython-312.pyc",
            ".pytest-basetemp-browser-flow-real/test/example.json",
        ]
    )

    by_path = {entry["path"]: entry for entry in payload["entries"]}

    assert payload["verdict"] == "GO"
    assert payload["safe_to_stage_all"] is False
    assert by_path["engine/project_evolution.py"]["primary_slice"] == "slice_3_harness_workforce_skill"
    assert (
        by_path["docs/product/12_HARNESS_ENGINEERING_SYSTEM.md"]["primary_slice"]
        == "slice_3_harness_workforce_skill"
    )
    assert by_path["engine/cli.py"]["primary_slice"] == "slice_4_pack_template_benchmark"
    assert by_path["demo/src/example.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["tests/test_agent_platform.py"]["primary_slice"] == "slice_4_pack_template_benchmark"
    assert by_path["tests/test_bridge.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["engine/project_bridge.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["engine/project_company_layer.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["engine/project_mission.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["engine/project_mode.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["tests/test_auto_mission_control.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["tests/test_company_layer.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert by_path["tests/test_project_mode.py"]["primary_slice"] == "slice_2_ai_company_auto_runtime"
    assert (
        by_path["docs/product/18_AI_REPLY_INGEST_CONTRACT.md"]["primary_slice"]
        == "slice_3_harness_workforce_skill"
    )
    assert (
        by_path["docs/product/19_JOB_VALIDATE_TRUST_GATE.md"]["primary_slice"]
        == "slice_3_harness_workforce_skill"
    )
    assert (
        by_path["docs/product/46_TRUE_HARNESS_CONTRACT.md"]["primary_slice"]
        == "slice_3_harness_workforce_skill"
    )
    assert by_path["ai_reply_patch_candidate.yaml"]["primary_slice"] == "slice_3_harness_workforce_skill"
    assert (
        by_path["tests/fixtures/one_good_harness/python_auth_service/src/auth_service.py"]["primary_slice"]
        == "slice_3_harness_workforce_skill"
    )
    assert by_path["CONTEXT_INDEX.md"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["scripts/check_cambrian_install_kit_send_ready.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["scripts/dogfood_auth_bug_run.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["scripts/prepare_pypi_release.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["tests/test_cambrian_install_kit.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["tests/test_dogfood_runbook.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["README.md"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path[".gitignore"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["tests/conftest.py"]["primary_slice"] == "slice_5_launch_pilot_release_docs"
    assert by_path["web/index.html"]["primary_slice"] == "slice_6_web_and_tools"
    assert (
        by_path["docs/release/RUNTIME_EVIDENCE_ARCHIVE_SLICE_READY.md"]["primary_slice"]
        == "slice_7_runtime_evidence_archive"
    )
    assert by_path[".cambrian/auto/report.yaml"]["risk"] == "excluded_by_default"
    assert by_path[".cambrian/auto/report.yaml"]["category"] == "runtime_evidence"
    assert by_path["tools/__pycache__/generate_web_catalog.cpython-312.pyc"]["risk"] == "excluded_by_default"
    assert by_path[".pytest-basetemp-browser-flow-real/test/example.json"]["risk"] == "excluded_by_default"
    assert by_path[".pytest-basetemp-browser-flow-real/test/example.json"]["category"] == "noisy_generated"
    assert payload["checks"]["runtime_evidence_excluded_by_default"] is True


def test_final_commit_staging_audit_blocks_sensitive_paths() -> None:
    payload = audit_paths([".env", "docs/release/FINAL_COMMIT_STAGING_HANDOFF.md"])

    assert payload["verdict"] == "NO_GO"
    assert payload["status"] == "blocked"
    assert payload["blockers"][0]["path"] == ".env"
    assert payload["blockers"][0]["risk"] == "forbidden"


def test_final_commit_slice_stage_audit_accepts_single_slice_paths() -> None:
    payload = validate_slice_paths(
        "slice_3_harness_workforce_skill",
        [
            "engine/project_evolution.py",
            "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md",
            "tests/test_skill_evolution.py",
        ],
    )

    assert payload["verdict"] == "GO"
    assert payload["status"] == "slice_stage_ready"
    assert payload["checks"]["no_cross_slice_paths"] is True
    assert payload["accepted_paths"] == [
        "engine/project_evolution.py",
        "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md",
        "tests/test_skill_evolution.py",
    ]
    assert len(payload["accepted_paths_sha256"]) == 64
    assert payload["wrong_slice"] == []

    locked = validate_slice_paths(
        "slice_3_harness_workforce_skill",
        [
            "tests/test_skill_evolution.py",
            "engine/project_evolution.py",
            "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md",
        ],
        expected_paths_sha256=payload["accepted_paths_sha256"],
    )
    assert locked["verdict"] == "GO"
    assert locked["checks"]["expected_paths_sha256_matched"] is True


def test_final_commit_slice_stage_audit_blocks_cross_slice_and_excluded_paths() -> None:
    payload = validate_slice_paths(
        "slice_3_harness_workforce_skill",
        [
            "engine/project_evolution.py",
            "web/index.html",
            ".cambrian/auto/report.yaml",
        ],
    )

    assert payload["verdict"] == "NO_GO"
    assert payload["status"] == "slice_stage_blocked"
    assert payload["checks"]["no_cross_slice_paths"] is False
    assert payload["checks"]["no_excluded_default_paths"] is False
    assert payload["wrong_slice"][0]["path"] == "web/index.html"
    assert payload["wrong_slice"][0]["primary_slice"] == "slice_6_web_and_tools"
    assert payload["excluded_by_default"][0]["path"] == ".cambrian/auto/report.yaml"


def test_final_commit_slice_stage_audit_blocks_digest_mismatch() -> None:
    payload = validate_slice_paths(
        "slice_3_harness_workforce_skill",
        ["engine/project_evolution.py"],
        expected_paths_sha256="0" * 64,
    )

    assert payload["verdict"] == "NO_GO"
    assert payload["checks"]["expected_paths_sha256_matched"] is False
    assert payload["expected_paths_sha256"] == "0" * 64
    assert len(payload["accepted_paths_sha256"]) == 64


def test_final_commit_worktree_slice_plan_lists_candidate_paths_and_verify_command() -> None:
    payload = plan_slice_paths(
        "slice_3_harness_workforce_skill",
        [
            "engine/project_evolution.py",
            "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md",
            "web/index.html",
            ".cambrian/auto/report.yaml",
        ],
    )

    assert payload["verdict"] == "GO"
    assert payload["status"] == "slice_worktree_ready"
    assert payload["candidate_paths"] == [
        "engine/project_evolution.py",
        "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md",
    ]
    assert len(payload["candidate_paths_sha256"]) == 64
    assert payload["candidate_count"] == 2
    assert payload["other_slice_counts"] == {"slice_6_web_and_tools": 1}
    assert payload["excluded_by_default"][0]["path"] == ".cambrian/auto/report.yaml"
    assert payload["stage_command_preview"] == (
        'git add -- "engine/project_evolution.py" "docs/product/24_EVOLUTION_ROLLBACK_CONTRACT.md"'
    )
    assert payload["verify_command"] == (
        "python scripts/check_final_commit_staging_handoff.py --staged --slice slice_3_harness_workforce_skill"
    )
    assert payload["verify_command_with_digest"].endswith(payload["candidate_paths_sha256"])


def test_final_commit_worktree_slice_plan_blocks_unknown_or_empty_slice() -> None:
    payload = plan_slice_paths("slice_6_web_and_tools", ["engine/project_evolution.py"])

    assert payload["verdict"] == "NO_GO"
    assert payload["status"] == "slice_worktree_blocked"
    assert payload["checks"]["candidate_paths_present"] is False
    assert payload["candidate_paths"] == []


def test_final_commit_all_slices_plan_groups_candidates_without_staging_all() -> None:
    payload = plan_all_slice_paths(
        [
            "engine/project_evolution.py",
            "web/index.html",
            "docs/release/RC_CHECKLIST.md",
            ".cambrian/auto/report.yaml",
        ]
    )

    assert payload["verdict"] == "GO"
    assert payload["status"] == "all_slices_worktree_ready"
    assert payload["safe_to_stage_all"] is False
    assert payload["active_slice_ids"] == [
        "slice_3_harness_workforce_skill",
        "slice_6_web_and_tools",
        "slice_7_runtime_evidence_archive",
    ]
    assert payload["slice_plans"]["slice_3_harness_workforce_skill"]["candidate_paths"] == [
        "engine/project_evolution.py"
    ]
    assert len(payload["slice_plans"]["slice_3_harness_workforce_skill"]["candidate_paths_sha256"]) == 64
    assert payload["slice_plans"]["slice_6_web_and_tools"]["candidate_paths"] == ["web/index.html"]
    assert payload["slice_plans"]["slice_7_runtime_evidence_archive"]["candidate_paths"] == [
        "docs/release/RC_CHECKLIST.md"
    ]
    assert payload["excluded_by_default"][0]["path"] == ".cambrian/auto/report.yaml"
    assert payload["next_action"] == "한 slice를 골라 candidate_paths만 stage한 뒤 --staged --slice 검증을 실행한다."


def test_final_commit_all_slices_plan_treats_clean_worktree_as_complete() -> None:
    payload = plan_all_slice_paths([])

    assert payload["verdict"] == "GO"
    assert payload["status"] == "all_slices_worktree_complete"
    assert payload["safe_to_stage_all"] is False
    assert payload["total_paths"] == 0
    assert payload["active_slice_ids"] == []
    assert payload["checks"]["active_slice_candidates_present"] is True
    assert payload["next_action"] == "No slice candidates remain; final staging is complete."


def test_final_commit_staging_receipt_accepts_clean_complete_plan(tmp_path: Path) -> None:
    plan = plan_all_slice_paths([])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "receipt_complete"
    assert result["verdict"] == "GO"
    assert payload["status"] == "receipt_complete"
    assert payload["active_slice_ids"] == []
    receipt = verify_staging_receipt_file(receipt_path)
    current_check = verify_staging_receipt_against_plan(receipt, plan)
    all_artifacts_check = verify_staging_receipt_all_artifacts(receipt, receipt_path, plan, base_dir=tmp_path)
    assert current_check["status"] == "receipt_current"
    assert all_artifacts_check["status"] == "receipt_all_artifacts_current"
    assert all_artifacts_check["verdict"] == "GO"


def test_final_commit_staging_receipt_writes_reviewable_json_and_markdown(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(
        [
            "engine/project_evolution.py",
            "web/index.html",
            ".cambrian/auto/report.yaml",
        ]
    )
    result = write_staging_receipt_from_plan(tmp_path, plan)

    json_path = Path(result["receipt_json"])
    md_path = Path(result["receipt_md"])
    runbook_path = Path(result["receipt_runbook"])
    pathspec_dir = Path(result["pathspec_dir"])
    evidence_template_dir = Path(result["test_gate_evidence_template_dir"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    runbook = runbook_path.read_text(encoding="utf-8")

    assert result["status"] == "receipt_ready"
    assert result["verdict"] == "GO"
    assert result["safe_to_stage_all"] is False
    assert len(result["receipt_body_sha256"]) == 64
    assert payload["schema_version"] == "final_commit_staging_receipt_v0_1"
    assert payload["receipt_body_sha256"] == result["receipt_body_sha256"]
    assert payload["receipt_policy"]["does_not_run_git_add"] is True
    assert payload["receipt_policy"]["untracked_paths"] == "file_level"
    assert payload["receipt_policy"]["default_output_excluded_from_source_commit"] == "dist/"
    assert payload["receipt_policy"]["excluded_by_default_sample_limit"] == RECEIPT_EXCLUDED_SAMPLE_LIMIT
    assert payload["receipt_policy"]["pathspec_files"] == "per_slice_line_delimited"
    assert payload["receipt_policy"]["test_gate_commands"] == "per_slice_receipt_locked"
    assert payload["receipt_policy"]["test_gate_evidence"] == "per_slice_manual_pass_receipt"
    assert payload["receipt_policy"]["test_gate_evidence_refs"] == (
        "portable_relative_under_final-commit-test-gate-logs"
    )
    assert payload["receipt_policy"]["test_gate_evidence_ref_uniqueness"] == "per_command_unique"
    assert payload["receipt_policy"]["test_gate_evidence_log_content"] == "contains_expected_command"
    assert payload["excluded_by_default_count"] == 1
    assert payload["excluded_by_default_summary"] == {"runtime_evidence": 1}
    assert payload["excluded_by_default_truncated"] is False
    assert payload["excluded_by_default"][0]["path"] == ".cambrian/auto/report.yaml"
    assert [item["slice_id"] for item in payload["slice_receipts"]] == [
        "slice_3_harness_workforce_skill",
        "slice_6_web_and_tools",
    ]
    for item in payload["slice_receipts"]:
        pathspec_file = pathspec_dir / f"{item['slice_id']}.pathspec"
        evidence_template_file = evidence_template_dir / f"{item['slice_id']}.template.json"
        assert pathspec_file.exists()
        assert evidence_template_file.exists()
        assert pathspec_file.read_text(encoding="utf-8").splitlines() == item["candidate_paths"]
        evidence_template = json.loads(evidence_template_file.read_text(encoding="utf-8"))
        assert evidence_template["schema_version"] == "final_commit_test_gate_evidence_v0_1"
        assert evidence_template["status"] == "PENDING"
        assert evidence_template["verdict"] == "NO_GO"
        assert evidence_template["slice_id"] == item["slice_id"]
        assert evidence_template["receipt_body_sha256"] == payload["receipt_body_sha256"]
        assert evidence_template["test_gate_commands_sha256"] == item["test_gate_commands_sha256"]
        assert [entry["command"] for entry in evidence_template["command_results"]] == item["test_gate_commands"]
        assert all("evidence_sha256" in entry for entry in evidence_template["command_results"])
        assert all(
            entry["evidence_ref"].startswith("dist/final-commit-test-gate-logs/")
            for entry in evidence_template["command_results"]
        )
        assert item["pathspec_file"].endswith(f"{item['slice_id']}.pathspec")
        assert item["test_gate_evidence_file"].endswith(f"{item['slice_id']}.json")
        assert item["test_gate_evidence_template_file"].endswith(f"{item['slice_id']}.template.json")
        assert "--verify-test-gate-evidence-from-receipt" in item["verify_test_gate_evidence_command"]
        assert item["test_gate_evidence_file"] in item["verify_test_gate_evidence_command"]
        assert "--verify-final-commit-from-receipt" in item["verify_final_commit_gate_command"]
        assert item["test_gate_evidence_file"] in item["verify_final_commit_gate_command"]
        assert item["stage_command_from_pathspec"] == f"git add --pathspec-from-file={item['pathspec_file']}"
        assert item["suggested_commit_message"]
        assert item["commit_command"] == f'git commit -m "{item["suggested_commit_message"]}"'
        assert item["test_gate_commands"]
        assert len(item["test_gate_commands_sha256"]) == 64
        test_gate_body = json.dumps(
            item["test_gate_commands"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert item["test_gate_commands_sha256"] == hashlib.sha256(
            test_gate_body.encode("utf-8")
        ).hexdigest()
        assert "python -m pytest" in "\n".join(item["test_gate_commands"])
    commands_by_slice = {item["slice_id"]: item["test_gate_commands"] for item in payload["slice_receipts"]}
    assert any(
        "tests/test_harness_workforce_skill_slice_ready.py" in command
        for command in commands_by_slice["slice_3_harness_workforce_skill"]
    )
    assert "python tools/generate_web_catalog.py" in commands_by_slice["slice_6_web_and_tools"]
    assert "Final Commit Staging Receipt" in markdown
    assert "total_count: `1`" in markdown
    assert "sample_count: `1`" in markdown
    assert "stage from pathspec" in markdown
    assert "test_gate_commands_sha256" in markdown
    assert "test gate before commit" in markdown
    assert "test_gate_evidence_template_file" in markdown
    assert "--verify-test-gate-evidence-from-receipt" in markdown
    assert "git add --pathspec-from-file=" in markdown
    assert "candidate_paths_sha256" in markdown
    assert "verify_command_with_digest" not in markdown
    assert "Final Commit Staging Runbook" in runbook
    assert "Global Preflight" in runbook
    assert "--verify-all-artifacts" in runbook
    assert "--verify-prestage-from-receipt" in runbook
    assert "git add --pathspec-from-file=" in runbook
    assert "--verify-staged-from-receipt" in runbook
    assert "--verify-commit-ready-from-receipt" in runbook
    assert "--verify-test-gate-evidence-from-receipt" in runbook
    assert "--verify-final-commit-from-receipt" in runbook
    assert "test_gate_commands_sha256" in runbook
    assert "tests/test_harness_workforce_skill_slice_ready.py" in runbook
    assert "python tools/generate_web_catalog.py" in runbook
    assert "git commit -m" in runbook
    assert "feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가" in runbook
    assert "git diff --cached --name-only" in runbook
    assert "--expect-paths-sha256" in markdown
    assert verify_staging_receipt_file(json_path)["receipt_body_sha256"] == result["receipt_body_sha256"]
    pathspec_check = verify_staging_receipt_pathspec_files(payload)
    assert pathspec_check["status"] == "receipt_pathspec_files_current"
    assert pathspec_check["verdict"] == "GO"
    assert pathspec_check["checks"]["all_pathspec_files_exist"] is True
    assert pathspec_check["checks"]["all_pathspec_digests_matched"] is True
    runbook_check = verify_staging_receipt_runbook(payload, tmp_path)
    assert runbook_check["status"] == "receipt_runbook_current"
    assert runbook_check["verdict"] == "GO"
    assert runbook_check["checks"]["runbook_body_matched"] is True
    evidence_template_check = verify_test_gate_evidence_templates(payload, tmp_path)
    assert evidence_template_check["status"] == "receipt_test_gate_evidence_templates_current"
    assert evidence_template_check["verdict"] == "GO"
    assert evidence_template_check["checks"]["all_template_digests_matched"] is True
    current_check = verify_staging_receipt_against_plan(payload, plan)
    assert current_check["status"] == "receipt_current"
    assert current_check["verdict"] == "GO"
    assert current_check["checks"]["active_slice_ids_matched"] is True
    all_artifacts_check = verify_staging_receipt_all_artifacts(payload, json_path, plan)
    assert all_artifacts_check["status"] == "receipt_all_artifacts_current"
    assert all_artifacts_check["verdict"] == "GO"
    assert all_artifacts_check["checks"]["receipt_current"] is True
    assert all_artifacts_check["checks"]["pathspec_files_current"] is True
    assert all_artifacts_check["checks"]["runbook_current"] is True
    assert all_artifacts_check["checks"]["test_gate_evidence_templates_current"] is True


def test_final_commit_test_gate_evidence_verifier_requires_matching_receipt(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt_path = Path(result["receipt_json"])
    receipt = verify_staging_receipt_file(receipt_path)
    receipt_item = receipt["slice_receipts"][0]
    commands = receipt_item["test_gate_commands"]
    log_dir = tmp_path / "final-commit-test-gate-logs"
    log_dir.mkdir()
    evidence_refs = []
    for index, command in enumerate(commands):
        log_path = log_dir / f"{receipt_item['slice_id']}-{index}.log"
        log_path.write_text(f"$ {command}\nPASS\n", encoding="utf-8")
        evidence_refs.append(
            {
                "ref": f"final-commit-test-gate-logs/{receipt_item['slice_id']}-{index}.log",
                "sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            }
        )
    evidence = {
        "schema_version": "final_commit_test_gate_evidence_v0_1",
        "status": "PASS",
        "verdict": "GO",
        "slice_id": receipt_item["slice_id"],
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "candidate_paths_sha256": receipt_item["candidate_paths_sha256"],
        "test_gate_commands_sha256": receipt_item["test_gate_commands_sha256"],
        "test_gate_commands": commands,
        "command_results": [
            {
                "command": command,
                "status": "PASS",
                "exit_code": 0,
                "evidence_ref": evidence_refs[index]["ref"],
                "evidence_sha256": evidence_refs[index]["sha256"],
            }
            for index, command in enumerate(commands)
        ],
    }

    ready = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        evidence,
        base_dir=tmp_path,
        evidence_path=tmp_path / receipt_item["test_gate_evidence_file"],
    )

    assert ready["verdict"] == "GO"
    assert ready["status"] == "test_gate_evidence_ready"
    assert ready["checks"]["receipt_body_sha256_matched"] is True
    assert ready["checks"]["test_gate_evidence_path_matched"] is True
    assert ready["actual_test_gate_evidence_file"] == receipt_item["test_gate_evidence_file"]
    assert ready["checks"]["all_command_results_passed"] is True
    assert ready["checks"]["all_command_results_have_evidence_ref"] is True
    assert ready["checks"]["all_evidence_refs_unique"] is True
    assert ready["checks"]["all_command_results_have_evidence_sha256"] is True
    assert ready["checks"]["all_evidence_refs_are_portable"] is True
    assert ready["checks"]["all_evidence_refs_use_log_dir"] is True
    assert ready["checks"]["all_evidence_files_exist"] is True
    assert ready["checks"]["all_evidence_sha256_matched"] is True
    assert ready["checks"]["all_evidence_files_contain_command"] is True

    blocked_evidence = dict(evidence)
    blocked_evidence["command_results"] = [
        {
            "command": command,
            "status": "PASS",
            "exit_code": 0,
            "evidence_ref": evidence_refs[index]["ref"],
            "evidence_sha256": evidence_refs[index]["sha256"],
        }
        for index, command in enumerate(commands)
    ]
    blocked_evidence["command_results"][0]["exit_code"] = 1
    blocked = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        blocked_evidence,
        base_dir=tmp_path,
    )

    assert blocked["verdict"] == "NO_GO"
    assert blocked["status"] == "test_gate_evidence_blocked"
    assert blocked["checks"]["all_command_results_passed"] is False

    no_ref_evidence = dict(evidence)
    no_ref_evidence["command_results"] = [
        {
            "command": command,
            "status": "PASS",
            "exit_code": 0,
            "evidence_ref": "",
            "evidence_sha256": evidence_refs[index]["sha256"],
        }
        for index, command in enumerate(commands)
    ]
    no_ref = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        no_ref_evidence,
        base_dir=tmp_path,
    )

    assert no_ref["verdict"] == "NO_GO"
    assert no_ref["status"] == "test_gate_evidence_blocked"
    assert no_ref["checks"]["all_command_results_have_evidence_ref"] is False

    missing_file_evidence = dict(evidence)
    missing_file_evidence["command_results"] = [
        {
            "command": command,
            "status": "PASS",
            "exit_code": 0,
            "evidence_ref": f"final-commit-test-gate-logs/missing-{index}.log",
            "evidence_sha256": evidence_refs[index]["sha256"],
        }
        for index, command in enumerate(commands)
    ]
    missing_file = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        missing_file_evidence,
        base_dir=tmp_path,
    )

    assert missing_file["verdict"] == "NO_GO"
    assert missing_file["status"] == "test_gate_evidence_blocked"
    assert missing_file["checks"]["all_evidence_files_exist"] is False

    wrong_sha_evidence = dict(evidence)
    wrong_sha_evidence["command_results"] = [
        {
            "command": command,
            "status": "PASS",
            "exit_code": 0,
            "evidence_ref": evidence_refs[index]["ref"],
            "evidence_sha256": "0" * 64,
        }
        for index, command in enumerate(commands)
    ]
    wrong_sha = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        wrong_sha_evidence,
        base_dir=tmp_path,
    )

    assert wrong_sha["verdict"] == "NO_GO"
    assert wrong_sha["status"] == "test_gate_evidence_blocked"
    assert wrong_sha["checks"]["all_evidence_sha256_matched"] is False

    missing_command_refs = []
    for index, _command in enumerate(commands):
        log_path = log_dir / f"{receipt_item['slice_id']}-missing-command-{index}.log"
        log_path.write_text("PASS\n", encoding="utf-8")
        missing_command_refs.append(
            {
                "ref": f"final-commit-test-gate-logs/{receipt_item['slice_id']}-missing-command-{index}.log",
                "sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            }
        )
    missing_command_evidence = dict(evidence)
    missing_command_evidence["command_results"] = [
        {
            "command": command,
            "status": "PASS",
            "exit_code": 0,
            "evidence_ref": missing_command_refs[index]["ref"],
            "evidence_sha256": missing_command_refs[index]["sha256"],
        }
        for index, command in enumerate(commands)
    ]
    missing_command = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        missing_command_evidence,
        base_dir=tmp_path,
    )

    assert missing_command["verdict"] == "NO_GO"
    assert missing_command["status"] == "test_gate_evidence_blocked"
    assert missing_command["checks"]["all_evidence_files_contain_command"] is False

    wrong_dir_evidence = dict(evidence)
    wrong_dir_log = tmp_path / "other.log"
    wrong_dir_log.write_text("PASS\n", encoding="utf-8")
    wrong_dir_evidence["command_results"] = [
        {
            "command": command,
            "status": "PASS",
            "exit_code": 0,
            "evidence_ref": "other.log",
            "evidence_sha256": hashlib.sha256(wrong_dir_log.read_bytes()).hexdigest(),
        }
        for command in commands
    ]
    wrong_dir = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        wrong_dir_evidence,
        base_dir=tmp_path,
    )

    assert wrong_dir["verdict"] == "NO_GO"
    assert wrong_dir["status"] == "test_gate_evidence_blocked"
    assert wrong_dir["checks"]["all_evidence_refs_use_log_dir"] is False

    wrong_evidence_path = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        evidence,
        base_dir=tmp_path,
        evidence_path=tmp_path / "dist/final-commit-test-gate-evidence/wrong-file.json",
    )

    assert wrong_evidence_path["verdict"] == "NO_GO"
    assert wrong_evidence_path["status"] == "test_gate_evidence_blocked"
    assert wrong_evidence_path["checks"]["test_gate_evidence_path_matched"] is False


def test_final_commit_test_gate_evidence_verifier_rejects_reused_log_refs(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["pyproject.toml"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))
    receipt_item = receipt["slice_receipts"][0]
    commands = receipt_item["test_gate_commands"]
    assert len(commands) > 1

    log_dir = tmp_path / "final-commit-test-gate-logs"
    log_dir.mkdir()
    shared_log = log_dir / f"{receipt_item['slice_id']}-shared.log"
    shared_log.write_text("\n".join(f"$ {command}\nPASS" for command in commands), encoding="utf-8")
    shared_ref = f"final-commit-test-gate-logs/{receipt_item['slice_id']}-shared.log"
    shared_sha = hashlib.sha256(shared_log.read_bytes()).hexdigest()
    evidence = {
        "schema_version": "final_commit_test_gate_evidence_v0_1",
        "status": "PASS",
        "verdict": "GO",
        "slice_id": receipt_item["slice_id"],
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "candidate_paths_sha256": receipt_item["candidate_paths_sha256"],
        "test_gate_commands_sha256": receipt_item["test_gate_commands_sha256"],
        "test_gate_commands": commands,
        "command_results": [
            {
                "command": command,
                "status": "PASS",
                "exit_code": 0,
                "evidence_ref": shared_ref,
                "evidence_sha256": shared_sha,
            }
            for command in commands
        ],
    }

    blocked = verify_test_gate_evidence_against_receipt(
        receipt,
        receipt_item["slice_id"],
        evidence,
        base_dir=tmp_path,
        evidence_path=tmp_path / receipt_item["test_gate_evidence_file"],
    )

    assert blocked["verdict"] == "NO_GO"
    assert blocked["status"] == "test_gate_evidence_blocked"
    assert blocked["checks"]["all_evidence_refs_unique"] is False


def test_final_commit_staging_receipt_compacts_large_excluded_sets(tmp_path: Path) -> None:
    excluded_paths = [
        f".cambrian/auto/file-{index}.yaml"
        for index in range(RECEIPT_EXCLUDED_SAMPLE_LIMIT + 10)
    ]
    plan = plan_all_slice_paths(["engine/project_evolution.py", *excluded_paths])
    result = write_staging_receipt_from_plan(tmp_path, plan)

    json_path = Path(result["receipt_json"])
    md_path = Path(result["receipt_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert payload["excluded_by_default_count"] == len(excluded_paths)
    assert payload["excluded_by_default_summary"] == {"runtime_evidence": len(excluded_paths)}
    assert payload["excluded_by_default_truncated"] is True
    assert len(payload["excluded_by_default"]) == RECEIPT_EXCLUDED_SAMPLE_LIMIT
    assert payload["slice_receipts"][0]["candidate_paths"] == ["engine/project_evolution.py"]
    assert f"total_count: `{len(excluded_paths)}`" in markdown
    assert f"sample_count: `{RECEIPT_EXCLUDED_SAMPLE_LIMIT}`" in markdown
    assert "truncated: `True`" in markdown
    assert f".cambrian/auto/file-{RECEIPT_EXCLUDED_SAMPLE_LIMIT + 1}.yaml" not in markdown
    assert verify_staging_receipt_file(json_path)["receipt_body_sha256"] == result["receipt_body_sha256"]


def test_final_commit_staging_receipt_pathspec_verifier_rejects_stale_file(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))
    pathspec_file = Path(receipt["slice_receipts"][0]["pathspec_file"])
    pathspec_file.write_text("engine/project_evolution.py\nweb/index.html\n", encoding="utf-8")

    pathspec_check = verify_staging_receipt_pathspec_files(receipt)

    assert pathspec_check["verdict"] == "NO_GO"
    assert pathspec_check["status"] == "receipt_pathspec_files_stale"
    first_slice = receipt["slice_receipts"][0]["slice_id"]
    assert pathspec_check["pathspec_checks"][first_slice]["pathspec_file_exists"] is True
    assert pathspec_check["pathspec_checks"][first_slice]["candidate_count_matched"] is False
    assert pathspec_check["pathspec_checks"][first_slice]["candidate_paths_sha256_matched"] is False


def test_final_commit_staging_receipt_runbook_verifier_rejects_stale_file(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))
    runbook_path = Path(result["receipt_runbook"])
    runbook_path.write_text("# stale runbook\n", encoding="utf-8")

    runbook_check = verify_staging_receipt_runbook(receipt, tmp_path)

    assert runbook_check["verdict"] == "NO_GO"
    assert runbook_check["status"] == "receipt_runbook_stale"
    assert runbook_check["checks"]["runbook_file_exists"] is True
    assert runbook_check["checks"]["runbook_body_matched"] is False
    assert runbook_check["expected_runbook_sha256"] != runbook_check["actual_runbook_sha256"]


def test_final_commit_prestage_verifier_requires_current_receipt_pathspec_and_empty_index(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))

    ready = verify_slice_prestage_ready(
        receipt=receipt,
        slice_id="slice_3_harness_workforce_skill",
        staged_paths=[],
        current_plan=plan,
    )

    assert ready["verdict"] == "GO"
    assert ready["status"] == "slice_prestage_ready"
    assert ready["checks"]["receipt_current"] is True
    assert ready["checks"]["pathspec_files_current"] is True
    assert ready["checks"]["staged_diff_empty"] is True
    assert ready["receipt_candidate_count"] == 1
    assert ready["stage_command_from_pathspec"].startswith("git add --pathspec-from-file=")
    assert "--verify-staged-from-receipt" in ready["receipt_backed_staged_verify_command"]

    blocked = verify_slice_prestage_ready(
        receipt=receipt,
        slice_id="slice_3_harness_workforce_skill",
        staged_paths=["web/index.html"],
        current_plan=plan,
    )

    assert blocked["verdict"] == "NO_GO"
    assert blocked["status"] == "slice_prestage_blocked"
    assert blocked["checks"]["staged_diff_empty"] is False
    assert blocked["existing_staged_paths"] == ["web/index.html"]
    assert ready["test_gate_commands"]
    assert len(ready["test_gate_commands_sha256"]) == 64


def test_final_commit_staging_receipt_verifier_rejects_tampering(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    json_path = Path(result["receipt_json"])

    body_tampered = json.loads(json_path.read_text(encoding="utf-8"))
    body_tampered["safe_to_stage_all"] = True
    body_tampered_path = tmp_path / "body-tampered.json"
    body_tampered_path.write_text(json.dumps(body_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        verify_staging_receipt_file(body_tampered_path)
    except ValueError as exc:
        assert "safe_to_stage_all" in str(exc)
    else:
        raise AssertionError("safe_to_stage_all 변조가 차단되어야 합니다.")

    digest_tampered = json.loads(json_path.read_text(encoding="utf-8"))
    digest_tampered["slice_receipts"][0]["candidate_paths"].append("tests/test_skill_evolution.py")
    digest_tampered["slice_receipts"][0]["candidate_count"] = len(
        digest_tampered["slice_receipts"][0]["candidate_paths"]
    )
    digest_tampered["receipt_body_sha256"] = _receipt_body_sha256(digest_tampered)
    digest_tampered_path = tmp_path / "digest-tampered.json"
    digest_tampered_path.write_text(
        json.dumps(digest_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    try:
        verify_staging_receipt_file(digest_tampered_path)
    except ValueError as exc:
        assert "candidate_paths_sha256" in str(exc)
    else:
        raise AssertionError("candidate_paths 변조가 차단되어야 합니다.")

    test_gate_tampered = json.loads(json_path.read_text(encoding="utf-8"))
    test_gate_commands = ["python -m pytest -q tests/test_skill_evolution.py"]
    test_gate_tampered["slice_receipts"][0]["test_gate_commands"] = test_gate_commands
    test_gate_body = json.dumps(test_gate_commands, ensure_ascii=False, separators=(",", ":"))
    test_gate_tampered["slice_receipts"][0]["test_gate_commands_sha256"] = hashlib.sha256(
        test_gate_body.encode("utf-8")
    ).hexdigest()
    test_gate_tampered["receipt_body_sha256"] = _receipt_body_sha256(test_gate_tampered)
    test_gate_tampered_path = tmp_path / "test-gate-tampered.json"
    test_gate_tampered_path.write_text(
        json.dumps(test_gate_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    try:
        verify_staging_receipt_file(test_gate_tampered_path)
    except ValueError as exc:
        assert "test_gate_commands" in str(exc)
    else:
        raise AssertionError("test_gate_commands 변조가 차단되어야 합니다.")


def test_final_commit_staging_receipt_current_check_rejects_stale_plan(tmp_path: Path) -> None:
    original_plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, original_plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))
    changed_plan = plan_all_slice_paths(["engine/project_evolution.py"])

    current_check = verify_staging_receipt_against_plan(receipt, changed_plan)

    assert current_check["verdict"] == "NO_GO"
    assert current_check["status"] == "receipt_stale"
    assert current_check["checks"]["active_slice_ids_matched"] is False
    assert current_check["slice_checks"]["slice_6_web_and_tools"]["present_in_receipt"] is True
    assert current_check["slice_checks"]["slice_6_web_and_tools"]["present_in_plan"] is False


def test_final_commit_receipt_can_verify_staged_slice_without_manual_digest_copy(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))

    ok = verify_staged_slice_against_receipt(
        receipt,
        "slice_3_harness_workforce_skill",
        ["engine/project_evolution.py"],
    )

    assert ok["verdict"] == "GO"
    assert ok["status"] == "receipt_staged_slice_ready"
    assert ok["checks"]["expected_paths_sha256_matched"] is True
    assert ok["receipt_candidate_count"] == 1
    assert ok["receipt_candidate_paths_sha256"] == ok["accepted_paths_sha256"]
    assert ok["test_gate_required_before_commit"] is True
    assert ok["test_gate_commands"]
    assert len(ok["test_gate_commands_sha256"]) == 64

    blocked = verify_staged_slice_against_receipt(
        receipt,
        "slice_3_harness_workforce_skill",
        ["engine/project_evolution.py", "web/index.html"],
    )

    assert blocked["verdict"] == "NO_GO"
    assert blocked["status"] == "receipt_staged_slice_blocked"
    assert blocked["checks"]["no_cross_slice_paths"] is False
    assert blocked["wrong_slice"][0]["path"] == "web/index.html"


def test_final_commit_receipt_can_verify_commit_ready_with_suggested_message(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt = verify_staging_receipt_file(Path(result["receipt_json"]))

    ready = verify_slice_commit_ready_against_receipt(
        receipt,
        "slice_3_harness_workforce_skill",
        ["engine/project_evolution.py"],
    )

    assert ready["verdict"] == "GO"
    assert ready["status"] == "slice_commit_ready"
    assert ready["checks"]["receipt_staged_slice_ready"] is True
    assert ready["checks"]["suggested_commit_message_present"] is True
    assert ready["checks"]["test_gate_commands_present"] is True
    assert ready["suggested_commit_message"] == "feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가"
    assert any(
        "tests/test_harness_workforce_skill_slice_ready.py" in command
        for command in ready["test_gate_commands"]
    )
    assert len(ready["test_gate_commands_sha256"]) == 64
    assert ready["commit_command"] == 'git commit -m "feat(harness): 대화형 하네스 인력 스킬 생성 흐름 추가"'
    assert ready["next_required_commands"][-1] == ready["commit_command"]
    assert ready["next_required_commands"][:-1] == ready["test_gate_commands"]

    blocked = verify_slice_commit_ready_against_receipt(
        receipt,
        "slice_3_harness_workforce_skill",
        ["web/index.html"],
    )

    assert blocked["verdict"] == "NO_GO"
    assert blocked["status"] == "slice_commit_blocked"
    assert blocked["checks"]["receipt_staged_slice_ready"] is False


def test_final_commit_integrated_gate_requires_staged_slice_and_test_evidence(tmp_path: Path) -> None:
    plan = plan_all_slice_paths(["engine/project_evolution.py", "web/index.html"])
    result = write_staging_receipt_from_plan(tmp_path, plan)
    receipt_path = Path(result["receipt_json"])
    receipt = verify_staging_receipt_file(receipt_path)
    receipt_item = receipt["slice_receipts"][0]
    receipt_artifacts_check = verify_staging_receipt_all_artifacts(receipt, receipt_path, plan, base_dir=tmp_path)
    commands = receipt_item["test_gate_commands"]
    log_dir = tmp_path / "final-commit-test-gate-logs"
    log_dir.mkdir()
    evidence_refs = []
    for index, command in enumerate(commands):
        log_path = log_dir / f"{receipt_item['slice_id']}-{index}.log"
        log_path.write_text(f"$ {command}\nPASS\n", encoding="utf-8")
        evidence_refs.append(
            {
                "ref": f"final-commit-test-gate-logs/{receipt_item['slice_id']}-{index}.log",
                "sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            }
        )
    evidence = {
        "schema_version": "final_commit_test_gate_evidence_v0_1",
        "status": "PASS",
        "verdict": "GO",
        "slice_id": receipt_item["slice_id"],
        "receipt_body_sha256": receipt["receipt_body_sha256"],
        "candidate_paths_sha256": receipt_item["candidate_paths_sha256"],
        "test_gate_commands_sha256": receipt_item["test_gate_commands_sha256"],
        "test_gate_commands": commands,
        "command_results": [
            {
                "command": command,
                "status": "PASS",
                "exit_code": 0,
                "evidence_ref": evidence_refs[index]["ref"],
                "evidence_sha256": evidence_refs[index]["sha256"],
            }
            for index, command in enumerate(commands)
        ],
    }
    expected_recovery_execution_policy = {
        "recovery_commands_are_suggestions_only": True,
        "script_executes_recovery_commands": False,
        "script_executes_git_add": False,
        "script_executes_git_commit": False,
        "script_executes_git_push": False,
        "index_mutation_requires_manual_user_confirmation": True,
        "dist_artifact_write_requires_manual_review": True,
        "commit_requires_user_confirmation": True,
    }

    ready = verify_slice_final_commit_gate_against_receipt(
        receipt=receipt,
        slice_id=receipt_item["slice_id"],
        staged_paths=["engine/project_evolution.py"],
        evidence=evidence,
        receipt_artifacts_check=receipt_artifacts_check,
        base_dir=tmp_path,
        evidence_path=tmp_path / receipt_item["test_gate_evidence_file"],
    )

    assert ready["verdict"] == "GO"
    assert ready["status"] == "slice_final_commit_gate_ready"
    assert ready["checks"]["receipt_all_artifacts_current"] is True
    assert ready["checks"]["slice_commit_ready"] is True
    assert ready["checks"]["test_gate_evidence_ready"] is True
    assert ready["checks"]["same_candidate_paths_sha256"] is True
    assert ready["checks"]["same_test_gate_commands_sha256"] is True
    assert ready["blocking_reasons"] == []
    assert ready["blocking_details"] == {}
    assert ready["recovery_commands"] == []
    assert ready["recovery_command_plan"] == []
    assert ready["recovery_command_summary"] == {
        "total_count": 0,
        "phase_counts": {},
        "command_kind_counts": {},
        "mutates_git_index_count": 0,
        "writes_dist_artifacts_count": 0,
        "runs_tests_count": 0,
        "requires_manual_review_count": 0,
        "has_index_mutations": False,
        "has_dist_artifact_writes": False,
        "has_test_runs": False,
    }
    assert ready["next_action"] == "사용자 확인 후 git commit 실행"
    assert ready["manual_commit_requires_user_confirmation"] is True
    assert ready["recovery_execution_policy"] == expected_recovery_execution_policy

    wrong_stage = verify_slice_final_commit_gate_against_receipt(
        receipt=receipt,
        slice_id=receipt_item["slice_id"],
        staged_paths=["web/index.html"],
        evidence=evidence,
        receipt_artifacts_check=receipt_artifacts_check,
        base_dir=tmp_path,
        evidence_path=tmp_path / receipt_item["test_gate_evidence_file"],
    )

    assert wrong_stage["verdict"] == "NO_GO"
    assert wrong_stage["status"] == "slice_final_commit_gate_blocked"
    assert wrong_stage["checks"]["slice_commit_ready"] is False
    assert wrong_stage["checks"]["test_gate_evidence_ready"] is True
    assert "staged slice가 receipt candidate digest와 일치하지 않음" in wrong_stage["blocking_reasons"]
    assert "commit_ready" in wrong_stage["blocking_details"]
    assert "expected_paths_sha256_matched" in wrong_stage["blocking_details"]["commit_ready"]
    assert "slice_commit_ready" in wrong_stage["blocking_details"]["integrated"]
    assert any("--verify-prestage-from-receipt" in command for command in wrong_stage["recovery_commands"])
    assert any("--verify-commit-ready-from-receipt" in command for command in wrong_stage["recovery_commands"])
    assert wrong_stage["recovery_commands"][-1] == receipt_item["verify_final_commit_gate_command"]
    stage_steps = [
        step
        for step in wrong_stage["recovery_command_plan"]
        if step["command"] == receipt_item["stage_command_from_pathspec"]
    ]
    assert stage_steps == [
        {
            "phase": "stage",
            "command_kind": "mutates_git_index",
            "command": receipt_item["stage_command_from_pathspec"],
            "mutates_git_index": True,
            "requires_manual_review": True,
        }
    ]
    assert wrong_stage["recovery_command_summary"]["has_index_mutations"] is True
    assert wrong_stage["recovery_command_summary"]["mutates_git_index_count"] == 1
    assert wrong_stage["recovery_execution_policy"] == expected_recovery_execution_policy
    assert wrong_stage["recovery_execution_policy"]["script_executes_recovery_commands"] is False
    assert wrong_stage["recovery_execution_policy"]["script_executes_git_add"] is False
    assert wrong_stage["recovery_execution_policy"]["index_mutation_requires_manual_user_confirmation"] is True
    assert wrong_stage["next_action"] == "blocking_reasons를 해결한 뒤 최종 통합 게이트를 재실행"

    failed_evidence = dict(evidence)
    failed_evidence["status"] = "PENDING"
    wrong_evidence = verify_slice_final_commit_gate_against_receipt(
        receipt=receipt,
        slice_id=receipt_item["slice_id"],
        staged_paths=["engine/project_evolution.py"],
        evidence=failed_evidence,
        receipt_artifacts_check=receipt_artifacts_check,
        base_dir=tmp_path,
        evidence_path=tmp_path / receipt_item["test_gate_evidence_file"],
    )

    assert wrong_evidence["verdict"] == "NO_GO"
    assert wrong_evidence["status"] == "slice_final_commit_gate_blocked"
    assert wrong_evidence["checks"]["slice_commit_ready"] is True
    assert wrong_evidence["checks"]["test_gate_evidence_ready"] is False
    assert "test gate evidence JSON 또는 참조 로그 검증 실패" in wrong_evidence["blocking_reasons"]
    assert "test_gate_evidence" in wrong_evidence["blocking_details"]
    assert "status_pass" in wrong_evidence["blocking_details"]["test_gate_evidence"]
    assert "test_gate_evidence_ready" in wrong_evidence["blocking_details"]["integrated"]
    assert commands[0] in wrong_evidence["recovery_commands"]
    assert receipt_item["verify_test_gate_evidence_command"] in wrong_evidence["recovery_commands"]
    assert wrong_evidence["recovery_commands"][-1] == receipt_item["verify_final_commit_gate_command"]
    assert any(
        step["phase"] == "test_gate" and step["command_kind"] == "runs_tests"
        for step in wrong_evidence["recovery_command_plan"]
    )
    assert wrong_evidence["recovery_command_summary"]["has_test_runs"] is True
    assert wrong_evidence["recovery_command_summary"]["runs_tests_count"] == 1
    assert wrong_evidence["recovery_execution_policy"] == expected_recovery_execution_policy

    stale_receipt_artifacts = dict(receipt_artifacts_check)
    stale_receipt_artifacts["status"] = "receipt_stale"
    stale_receipt_artifacts["verdict"] = "NO_GO"
    stale_receipt = verify_slice_final_commit_gate_against_receipt(
        receipt=receipt,
        slice_id=receipt_item["slice_id"],
        staged_paths=["engine/project_evolution.py"],
        evidence=evidence,
        receipt_artifacts_check=stale_receipt_artifacts,
        base_dir=tmp_path,
        evidence_path=tmp_path / receipt_item["test_gate_evidence_file"],
    )

    assert stale_receipt["verdict"] == "NO_GO"
    assert stale_receipt["status"] == "slice_final_commit_gate_blocked"
    assert stale_receipt["checks"]["receipt_all_artifacts_current"] is False
    assert stale_receipt["checks"]["slice_commit_ready"] is True
    assert stale_receipt["checks"]["test_gate_evidence_ready"] is True
    assert "receipt/pathspec/runbook/evidence template 최신성 검증 실패" in stale_receipt["blocking_reasons"]
    assert stale_receipt["blocking_details"]["receipt_artifacts"] == ["receipt_stale"]
    assert "receipt_all_artifacts_current" in stale_receipt["blocking_details"]["integrated"]
    assert stale_receipt["recovery_commands"][:2] == [
        "python scripts/check_final_commit_staging_handoff.py --write-receipt-dir dist",
        "python scripts/check_final_commit_staging_handoff.py --verify-all-artifacts dist/final-commit-staging-receipt.json",
    ]
    assert stale_receipt["recovery_commands"][-1] == receipt_item["verify_final_commit_gate_command"]
    assert stale_receipt["recovery_command_plan"][0]["command_kind"] == "writes_dist_artifacts"
    assert stale_receipt["recovery_command_plan"][0]["requires_manual_review"] is True
    assert stale_receipt["recovery_command_summary"]["has_dist_artifact_writes"] is True
    assert stale_receipt["recovery_command_summary"]["writes_dist_artifacts_count"] == 1
    assert stale_receipt["recovery_execution_policy"] == expected_recovery_execution_policy
