import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from tools.verify_promotion_audit_link import verify_promotion_audit_link


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PROMOTED = ROOT / "web" / "assets" / "document-organizer.promoted.agent-pack.json"
SAMPLE_PROMOTION_RECORD = ROOT / "web" / "assets" / "document-organizer.candidate-promotion-record.json"
VERIFIER = ROOT / "tools" / "verify_promotion_audit_link.py"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _error_codes(report: dict) -> set[str]:
    return {str(error["code"]) for error in report["errors"]}


def test_promotion_audit_link_verifier_passes_sample() -> None:
    report = verify_promotion_audit_link(SAMPLE_PROMOTED, SAMPLE_PROMOTION_RECORD)

    assert report["status"] == "pass"
    assert report["validator"] == "promotion_audit_link_verifier_v0_1"
    assert report["agent_id"] == "document-organizer"
    assert report["source"]["promoted_pack_hash"].startswith("sha256:")
    assert {check["status"] for check in report["checks"]} == {"pass"}


def test_promotion_audit_link_verifier_rejects_promoted_hash_mismatch(tmp_path: Path) -> None:
    broken = deepcopy(_read_json(SAMPLE_PROMOTION_RECORD))
    broken["source"]["promoted_pack_hash"] = "sha256:" + "0" * 64
    broken_path = tmp_path / "broken.candidate-promotion-record.json"
    _write_json(broken_path, broken)

    report = verify_promotion_audit_link(SAMPLE_PROMOTED, broken_path)

    assert report["status"] == "fail"
    assert "promoted_pack_hash_matches_record" in _error_codes(report)


def test_promotion_audit_link_verifier_rejects_diff_hash_mismatch(tmp_path: Path) -> None:
    broken = deepcopy(_read_json(SAMPLE_PROMOTED))
    broken["promotion_metadata"]["diff_report_hash"] = "sha256:" + "1" * 64
    broken_path = tmp_path / "broken.promoted.agent-pack.json"
    _write_json(broken_path, broken)

    report = verify_promotion_audit_link(broken_path, SAMPLE_PROMOTION_RECORD)

    assert report["status"] == "fail"
    assert "diff_report_hash_matches_record" in _error_codes(report)


def test_promotion_audit_link_verifier_cli_outputs_json() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VERIFIER), str(SAMPLE_PROMOTED), str(SAMPLE_PROMOTION_RECORD), "--pretty"],
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
    assert report["validator"] == "promotion_audit_link_verifier_v0_1"
