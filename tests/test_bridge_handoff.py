from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_packet_and_patch_reply(project_root: Path) -> tuple[str, str]:
    packet_proc = _run_cli(["bridge", "prepare", "로그인 에러 수정해", "--json"], cwd=project_root)
    assert packet_proc.returncode == 0, packet_proc.stderr
    packet_path = json.loads(packet_proc.stdout)["saved_path"]
    reply_path = project_root / "reply.yaml"
    _write_text(
        reply_path,
        "\n".join(
            [
                "response_kind: patch_candidate",
                "summary: normalize username before login",
                "target_path: src/auth.py",
                "old_text: return username",
                "new_text: return username.strip().lower()",
                "reason: narrow auth fix with test-first intent",
                "related_tests:",
                "  - tests/test_auth.py",
            ]
        ),
    )
    ingest_proc = _run_cli(
        ["bridge", "ingest", str(reply_path), "--packet", packet_path, "--session", "session-123", "--json"],
        cwd=project_root,
    )
    assert ingest_proc.returncode == 0, ingest_proc.stderr
    reply_saved = json.loads(ingest_proc.stdout)["saved_path"]
    return packet_path, reply_saved


def _write_invalid_patch_reply_artifact(project_root: Path) -> str:
    reply_path = project_root / ".cambrian" / "bridge" / "replies" / "reply_bad.yaml"
    _write_yaml(
        reply_path,
        {
            "schema_version": "1.0.0",
            "reply_id": "reply_bad",
            "created_at": "2026-04-28T00:00:00+00:00",
            "packet_id": None,
            "project_name": project_root.name,
            "request": "로그인 에러 수정해",
            "response_kind": "patch_candidate",
            "content": {
                "response_kind": "patch_candidate",
                "summary": "missing new text",
                "target_path": "src/auth.py",
                "old_text": "return username",
                "reason": "missing field test",
            },
            "raw_text": None,
            "source_reply_path": None,
            "linked_session_id": None,
            "linked_request_ref": None,
            "warnings": [],
            "errors": [],
        },
    )
    return str(reply_path.relative_to(project_root)).replace("\\", "/")


def test_bridge_review_patch_candidate_usable(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    _, reply_saved = _prepare_packet_and_patch_reply(tmp_path)

    proc = _run_cli(["bridge", "review", reply_saved, "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    review = json.loads(proc.stdout)
    assert review["response_kind"] == "patch_candidate"
    assert review["usable"] is True
    assert "patch_intent" in review["handoff_options"]
    assert "target_path" in review["required_fields_present"]


def test_bridge_review_patch_candidate_missing_field(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _write_invalid_patch_reply_artifact(tmp_path)

    proc = _run_cli(["bridge", "review", reply_saved, "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    review = json.loads(proc.stdout)
    assert review["usable"] is False
    assert "new_text" in review["missing_fields"]
    assert review["handoff_options"] == []


def test_bridge_review_analysis_has_no_patch_handoff(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_path = tmp_path / "analysis.yaml"
    _write_text(
        reply_path,
        "response_kind: analysis\nsummary: inspect auth flow first\nrecommended_files:\n  - src/auth.py\n",
    )
    ingest_proc = _run_cli(["bridge", "ingest", str(reply_path), "--json"], cwd=tmp_path)
    assert ingest_proc.returncode == 0, ingest_proc.stderr
    reply_saved = json.loads(ingest_proc.stdout)["saved_path"]

    proc = _run_cli(["bridge", "review", reply_saved, "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    review = json.loads(proc.stdout)
    assert review["response_kind"] == "analysis"
    assert review["usable"] is True
    assert review["handoff_options"] == []


def test_bridge_handoff_patch_candidate_creates_patch_intent_draft(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    packet_path, reply_saved = _prepare_packet_and_patch_reply(tmp_path)

    proc = _run_cli(["bridge", "handoff", reply_saved, "--as", "patch_intent", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    record = json.loads(proc.stdout)
    assert record["status"] == "created"
    assert record["handoff_kind"] == "patch_intent"
    intent_path = tmp_path / record["target_artifact_ref"]
    assert intent_path.exists()
    intent = _read_yaml(intent_path)
    assert intent["status"] == "draft"
    assert intent["origin"] == "bridge_handoff"
    assert intent["source_bridge_reply_ref"] == reply_saved
    assert intent["source_bridge_packet_ref"] == packet_path
    assert intent["source_session_ref"] == "session-123"
    assert intent["target_path"] == "src/auth.py"
    assert intent["new_text"] == "return username.strip().lower()"
    assert intent["old_text_candidates"][0]["text"] == "return username"


def test_bridge_handoff_blocked_when_reply_unusable(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_saved = _write_invalid_patch_reply_artifact(tmp_path)

    proc = _run_cli(["bridge", "handoff", reply_saved, "--as", "patch_intent", "--json"], cwd=tmp_path)

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert not list((tmp_path / ".cambrian" / "patch_intents").glob("patch_intent_*.yaml"))
    assert list((tmp_path / ".cambrian" / "bridge" / "handoffs").glob("handoff_*.yaml"))


def test_bridge_reply_show_includes_handoff_summary(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    _, reply_saved = _prepare_packet_and_patch_reply(tmp_path)
    handoff_proc = _run_cli(["bridge", "handoff", reply_saved, "--as", "patch_intent"], cwd=tmp_path)
    assert handoff_proc.returncode == 0, handoff_proc.stderr

    proc = _run_cli(["bridge", "reply-show", reply_saved], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Handoff:" in proc.stdout
    assert "patch_intent created" in proc.stdout


def test_status_shows_bridge_review_hint(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    _, reply_saved = _prepare_packet_and_patch_reply(tmp_path)
    review_proc = _run_cli(["bridge", "review", reply_saved, "--save"], cwd=tmp_path)
    assert review_proc.returncode == 0, review_proc.stderr

    proc = _run_cli(["status"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Bridge:" in proc.stdout
    assert "review        : usable" in proc.stdout
    assert "bridge handoff" in proc.stdout


def test_bridge_review_and_handoff_do_not_mutate_source_files(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before = _hash_file(source_path)
    _, reply_saved = _prepare_packet_and_patch_reply(tmp_path)

    review_proc = _run_cli(["bridge", "review", reply_saved, "--save"], cwd=tmp_path)
    assert review_proc.returncode == 0, review_proc.stderr
    handoff_proc = _run_cli(["bridge", "handoff", reply_saved, "--as", "patch_intent"], cwd=tmp_path)
    assert handoff_proc.returncode == 0, handoff_proc.stderr
    status_proc = _run_cli(["status"], cwd=tmp_path)
    assert status_proc.returncode == 0, status_proc.stderr

    assert _hash_file(source_path) == before
