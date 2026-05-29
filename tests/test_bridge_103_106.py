from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ingest_reply(project_root: Path, text: str) -> str:
    reply_path = project_root / "bridge_reply.yaml"
    _write_text(reply_path, text)
    proc = _run_cli(["bridge", "ingest", str(reply_path), "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["saved_path"]


def test_bridge_materialize_analysis_and_context_hint(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "\n".join(
            [
                "response_kind: analysis",
                "summary: login flow likely needs auth normalization",
                "recommended_files:",
                "  - src/auth.py",
                "recommended_tests:",
                "  - tests/test_auth.py",
                "warnings:",
                "  - keep scope narrow",
            ]
        ),
    )

    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    materialized = json.loads(materialize.stdout)
    assert materialized["materialization_kind"] == "analysis_brief"

    handoff = _run_cli(["bridge", "handoff", materialized["saved_path"], "--as", "context_hint", "--json"], cwd=tmp_path)
    assert handoff.returncode == 0, handoff.stderr
    hint = json.loads(handoff.stdout)
    assert hint["recommended_files"] == ["src/auth.py"]
    assert hint["recommended_tests"] == ["tests/test_auth.py"]

    scan = _run_cli(["context", "scan", "login auth error", "--json"], cwd=tmp_path)
    assert scan.returncode == 0, scan.stderr
    payload = json.loads(scan.stdout)
    source = next(item for item in payload["suggested_sources"] if item["path"] == "src/auth.py")
    assert "AI bridge analysis suggested this file/test" in source["reasons"]

    list_proc = _run_cli(["bridge", "context-hints", "--json"], cwd=tmp_path)
    assert list_proc.returncode == 0, list_proc.stderr
    assert json.loads(list_proc.stdout)[0]["hint_id"] == hint["hint_id"]

    show_proc = _run_cli(["bridge", "context-hint-show", hint["hint_id"]], cwd=tmp_path)
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Bridge Context Hint" in show_proc.stdout


def test_bridge_materialize_review_reply_and_list(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "\n".join(
            [
                "response_kind: review",
                "summary: proposed fix is narrow and testable",
                "positives:",
                "  - keeps scope small",
                "cautions:",
                "  - verify auth edge cases",
                "recommended_next_actions:",
                "  - run tests/test_auth.py",
            ]
        ),
    )

    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    record = json.loads(materialize.stdout)
    assert record["materialization_kind"] == "review_note"
    assert "keeps scope small" in record["positives"]
    assert "verify auth edge cases" in record["cautions"]

    list_proc = _run_cli(["bridge", "materializations", "--kind", "review_note", "--json"], cwd=tmp_path)
    assert list_proc.returncode == 0, list_proc.stderr
    assert json.loads(list_proc.stdout)[0]["materialization_id"] == record["materialization_id"]


def test_bridge_materialize_patch_candidate_redirects_to_handoff(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "\n".join(
            [
                "response_kind: patch_candidate",
                "summary: normalize username before login",
                "target_path: src/auth.py",
                "old_text: return username",
                "new_text: return username.strip().lower()",
                "reason: narrow auth fix",
            ]
        ),
    )

    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode != 0
    payload = json.loads(materialize.stdout)
    assert payload["materialization_kind"] == "none"
    assert any("bridge handoff" in item for item in payload["next_actions"])
    materialized_dir = tmp_path / ".cambrian" / "bridge" / "materialized"
    assert not list(materialized_dir.glob("materialized_*.yaml")) if materialized_dir.exists() else True


def test_bridge_plan_materialization_to_checklist_and_step_tracking(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "\n".join(
            [
                "response_kind: plan",
                "summary: safe login normalization plan",
                "steps:",
                "  - inspect src/auth.py",
                "  - run tests/test_auth.py",
                "  - validate before apply",
            ]
        ),
    )
    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    materialized = json.loads(materialize.stdout)

    handoff = _run_cli(["bridge", "handoff", materialized["saved_path"], "--as", "checklist", "--json"], cwd=tmp_path)
    assert handoff.returncode == 0, handoff.stderr
    checklist = json.loads(handoff.stdout)
    assert checklist["overall_status"] == "open"
    assert checklist["next_step_id"] == "step-1"

    update = _run_cli(["bridge", "checklist-step", checklist["checklist_id"], "step-1", "--done", "--json"], cwd=tmp_path)
    assert update.returncode == 0, update.stderr
    updated = json.loads(update.stdout)
    assert updated["steps"][0]["status"] == "done"
    assert updated["overall_status"] == "in_progress"
    assert updated["next_step_id"] == "step-2"

    show = _run_cli(["bridge", "checklist-show", checklist["checklist_id"]], cwd=tmp_path)
    assert show.returncode == 0, show.stderr
    assert "Bridge Checklist" in show.stdout
    assert "run tests/test_auth.py" in show.stdout


def test_bridge_patch_handoff_creates_linked_session_and_continue_uses_prefill(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "\n".join(
            [
                "response_kind: patch_candidate",
                "summary: normalize username before login",
                "target_path: src/auth.py",
                "old_text: return username",
                "new_text: return username.strip().lower()",
                "reason: narrow auth fix",
                "related_tests:",
                "  - tests/test_auth.py",
            ]
        ),
    )

    handoff = _run_cli(["bridge", "handoff", reply_saved, "--as", "patch_intent", "--json"], cwd=tmp_path)
    assert handoff.returncode == 0, handoff.stderr
    payload = json.loads(handoff.stdout)
    link = payload["bridge_link"]
    assert link["session_id"]
    assert link["patch_intent_ref"] == payload["target_artifact_ref"]
    intent = _read_yaml(tmp_path / payload["target_artifact_ref"])
    assert intent["memory_guidance"]["bridge_prefill"]["new_text"] == "return username.strip().lower()"
    assert intent["bridge_prefill"]["new_text"] == "return username.strip().lower()"

    resume = _run_cli(["bridge", "resume", reply_saved], cwd=tmp_path)
    assert resume.returncode == 0, resume.stderr
    assert "cambrian do --continue --session" in resume.stdout

    cont = _run_cli(["do", "--continue", "--session", link["session_id"], "--validate", "--json"], cwd=tmp_path)
    assert cont.returncode == 0, cont.stderr
    continued = json.loads(cont.stdout)
    assert continued["summary"]["patch_intent_status"] in {"ready_for_proposal", "draft"}
    assert continued["artifacts"]["patch_intent_path"] == payload["target_artifact_ref"]


def test_bridge_non_analysis_materialization_cannot_be_context_hint(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(tmp_path, "response_kind: plan\nsummary: safe plan\nsteps:\n  - inspect src/auth.py\n")
    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    materialized = json.loads(materialize.stdout)

    handoff = _run_cli(["bridge", "handoff", materialized["saved_path"], "--as", "context_hint", "--json"], cwd=tmp_path)
    assert handoff.returncode != 0
    assert "analysis_brief" in handoff.stderr


def test_bridge_do_and_clarify_surface_context_hint(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "\n".join(
            [
                "response_kind: analysis",
                "summary: auth file likely needs a narrow fix",
                "recommended_files:",
                "  - src/auth.py",
                "recommended_tests:",
                "  - tests/test_auth.py",
            ]
        ),
    )
    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    handoff = _run_cli(["bridge", "handoff", json.loads(materialize.stdout)["saved_path"], "--as", "context_hint"], cwd=tmp_path)
    assert handoff.returncode == 0, handoff.stderr

    do_proc = _run_cli(["do", "login auth error"], cwd=tmp_path)
    assert do_proc.returncode == 0, do_proc.stderr
    assert "Bridge hint:" in do_proc.stdout
    assert "src/auth.py" in do_proc.stdout

    do_json = _run_cli(["do", "login auth error", "--json"], cwd=tmp_path)
    assert do_json.returncode == 0, do_json.stderr
    request_ref = json.loads(do_json.stdout)["artifacts"]["request_path"]
    request_id = _read_yaml(tmp_path / request_ref)["request_id"]
    clarify = _run_cli(["clarify", request_id], cwd=tmp_path)
    assert clarify.returncode == 0, clarify.stderr
    assert "AI bridge analysis suggested this file/test" in clarify.stdout


def test_bridge_plan_summary_only_creates_synthetic_checklist_step(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(tmp_path, "response_kind: plan\nsummary: inspect auth carefully\n")
    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    handoff = _run_cli(
        ["bridge", "handoff", json.loads(materialize.stdout)["saved_path"], "--as", "checklist", "--json"],
        cwd=tmp_path,
    )
    assert handoff.returncode == 0, handoff.stderr
    checklist = json.loads(handoff.stdout)
    assert checklist["steps"][0]["text"] == "inspect auth carefully"
    assert any("summary step" in warning for warning in checklist["warnings"])


def test_bridge_checklist_blocked_and_completed_statuses(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _ingest_reply(
        tmp_path,
        "response_kind: plan\nsummary: two step plan\nsteps:\n  - inspect src/auth.py\n  - run tests/test_auth.py\n",
    )
    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    handoff = _run_cli(["bridge", "handoff", json.loads(materialize.stdout)["saved_path"], "--as", "checklist", "--json"], cwd=tmp_path)
    assert handoff.returncode == 0, handoff.stderr
    checklist_id = json.loads(handoff.stdout)["checklist_id"]

    blocked = _run_cli(
        ["bridge", "checklist-step", checklist_id, "step-2", "--blocked", "--note", "test file missing", "--json"],
        cwd=tmp_path,
    )
    assert blocked.returncode == 0, blocked.stderr
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["overall_status"] == "blocked"
    assert blocked_payload["steps"][1]["note"] == "test file missing"

    done_1 = _run_cli(["bridge", "checklist-step", checklist_id, "step-1", "--done", "--json"], cwd=tmp_path)
    done_2 = _run_cli(["bridge", "checklist-step", checklist_id, "step-2", "--done", "--json"], cwd=tmp_path)
    assert done_1.returncode == 0, done_1.stderr
    assert done_2.returncode == 0, done_2.stderr
    assert json.loads(done_2.stdout)["overall_status"] == "completed"


def test_bridge_context_and_checklist_do_not_mutate_source(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    before = _hash(source)
    reply_saved = _ingest_reply(
        tmp_path,
        "response_kind: plan\nsummary: summary-only plan\n",
    )
    materialize = _run_cli(["bridge", "materialize", reply_saved, "--json"], cwd=tmp_path)
    assert materialize.returncode == 0, materialize.stderr
    handoff = _run_cli(["bridge", "handoff", json.loads(materialize.stdout)["saved_path"], "--as", "checklist"], cwd=tmp_path)
    assert handoff.returncode == 0, handoff.stderr
    status = _run_cli(["status"], cwd=tmp_path)
    assert status.returncode == 0, status.stderr
    assert _hash(source) == before
