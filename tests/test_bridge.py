from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bridge_prepare_builds_packet_from_current_harness(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)

    proc = _run_cli(["bridge", "prepare", "로그인 에러 수정해", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    packet = payload["packet"]
    assert payload["status"] == "prepared"
    assert packet["request"] == "로그인 에러 수정해"
    assert packet["harness_summary"]["test_command"]
    assert "agent_summary" in packet
    assert "policy_summary" in packet
    assert "memory_summary" in packet
    assert "response_contract" in packet
    assert (tmp_path / payload["saved_path"]).exists()


def test_bridge_prepare_markdown_packet(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)

    proc = _run_cli(["bridge", "prepare", "로그인 에러 수정해", "--format", "md"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "# Cambrian Bridge Packet" in proc.stdout
    assert "## Request" in proc.stdout
    assert "## Response Contract" in proc.stdout
    assert "response_kind" in proc.stdout


def test_bridge_ingest_yaml_reply(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_path = tmp_path / "reply.yaml"
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
                "warnings:",
                "  - keep scope narrow",
            ]
        ),
    )

    proc = _run_cli(["bridge", "ingest", str(reply_path), "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    reply = payload["reply"]
    assert payload["status"] == "ingested"
    assert reply["response_kind"] == "patch_candidate"
    assert (tmp_path / payload["saved_path"]).exists()


def test_bridge_ingest_json_reply(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_path = tmp_path / "reply.json"
    _write_text(
        reply_path,
        json.dumps(
            {
                "response_kind": "analysis",
                "summary": "auth handling should stay narrow",
                "recommended_files": ["src/auth.py"],
                "recommended_tests": ["tests/test_auth.py"],
            },
            ensure_ascii=False,
        ),
    )

    proc = _run_cli(["bridge", "ingest", str(reply_path), "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    reply = json.loads(proc.stdout)["reply"]
    assert reply["response_kind"] == "analysis"
    assert reply["content"]["recommended_files"] == ["src/auth.py"]


def test_bridge_ingest_fenced_markdown_reply(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_path = tmp_path / "reply.md"
    _write_text(
        reply_path,
        """Here is the structured answer.

```yaml
response_kind: plan
summary: inspect auth path and add regression test first
steps:
  - inspect src/auth.py
  - add regression test
```
""",
    )

    proc = _run_cli(["bridge", "ingest", str(reply_path), "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    reply = json.loads(proc.stdout)["reply"]
    assert reply["response_kind"] == "plan"
    assert any("fenced markdown" in warning for warning in reply["warnings"])


def test_bridge_reply_linked_to_packet_and_session(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    packet_proc = _run_cli(["bridge", "prepare", "로그인 에러 수정해", "--json"], cwd=tmp_path)
    assert packet_proc.returncode == 0, packet_proc.stderr
    packet_payload = json.loads(packet_proc.stdout)
    packet = packet_payload["packet"]
    packet_path = packet_payload["saved_path"]
    reply_path = tmp_path / "reply.yaml"
    _write_text(reply_path, "response_kind: review\nsummary: patch looks narrow\n")

    proc = _run_cli(
        ["bridge", "ingest", str(reply_path), "--packet", packet_path, "--session", "session-123", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    reply = json.loads(proc.stdout)["reply"]
    assert reply["packet_id"] == packet["packet_id"]
    assert reply["request"] == packet["request"]
    assert reply["linked_session_id"] == "session-123"
    assert reply["linked_request_ref"] == packet_path


def test_bridge_invalid_reply_blocked_without_reply_artifact(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    reply_path = tmp_path / "bad_reply.yaml"
    _write_text(reply_path, "summary: missing response kind\n")

    proc = _run_cli(["bridge", "ingest", str(reply_path), "--json"], cwd=tmp_path)

    assert proc.returncode != 0
    replies_dir = tmp_path / ".cambrian" / "bridge" / "replies"
    assert not list(replies_dir.glob("reply_*.yaml")) if replies_dir.exists() else True


def test_status_shows_bridge_summary(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    packet_proc = _run_cli(["bridge", "prepare", "로그인 에러 수정해", "--json"], cwd=tmp_path)
    assert packet_proc.returncode == 0, packet_proc.stderr
    packet_path = json.loads(packet_proc.stdout)["saved_path"]
    reply_path = tmp_path / "reply.yaml"
    _write_text(reply_path, "response_kind: analysis\nsummary: inspect auth flow\n")
    ingest_proc = _run_cli(["bridge", "ingest", str(reply_path), "--packet", packet_path], cwd=tmp_path)
    assert ingest_proc.returncode == 0, ingest_proc.stderr

    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Bridge:" in status_proc.stdout
    assert "latest packet" in status_proc.stdout
    assert "latest reply" in status_proc.stdout


def test_bridge_commands_do_not_mutate_source_files(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before = _hash_file(source_path)

    packet_proc = _run_cli(["bridge", "prepare", "로그인 에러 수정해", "--json"], cwd=tmp_path)
    assert packet_proc.returncode == 0, packet_proc.stderr
    packet_payload = json.loads(packet_proc.stdout)
    packet_path = packet_payload["saved_path"]
    show_proc = _run_cli(["bridge", "show", packet_path], cwd=tmp_path)
    assert show_proc.returncode == 0, show_proc.stderr
    reply_path = tmp_path / "reply.yaml"
    _write_text(reply_path, "response_kind: analysis\nsummary: inspect auth flow\n")
    ingest_proc = _run_cli(["bridge", "ingest", str(reply_path), "--packet", packet_path, "--json"], cwd=tmp_path)
    assert ingest_proc.returncode == 0, ingest_proc.stderr
    reply_saved = json.loads(ingest_proc.stdout)["saved_path"]
    reply_show_proc = _run_cli(["bridge", "reply-show", reply_saved], cwd=tmp_path)
    assert reply_show_proc.returncode == 0, reply_show_proc.stderr

    assert _hash_file(source_path) == before
    reply_payload = _read_yaml(tmp_path / reply_saved)
    assert reply_payload["source_reply_path"] == "reply.yaml"
