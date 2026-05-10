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
from engine.project_pack_proof_export import PackProofExporter


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


def test_studio_agent_pack_doctor_surfaces_contract_preflight(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

    result = _cli(tmp_path, "pack", "doctor", "document-organizer-agent", "--json")
    payload = json.loads(result.stdout)
    show = _cli(tmp_path, "pack", "doctor", "document-organizer-agent")
    checks = {check["check_id"]: check for check in payload["checks"]}
    preflight = checks["agent_contract_preflight"]
    first_job = checks["first_job_ready"]

    assert result.returncode == 0, result.stderr
    assert payload["pack_kind"] == "agent"
    assert payload["readiness_status"] == "partial"
    assert preflight["status"] == "pass"
    assert preflight["summary"] == "agent contract is ready for local preflight"
    assert first_job["status"] == "pass"
    assert first_job["summary"] == "agent worker/template context is available"
    assert any("source trust is unknown" in warning for warning in payload["warnings"])
    assert any("criteria=2" in detail for detail in preflight["details"])
    assert any("install policy: no auto apply/bootstrap/promote/canary" in detail for detail in preflight["details"])
    assert show.returncode == 0, show.stderr
    assert "Agent contract preflight" in show.stdout
    assert "criteria=2" in show.stdout


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
    assert any("--criteria-status satisfied" in command for command in payload["next_commands"])
    assert any("--criteria-status failed" in command for command in payload["next_commands"])
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


def test_studio_agent_proof_export_blocks_marketplace_until_contract_satisfied(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "organize my documents by topic",
        "--json",
    )
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    snapshot = PackProofExporter().export(tmp_path, "document-organizer-agent")

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert snapshot.privacy_classification == "public_safe"
    assert snapshot.marketplace_readiness == "blocked"
    assert "agent contract validation must be satisfied before marketplace listing" in snapshot.marketplace_blockers
    assert any("--criteria-status satisfied" in command for command in snapshot.marketplace_next_actions)


def test_studio_agent_marketplace_listing_blocks_before_contract_satisfied(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "organize my documents by topic",
        "--json",
    )
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    listing = _cli(tmp_path, "pack", "marketplace-export", "document-organizer-agent", "--json")
    payload = json.loads(listing.stdout)

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert listing.returncode != 0
    assert payload["listing_status"] == "blocked"
    assert payload["marketplace_readiness"] == "blocked"
    assert "agent contract validation must be satisfied before marketplace listing" in payload["marketplace_blockers"]
    assert Path(tmp_path / payload["saved_ref"]).exists()


def test_studio_agent_marketplace_show_reopens_blocked_listing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

    start = _cli(
        tmp_path,
        "job",
        "start",
        "--pack",
        "document-organizer-agent",
        "organize my documents by topic",
        "--json",
    )
    validate = _cli(tmp_path, "pack", "job-validate", "latest", "--json")
    listing = _cli(tmp_path, "pack", "marketplace-export", "document-organizer-agent", "--json")
    shown = _cli(tmp_path, "pack", "marketplace-show", "latest")

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert listing.returncode != 0
    assert shown.returncode == 0, shown.stderr
    assert "Pack Marketplace Listing Draft" in shown.stdout
    assert "status: blocked" in shown.stdout
    assert "agent contract validation must be satisfied before marketplace listing" in shown.stdout


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
    show = _cli(tmp_path, "pack", "job-show", "latest")
    payload = json.loads(validate.stdout)
    evidence = yaml.safe_load((tmp_path / payload["evidence_ref"]).read_text(encoding="utf-8"))
    latest = latest_pack_proof_card(tmp_path, "document-organizer-agent")
    metrics = {metric.key: metric.value for metric in latest.key_metrics} if latest is not None else {}
    claims = {claim.claim_id: claim for claim in latest.claims} if latest is not None else {}
    queue = PackImprovementQueueBuilder().build(tmp_path, "document-organizer-agent")
    source_signals = {signal for item in queue.items for signal in item.source_signal_kinds}

    assert start.returncode == 0, start.stderr
    assert validate.returncode == 0, validate.stderr
    assert show.returncode == 0, show.stderr
    assert payload["ok"] is True
    assert payload["validation_status"] == "validated"
    assert payload["validation_criteria"] == criteria
    assert payload["validation_criteria_status"] == "satisfied"
    assert payload["manual_contract_review"]["status"] == "satisfied"
    assert payload["manual_contract_review"]["reviewer"] == "studio-owner"
    assert payload["manual_contract_review"]["notes"] == "local criteria reviewed"
    assert payload["next_commands"][0] == "cambrian pack proof document-organizer-agent"
    assert "Contract validation criteria require manual review" not in payload["unchecked_items"]
    assert "Contract criteria:" in show.stdout
    assert "status: satisfied" in show.stdout
    assert "reviewer: studio-owner" in show.stdout
    assert "notes: local criteria reviewed" in show.stdout
    assert evidence["validation_criteria_status"] == "satisfied"
    assert evidence["manual_contract_review"]["reviewer"] == "studio-owner"
    assert latest is not None
    assert metrics["contract_validation_status"] == "satisfied"
    assert metrics["contract_validation_criteria_count"] == len(criteria)
    assert claims["agent_contract_validation"].verdict == "proven"
    assert latest.source_refs["latest_validation_evidence_ref"] == payload["evidence_ref"]
    assert "contract_validation_review_gap" not in source_signals


def test_studio_agent_satisfied_contract_exports_marketplace_draft_only(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

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
        "--json",
    )
    snapshot = PackProofExporter().export(tmp_path, "document-organizer-agent")
    metric_values = {metric.key: metric.value for metric in snapshot.public_metrics}

    assert start.returncode == 0, start.stderr
    assert validate.returncode == 0, validate.stderr
    assert snapshot.privacy_classification == "public_safe"
    assert snapshot.marketplace_readiness == "draft_only"
    assert snapshot.marketplace_blockers == []
    assert metric_values["contract_validation_status"] == "satisfied"
    assert any("representative request" in command for command in snapshot.marketplace_next_actions)


def test_studio_agent_marketplace_listing_draft_preserves_manifest_metadata(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

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
        "--json",
    )
    listing = _cli(tmp_path, "pack", "marketplace-export", "document-organizer-agent", "--json")
    payload = json.loads(listing.stdout)
    shown = _cli(tmp_path, "pack", "marketplace-show", "latest", "--json")
    shown_payload = json.loads(shown.stdout)
    status = _cli(tmp_path, "pack", "marketplace-status", "latest", "--json")
    status_payload = json.loads(status.stdout)
    status_list = _cli(tmp_path, "pack", "marketplace-status-list", "--json")
    status_list_payload = json.loads(status_list.stdout)

    assert start.returncode == 0, start.stderr
    assert validate.returncode == 0, validate.stderr
    assert listing.returncode == 0, listing.stderr
    assert shown.returncode == 0, shown.stderr
    assert status.returncode == 0, status.stderr
    assert status_list.returncode == 0, status_list.stderr
    assert payload["pack_id"] == "document-organizer-agent"
    assert payload["pack_kind"] == "agent"
    assert payload["author"] == "local-author"
    assert payload["license"] == "personal_local"
    assert payload["provenance"] == "studio_generated"
    assert payload["public_visibility"] == "private"
    assert payload["signature_status"] == "unsigned_local"
    assert payload["marketplace_readiness"] == "draft_only"
    assert payload["listing_status"] == "draft_only"
    assert payload["safe_to_publish"] is False
    assert payload["manifest_sha256"]
    assert payload["proof_export_ref"]
    assert "OCR이 필요한 스캔 PDF는 별도 도구가 필요할 수 있다." in payload["known_limits"]
    assert Path(tmp_path / payload["saved_ref"]).exists()
    assert shown_payload["listing_id"] == payload["listing_id"]
    assert shown_payload["path"].endswith("latest.yaml")
    assert shown_payload["latest_review"] is None
    assert status_payload["listing_id"] == payload["listing_id"]
    assert status_payload["operational_status"] == "draft_only"
    assert status_payload["latest_review_decision"] is None
    assert status_list_payload["count"] == 1
    assert status_list_payload["summary"]["total"] == 1
    assert status_list_payload["summary"]["draft_only"] == 1
    assert status_list_payload["statuses"][0]["listing_id"] == payload["listing_id"]
    assert status_list_payload["statuses"][0]["operational_status"] == "draft_only"


def test_studio_agent_marketplace_review_records_needs_work(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

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
        "--json",
    )
    listing = _cli(tmp_path, "pack", "marketplace-export", "document-organizer-agent", "--json")
    review = _cli(
        tmp_path,
        "pack",
        "marketplace-review",
        "latest",
        "--decision",
        "needs_work",
        "--notes",
        "Collect more runtime evidence before public listing.",
        "--reviewer",
        "studio-owner",
        "--json",
    )
    payload = json.loads(review.stdout)
    shown = _cli(tmp_path, "pack", "marketplace-review-show", "latest", "--json")
    shown_payload = json.loads(shown.stdout)
    shown_by_path = _cli(tmp_path, "pack", "marketplace-review-show", payload["saved_ref"], "--json")
    shown_by_path_payload = json.loads(shown_by_path.stdout)
    shown_text = _cli(tmp_path, "pack", "marketplace-review-show", "latest")
    listed = _cli(tmp_path, "pack", "marketplace-review-list", "--json")
    listed_payload = json.loads(listed.stdout)
    listed_text = _cli(tmp_path, "pack", "marketplace-review-list")
    listing_with_review = _cli(tmp_path, "pack", "marketplace-show", "latest", "--json")
    listing_with_review_payload = json.loads(listing_with_review.stdout)
    listing_with_review_text = _cli(tmp_path, "pack", "marketplace-show", "latest")
    status = _cli(tmp_path, "pack", "marketplace-status", "latest", "--json")
    status_payload = json.loads(status.stdout)
    status_text = _cli(tmp_path, "pack", "marketplace-status", "latest")
    status_list = _cli(tmp_path, "pack", "marketplace-status-list", "--json")
    status_list_payload = json.loads(status_list.stdout)
    status_list_text = _cli(tmp_path, "pack", "marketplace-status-list")
    filtered_status_list = _cli(tmp_path, "pack", "marketplace-status-list", "--status", "needs_work", "--json")
    filtered_status_list_payload = json.loads(filtered_status_list.stdout)
    empty_status_list = _cli(tmp_path, "pack", "marketplace-status-list", "--status", "ready_for_review", "--json")
    empty_status_list_payload = json.loads(empty_status_list.stdout)
    saved_status_list = _cli(
        tmp_path,
        "pack",
        "marketplace-status-list",
        "--status",
        "needs_work",
        "--save",
        "--json",
    )
    saved_status_list_payload = json.loads(saved_status_list.stdout)
    shown_status_dashboard = _cli(tmp_path, "pack", "marketplace-status-show", "latest", "--json")
    shown_status_dashboard_payload = json.loads(shown_status_dashboard.stdout)
    shown_status_dashboard_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-show",
        saved_status_list_payload["saved_ref"],
        "--json",
    )
    shown_status_dashboard_by_path_payload = json.loads(shown_status_dashboard_by_path.stdout)
    shown_status_dashboard_text = _cli(tmp_path, "pack", "marketplace-status-show", "latest")
    checked_status_dashboard = _cli(tmp_path, "pack", "marketplace-status-check", "latest", "--json")
    checked_status_dashboard_payload = json.loads(checked_status_dashboard.stdout)
    checked_status_dashboard_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-check",
        saved_status_list_payload["saved_ref"],
        "--json",
    )
    checked_status_dashboard_by_path_payload = json.loads(checked_status_dashboard_by_path.stdout)
    checked_status_dashboard_text = _cli(tmp_path, "pack", "marketplace-status-check", "latest")
    saved_status_dashboard_check = _cli(tmp_path, "pack", "marketplace-status-check", "latest", "--save", "--json")
    saved_status_dashboard_check_payload = json.loads(saved_status_dashboard_check.stdout)
    shown_status_dashboard_check = _cli(tmp_path, "pack", "marketplace-status-check-show", "latest", "--json")
    shown_status_dashboard_check_payload = json.loads(shown_status_dashboard_check.stdout)
    shown_status_dashboard_check_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-check-show",
        saved_status_dashboard_check_payload["saved_ref"],
        "--json",
    )
    shown_status_dashboard_check_by_path_payload = json.loads(shown_status_dashboard_check_by_path.stdout)
    shown_status_dashboard_check_text = _cli(tmp_path, "pack", "marketplace-status-check-show", "latest")
    status_ready = _cli(tmp_path, "pack", "marketplace-status-ready", "--json")
    status_ready_payload = json.loads(status_ready.stdout)
    status_ready_text = _cli(tmp_path, "pack", "marketplace-status-ready")
    saved_status_ready = _cli(tmp_path, "pack", "marketplace-status-ready", "--save", "--json")
    saved_status_ready_payload = json.loads(saved_status_ready.stdout)
    shown_status_ready = _cli(tmp_path, "pack", "marketplace-status-ready-show", "latest", "--json")
    shown_status_ready_payload = json.loads(shown_status_ready.stdout)
    shown_status_ready_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-ready-show",
        saved_status_ready_payload["saved_ref"],
        "--json",
    )
    shown_status_ready_by_path_payload = json.loads(shown_status_ready_by_path.stdout)
    shown_status_ready_text = _cli(tmp_path, "pack", "marketplace-status-ready-show", "latest")
    checked_status_ready = _cli(tmp_path, "pack", "marketplace-status-ready-check", "latest", "--json")
    checked_status_ready_payload = json.loads(checked_status_ready.stdout)
    checked_status_ready_text = _cli(tmp_path, "pack", "marketplace-status-ready-check", "latest")
    saved_status_ready_check = _cli(tmp_path, "pack", "marketplace-status-ready-check", "latest", "--save", "--json")
    saved_status_ready_check_payload = json.loads(saved_status_ready_check.stdout)
    shown_status_ready_check = _cli(tmp_path, "pack", "marketplace-status-ready-check-show", "latest", "--json")
    shown_status_ready_check_payload = json.loads(shown_status_ready_check.stdout)
    shown_status_ready_check_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-ready-check-show",
        saved_status_ready_check_payload["saved_ref"],
        "--json",
    )
    shown_status_ready_check_by_path_payload = json.loads(shown_status_ready_check_by_path.stdout)
    shown_status_ready_check_text = _cli(tmp_path, "pack", "marketplace-status-ready-check-show", "latest")
    studio_handoff = _cli(tmp_path, "pack", "marketplace-status-studio", "--json")
    studio_handoff_payload = json.loads(studio_handoff.stdout)
    studio_handoff_text = _cli(tmp_path, "pack", "marketplace-status-studio")
    saved_studio_handoff = _cli(tmp_path, "pack", "marketplace-status-studio", "--save", "--json")
    saved_studio_handoff_payload = json.loads(saved_studio_handoff.stdout)
    shown_studio_handoff = _cli(tmp_path, "pack", "marketplace-status-studio-show", "latest", "--json")
    shown_studio_handoff_payload = json.loads(shown_studio_handoff.stdout)
    shown_studio_handoff_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-studio-show",
        saved_studio_handoff_payload["saved_ref"],
        "--json",
    )
    shown_studio_handoff_by_path_payload = json.loads(shown_studio_handoff_by_path.stdout)
    shown_studio_handoff_text = _cli(tmp_path, "pack", "marketplace-status-studio-show", "latest")
    checked_studio_handoff = _cli(tmp_path, "pack", "marketplace-status-studio-check", "latest", "--json")
    checked_studio_handoff_payload = json.loads(checked_studio_handoff.stdout)
    checked_studio_handoff_text = _cli(tmp_path, "pack", "marketplace-status-studio-check", "latest")
    saved_studio_handoff_check = _cli(tmp_path, "pack", "marketplace-status-studio-check", "latest", "--save", "--json")
    saved_studio_handoff_check_payload = json.loads(saved_studio_handoff_check.stdout)
    shown_studio_handoff_check = _cli(tmp_path, "pack", "marketplace-status-studio-check-show", "latest", "--json")
    shown_studio_handoff_check_payload = json.loads(shown_studio_handoff_check.stdout)
    shown_studio_handoff_check_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-studio-check-show",
        saved_studio_handoff_check_payload["saved_ref"],
        "--json",
    )
    shown_studio_handoff_check_by_path_payload = json.loads(shown_studio_handoff_check_by_path.stdout)
    shown_studio_handoff_check_text = _cli(tmp_path, "pack", "marketplace-status-studio-check-show", "latest")
    studio_refresh = _cli(tmp_path, "pack", "marketplace-status-studio-refresh", "--status", "needs_work", "--json")
    studio_refresh_payload = json.loads(studio_refresh.stdout)
    studio_refresh_text = _cli(tmp_path, "pack", "marketplace-status-studio-refresh", "--status", "needs_work")
    shown_studio_refresh = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-show", "latest", "--json")
    shown_studio_refresh_payload = json.loads(shown_studio_refresh.stdout)
    shown_studio_refresh_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-studio-refresh-show",
        studio_refresh_payload["saved_ref"],
        "--json",
    )
    shown_studio_refresh_by_path_payload = json.loads(shown_studio_refresh_by_path.stdout)
    shown_studio_refresh_text = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-show", "latest")
    checked_studio_refresh = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-check", "latest", "--json")
    checked_studio_refresh_payload = json.loads(checked_studio_refresh.stdout)
    checked_studio_refresh_text = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-check", "latest")
    saved_studio_refresh_check = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-check", "latest", "--save", "--json")
    saved_studio_refresh_check_payload = json.loads(saved_studio_refresh_check.stdout)
    shown_studio_refresh_check = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-check-show", "latest", "--json")
    shown_studio_refresh_check_payload = json.loads(shown_studio_refresh_check.stdout)
    shown_studio_refresh_check_by_path = _cli(
        tmp_path,
        "pack",
        "marketplace-status-studio-refresh-check-show",
        saved_studio_refresh_check_payload["saved_ref"],
        "--json",
    )
    shown_studio_refresh_check_by_path_payload = json.loads(shown_studio_refresh_check_by_path.stdout)
    shown_studio_refresh_check_text = _cli(tmp_path, "pack", "marketplace-status-studio-refresh-check-show", "latest")

    assert start.returncode == 0, start.stderr
    assert validate.returncode == 0, validate.stderr
    assert listing.returncode == 0, listing.stderr
    assert review.returncode == 0, review.stderr
    assert shown.returncode == 0, shown.stderr
    assert shown_by_path.returncode == 0, shown_by_path.stderr
    assert shown_text.returncode == 0, shown_text.stderr
    assert listed.returncode == 0, listed.stderr
    assert listed_text.returncode == 0, listed_text.stderr
    assert listing_with_review.returncode == 0, listing_with_review.stderr
    assert listing_with_review_text.returncode == 0, listing_with_review_text.stderr
    assert status.returncode == 0, status.stderr
    assert status_text.returncode == 0, status_text.stderr
    assert status_list.returncode == 0, status_list.stderr
    assert status_list_text.returncode == 0, status_list_text.stderr
    assert filtered_status_list.returncode == 0, filtered_status_list.stderr
    assert empty_status_list.returncode == 0, empty_status_list.stderr
    assert saved_status_list.returncode == 0, saved_status_list.stderr
    assert shown_status_dashboard.returncode == 0, shown_status_dashboard.stderr
    assert shown_status_dashboard_by_path.returncode == 0, shown_status_dashboard_by_path.stderr
    assert shown_status_dashboard_text.returncode == 0, shown_status_dashboard_text.stderr
    assert checked_status_dashboard.returncode == 0, checked_status_dashboard.stderr
    assert checked_status_dashboard_by_path.returncode == 0, checked_status_dashboard_by_path.stderr
    assert checked_status_dashboard_text.returncode == 0, checked_status_dashboard_text.stderr
    assert saved_status_dashboard_check.returncode == 0, saved_status_dashboard_check.stderr
    assert shown_status_dashboard_check.returncode == 0, shown_status_dashboard_check.stderr
    assert shown_status_dashboard_check_by_path.returncode == 0, shown_status_dashboard_check_by_path.stderr
    assert shown_status_dashboard_check_text.returncode == 0, shown_status_dashboard_check_text.stderr
    assert status_ready.returncode == 0, status_ready.stderr
    assert status_ready_text.returncode == 0, status_ready_text.stderr
    assert saved_status_ready.returncode == 0, saved_status_ready.stderr
    assert shown_status_ready.returncode == 0, shown_status_ready.stderr
    assert shown_status_ready_by_path.returncode == 0, shown_status_ready_by_path.stderr
    assert shown_status_ready_text.returncode == 0, shown_status_ready_text.stderr
    assert checked_status_ready.returncode == 0, checked_status_ready.stderr
    assert checked_status_ready_text.returncode == 0, checked_status_ready_text.stderr
    assert saved_status_ready_check.returncode == 0, saved_status_ready_check.stderr
    assert shown_status_ready_check.returncode == 0, shown_status_ready_check.stderr
    assert shown_status_ready_check_by_path.returncode == 0, shown_status_ready_check_by_path.stderr
    assert shown_status_ready_check_text.returncode == 0, shown_status_ready_check_text.stderr
    assert studio_handoff.returncode == 0, studio_handoff.stderr
    assert studio_handoff_text.returncode == 0, studio_handoff_text.stderr
    assert saved_studio_handoff.returncode == 0, saved_studio_handoff.stderr
    assert shown_studio_handoff.returncode == 0, shown_studio_handoff.stderr
    assert shown_studio_handoff_by_path.returncode == 0, shown_studio_handoff_by_path.stderr
    assert shown_studio_handoff_text.returncode == 0, shown_studio_handoff_text.stderr
    assert checked_studio_handoff.returncode == 0, checked_studio_handoff.stderr
    assert checked_studio_handoff_text.returncode == 0, checked_studio_handoff_text.stderr
    assert saved_studio_handoff_check.returncode == 0, saved_studio_handoff_check.stderr
    assert shown_studio_handoff_check.returncode == 0, shown_studio_handoff_check.stderr
    assert shown_studio_handoff_check_by_path.returncode == 0, shown_studio_handoff_check_by_path.stderr
    assert shown_studio_handoff_check_text.returncode == 0, shown_studio_handoff_check_text.stderr
    assert studio_refresh.returncode == 0, studio_refresh.stderr
    assert studio_refresh_text.returncode == 0, studio_refresh_text.stderr
    assert shown_studio_refresh.returncode == 0, shown_studio_refresh.stderr
    assert shown_studio_refresh_by_path.returncode == 0, shown_studio_refresh_by_path.stderr
    assert shown_studio_refresh_text.returncode == 0, shown_studio_refresh_text.stderr
    assert checked_studio_refresh.returncode == 0, checked_studio_refresh.stderr
    assert checked_studio_refresh_text.returncode == 0, checked_studio_refresh_text.stderr
    assert saved_studio_refresh_check.returncode == 0, saved_studio_refresh_check.stderr
    assert shown_studio_refresh_check.returncode == 0, shown_studio_refresh_check.stderr
    assert shown_studio_refresh_check_by_path.returncode == 0, shown_studio_refresh_check_by_path.stderr
    assert shown_studio_refresh_check_text.returncode == 0, shown_studio_refresh_check_text.stderr
    assert payload["decision"] == "needs_work"
    assert payload["reviewer"] == "studio-owner"
    assert payload["notes"] == "Collect more runtime evidence before public listing."
    assert payload["safe_to_publish"] is False
    assert payload["marketplace_readiness"] == "draft_only"
    assert "listing visibility is not public" in payload["blockers"]
    assert Path(tmp_path / payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "reviews" / "latest.yaml").exists()
    assert shown_payload["review_id"] == payload["review_id"]
    assert shown_payload["path"].endswith("latest.yaml")
    assert shown_by_path_payload["review_id"] == payload["review_id"]
    assert "Pack Marketplace Review" in shown_text.stdout
    assert "needs_work" in shown_text.stdout
    assert listed_payload["count"] == 1
    assert listed_payload["reviews"][0]["review_id"] == payload["review_id"]
    assert "Pack Marketplace Reviews" in listed_text.stdout
    assert payload["review_id"] in listed_text.stdout
    assert listing_with_review_payload["latest_review"]["review_id"] == payload["review_id"]
    assert listing_with_review_payload["latest_review"]["decision"] == "needs_work"
    assert "Latest review:" in listing_with_review_text.stdout
    assert "decision: needs_work" in listing_with_review_text.stdout
    assert status_payload["operational_status"] == "needs_work"
    assert status_payload["latest_review_decision"] == "needs_work"
    assert "listing visibility is not public" in status_payload["blockers"]
    assert "Pack Marketplace Status" in status_text.stdout
    assert "operational_status: needs_work" in status_text.stdout
    assert status_list_payload["count"] == 1
    assert status_list_payload["summary"]["total"] == 1
    assert status_list_payload["summary"]["needs_work"] == 1
    assert status_list_payload["statuses"][0]["operational_status"] == "needs_work"
    assert status_list_payload["statuses"][0]["latest_review_decision"] == "needs_work"
    assert "Pack Marketplace Status List" in status_list_text.stdout
    assert "Summary:" in status_list_text.stdout
    assert "needs_work" in status_list_text.stdout
    assert filtered_status_list_payload["status_filter"] == "needs_work"
    assert filtered_status_list_payload["count"] == 1
    assert filtered_status_list_payload["summary"]["needs_work"] == 1
    assert empty_status_list_payload["status_filter"] == "ready_for_review"
    assert empty_status_list_payload["count"] == 0
    assert empty_status_list_payload["summary"]["total"] == 0
    assert saved_status_list_payload["status_filter"] == "needs_work"
    assert saved_status_list_payload["summary"]["needs_work"] == 1
    assert Path(tmp_path / saved_status_list_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "latest.yaml").exists()
    assert shown_status_dashboard_payload["status_filter"] == "needs_work"
    assert shown_status_dashboard_payload["path"].endswith("latest.yaml")
    assert shown_status_dashboard_payload["summary"]["needs_work"] == 1
    assert shown_status_dashboard_by_path_payload["status_filter"] == "needs_work"
    assert shown_status_dashboard_by_path_payload["statuses"][0]["operational_status"] == "needs_work"
    assert "Pack Marketplace Status Dashboard" in shown_status_dashboard_text.stdout
    assert "Status filter: needs_work" in shown_status_dashboard_text.stdout
    assert checked_status_dashboard_payload["ok"] is True
    assert checked_status_dashboard_payload["error_count"] == 0
    assert checked_status_dashboard_payload["status_ref"].endswith("latest.yaml")
    assert checked_status_dashboard_by_path_payload["ok"] is True
    assert checked_status_dashboard_by_path_payload["error_count"] == 0
    assert "Pack Marketplace Status Check" in checked_status_dashboard_text.stdout
    assert "OK: true" in checked_status_dashboard_text.stdout
    assert saved_status_dashboard_check_payload["ok"] is True
    assert saved_status_dashboard_check_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / saved_status_dashboard_check_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "checks" / "latest.yaml").exists()
    assert shown_status_dashboard_check_payload["ok"] is True
    assert shown_status_dashboard_check_payload["path"].endswith("latest.yaml")
    assert shown_status_dashboard_check_by_path_payload["ok"] is True
    assert shown_status_dashboard_check_by_path_payload["saved_ref"] == saved_status_dashboard_check_payload["saved_ref"]
    assert "Pack Marketplace Status Check" in shown_status_dashboard_check_text.stdout
    assert "Saved:" in shown_status_dashboard_check_text.stdout
    assert status_ready_payload["ready_for_studio"] is True
    assert status_ready_payload["check_ok"] is True
    assert status_ready_payload["dashboard"]["status_filter"] == "needs_work"
    assert status_ready_payload["check"]["ok"] is True
    assert "Pack Marketplace Status Ready" in status_ready_text.stdout
    assert "Ready for Studio: true" in status_ready_text.stdout
    assert saved_status_ready_payload["ready_for_studio"] is True
    assert saved_status_ready_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / saved_status_ready_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "ready" / "latest.yaml").exists()
    assert shown_status_ready_payload["ready_for_studio"] is True
    assert shown_status_ready_payload["path"].endswith("latest.yaml")
    assert shown_status_ready_by_path_payload["saved_ref"] == saved_status_ready_payload["saved_ref"]
    assert shown_status_ready_by_path_payload["dashboard"]["status_filter"] == "needs_work"
    assert "Pack Marketplace Status Ready" in shown_status_ready_text.stdout
    assert "Saved:" in shown_status_ready_text.stdout
    assert checked_status_ready_payload["ok"] is True
    assert checked_status_ready_payload["ready_for_studio"] is True
    assert checked_status_ready_payload["ready_ref"].endswith("latest.yaml")
    assert checked_status_ready_payload["error_count"] == 0
    assert "Pack Marketplace Status Ready Check" in checked_status_ready_text.stdout
    assert "OK: true" in checked_status_ready_text.stdout
    assert saved_status_ready_check_payload["ok"] is True
    assert saved_status_ready_check_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / saved_status_ready_check_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "ready" / "checks" / "latest.yaml").exists()
    assert shown_status_ready_check_payload["ok"] is True
    assert shown_status_ready_check_payload["path"].endswith("latest.yaml")
    assert shown_status_ready_check_by_path_payload["saved_ref"] == saved_status_ready_check_payload["saved_ref"]
    assert shown_status_ready_check_by_path_payload["ready_for_studio"] is True
    assert "Pack Marketplace Status Ready Check" in shown_status_ready_check_text.stdout
    assert "Saved:" in shown_status_ready_check_text.stdout
    assert studio_handoff_payload["studio_handoff_ready"] is True
    assert studio_handoff_payload["ready_for_studio"] is True
    assert studio_handoff_payload["ready_check_ok"] is True
    assert studio_handoff_payload["dashboard"]["status_filter"] == "needs_work"
    assert studio_handoff_payload["ready"]["ready_for_studio"] is True
    assert studio_handoff_payload["ready_check"]["ok"] is True
    assert "Pack Marketplace Status Studio Handoff" in studio_handoff_text.stdout
    assert "Studio handoff ready: true" in studio_handoff_text.stdout
    assert saved_studio_handoff_payload["studio_handoff_ready"] is True
    assert saved_studio_handoff_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / saved_studio_handoff_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "studio" / "latest.yaml").exists()
    assert shown_studio_handoff_payload["studio_handoff_ready"] is True
    assert shown_studio_handoff_payload["path"].endswith("latest.yaml")
    assert shown_studio_handoff_by_path_payload["saved_ref"] == saved_studio_handoff_payload["saved_ref"]
    assert shown_studio_handoff_by_path_payload["ready_check"]["ok"] is True
    assert "Pack Marketplace Status Studio Handoff" in shown_studio_handoff_text.stdout
    assert "Saved:" in shown_studio_handoff_text.stdout
    assert checked_studio_handoff_payload["ok"] is True
    assert checked_studio_handoff_payload["studio_handoff_ready"] is True
    assert checked_studio_handoff_payload["ready_for_studio"] is True
    assert checked_studio_handoff_payload["handoff_ref"].endswith("latest.yaml")
    assert checked_studio_handoff_payload["error_count"] == 0
    assert "Pack Marketplace Status Studio Check" in checked_studio_handoff_text.stdout
    assert "OK: true" in checked_studio_handoff_text.stdout
    assert saved_studio_handoff_check_payload["ok"] is True
    assert saved_studio_handoff_check_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / saved_studio_handoff_check_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "studio" / "checks" / "latest.yaml").exists()
    assert shown_studio_handoff_check_payload["ok"] is True
    assert shown_studio_handoff_check_payload["path"].endswith("latest.yaml")
    assert shown_studio_handoff_check_by_path_payload["saved_ref"] == saved_studio_handoff_check_payload["saved_ref"]
    assert shown_studio_handoff_check_by_path_payload["studio_handoff_ready"] is True
    assert "Pack Marketplace Status Studio Check" in shown_studio_handoff_check_text.stdout
    assert "Saved:" in shown_studio_handoff_check_text.stdout
    assert studio_refresh_payload["studio_refresh_ok"] is True
    assert studio_refresh_payload["studio_handoff_ready"] is True
    assert studio_refresh_payload["studio_check_ok"] is True
    assert studio_refresh_payload["status_filter"] == "needs_work"
    assert studio_refresh_payload["count"] == 1
    assert studio_refresh_payload["refs"]["dashboard"].endswith(".yaml")
    assert studio_refresh_payload["refs"]["dashboard_check"].endswith(".yaml")
    assert studio_refresh_payload["refs"]["ready"].endswith(".yaml")
    assert studio_refresh_payload["refs"]["ready_check"].endswith(".yaml")
    assert studio_refresh_payload["refs"]["studio_handoff"].endswith(".yaml")
    assert studio_refresh_payload["refs"]["studio_check"].endswith(".yaml")
    assert Path(tmp_path / studio_refresh_payload["refs"]["studio_handoff"]).exists()
    assert Path(tmp_path / studio_refresh_payload["refs"]["studio_check"]).exists()
    assert studio_refresh_payload["studio_handoff"]["studio_handoff_ready"] is True
    assert studio_refresh_payload["studio_check"]["ok"] is True
    assert studio_refresh_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / studio_refresh_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "studio" / "refreshes" / "latest.yaml").exists()
    assert "Pack Marketplace Status Studio Refresh" in studio_refresh_text.stdout
    assert "Refresh OK: true" in studio_refresh_text.stdout
    assert "Saved:" in studio_refresh_text.stdout
    assert shown_studio_refresh_payload["studio_refresh_ok"] is True
    assert shown_studio_refresh_payload["path"].endswith("latest.yaml")
    assert shown_studio_refresh_by_path_payload["saved_ref"] == studio_refresh_payload["saved_ref"]
    assert shown_studio_refresh_by_path_payload["refs"]["studio_handoff"] == studio_refresh_payload["refs"]["studio_handoff"]
    assert "Pack Marketplace Status Studio Refresh" in shown_studio_refresh_text.stdout
    assert "Saved:" in shown_studio_refresh_text.stdout
    assert checked_studio_refresh_payload["ok"] is True
    assert checked_studio_refresh_payload["studio_refresh_ok"] is True
    assert checked_studio_refresh_payload["refresh_ref"].endswith("latest.yaml")
    assert checked_studio_refresh_payload["studio_handoff_ref"].endswith(".yaml")
    assert checked_studio_refresh_payload["studio_check_ref"].endswith(".yaml")
    assert checked_studio_refresh_payload["error_count"] == 0
    assert "Pack Marketplace Status Studio Refresh Check" in checked_studio_refresh_text.stdout
    assert "OK: true" in checked_studio_refresh_text.stdout
    assert saved_studio_refresh_check_payload["ok"] is True
    assert saved_studio_refresh_check_payload["saved_ref"].endswith(".yaml")
    assert Path(tmp_path / saved_studio_refresh_check_payload["saved_ref"]).exists()
    assert (tmp_path / ".cambrian" / "packs" / "marketplace" / "status" / "studio" / "refreshes" / "checks" / "latest.yaml").exists()
    assert shown_studio_refresh_check_payload["ok"] is True
    assert shown_studio_refresh_check_payload["path"].endswith("latest.yaml")
    assert shown_studio_refresh_check_by_path_payload["saved_ref"] == saved_studio_refresh_check_payload["saved_ref"]
    assert shown_studio_refresh_check_by_path_payload["studio_refresh_ok"] is True
    assert "Pack Marketplace Status Studio Refresh Check" in shown_studio_refresh_check_text.stdout
    assert "Saved:" in shown_studio_refresh_check_text.stdout


def test_marketplace_status_artifact_paths_are_unique_inside_same_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime as real_datetime
    from datetime import timezone

    from engine import project_pack_marketplace as marketplace

    class SequenceDateTime:
        tick = 0

        @classmethod
        def now(cls, tz=None):
            cls.tick += 1
            return real_datetime(2026, 5, 10, 1, 2, 3, cls.tick, tzinfo=timezone.utc)

    monkeypatch.setattr(marketplace, "datetime", SequenceDateTime)

    first = marketplace.default_marketplace_status_path(tmp_path)
    second = marketplace.default_marketplace_status_path(tmp_path)

    assert first != second
    assert first.name == "status_20260510_010203_000001.yaml"
    assert second.name == "status_20260510_010203_000002.yaml"


def test_studio_agent_marketplace_review_blocks_accept_before_publish_safe(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

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
        "--json",
    )
    listing = _cli(tmp_path, "pack", "marketplace-export", "document-organizer-agent", "--json")
    review = _cli(tmp_path, "pack", "marketplace-review", "latest", "--decision", "accepted", "--json")

    assert start.returncode == 0, start.stderr
    assert validate.returncode == 0, validate.stderr
    assert listing.returncode == 0, listing.stderr
    assert review.returncode != 0
    assert "cannot be accepted until safe_to_publish is true" in review.stderr


def test_studio_agent_manual_contract_review_failure_blocks_latest_proof(tmp_path: Path) -> None:
    manifest_path = tmp_path / "document-organizer-agent.cambrian-pack.yaml"
    _write_yaml(manifest_path, _studio_agent_manifest())
    PackInstaller().install(tmp_path, manifest_path)

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
        "failed",
        "--criteria-notes",
        "output missed required exception list",
        "--json",
    )
    payload = json.loads(validate.stdout)
    latest = latest_pack_proof_card(tmp_path, "document-organizer-agent")
    metrics = {metric.key: metric.value for metric in latest.key_metrics} if latest is not None else {}
    claims = {claim.claim_id: claim for claim in latest.claims} if latest is not None else {}
    queue = PackImprovementQueueBuilder().build(tmp_path, "document-organizer-agent")
    item = next(candidate for candidate in queue.items if candidate.kind == "improve_validation_support")

    assert start.returncode == 0, start.stderr
    assert validate.returncode != 0
    assert payload["ok"] is False
    assert payload["validation_status"] == "failed"
    assert payload["validation_criteria_status"] == "failed"
    assert payload["manual_contract_review"]["status"] == "failed"
    assert "Contract validation criteria failed manual review" in payload["unchecked_items"]
    assert latest is not None
    assert metrics["contract_validation_status"] == "failed"
    assert claims["agent_contract_validation"].verdict == "failed"
    assert "contract_validation_review_gap" in item.source_signal_kinds
    assert payload["evidence_ref"] in item.evidence_refs


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
