from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def prepare_plan(tmp_path: Path, *, full_authority: bool = True) -> None:
    if full_authority:
        prepare_auto(tmp_path)
    else:
        assert run_cli(tmp_path, "authority", "init", "--json").returncode == 0
        assert run_cli(tmp_path, "auto", "init", "--goal", "제품을 설치형 RC로 완성", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0


def test_auto_run_respects_max_steps_and_writes_execution_log(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "2", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["authority"] == "full_authority"
    assert payload["max_steps"] == 2
    assert payload["executed_steps"] == 2
    assert payload["blocked_steps"] == []
    assert payload["source_code_modified"] is False

    log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    assert len(log["runs"]) == 1
    assert len(log["runs"][0]["executed_steps"]) == 2
    assert log["runs"][0]["changed_files"] == []


def test_auto_run_creates_codex_task_directives_without_source_changes(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["waiting_for_result"] == 1
    assert payload["task_refs"]
    assert payload["directive_refs"]
    task_path = tmp_path / payload["task_refs"][0]
    directive_path = tmp_path / payload["directive_refs"][0]
    assert task_path.exists()
    assert directive_path.exists()
    task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    directive = directive_path.read_text(encoding="utf-8")
    assert task["status"] == "waiting_for_result"
    assert task["directive_type"] == "role_specific_auto_task"
    assert task["execution_engine"] == "Codex or Claude"
    assert task["safety"]["source_code_modified_by_auto_run"] is False
    assert "Cambrian Auto Task Directive" in directive
    assert "역할별 작업 지시" in directive
    assert "결과 계약" in directive
    assert "status:" in directive
    assert "evidence:" in directive

    log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    run = log["runs"][0]
    assert run["waiting_for_result"] == 1
    assert run["task_refs"] == payload["task_refs"]
    assert run["directive_refs"] == payload["directive_refs"]
    assert run["executed_steps"][0]["status"] == "waiting_for_result"
    assert run["changed_files"] == []


def test_auto_step_ingest_validates_result_and_updates_task(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    run_payload = json.loads(run_result.stdout)
    task_ref = run_payload["task_refs"][0]
    result_file = tmp_path / "step_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "작업 결과를 검증 가능한 형태로 정리했다.",
                "changed_files": ["docs/product/example.md"],
                "tests": [{"command": "python -m pytest tests/test_example.py", "status": "passed"}],
                "blockers": [],
                "next_action": "auto report로 상태를 확인한다.",
                "evidence": {"notes": ["테스트 통과"], "artifacts": []},
                "role_outputs": {
                    "scope": "문서 예시 변경",
                    "acceptance_criteria": ["테스트 통과"],
                    "test_plan": ["python -m pytest tests/test_example.py"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "validated"
    assert payload["next_state"] == "VALIDATION"
    assert payload["source_code_modified"] is False
    assert (tmp_path / payload["result_ref"]).exists()
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["status"] == "validated"
    assert task["result_ref"] == "step_result.yaml"
    assert task["result_tests"][0]["status"] == "passed"
    log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    assert log["step_results"][-1]["status"] == "validated"
    assert log["step_results"][-1]["source_code_modified_by_ingest"] is False


def test_auto_report_summarizes_validated_step_result(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "validated_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "step complete",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "validated result",
                    "acceptance_criteria": ["report can summarize result"],
                    "test_plan": ["python -m pytest"],
                },
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
    assert payload["ok"] is True
    summary = payload["report"]["step_results"]
    assert summary["total"] == 1
    assert summary["validated"] == 1
    assert summary["blocked"] == 0
    assert payload["report"]["task_statuses"]["waiting_for_result"] == 0
    assert payload["decision_handoff"]["status"] == "ready_for_release_or_next_plan"
    assert payload["decision_handoff"]["next_command"] == "cambrian auto plan --json"


def test_auto_step_ingest_records_blocked_result(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "blocked_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "검증 명령이 실패했다.",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["테스트 실패 원인 확인 필요"],
                "next_action": "boardroom에서 다음 결정을 다시 잡는다.",
                "evidence": {"notes": ["테스트 실패"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "blocked"
    assert payload["next_state"] == "REVIEW"
    assert payload["blockers"] == ["테스트 실패 원인 확인 필요"]
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["status"] == "blocked"


def test_auto_step_ingest_rejects_invalid_result_contract(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "invalid_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "missing required contract fields",
                "tests": [{"command": "python -m pytest", "status": "passed"}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 1
    payload = json.loads(ingest.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_result_contract"
    assert "missing required field: evidence" in payload["errors"]
    assert payload["source_code_modified"] is False
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["status"] == "waiting_for_result"


def test_auto_report_hands_blocked_step_back_to_boardroom(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "blocked_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked by test failure",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["test failure"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["blocked"], "artifacts": []},
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
    summary = payload["report"]["step_results"]
    assert summary["blocked"] == 1
    assert summary["open_blockers"][0]["blockers"] == ["test failure"]
    assert payload["decision_handoff"]["status"] == "needs_boardroom_review"
    assert payload["decision_handoff"]["next_command"] == "cambrian auto boardroom --json"


def test_auto_report_uses_latest_step_result_per_task(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=True)
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    blocked_result = tmp_path / "blocked_result.yaml"
    blocked_result.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked by timeout",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["timeout"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["blocked"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    first_ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(blocked_result), "--json")
    assert first_ingest.returncode == 0, first_ingest.stderr
    blocked_report = run_cli(tmp_path, "auto", "report", "--json")
    assert blocked_report.returncode == 0, blocked_report.stderr
    blocked_payload = json.loads(blocked_report.stdout)
    assert blocked_payload["report"]["step_results"]["blocked"] == 1

    resolved_result = tmp_path / "resolved_result.yaml"
    resolved_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "timeout resolved with split-run evidence",
                "changed_files": [],
                "tests": [{"command": "python -m pytest tests/test_auto_run_limits.py", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "validated timeout recovery",
                    "acceptance_criteria": ["stale blockers are not counted after resolution"],
                    "test_plan": ["python -m pytest tests/test_auto_run_limits.py"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    second_ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(resolved_result), "--json")
    assert second_ingest.returncode == 0, second_ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")

    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    summary = payload["report"]["step_results"]
    assert summary["total"] == 1
    assert summary["blocked"] == 0
    assert summary["validated"] == 1
    assert summary["open_blockers"] == []
    assert payload["report"]["task_statuses"]["blocked"] == 0
    assert payload["decision_handoff"]["status"] == "ready_for_release_or_next_plan"


def test_auto_task_directive_bridge_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "25_AUTO_TASK_DIRECTIVE_BRIDGE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto run",
        "waiting_for_result",
        ".cambrian/auto/tasks",
        "Codex 또는 Claude",
        "source code를 직접 수정하지 않는다",
    ]:
        assert phrase in text
    assert "docs/product/25_AUTO_TASK_DIRECTIVE_BRIDGE.md" in readme
    assert "25_AUTO_TASK_DIRECTIVE_BRIDGE.md" in index


def test_auto_step_result_intake_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "26_AUTO_STEP_RESULT_INTAKE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto step ingest",
        ".cambrian/auto/results",
        ".cambrian/auto/tasks",
        "execution_log.yaml",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/26_AUTO_STEP_RESULT_INTAKE.md" in readme
    assert "26_AUTO_STEP_RESULT_INTAKE.md" in index


def test_auto_result_report_handoff_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "27_AUTO_RESULT_REPORT_HANDOFF.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto report",
        "decision_handoff",
        "waiting_for_external_result",
        "needs_boardroom_review",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/27_AUTO_RESULT_REPORT_HANDOFF.md" in readme
    assert "27_AUTO_RESULT_REPORT_HANDOFF.md" in index


def test_codex_result_contract_hardening_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "31_CODEX_RESULT_CONTRACT_HARDENING.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "invalid_result_contract",
        "status",
        "summary",
        "changed_files",
        "evidence",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/31_CODEX_RESULT_CONTRACT_HARDENING.md" in readme
    assert "31_CODEX_RESULT_CONTRACT_HARDENING.md" in index


def test_auto_run_blocks_steps_without_authority(tmp_path: Path) -> None:
    prepare_plan(tmp_path, full_authority=False)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["authority"] == "proposal_only"
    assert payload["blocked_steps"]
    missing = [permission for step in payload["blocked_steps"] for permission in step["missing_permissions"]]
    assert "filesystem_write" in missing
    assert "command_exec" in missing
    assert "build_artifact" in missing


def test_auto_run_requires_plan(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "run", "--max-steps", "5", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "auto plan is missing" in payload["errors"]
