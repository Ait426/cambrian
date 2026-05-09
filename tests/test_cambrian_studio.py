from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from engine.project_pack_derivatives import PackDerivativePlanner
from engine.project_pack_improvements import (
    PackImprovementQueueBuilder,
    record_pack_improvement_decision,
    save_pack_improvement_queue,
)
from engine.project_pack_install import PackInstaller, PackManifestLoader
from engine.project_pack_proof import PackProofBuilder, latest_pack_proof_card, save_pack_proof_card


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _studio_agent_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "pack_id": "document-organizer-agent",
        "pack_name": "Document Organizer Agent",
        "pack_kind": "agent",
        "version": "0.1.0",
        "description": "문서를 주제별로 분류하고 정리 제안을 만든다.",
        "source": {
            "kind": "cambrian_studio",
            "registry": "local",
            "author": "local-author",
            "origin_ref": "web/studio",
            "provenance": "studio_generated",
            "public_visibility": "private",
            "signature_status": "unsigned_local",
        },
        "compatibility": {
            "stacks": ["local_files"],
            "request_classes": ["document_organization"],
            "domains": ["documents", "knowledge_management"],
        },
        "workers": [
            {
                "id": "document-organizer-agent",
                "name": "Document Organizer Agent",
                "capabilities": [
                    "document classification",
                    "duplicate candidate detection",
                    "organization report drafting",
                ],
                "tags": ["documents", "organizer", "studio_generated"],
            }
        ],
        "teams": [
            {
                "name": "document-organizer-agent-team",
                "lead_agent_id": "document-organizer-agent",
                "supporting_agent_ids": [],
                "tags": ["documents", "organizer"],
            }
        ],
        "templates": [
            {
                "name": "document-organizer-agent-template",
                "template_kind": "agent_contract",
                "description": "문서를 주제별로 분류하고 정리 제안을 만든다.",
                "project_defaults": {
                    "stack": ["local_files"],
                    "primary_use_cases": ["document_organization"],
                    "output_format": "markdown_report",
                    "document_types": ["pdf", "docx", "txt", "markdown"],
                },
                "safety_defaults": {
                    "explicit_adoption_only": True,
                    "preserve_source_artifacts": True,
                    "no_external_upload": True,
                    "approval_required_actions": ["파일 이름 변경", "폴더 이동"],
                    "forbidden_actions": ["원본 파일 삭제", "외부 서비스로 문서 업로드"],
                },
                "policy_defaults": {
                    "read_only_first": True,
                    "draft_outputs_only": True,
                    "require_user_approval_for_file_moves": True,
                },
                "validation_defaults": {
                    "proof_status": "preflight_only",
                    "runtime_evidence": "none",
                    "success_metrics_available": False,
                    "validation_criteria": [
                        "원본 파일을 변경하지 않았는지 확인",
                        "분류 기준과 예외 파일 목록을 결과에 포함",
                    ],
                },
                "evolution_defaults": {
                    "track_signals": [
                        "user_correction_required",
                        "validation_gap_found",
                        "forbidden_action_blocked",
                    ]
                },
                "fit_hints": ["strongest for local document organization and draft reports"],
            }
        ],
        "benchmarks": [
            {
                "name": "document-organizer-agent-preflight-workset",
                "description": "Preflight checklist for document organization agents",
                "tags": ["documents", "preflight"],
            }
        ],
        "proof_seed": {
            "status": "preflight_only",
            "runtime_evidence": "none",
            "success_rate": None,
            "human_intervention_rate": None,
            "validation_pass_rate": None,
        },
        "marketplace": {
            "license": "personal_local",
            "checksum": "pending_after_export",
            "signature": "unsigned_local",
            "evolution_lineage": [],
            "known_limits": ["OCR이 필요한 스캔 PDF는 별도 도구가 필요할 수 있다."],
        },
        "install": {
            "install_as_library": True,
            "auto_apply": False,
            "auto_bootstrap": False,
            "auto_promote": False,
            "auto_canary": False,
        },
        "warnings": [
            "Generated by Cambrian Studio preflight. Local runtime evidence is required before public proof claims."
        ],
    }


def test_studio_page_exists_and_explains_builder() -> None:
    studio = _read(WEB / "studio" / "index.html")

    for phrase in [
        "Cambrian Studio",
        "Agent Contract Builder",
        "Document Organizer Agent",
        "문서 정리 에이전트",
        "preflight_only",
        "cambrian install manifest ./",
        "cambrian job start --pack",
        "실제 성능 proof는 로컬 job 실행 후에만 생성됩니다.",
    ]:
        assert phrase in studio


def test_studio_generated_contract_contains_runtime_safe_defaults() -> None:
    studio = _read(WEB / "studio" / "index.html")

    for phrase in [
        "pack_kind: agent",
        "template_kind: agent_contract",
        "kind: cambrian_studio",
        "signature_status: unsigned_local",
        "public_visibility: private",
        "proof_seed:",
        "runtime_evidence: none",
        "success_rate: null",
        "human_intervention_rate: null",
        "validation_pass_rate: null",
        "auto_apply: false",
        "auto_bootstrap: false",
        "auto_promote: false",
        "auto_canary: false",
    ]:
        assert phrase in studio


def test_studio_makes_no_fake_performance_claims() -> None:
    studio = _read(WEB / "studio" / "index.html").lower()

    for forbidden in [
        "100% success",
        "proven best",
        "guaranteed",
        "fully autonomous",
        "validated_proposal_rate",
        "success_rate: 1",
    ]:
        assert forbidden not in studio

    assert "actual performance proof is generated only after local cambrian runtime jobs" in studio
    assert "no fake proof" in studio


def test_studio_is_linked_from_web_surfaces() -> None:
    landing = _read(WEB / "index.html")
    packs = _read(WEB / "packs" / "index.html")
    detail = _read(WEB / "packs" / "auth-bug-core.html")

    assert "studio/index.html" in landing
    assert "../studio/index.html" in packs
    assert "../studio/index.html" in detail
    assert "Open Cambrian Studio" in landing


def test_generate_web_catalog_emits_studio_without_runtime_mutation(tmp_path: Path) -> None:
    out_dir = tmp_path / "web"
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "generate_web_catalog.py"),
            "--catalog",
            str(ROOT / "packs" / "catalog.yaml"),
            "--out",
            str(out_dir),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "studio" / "index.html").exists()
    assert "Cambrian Studio" in _read(out_dir / "studio" / "index.html")
    assert not (tmp_path / ".cambrian").exists()


def test_studio_agent_pack_manifest_loads_and_installs(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())

    manifest = PackManifestLoader().load(manifest_path)
    plan = PackInstaller().install(tmp_path, manifest_path)

    assert manifest.pack_kind == "agent"
    assert plan.safe_to_install is True
    assert (tmp_path / ".cambrian" / "agents" / "registry.yaml").exists()
    assert (tmp_path / ".cambrian" / "templates" / "templates.yaml").exists()
    assert (tmp_path / ".cambrian" / "install" / "installed_packs.yaml").exists()


def test_studio_agent_pack_requires_contract_template(tmp_path: Path) -> None:
    payload = _studio_agent_manifest()
    payload["templates"] = []
    manifest_path = tmp_path / "broken-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, payload)

    with pytest.raises(ValueError, match="agent contract template"):
        PackManifestLoader().load(manifest_path)


def test_studio_agent_pack_blocks_forbidden_approval_conflicts(tmp_path: Path) -> None:
    payload = deepcopy(_studio_agent_manifest())
    safety = payload["templates"][0]["safety_defaults"]
    safety["approval_required_actions"].append("원본 파일 삭제")
    manifest_path = tmp_path / "conflicting-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, payload)

    with pytest.raises(ValueError, match="conflicting forbidden and approval-required actions"):
        PackManifestLoader().load(manifest_path)


def test_studio_agent_pack_blocks_unsafe_install_flags(tmp_path: Path) -> None:
    payload = _studio_agent_manifest()
    payload["install"]["auto_apply"] = True
    manifest_path = tmp_path / "unsafe-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, payload)

    plan = PackInstaller().install(tmp_path, manifest_path, dry_run=True)

    assert plan.safe_to_install is False
    assert "install must not auto apply templates" in plan.errors


def test_studio_agent_pack_can_initialize_local_proof_card(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())

    PackInstaller().install(tmp_path, manifest_path)
    card = PackProofBuilder().build(tmp_path, "document-organizer-agent")
    saved_paths = save_pack_proof_card(tmp_path, card, format_kind="both")
    latest = latest_pack_proof_card(tmp_path, "document-organizer-agent")
    metrics = {metric.key: metric.value for metric in card.key_metrics}

    assert card.pack_id == "document-organizer-agent"
    assert card.pack_kind == "agent"
    assert card.source_kind == "cambrian_studio"
    assert card.installed is True
    assert card.reputation_verdict == "insufficient_data"
    assert card.used_count == 0
    assert card.outcome_linked_count == 0
    assert metrics["validated_proposal_rate"] is None
    assert any("not been used" in item for item in card.where_weak)
    assert any("local proof is not enough" in item for item in card.known_limits)
    assert any("do not present" in item for item in card.warnings)
    assert (tmp_path / saved_paths["yaml"]).exists()
    assert (tmp_path / saved_paths["md"]).exists()
    assert latest is not None
    assert latest.pack_id == "document-organizer-agent"


def test_studio_agent_proof_gap_creates_approval_gated_evolution_plan(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())

    PackInstaller().install(tmp_path, manifest_path)
    card = PackProofBuilder().build(tmp_path, "document-organizer-agent")
    save_pack_proof_card(tmp_path, card, format_kind="both")
    queue = PackImprovementQueueBuilder().build(tmp_path, "document-organizer-agent")
    save_pack_improvement_queue(tmp_path, queue)
    item = next(candidate for candidate in queue.items if candidate.kind == "improve_first_job_guide")
    plan_before_approval = PackDerivativePlanner().build(tmp_path, "document-organizer-agent")

    assert item.status == "open"
    assert item.priority == "medium"
    assert "runtime_evidence_gap" in item.source_signal_kinds
    assert plan_before_approval.safe_to_create_draft is False

    _, accepted_item, _ = record_pack_improvement_decision(
        tmp_path,
        item.item_id,
        "accepted",
        "Prepare the first verified Studio agent run before vNext.",
    )
    plan = PackDerivativePlanner().build(tmp_path, "document-organizer-agent")

    assert accepted_item.status == "accepted"
    assert plan.safe_to_create_draft is True
    assert plan.suggested_target_pack_id == "document-organizer-agent-v2"
    assert plan.suggested_version == "0.1.1"
    assert "first_job_guide_update" in {change.kind for change in plan.changes}


def test_job_start_pack_option_dispatches_studio_agent_and_updates_proof(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    manifest = _studio_agent_manifest()
    _write_yaml(manifest_path, manifest)
    PackInstaller().install(tmp_path, manifest_path)
    template = manifest["templates"][0]
    criteria = template["validation_defaults"]["validation_criteria"]
    safety = template["safety_defaults"]

    result = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "문서 폴더를 주제별로 정리해줘",
        "--json",
    )
    payload = json.loads(result.stdout)
    packet = yaml.safe_load((tmp_path / payload["request_packet_ref"]).read_text(encoding="utf-8"))
    contract = packet["execution_contract"]
    context = packet["active_pack_context"]
    job = payload["pack_job"]["result"]["job"]
    latest = latest_pack_proof_card(tmp_path, "document-organizer-agent")
    queue = PackImprovementQueueBuilder().build(tmp_path, "document-organizer-agent")

    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["harness_id"] == "document-organizer-agent"
    assert payload["selected_agents"] == ["document-organizer-agent"]
    assert payload["ai_provider_called"] is False
    assert payload["source_code_modified"] is False
    assert (tmp_path / payload["job_ref"]).exists()
    assert (tmp_path / payload["request_packet_ref"]).exists()
    assert job["pack_kind"] == "agent"
    assert job["active_template"] == "document-organizer-agent-template"
    assert job["usage_event_ref"]
    assert job["outcome_snapshot"]["proof_ref"]
    assert context["pack_kind"] == "agent"
    assert context["selected_agents"] == ["document-organizer-agent"]
    assert context["validation_criteria"] == criteria
    assert context["forbidden_actions"] == safety["forbidden_actions"]
    assert context["approval_required_actions"] == safety["approval_required_actions"]
    assert contract["selected_agents"] == ["document-organizer-agent"]
    assert contract["change_policy"] == "proposal_only"
    assert contract["validation_criteria"] == criteria
    assert contract["forbidden_actions"] == safety["forbidden_actions"]
    assert contract["approval_required_actions"] == safety["approval_required_actions"]
    assert job["outcome_snapshot"]["validation_criteria"] == criteria
    assert latest is not None
    assert latest.used_count == 1
    assert latest.outcome_linked_count == 0
    assert latest.reputation_verdict == "insufficient_data"
    assert "improve_validation_support" in {item.kind for item in queue.items}


def test_studio_agent_validation_evidence_includes_contract_criteria(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    manifest = _studio_agent_manifest()
    _write_yaml(manifest_path, manifest)
    PackInstaller().install(tmp_path, manifest_path)
    template = manifest["templates"][0]
    criteria = template["validation_defaults"]["validation_criteria"]
    safety = template["safety_defaults"]

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "문서 폴더를 주제별로 정리해줘",
        "--json",
    )
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    payload = json.loads(validate.stdout)
    evidence = yaml.safe_load((tmp_path / payload["evidence_ref"]).read_text(encoding="utf-8"))

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert payload["validation_status"] == "not_ready"
    assert payload["validation_criteria"] == criteria
    assert payload["validation_criteria_status"] == "manual_review_required"
    assert payload["forbidden_actions"] == safety["forbidden_actions"]
    assert payload["approval_required_actions"] == safety["approval_required_actions"]
    assert "Contract validation criteria require manual review" in payload["unchecked_items"]
    assert evidence["validation_criteria"] == criteria
    assert evidence["validation_criteria_status"] == "manual_review_required"
    assert evidence["forbidden_actions"] == safety["forbidden_actions"]
    assert evidence["approval_required_actions"] == safety["approval_required_actions"]
    assert evidence["source_code_modified"] is False
    assert evidence["ai_provider_called"] is False


def test_studio_agent_proof_card_surfaces_latest_validation_evidence(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    manifest = _studio_agent_manifest()
    _write_yaml(manifest_path, manifest)
    PackInstaller().install(tmp_path, manifest_path)
    criteria = manifest["templates"][0]["validation_defaults"]["validation_criteria"]

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "문서 폴더를 주제별로 정리해줘",
        "--json",
    )
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    payload = json.loads(validate.stdout)
    card = PackProofBuilder().build(tmp_path, "document-organizer-agent")
    metrics = {metric.key: metric.value for metric in card.key_metrics}
    claims = {claim.claim_id: claim for claim in card.claims}

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert metrics["contract_validation_status"] == "manual_review_required"
    assert metrics["contract_validation_criteria_count"] == len(criteria)
    assert claims["agent_contract_validation"].verdict == "manual_review_required"
    assert claims["agent_contract_validation"].evidence_refs == [payload["evidence_ref"]]
    assert card.source_refs["latest_validation_evidence_ref"] == payload["evidence_ref"]
    assert any("latest contract validation evidence is manual_review_required" in item for item in card.where_weak)
    assert any("contract validation evidence is not satisfied" in item for item in card.known_limits)


def test_studio_agent_manual_contract_review_satisfies_latest_proof(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    manifest = _studio_agent_manifest()
    _write_yaml(manifest_path, manifest)
    PackInstaller().install(tmp_path, manifest_path)
    criteria = manifest["templates"][0]["validation_defaults"]["validation_criteria"]

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "organize my documents by topic",
        "--json",
    )
    validate = _cli(
        tmp_path,
        "pack",
        "job-validate",
        "latest",
        "--criteria-status",
        "satisfied",
        "--criteria-notes",
        "local criteria reviewed",
        "--reviewer",
        "studio-owner",
        "--json",
    )
    payload = json.loads(validate.stdout)
    evidence = yaml.safe_load((tmp_path / payload["evidence_ref"]).read_text(encoding="utf-8"))
    latest = latest_pack_proof_card(tmp_path, "document-organizer-agent")
    metrics = {metric.key: metric.value for metric in latest.key_metrics} if latest is not None else {}
    claims = {claim.claim_id: claim for claim in latest.claims} if latest is not None else {}
    queue = PackImprovementQueueBuilder().build(tmp_path, "document-organizer-agent")
    source_signals = {signal for item in queue.items for signal in item.source_signal_kinds}

    assert start.returncode == 0, start.stderr
    assert validate.returncode == 0, validate.stderr
    assert payload["ok"] is True
    assert payload["validation_status"] == "validated"
    assert payload["validation_criteria"] == criteria
    assert payload["validation_criteria_status"] == "satisfied"
    assert payload["manual_contract_review"]["status"] == "satisfied"
    assert payload["manual_contract_review"]["reviewer"] == "studio-owner"
    assert payload["manual_contract_review"]["notes"] == "local criteria reviewed"
    assert payload["next_commands"][0] == "cambrian pack proof document-organizer-agent"
    assert "Contract validation criteria require manual review" not in payload["unchecked_items"]
    assert evidence["validation_criteria_status"] == "satisfied"
    assert evidence["manual_contract_review"]["reviewer"] == "studio-owner"
    assert latest is not None
    assert metrics["contract_validation_status"] == "satisfied"
    assert metrics["contract_validation_criteria_count"] == len(criteria)
    assert claims["agent_contract_validation"].verdict == "proven"
    assert latest.source_refs["latest_validation_evidence_ref"] == payload["evidence_ref"]
    assert "contract_validation_review_gap" not in source_signals


def test_studio_agent_contract_validation_gap_feeds_improvement_and_derivative_plan(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "문서 폴더를 주제별로 정리해줘",
        "--json",
    )
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    payload = json.loads(validate.stdout)
    latest = latest_pack_proof_card(tmp_path, "document-organizer-agent")
    metrics = {metric.key: metric.value for metric in latest.key_metrics} if latest is not None else {}
    queue = PackImprovementQueueBuilder().build(tmp_path, "document-organizer-agent")
    item = next(candidate for candidate in queue.items if candidate.kind == "improve_validation_support")

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert latest is not None
    assert metrics["contract_validation_status"] == "manual_review_required"
    assert "contract_validation_review_gap" in item.source_signal_kinds
    assert payload["evidence_ref"] in item.evidence_refs

    save_pack_improvement_queue(tmp_path, queue)
    _, accepted_item, _ = record_pack_improvement_decision(
        tmp_path,
        item.item_id,
        "accepted",
        "Strengthen Studio agent contract validation before vNext.",
    )
    plan = PackDerivativePlanner().build(tmp_path, "document-organizer-agent")
    change_kinds = {change.kind for change in plan.changes}

    assert accepted_item.status == "accepted"
    assert {"template_evolution_required", "benchmark_case_required"} <= change_kinds
    assert plan.suggested_version_bump == "minor"
    assert plan.unresolved_change_count >= 2
    assert any("required action is not implemented" in warning for change in plan.changes for warning in change.warnings)
