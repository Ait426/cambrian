import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import tools.validate_agent_pack as validator_module
from tools.validate_agent_pack import validate_agent_pack


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACK = ROOT / "web" / "assets" / "document-organizer.agent-pack.json"
VALIDATOR = ROOT / "tools" / "validate_agent_pack.py"
AGENT_PACK_BUNDLE_SCHEMA = ROOT / "schemas" / "agent_pack_bundle_v0_1.schema.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_validate_agent_pack_passes_sample_pack() -> None:
    report = validate_agent_pack(SAMPLE_PACK)
    bundle_schema = _read_json(AGENT_PACK_BUNDLE_SCHEMA)
    required_checks = set(bundle_schema["x-required_preflight_checks"])
    embedded_checks = {check["name"] for check in _read_json(SAMPLE_PACK)["files"]["preflight_report.json"]["checks"]}

    assert report["validator"] == "agent_pack_preflight_v0_1"
    assert report["status"] == "pass"
    assert report["agent_id"] == "document-organizer"
    assert report["risk_level"] == "green"
    assert not report["errors"]
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert any(check["name"] == "embedded_preflight_checks_complete" for check in report["checks"])
    assert any(check["name"] == "builder_pack_has_no_candidate_metadata" for check in report["checks"])
    assert any(check["name"] == "builder_pack_has_no_promotion_metadata" for check in report["checks"])
    assert required_checks
    assert required_checks.issubset(embedded_checks)


def test_validate_agent_pack_rejects_builder_pack_with_candidate_metadata(tmp_path: Path) -> None:
    broken = deepcopy(_read_json(SAMPLE_PACK))
    broken["candidate_metadata"] = {
        "metadata_kind": "candidate_agent_pack_metadata_v0_1",
        "source_suggestion_kind": "evolution_suggestion_v0_1",
        "source_decision_kind": "evolution_review_decision_v0_1",
        "apply_status": "candidate_not_applied",
        "auto_apply": False,
        "auto_promote": False,
        "approved_decision_ids": ["decision_1"],
        "approved_recommendation_ids": ["evo_1"],
        "deferred_recommendation_ids": [],
        "rejected_recommendation_ids": [],
        "requires_user_final_review": True,
        "original_pack_preserved": True,
        "generated_at": "2026-05-10T00:00:00Z",
    }
    broken_path = tmp_path / "builder-with-candidate-metadata.agent-pack.json"
    _write_json(broken_path, broken)

    report = validate_agent_pack(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "bundle_schema" for error in report["errors"])
    assert any(error["code"] == "builder_pack_has_no_candidate_metadata" for error in report["errors"])


def test_validate_agent_pack_rejects_builder_pack_with_promotion_metadata(tmp_path: Path) -> None:
    broken = deepcopy(_read_json(SAMPLE_PACK))
    broken["promotion_metadata"] = {
        "metadata_kind": "promoted_agent_pack_metadata_v0_1",
        "source_candidate_metadata_kind": "candidate_agent_pack_metadata_v0_1",
        "source_candidate_generated_by": "tools/generate_candidate_pack.py",
        "source_diff_report_kind": "candidate_diff_report_v0_1",
        "source_diff_report_generated_by": "tools/generate_candidate_diff_report.py",
        "promotion_status": "promoted_private_version",
        "candidate_apply_status_before_promotion": "candidate_not_applied",
        "user_command_required": True,
        "auto_promote": False,
        "approved_decision_ids": ["decision_1"],
        "approved_recommendation_ids": ["evo_1"],
        "original_pack_preserved": True,
        "candidate_pack_preserved": True,
        "proof_claim_allowed": False,
        "marketplace_sale_ready": False,
        "promoted_from_candidate_hash": "sha256:" + ("1" * 64),
        "diff_report_hash": "sha256:" + ("2" * 64),
        "generated_at": "2026-05-10T00:00:00Z",
    }
    broken_path = tmp_path / "builder-with-promotion-metadata.agent-pack.json"
    _write_json(broken_path, broken)

    report = validate_agent_pack(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "bundle_schema" for error in report["errors"])
    assert any(error["code"] == "builder_pack_has_no_promotion_metadata" for error in report["errors"])


def test_validate_agent_pack_fails_when_required_file_is_missing(tmp_path: Path) -> None:
    broken = deepcopy(_read_json(SAMPLE_PACK))
    del broken["files"]["legal_notice.md"]
    broken_path = tmp_path / "broken.agent-pack.json"
    _write_json(broken_path, broken)

    report = validate_agent_pack(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "bundle_schema" for error in report["errors"])
    assert any(error["code"] == "required_files_present" for error in report["errors"])


def test_validate_agent_pack_fails_when_embedded_preflight_is_stale(tmp_path: Path) -> None:
    stale = deepcopy(_read_json(SAMPLE_PACK))
    stale["files"]["preflight_report.json"]["checks"] = [
        check
        for check in stale["files"]["preflight_report.json"]["checks"]
        if check["name"] != "runner_names_cambrian_optional"
    ]
    stale_path = tmp_path / "stale.agent-pack.json"
    _write_json(stale_path, stale)

    report = validate_agent_pack(stale_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "embedded_preflight_checks_complete" for error in report["errors"])


def test_validate_agent_pack_uses_schema_required_preflight_checks(monkeypatch, tmp_path: Path) -> None:
    schema = deepcopy(_read_json(AGENT_PACK_BUNDLE_SCHEMA))
    schema["x-required_preflight_checks"].append("future_required_check")
    schema_path = tmp_path / "agent_pack_bundle_v0_1.schema.json"
    _write_json(schema_path, schema)
    monkeypatch.setattr(validator_module, "AGENT_PACK_BUNDLE_SCHEMA", schema_path)

    report = validator_module.validate_agent_pack(SAMPLE_PACK)

    assert report["status"] == "fail"
    assert any(error["code"] == "embedded_preflight_checks_complete" for error in report["errors"])


def test_validate_agent_pack_blocks_red_risk_without_schema_failure(tmp_path: Path) -> None:
    blocked = deepcopy(_read_json(SAMPLE_PACK))
    blocked["riskReport"]["level"] = "Red"
    blocked["riskReport"]["blocks"] = ["의료 결정은 차단 대상입니다."]
    blocked["files"]["agent.json"]["risk_level"] = "red"
    blocked["files"]["agent_card.json"]["risk_level"] = "red"
    blocked["files"]["agent_card.json"]["preflight_status"] = "blocked"
    blocked["files"]["manifest.json"]["risk_level"] = "Red"
    blocked["files"]["preflight_report.json"]["status"] = "blocked"
    blocked["files"]["preflight_report.json"]["risk_level"] = "red"
    blocked["files"]["preflight_report.json"]["warnings"] = [
        {"code": "risk_blocked", "message": "차단 대상 위험이 포함되어 blocked 상태가 된다."}
    ]
    blocked_path = tmp_path / "red.agent-pack.json"
    _write_json(blocked_path, blocked)

    report = validate_agent_pack(blocked_path)

    assert report["status"] == "blocked"
    assert not report["errors"]
    assert any(warning["code"] == "risk_blocked" for warning in report["warnings"])


def test_validate_agent_pack_cli_outputs_json_report() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(SAMPLE_PACK), "--pretty"],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "pass"
    assert report["validator"] == "agent_pack_preflight_v0_1"
    assert any(check["name"] == "preflight_status_matches_risk" for check in report["checks"])


def test_sample_pack_legal_boundary_is_readable_and_blocks_fake_proof() -> None:
    sample = _read_json(SAMPLE_PACK)
    files = sample["files"]
    legal_notice = files["legal_notice.md"]
    run_local = files["run_local.md"]
    agent = files["agent.json"]
    card = files["agent_card.json"]
    manifest = files["manifest.json"]

    for phrase in [
        "의료 결정",
        "법률 결정",
        "투자·금융 결정",
        "채용·해고 판단",
        "no_runtime_evidence",
        "proof, 성능, 성공률을 주장하지 않습니다",
    ]:
        assert phrase in legal_notice

    assert "Cambrian 없이도 사용할 수 있습니다" in run_local
    assert agent["data_policy"]["secret_collection"] == "forbidden_by_default"
    assert card["card_kind"] == "private_agent_card"
    assert card["marketplace"]["sale_ready"] is False
    assert card["marketplace"]["proof_claim_allowed"] is False
    assert manifest["marketplace"]["sale_ready"] is False
    assert manifest["marketplace"]["proof_claim_allowed"] is False

    combined = json.dumps(sample, ensure_ascii=False)
    for marker in ["濡", "먯", "꾪", "�"]:
        assert marker not in combined
