import json
import hashlib
from pathlib import Path

import pytest

from scripts.audit_external_alpha_send_chain import (
    SendChainAuditError,
    _source_files_match_release_manifest,
    audit_send_chain,
)
from scripts.audit_external_alpha_operator_send_bypass import (
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    audit_operator_send_bypass,
)
from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_pilot_iteration import check_pilot_iteration
from scripts.prepare_external_alpha_first_recipient_send_workspace import prepare_first_recipient_send_workspace
from scripts.prepare_external_alpha_handoff import HANDOFF_JSON_NAME, _handoff_body_sha256, _handoff_checks
from scripts.prepare_external_alpha_operator_dispatch_packet import (
    PACKET_JSON_NAME,
    _packet_body_sha256,
    prepare_operator_dispatch_packet,
)
from scripts.smoke_external_alpha_manual_send_go_rehearsal import (
    MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
    _receipt_body_sha256 as _manual_rehearsal_body_sha256,
    smoke_manual_send_go_rehearsal,
)
from scripts.smoke_external_alpha_release_bundle import SMOKE_RECEIPT_NAME, smoke_release_bundle


def test_external_alpha_send_chain_audit_passes_without_rewriting_artifacts(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    before = _file_hashes(tmp_path)

    result = audit_send_chain(tmp_path)

    assert result["status"] == "pass"
    assert result["verdict"] == "READY_TO_SEND_ONE"
    assert result["checks"]["receipt_matches_handoff"] is True
    assert result["checks"]["release_sources_match_current_manifest"] is True
    assert result["checks"]["receipt_matches_send_ready"] is True
    assert result["checks"]["send_ready_receipt_cross_check"] is True
    assert result["checks"]["bundle_smoke_verified"] is True
    assert result["checks"]["bundle_smoke_release_hash_matches"] is True
    assert result["checks"]["operator_packet_ready_to_send_one"] is True
    assert result["checks"]["operator_packet_release_hash_matches"] is True
    assert result["checks"]["operator_packet_self_checks_passed"] is True
    assert result["checks"]["operator_packet_recalculated_self_checks_match"] is True
    assert result["checks"]["operator_packet_post_send_real_preflight_gate"] is True
    assert result["checks"]["operator_packet_post_send_template_contract"] is True
    assert result["checks"]["operator_send_bypass_audit_verified"] is True
    assert result["checks"]["operator_send_bypass_audit_release_hash_matches"] is True
    assert result["checks"]["operator_send_bypass_audit_packet_hash_matches"] is True
    assert result["checks"]["manual_send_go_rehearsal_verified"] is True
    assert result["checks"]["manual_send_go_rehearsal_release_hash_matches"] is True
    assert result["checks"]["manual_send_go_rehearsal_no_real_manual_send_claim"] is True
    assert result["checks"]["manual_send_go_rehearsal_no_real_recipient_claim"] is True
    assert result["checks"]["manual_send_go_rehearsal_template_contract"] is True
    assert result["checks"]["manual_send_go_rehearsal_operator_status_ready"] is True
    assert result["checks"]["manual_send_go_rehearsal_operator_status_packet_bound"] is True
    assert result["operator_send_bypass_audit_required"] is True
    assert result["operator_send_bypass_audit_body_sha256"]
    assert result["manual_send_go_rehearsal_body_sha256"]
    assert result["checks"]["final_chain_complete"] is True
    assert result["checks"]["artifact_chains_match_payload_hashes"] is True
    assert result["final_chain_depth"] >= 12
    assert _file_hashes(tmp_path) == before


def test_external_alpha_send_chain_audit_rejects_stale_handoff_receipt_hash(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    handoff_path = tmp_path / HANDOFF_JSON_NAME
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["receipt"]["body_sha256"] = "0" * 64
    handoff["handoff_body_sha256"] = _handoff_body_sha256(handoff)
    handoff["handoff_checks"] = _handoff_checks(handoff)
    handoff_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SendChainAuditError, match="receipt_matches_handoff"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_requires_bundle_smoke_receipt(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
    (tmp_path / SMOKE_RECEIPT_NAME).unlink()

    with pytest.raises(SendChainAuditError, match="bundle smoke receipt verification failed"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_detects_source_manifest_drift(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
    manifest_path = tmp_path / f"{RELEASE_SLUG}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first_file = manifest["files"][0]
    first_file["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    assert _source_files_match_release_manifest(manifest_path) is False


def test_external_alpha_send_chain_audit_requires_operator_bypass_receipt(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    prepare_operator_dispatch_packet(tmp_path, refresh_chain=False)

    with pytest.raises(SendChainAuditError, match="operator send bypass audit file is missing"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_rejects_stale_manual_send_go_rehearsal(
    tmp_path: Path,
) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    rehearsal_path = tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    rehearsal["release"]["archive_sha256"] = "0" * 64
    rehearsal["manual_send_go_rehearsal_receipt_body_sha256"] = _manual_rehearsal_body_sha256(rehearsal)
    rehearsal_path.write_text(json.dumps(rehearsal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SendChainAuditError, match="manual_send_go_rehearsal_release_hash_matches"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_rejects_manual_rehearsal_without_ready_operator_status(
    tmp_path: Path,
) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    rehearsal_path = tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    rehearsal["rehearsed_flow"]["operator_status_verdict"] = "FILL_PRIVATE_FIELDS"
    rehearsal["manual_send_go_rehearsal_receipt_body_sha256"] = _manual_rehearsal_body_sha256(rehearsal)
    rehearsal_path.write_text(
        json.dumps(rehearsal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SendChainAuditError, match="operator status is not ready"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_rejects_manual_rehearsal_without_operator_status_packet_binding(
    tmp_path: Path,
) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    rehearsal_path = tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    rehearsal["rehearsed_flow"]["operator_status_manual_send_go_packet_bound"] = False
    rehearsal["manual_send_go_rehearsal_receipt_body_sha256"] = _manual_rehearsal_body_sha256(rehearsal)
    rehearsal_path.write_text(
        json.dumps(rehearsal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SendChainAuditError, match="operator status packet binding is not ready"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_rejects_operator_packet_without_real_preflight_contract(
    tmp_path: Path,
) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    packet_path = tmp_path / PACKET_JSON_NAME
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["operator_dispatch_packet_checks"]["post_send_rehearsal_real_preflight_gate"] = False
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SendChainAuditError, match="operator dispatch packet self-checks failed"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_rejects_stale_operator_packet_self_checks(
    tmp_path: Path,
) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    packet_path = tmp_path / PACKET_JSON_NAME
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    del packet["operator_dispatch_packet_checks"]["body_hash_matched"]
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SendChainAuditError, match="operator dispatch packet recalculated self-checks mismatch"):
        audit_send_chain(tmp_path)


def test_external_alpha_send_chain_audit_rejects_operator_packet_without_packet_arg(
    tmp_path: Path,
) -> None:
    check_pilot_iteration(tmp_path)
    _write_bundle_smoke_receipt(tmp_path)
    _write_operator_bypass_receipt(tmp_path)
    packet_path = tmp_path / PACKET_JSON_NAME
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["before_manual_send"]["pre_send_preflight_command"] = (
        "python scripts/check_external_alpha_first_recipient_send_preflight.py "
        "--workspace-dir <private-workspace-dir>"
    )
    packet["operator_dispatch_packet_body_sha256"] = _packet_body_sha256(packet)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SendChainAuditError, match="operator dispatch packet recalculated self-checks mismatch"):
        audit_send_chain(tmp_path)


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[str(path.relative_to(root))] = digest
    return hashes


def _write_bundle_smoke_receipt(root: Path) -> None:
    smoke_release_bundle(
        zip_path=root / f"{RELEASE_SLUG}.zip",
        manifest_path=root / f"{RELEASE_SLUG}.manifest.json",
        receipt_path=root / SMOKE_RECEIPT_NAME,
    )


def _write_operator_bypass_receipt(root: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(root, refresh_chain=False)
    workspace = root / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    audit_operator_send_bypass(root, workspace_dir=workspace, receipt_path=root / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME)
    smoke_manual_send_go_rehearsal(root)
