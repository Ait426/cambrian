from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_harness_engineer_design import pass_engineering_gate, prepare_engineering_project, run_cli


ROOT = Path(__file__).resolve().parents[1]



def test_job_start_json_exposes_runtime_contract(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr

    result = run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    expected_fields = {
        "ok",
        "status",
        "job_id",
        "job_status",
        "harness_id",
        "workforce_id",
        "selected_agents",
        "selected_skills",
        "dispatch_reason",
        "change_policy",
        "validation_commands",
        "request_packet",
        "request_packet_ref",
        "job_ref",
        "ai_provider_called",
        "source_code_modified",
        "next_commands",
        "pack_job",
    }
    assert expected_fields.issubset(payload)
    assert payload["ok"] is True
    assert payload["job_status"] == "waiting_for_ai_reply"
    assert payload["request_packet_ref"] == payload["request_packet"]
    assert payload["ai_provider_called"] is False
    assert payload["source_code_modified"] is False
    assert payload["selected_agents"]
    assert payload["selected_skills"]
    assert "npm test" in payload["validation_commands"]
    packet_path = tmp_path / payload["request_packet_ref"]
    assert packet_path.exists()
    assert (tmp_path / payload["job_ref"]).exists()
    packet = yaml.safe_load(packet_path.read_text(encoding="utf-8"))
    assert "codex_claude_instruction" in packet
    assert "execution_contract" in packet
    contract = packet["execution_contract"]
    assert contract["role"] == "Cambrian 프로젝트 AI 회사의 실행 엔진"
    assert contract["task"]
    assert contract["harness_id"] == payload["harness_id"]
    assert contract["workforce_id"] == payload["workforce_id"]
    assert contract["selected_agents"] == payload["selected_agents"]
    assert contract["selected_skills"] == payload["selected_skills"]
    assert "npm test" in contract["validation_commands"]
    assert "패치를 적용했다고 말하지 않는다." in contract["must_not_do"]
    assert contract["handoff_back"] == [
        "AI 응답을 ai_reply_patch_candidate.yaml 파일로 저장한다.",
        "cambrian job ingest latest ai_reply_patch_candidate.yaml",
        "cambrian job validate latest",
    ]


def test_job_ingest_accepts_nested_patch_candidate_without_applying(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    source_path = tmp_path / "backend" / "src" / "middleware" / "authMiddleware.ts"
    source_before = source_path.read_text(encoding="utf-8")
    start = run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "ai_reply_patch_candidate.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "reason": "Authorization 헤더에서 Bearer 접두사를 제거해야 한다.",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["reply_kind"] == "patch_candidate"
    assert payload["reply_contract_status"] == "accepted_patch_candidate"
    assert payload["status"] == "validation_ready"
    assert payload["patch_candidate_accepted"] is True
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert payload["ai_provider_called"] is False
    assert payload["request_packet_ref"]
    assert payload["reply_file_ref"]
    assert payload["patch_intent_ref"]
    assert "cambrian job validate" in "\n".join(payload["next_commands"])
    assert source_path.read_text(encoding="utf-8") == source_before
    reply = yaml.safe_load((tmp_path / payload["bridge_reply_ref"]).read_text(encoding="utf-8"))
    assert reply["content"]["target_path"] == "backend/src/middleware/authMiddleware.ts"
    assert reply["source_reply_path"] == "ai_reply_patch_candidate.yaml"


def test_job_validate_returns_trust_gate_and_evidence_for_manual_custom_validation(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    start = run_cli(tmp_path, "job", "start", "login session expiry issue", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "ai_reply_patch_candidate.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Bearer token parsing fix proposal",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "reason": "Authorization header must strip the Bearer prefix.",
                    "old_text": "export function auth() {}",
                    "new_text": "export function auth() { return true; }",
                    "related_tests": ["backend/tests/auth.test.ts"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "job", "ingest", "latest", "ai_reply_patch_candidate.yaml", "--json")
    assert ingest.returncode == 0, ingest.stderr

    result = run_cli(tmp_path, "job", "validate", "latest", "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["validation_status"] == "not_ready"
    assert payload["validation_contract_status"] == "manual_validation_required"
    assert payload["trust_gate_status"] == "manual_required"
    assert payload["manual_validation_required"] is True
    assert "npm test" in payload["validation_commands"]
    assert payload["evidence_ref"]
    assert (tmp_path / payload["evidence_ref"]).exists()
    assert payload["request_packet_ref"]
    assert payload["reply_file_ref"]
    assert payload["patch_intent_ref"]
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert payload["ai_provider_called"] is False
    assert any(item.endswith("ai_reply_patch_candidate.yaml") for item in payload["checked_artifacts"])
    assert "Patch proposal was not applied to source code" in payload["unchecked_items"]
    assert "cambrian job complete" in "\n".join(payload["next_commands"])
    evidence = yaml.safe_load((tmp_path / payload["evidence_ref"]).read_text(encoding="utf-8"))
    assert evidence["trust_gate_status"] == "manual_required"
    assert evidence["source_code_modified"] is False


def test_job_ingest_blocks_invalid_patch_candidate_with_contract_error(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    install = run_cli(tmp_path, "harness", "install", "--confirm", "--json")
    assert install.returncode == 0, install.stderr
    start = run_cli(tmp_path, "job", "start", "로그인 세션 만료 문제 확인해", "--json")
    assert start.returncode == 0, start.stderr
    reply_path = tmp_path / "bad_reply.yaml"
    reply_path.write_text(
        yaml.safe_dump(
            {
                "response_kind": "patch_candidate",
                "summary": "Missing new text",
                "patch": {
                    "target_path": "backend/src/middleware/authMiddleware.ts",
                    "old_text": "export function auth() {}",
                    "reason": "new_text 누락 테스트",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "job", "ingest", "latest", "bad_reply.yaml", "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["reply_contract_status"] == "blocked"
    assert payload["patch_candidate_accepted"] is False
    assert payload["patch_applied"] is False
    assert payload["source_code_modified"] is False
    assert "new_text is required for patch_candidate" in "\n".join(payload["errors"])
