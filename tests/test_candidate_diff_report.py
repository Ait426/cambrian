import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.generate_candidate_pack import generate_candidate_pack
from tools.generate_candidate_diff_report import CandidateDiffError, generate_candidate_diff_report
from tools.validate_candidate_diff_report import validate_candidate_diff_report


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACK = ROOT / "web" / "assets" / "document-organizer.agent-pack.json"
SAMPLE_CANDIDATE = ROOT / "web" / "assets" / "document-organizer.candidate.agent-pack.json"
SAMPLE_PROMOTED = ROOT / "web" / "assets" / "document-organizer.promoted.agent-pack.json"
SAMPLE_SUGGESTION = ROOT / "web" / "assets" / "document-organizer.evolution-suggestion.json"
SAMPLE_DECISION = ROOT / "web" / "assets" / "document-organizer.evolution-review-decision.json"
SAMPLE_DIFF_REPORT = ROOT / "web" / "assets" / "document-organizer.candidate-diff-report.json"
GENERATOR = ROOT / "tools" / "generate_candidate_diff_report.py"
VALIDATOR = ROOT / "tools" / "validate_candidate_diff_report.py"
CANDIDATE_DIFF_REPORT_SCHEMA = ROOT / "schemas" / "candidate_diff_report_v0_1.schema.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_candidate_diff_report_schema_is_valid() -> None:
    schema = _read_json(CANDIDATE_DIFF_REPORT_SCHEMA)

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["report_kind"]["const"] == "candidate_diff_report_v0_1"
    assert schema["properties"]["diff_status"]["enum"] == ["review_pass_not_promoted", "review_fail"]
    assert schema["properties"]["approval_gate"]["properties"]["auto_promote"]["const"] is False
    assert schema["properties"]["unexpected_changes"]["maxItems"] == 0
    assert schema["properties"]["next_step"]["properties"]["blocked"]["const"] == "automatic_candidate_promotion"


def test_generate_candidate_diff_report_passes_for_sample_candidate() -> None:
    report = generate_candidate_diff_report(
        SAMPLE_PACK,
        SAMPLE_CANDIDATE,
        SAMPLE_DECISION,
        generated_at="2026-05-10T00:00:00Z",
    )

    assert report["report_kind"] == "candidate_diff_report_v0_1"
    assert report["diff_status"] == "review_pass_not_promoted"
    assert report["comparison"]["only_approved_decisions_applied"] is True
    assert report["comparison"]["deferred_and_rejected_not_applied"] is True
    assert report["approval_gate"]["auto_promote"] is False
    assert not report["unexpected_changes"]
    assert "evo_1" in report["change_summary"]["approved_decision_ids"]
    assert "evo_2" in report["change_summary"]["approved_decision_ids"]
    assert "evo_3" in report["change_summary"]["deferred_or_rejected_decision_ids"]


def test_candidate_diff_report_allows_promoted_source_metadata_removal(tmp_path: Path) -> None:
    candidate = generate_candidate_pack(
        SAMPLE_PROMOTED,
        SAMPLE_SUGGESTION,
        SAMPLE_DECISION,
        generated_at="2026-05-10T00:00:00Z",
    )
    candidate_path = tmp_path / "candidate-from-promoted.agent-pack.json"
    _write_json(candidate_path, candidate)

    report = generate_candidate_diff_report(
        SAMPLE_PROMOTED,
        candidate_path,
        SAMPLE_DECISION,
        generated_at="2026-05-10T00:00:00Z",
    )
    allowed_paths = {item["path"] for item in report["allowed_changes"]}

    assert report["diff_status"] == "review_pass_not_promoted"
    assert not report["unexpected_changes"]
    assert "promotion_metadata.promotion_status" in allowed_paths
    assert all(
        item["change_type"] == "removed"
        for item in report["allowed_changes"]
        if item["path"].startswith("promotion_metadata.")
    )


def test_validate_candidate_diff_report_passes_sample() -> None:
    report = validate_candidate_diff_report(SAMPLE_DIFF_REPORT)

    assert report["validator"] == "candidate_diff_report_validator_v0_1"
    assert report["status"] == "pass"
    assert report["agent_id"] == "document-organizer"
    assert not report["errors"]
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert any(check["name"] == "only_approved_changes" for check in report["checks"])


def test_generate_candidate_diff_report_rejects_unapproved_candidate_change(tmp_path: Path) -> None:
    candidate = deepcopy(_read_json(SAMPLE_CANDIDATE))
    candidate["files"]["agent.json"]["validation_criteria"].append(
        "보류된 항목을 몰래 반영한 변경입니다."
    )
    candidate_path = tmp_path / "tampered.candidate.agent-pack.json"
    _write_json(candidate_path, candidate)

    with pytest.raises(CandidateDiffError, match="schema"):
        generate_candidate_diff_report(SAMPLE_PACK, candidate_path, SAMPLE_DECISION)


def test_validate_candidate_diff_report_blocks_unexpected_changes(tmp_path: Path) -> None:
    report = deepcopy(_read_json(SAMPLE_DIFF_REPORT))
    report["diff_status"] = "review_fail"
    report["comparison"]["only_approved_decisions_applied"] = False
    report["unexpected_changes"] = [
        {"path": "files.agent.json.validation_criteria", "change_type": "modified"}
    ]
    broken_path = tmp_path / "bad.candidate-diff-report.json"
    _write_json(broken_path, report)

    validation = validate_candidate_diff_report(broken_path)

    assert validation["status"] == "fail"
    assert any(error["code"] == "diff_report_schema" for error in validation["errors"])
    assert any(error["code"] == "review_pass_not_promoted" for error in validation["errors"])
    assert any(error["code"] == "only_approved_changes" for error in validation["errors"])


def test_candidate_diff_report_generator_cli_outputs_json() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            str(SAMPLE_PACK),
            str(SAMPLE_CANDIDATE),
            str(SAMPLE_DECISION),
            "--pretty",
            "--generated-at",
            "2026-05-10T00:00:00Z",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["diff_status"] == "review_pass_not_promoted"
    assert report["next_step"]["blocked"] == "automatic_candidate_promotion"


def test_candidate_diff_report_validator_cli_outputs_json() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(SAMPLE_DIFF_REPORT), "--pretty"],
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
    assert report["validator"] == "candidate_diff_report_validator_v0_1"
