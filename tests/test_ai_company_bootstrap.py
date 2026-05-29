from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_harness_engineer_design import pass_engineering_gate, prepare_engineering_project, run_cli


ROOT = Path(__file__).resolve().parents[1]


def test_ai_company_bootstrap_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "15_AI_COMPANY_BOOTSTRAP.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "AI Company Bootstrap" in text
    assert "cambrian harness install --confirm --json" in text
    assert ".cambrian/authority.yaml" in text
    assert "Bootstrap does not dispatch agents." in text
    assert "docs/product/15_AI_COMPANY_BOOTSTRAP.md" in readme
    assert "15_AI_COMPANY_BOOTSTRAP.md" in index


def test_ai_company_bootstrap_installs_required_company_files(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)

    result = run_cli(tmp_path, "harness", "install", "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    required_paths = [
        ".cambrian/profile.yaml",
        ".cambrian/harness.yaml",
        ".cambrian/workforce.yaml",
        ".cambrian/validation.yaml",
        ".cambrian/operating_rules.yaml",
        ".cambrian/authority.yaml",
        ".cambrian/interview/questions.yaml",
        ".cambrian/interview/answers.yaml",
        ".cambrian/engineering/design_candidate.yaml",
        ".cambrian/engineering/review.yaml",
        ".cambrian/engineering/dry_run.yaml",
        ".cambrian/plan.yaml",
    ]
    for relative_path in required_paths:
        assert (tmp_path / relative_path).exists(), relative_path
    assert list((tmp_path / ".cambrian" / "agents").glob("*.yaml"))
    assert list((tmp_path / ".cambrian" / "skills").glob("*.yaml"))

    workforce = yaml.safe_load((tmp_path / ".cambrian" / "workforce.yaml").read_text(encoding="utf-8"))
    assert workforce["dispatch_policy"]["mode"] == "on_demand"
    assert workforce["dispatch_policy"]["auto_dispatch_on_install"] is False

    authority = yaml.safe_load((tmp_path / ".cambrian" / "authority.yaml").read_text(encoding="utf-8"))
    assert authority["mode"] == "proposal_only"
    assert authority["permissions"]["filesystem_write"] is False


def test_empty_project_goal_bootstrap_installs_project_fit_company_and_auto_contract(tmp_path: Path) -> None:
    goal = "평택스테이호텔 홈페이지를 만들고싶어"

    first = run_cli(tmp_path, "harness", "bootstrap", "--goal", goal, "--auto-24h", "--json")

    assert first.returncode == 0, first.stderr
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "answers_required"
    assert first_payload["product_intent_ref"] == ".cambrian/company/bootstrap/product_intent.yaml"
    assert "--auto-24h" in first_payload["next_commands"][1]
    assert (tmp_path / "PROJECT_BRIEF.md").exists()
    assert (tmp_path / "CONTEXT_INDEX.md").exists()
    assert (tmp_path / "TODO.md").exists()

    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        (tmp_path / ".cambrian" / "interview" / "answers.draft.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    installed = run_cli(
        tmp_path,
        "harness",
        "bootstrap",
        "--goal",
        goal,
        "--answers",
        ".cambrian/interview/answers.yaml",
        "--request",
        "호텔 홈페이지 첫 버전 구축",
        "--auto-24h",
        "--confirm",
        "--json",
    )

    assert installed.returncode == 0, installed.stderr
    payload = json.loads(installed.stdout)
    assert payload["status"] == "installed"
    assert payload["auto_24h"]["status"] == "started"
    assert payload["auto_24h"]["contract_ref"] == ".cambrian/auto/24h_contract.yaml"
    assert "web-experience-reviewer" in payload["generated_agents"]
    assert "hospitality-product-reviewer" in payload["generated_agents"]
    assert "shape-website-golden-path" in payload["generated_skills"]
    assert "review-hospitality-site-contract" in payload["generated_skills"]

    candidate = yaml.safe_load((tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml").read_text(encoding="utf-8"))
    assert candidate["codebase_evidence"]["bootstrap_mode"] == "blank_project_identity_grounded"
    assert candidate["codebase_evidence"]["domain_confidence"]["confirmed"] == ["hotel_site", "website"]
    assert candidate["quality_gate"]["status"] == "pass"

    contract = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "24h_contract.yaml").read_text(encoding="utf-8"))
    assert contract["goal"] == goal
    assert contract["safety"]["source_code_modified_by_bootstrap"] is False
    assert contract["safety"]["provider_api_called_by_bootstrap"] is False

    job = run_cli(tmp_path, "job", "start", "호텔 홈페이지 첫 화면과 예약 문의 흐름을 만들어줘", "--json")

    assert job.returncode == 0, job.stderr
    job_payload = json.loads(job.stdout)
    assert "web-experience-reviewer" in job_payload["selected_agents"]
    assert "hospitality-product-reviewer" in job_payload["selected_agents"]
    assert "shape-website-golden-path" in job_payload["selected_skills"]
    assert "review-hospitality-site-contract" in job_payload["selected_skills"]
    packet = yaml.safe_load((tmp_path / job_payload["job_ref"]).read_text(encoding="utf-8"))
    assert packet["outcome_snapshot"]["evidence_status"] == "grounded"
    assert packet["outcome_snapshot"]["domain_confidence"]["confirmed"] == ["hotel_site", "website"]

    cycle = run_cli(tmp_path, "auto", "cycle", "--max-steps", "2", "--json")

    assert cycle.returncode == 0, cycle.stderr
    cycle_payload = json.loads(cycle.stdout)
    assert cycle_payload["executed_steps"] == 1
    assert cycle_payload["job_refs"]
    assert cycle_payload["packet_refs"]
    assert cycle_payload["source_code_modified"] is False
    assert cycle_payload["provider_api_called"] is False

    task_payload = yaml.safe_load((tmp_path / cycle_payload["task_refs"][0]).read_text(encoding="utf-8"))
    job_bridge = task_payload["job_bridge"]
    assert job_bridge["status"] == "linked"
    assert (tmp_path / job_bridge["job_ref"]).exists()
    assert (tmp_path / job_bridge["packet_ref"]).exists()
    assert "hospitality-product-reviewer" in job_bridge["selected_agents"]
    assert "web-experience-reviewer" in job_bridge["selected_agents"]
    assert "review-hospitality-site-contract" in job_bridge["selected_skills"]
    assert "shape-website-golden-path" in job_bridge["selected_skills"]
    assert job_bridge["source_code_modified_by_job_bridge"] is False
    assert job_bridge["provider_api_called_by_job_bridge"] is False

    directive = (tmp_path / cycle_payload["directive_refs"][0]).read_text(encoding="utf-8")
    assert "## Cambrian Job Bridge" in directive
    assert job_bridge["packet_ref"] in directive
    assert "auto step result contract" in directive

    execution_log = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "execution_log.yaml").read_text(encoding="utf-8"))
    latest_run = execution_log["runs"][-1]
    assert latest_run["job_refs"] == cycle_payload["job_refs"]
    assert latest_run["packet_refs"] == cycle_payload["packet_refs"]
    assert latest_run["source_code_modified"] is False
    assert latest_run["provider_api_called"] is False

    required_role_keys = task_payload["result_contract"]["required_role_output_keys"]
    step_result = tmp_path / "hotel_step_result.yaml"
    step_result.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "호텔 홈페이지 첫 작업 결과를 검증 가능한 형태로 정리했다.",
                "changed_files": ["PROJECT_BRIEF.md"],
                "tests": [{"command": "확인 필요", "status": "manual_required"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["호텔 사이트 목표와 작업 결과를 연결했다."], "artifacts": ["PROJECT_BRIEF.md"]},
                "role_outputs": {key: f"{key} evidence" for key in required_role_keys},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", cycle_payload["task_refs"][0], "--result", str(step_result), "--json")

    assert ingest.returncode == 0, ingest.stderr
    ingest_payload = json.loads(ingest.stdout)
    assert ingest_payload["company_verification_record"]["status"] == "verification_recorded"
    assert ingest_payload["company_context_record"]["status"] == "context_recorded"
    assert ingest_payload["company_context_record"]["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"

    follow_up = run_cli(tmp_path, "job", "start", "방금 auto 결과를 반영해서 호텔 홈페이지 다음 작업을 정리해줘", "--json")

    assert follow_up.returncode == 0, follow_up.stderr
    follow_up_payload = json.loads(follow_up.stdout)
    follow_up_packet = yaml.safe_load((tmp_path / follow_up_payload["request_packet_ref"]).read_text(encoding="utf-8"))
    loop_context = follow_up_packet["execution_contract"]["company_loop_context"]
    assert loop_context["status"] == "available"
    assert loop_context["context_records"]
    assert loop_context["candidate_context_records"]
    assert loop_context["verification_entries"]
    assert loop_context["promotion_policy"]["auto_promote"] is False
    assert loop_context["promotion_review_ref"] == ".cambrian/company/context/promotion_review.yaml"
    assert any("company_loop_context" in item for item in follow_up_packet["execution_contract"]["must_do"])
