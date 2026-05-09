from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import run_cli


GARBLED_TEXT_PATTERNS = ["\ufffd", "\u6028", "\uf9cf", "?꾨", "?앺", "?묒", "寃", "由대"]


def _prepare_waiting_task(tmp_path: Path) -> str:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    return str(json.loads(run_result.stdout)["task_refs"][0])


def test_auto_report_pauses_when_blocked_result_requires_human_input(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "blocked",
                "summary": "야놀자 취소 상태 코드가 없어 안전하게 패치할 수 없다.",
                "changed_files": [],
                "tests": [{"command": "static inspection", "status": "passed"}],
                "blockers": ["야놀자 취소 예약 raw 응답의 stayStatus 값이 필요하다."],
                "required_input": [
                    {
                        "id": "yanolja_cancel_stay_status",
                        "field": "stayStatus",
                        "description": "취소된 야놀자 예약 raw 응답의 stayStatus 값",
                        "example": {"stayStatus": "..."},
                    }
                ],
                "next_action": "사용자가 stayStatus 값을 제공해야 한다.",
                "evidence": {"notes": ["외부 상태 코드가 없으면 추측 패치 금지"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")

    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    handoff = payload["decision_handoff"]
    assert handoff["status"] == "input_required"
    assert handoff["next_command"] is None
    assert handoff["required_inputs"][0]["field"] == "stayStatus"
    assert handoff["input_request_refs"]
    request_path = tmp_path / handoff["input_request_refs"][0]
    assert request_path.exists()
    request_text = request_path.read_text(encoding="utf-8")
    assert "stayStatus" in request_text
    assert "Authorization" in request_text
    for pattern in GARBLED_TEXT_PATTERNS:
        assert pattern not in request_text

    status = run_cli(tmp_path, "auto", "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["status"] == "paused"
    assert status_payload["decision_handoff"]["status"] == "input_required"


def test_auto_input_list_shows_current_required_inputs(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "blocked",
                "summary": "외부 상태 코드가 필요하다.",
                "changed_files": [],
                "tests": [{"command": "static inspection", "status": "passed"}],
                "blockers": ["야놀자 취소 예약 raw 응답의 stayStatus 값이 필요하다."],
                "required_input": [{"id": "yanolja_cancel_stay_status", "field": "stayStatus"}],
                "next_action": "사용자가 stayStatus 값을 제공해야 한다.",
                "evidence": {"notes": ["입력 대기"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0

    result = run_cli(tmp_path, "auto", "input", "list", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "input_required"
    assert payload["required_inputs"][0]["field"] == "stayStatus"
    assert payload["input_request_refs"]
    assert (tmp_path / payload["input_request_refs"][0]).exists()
    status = run_cli(tmp_path, "auto", "status", "--json")
    assert json.loads(status.stdout)["status"] == "paused"


def test_auto_plan_does_not_create_recovery_tasks_for_input_required(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "blocked",
                "summary": "외부 샘플 값이 필요하다.",
                "changed_files": [],
                "tests": [{"command": "static inspection", "status": "passed"}],
                "blockers": ["사용자 입력 샘플 값이 필요하다."],
                "required_input": [{"id": "sample_value", "field": "sample_value"}],
                "next_action": "사용자가 sample_value를 제공해야 한다.",
                "evidence": {"notes": ["입력 대기"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0

    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan.returncode == 0, plan.stderr
    payload = json.loads(plan.stdout)
    assert payload["plan_kind"] == "input_wait"
    assert payload["steps"] == []
    assert payload["next_command"] is None


def test_auto_input_answer_records_value_and_unpauses_when_all_inputs_resolved(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "blocked",
                "summary": "야놀자 취소 상태 코드가 필요하다.",
                "changed_files": [],
                "tests": [{"command": "static inspection", "status": "passed"}],
                "blockers": ["야놀자 취소 예약 raw 응답의 stayStatus 값이 필요하다."],
                "required_input": [
                    {
                        "id": "yanolja_cancel_stay_status",
                        "field": "stayStatus",
                        "description": "취소된 야놀자 예약 raw 응답의 stayStatus 값",
                        "example": {"stayStatus": "..."},
                    }
                ],
                "next_action": "사용자가 stayStatus 값을 제공해야 한다.",
                "evidence": {"notes": ["입력 대기"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0

    answer = run_cli(
        tmp_path,
        "auto",
        "input",
        "answer",
        "--field",
        "stayStatus",
        "--value",
        "CXL",
        "--json",
    )

    assert answer.returncode == 0, answer.stderr
    answer_payload = json.loads(answer.stdout)
    assert answer_payload["ok"] is True
    assert answer_payload["field"] == "stayStatus"
    assert answer_payload["remaining_required_inputs"] == []
    assert answer_payload["auto_paused"] is False
    answer_path = tmp_path / answer_payload["answer_ref"]
    assert answer_path.exists()
    answer_file = yaml.safe_load(answer_path.read_text(encoding="utf-8"))
    assert answer_file["value"] == "CXL"

    status = run_cli(tmp_path, "auto", "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["status"] == "active"
    assert status_payload["decision_handoff"]["status"] == "needs_boardroom_review"

    listed = run_cli(tmp_path, "auto", "input", "list", "--json")
    assert listed.returncode == 0, listed.stderr
    listed_payload = json.loads(listed.stdout)
    assert listed_payload["status"] == "no_input_required"
    assert listed_payload["required_inputs"] == []


def test_auto_input_answer_rejects_unrequested_field(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "blocked",
                "summary": "외부 입력이 필요하다.",
                "changed_files": [],
                "tests": [{"command": "static inspection", "status": "passed"}],
                "blockers": ["sample_value가 필요하다."],
                "required_input": [{"id": "sample_value", "field": "sample_value"}],
                "next_action": "sample_value를 제공한다.",
                "evidence": {"notes": ["입력 대기"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0

    answer = run_cli(tmp_path, "auto", "input", "answer", "--field", "other", "--value", "x", "--json")

    assert answer.returncode == 1
    payload = json.loads(answer.stdout)
    assert payload["ok"] is False
    assert "input field is not currently required" in payload["errors"][0]


def test_auto_input_defer_records_evidence_and_unblocks_planning(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "blocked",
                "summary": "external vendor cancel status is unavailable.",
                "changed_files": [],
                "tests": [{"command": "static inspection", "status": "passed"}],
                "blockers": ["cancel raw response stayStatus is required."],
                "required_input": [
                    {
                        "id": "yanolja_cancel_stay_status",
                        "field": "stayStatus",
                        "description": "Canceled vendor reservation stayStatus value",
                        "example": {"stayStatus": "..."},
                    }
                ],
                "next_action": "provide stayStatus or defer this external verification.",
                "evidence": {"notes": ["external input gate"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0

    defer = run_cli(
        tmp_path,
        "auto",
        "input",
        "defer",
        "--field",
        "stayStatus",
        "--reason",
        "external vendor evidence is unavailable in this iteration",
        "--json",
    )

    assert defer.returncode == 0, defer.stderr
    defer_payload = json.loads(defer.stdout)
    assert defer_payload["ok"] is True
    assert defer_payload["status"] == "input_deferred"
    assert defer_payload["field"] == "stayStatus"
    assert defer_payload["auto_paused"] is False
    assert defer_payload["next_command"] == "cambrian auto boardroom --json"
    defer_path = tmp_path / defer_payload["defer_ref"]
    assert defer_path.exists()
    defer_file = yaml.safe_load(defer_path.read_text(encoding="utf-8"))
    assert defer_file["source"] == "human_defer"
    assert defer_file["reason"] == "external vendor evidence is unavailable in this iteration"

    listed = run_cli(tmp_path, "auto", "input", "list", "--json")
    assert listed.returncode == 0, listed.stderr
    listed_payload = json.loads(listed.stdout)
    assert listed_payload["status"] == "no_input_required"
    assert "stayStatus" in listed_payload["deferred_inputs"]

    status = run_cli(tmp_path, "auto", "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["status"] == "active"
    assert status_payload["decision_handoff"]["status"] == "needs_boardroom_review"
