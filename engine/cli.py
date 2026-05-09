"""Cambrian CLI 진입점."""

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from engine.absorber import SkillAbsorber
from engine.exceptions import (
    SecurityViolationError,
    SkillNotFoundError,
    SkillValidationError,
)
from engine.loop import CambrianEngine

CURRENT_STRONGEST_LANE = "Python + pytest + auth/login narrow bug fix"


def _attach_recovery_payload(payload: dict, hint) -> dict:
    """JSON 출력 payload에 recovery hint를 붙인다."""
    from engine.project_errors import attach_recovery_payload

    return attach_recovery_payload(payload, hint)


def _save_recovery_hint(project_root: Path, hint) -> None:
    """초기화된 프로젝트라면 마지막 오류를 저장한다."""
    from engine.project_errors import save_last_error

    save_last_error(project_root, hint)


def main() -> None:
    """CLI 진입점. argparse로 명령어를 파싱하고 실행한다."""
    # Windows cp949 인코딩 문제 방지: stdout/stderr를 UTF-8로 강제 설정
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--db",
        type=str,
        default="skill_pool/registry.db",
        help="SQLite DB 경로 (기본값: skill_pool/registry.db)",
    )
    common_parser.add_argument(
        "--schemas",
        type=str,
        default="schemas",
        help="JSON Schema 디렉토리 (기본값: schemas)",
    )
    common_parser.add_argument(
        "--skills",
        type=str,
        default="skills",
        help="시드 스킬 디렉토리 (기본값: skills)",
    )
    common_parser.add_argument(
        "--pool",
        type=str,
        default="skill_pool",
        help="스킬 풀 디렉토리 (기본값: skill_pool)",
    )
    common_parser.add_argument(
        "--external",
        type=str,
        nargs="*",
        default=[],
        help="외부 스킬 검색 디렉토리 (여러 개 가능)",
    )
    common_parser.add_argument(
        "--policy",
        type=str,
        default=None,
        help="정책 JSON 파일 경로 (기본: cambrian_policy.json 또는 내장 기본값)",
    )
    common_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="상세 로그 출력",
    )
    common_parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM 프로바이더 (anthropic|openai|google, 기본: anthropic)",
    )
    common_parser.add_argument(
        "--llm-model",
        type=str,
        default=None,
        dest="llm_model",
        help="LLM 모델 ID (미지정 시 프로바이더 기본값)",
    )

    parser = argparse.ArgumentParser(
        prog="cambrian",
        description="Cambrian - AI 위에 입히는 프로젝트용 진화형 신뢰 하네스",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="명령어")

    run_parser = subparsers.add_parser(
        "run",
        help="프로젝트 요청을 준비하거나 실행",
        parents=[common_parser],
    )
    run_parser.add_argument(
        "request",
        nargs="?",
        help="프로젝트 모드 자연어 요청",
    )
    run_parser.add_argument("--domain", "-d", required=False, help="스킬 도메인")
    run_parser.add_argument("--tags", "-t", nargs="+", required=False, help="스킬 태그")
    run_parser.add_argument(
        "--input",
        "-i",
        required=False,
        default=None,
        help="입력 데이터 (JSON 문자열)",
    )
    run_parser.add_argument(
        "--input-file",
        "-f",
        required=False,
        default=None,
        help="입력 데이터 파일 경로 (JSON 파일, -i 대신 사용)",
    )
    run_parser.add_argument(
        "--retries",
        "-r",
        type=int,
        default=3,
        choices=range(0, 11),
        metavar="N",
        help="최대 재시도 0~10 (기본값: 3)",
    )
    run_parser.add_argument(
        "--auto-evolve",
        action="store_true",
        help="fitness < 0.3인 스킬에 자동 진화 실행",
    )
    run_parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        dest="max_candidates",
        help="경쟁 실행 최대 후보 수 (기본: 5)",
    )
    run_parser.add_argument(
        "--execute",
        action="store_true",
        help="프로젝트 모드 request를 실행 가능한 초안으로 시도",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="프로젝트 모드 request를 미리보기만 한다",
    )
    run_parser.add_argument(
        "--skill",
        action="append",
        default=[],
        dest="skills_override",
        help="프로젝트 모드에서 사용할 스킬 ID (반복 가능)",
    )
    run_parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="명시적 대상 파일 경로",
    )
    run_parser.add_argument(
        "--source",
        action="append",
        default=[],
        dest="source_paths_override",
        help="진단 실행에 사용할 source 파일 경로 (반복 가능)",
    )
    run_parser.add_argument(
        "--test",
        action="append",
        default=[],
        dest="related_tests_override",
        help="관련 테스트 파일 경로 (반복 가능)",
    )
    run_parser.add_argument(
        "--output",
        action="append",
        default=[],
        dest="output_paths_override",
        help="예상 출력 파일 경로 (반복 가능)",
    )
    run_parser.add_argument(
        "--action",
        choices=["write_file", "patch_file", "none"],
        default="none",
        help="명시적 실행 액션",
    )
    run_parser.add_argument(
        "--use-top-context",
        action="store_true",
        dest="use_top_context",
        help="추천된 top source/test 문맥을 명시 승인하여 사용",
    )
    run_parser.add_argument(
        "--context",
        type=str,
        default=None,
        dest="context_path",
        help="기존 context artifact 경로",
    )
    run_parser.add_argument(
        "--diagnose-only",
        action="store_true",
        dest="diagnose_only",
        help="수정 없이 inspect/test만 수행하는 진단 실행 준비",
    )
    run_parser.add_argument(
        "--no-scan",
        action="store_true",
        dest="no_scan",
        help="needs_context일 때 자동 context scan을 생략",
    )
    run_parser.add_argument(
        "--content",
        type=str,
        default=None,
        help="write_file에 사용할 내용",
    )
    run_parser.add_argument(
        "--content-file",
        type=str,
        default=None,
        dest="content_file",
        help="write_file에 사용할 내용 파일 경로",
    )
    run_parser.add_argument(
        "--old-text",
        type=str,
        default=None,
        dest="old_text",
        help="patch_file에서 바꿀 기존 문자열",
    )
    run_parser.add_argument(
        "--new-text",
        type=str,
        default=None,
        dest="new_text",
        help="patch_file에서 넣을 새 문자열",
    )
    run_parser.add_argument(
        "--max-variants",
        type=int,
        default=None,
        dest="project_max_variants",
        help="프로젝트 모드 max variants override",
    )
    run_parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        dest="project_max_iterations",
        help="프로젝트 모드 max iterations override",
    )
    run_parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        dest="project_out_dir",
        help="프로젝트 모드 request artifact 저장 경로",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )

    subparsers.add_parser(
        "skills",
        help="등록된 스킬 목록",
        parents=[common_parser],
    )

    skill_parser = subparsers.add_parser(
        "skill",
        help="스킬 상세 정보",
        parents=[common_parser],
    )
    skill_parser.add_argument("skill_id", nargs="?", help="Skill ID or generate")
    skill_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    absorb_parser = subparsers.add_parser(
        "absorb",
        help="외부 스킬 흡수",
        parents=[common_parser],
    )
    absorb_parser.add_argument("path", help="흡수할 스킬 디렉토리 경로")

    remove_parser = subparsers.add_parser(
        "remove",
        help="흡수된 스킬 제거",
        parents=[common_parser],
    )
    remove_parser.add_argument("skill_id", help="제거할 스킬 ID")

    stats_parser = subparsers.add_parser(
        "stats",
        help="엔진 통계",
        parents=[common_parser],
    )
    stats_parser.add_argument(
        "--skill", "-s", default=None, help="특정 스킬 상세 통계",
    )

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="스킬 벤치마크",
        parents=[common_parser],
    )
    benchmark_parser.add_argument("--domain", "-d", required=True, help="스킬 도메인")
    benchmark_parser.add_argument("--tags", "-t", nargs="+", required=True, help="스킬 태그")
    benchmark_parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="입력 데이터 (JSON 문자열)",
    )

    for _action in benchmark_parser._actions:
        if getattr(_action, "dest", None) in {"domain", "tags", "input"}:
            _action.required = False
    benchmark_subparsers = benchmark_parser.add_subparsers(
        dest="benchmark_command",
        help="benchmark 하위 명령",
    )
    benchmark_case_add_parser = benchmark_subparsers.add_parser(
        "case-add",
        help="반복 측정할 benchmark case 저장",
        parents=[common_parser],
    )
    benchmark_case_add_parser.add_argument("request", help="benchmark request")
    benchmark_case_add_parser.add_argument("--name", default=None, help="case name")
    benchmark_case_add_parser.add_argument("--class", dest="request_class", choices=["bug_fix", "review", "docs", "refactor", "unknown"], default="unknown")
    benchmark_case_add_parser.add_argument("--description", default=None)
    benchmark_case_add_parser.add_argument("--tag", action="append", default=[], dest="benchmark_tags")
    benchmark_case_add_parser.add_argument("--focus", action="append", default=[], dest="expected_focus")
    benchmark_case_add_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_cases_parser = benchmark_subparsers.add_parser(
        "cases",
        help="benchmark case 목록",
        parents=[common_parser],
    )
    benchmark_cases_parser.add_argument("--class", dest="request_class", choices=["bug_fix", "review", "docs", "refactor", "unknown"], default=None)
    benchmark_cases_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_workset_save_parser = benchmark_subparsers.add_parser(
        "workset-save",
        help="benchmark workset 저장",
        parents=[common_parser],
    )
    benchmark_workset_save_parser.add_argument("name", help="workset name")
    benchmark_workset_save_parser.add_argument("--case", action="append", default=[], dest="case_refs", help="case id 또는 name")
    benchmark_workset_save_parser.add_argument("--description", default=None)
    benchmark_workset_save_parser.add_argument("--tag", action="append", default=[], dest="benchmark_tags")
    benchmark_workset_save_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_worksets_parser = benchmark_subparsers.add_parser(
        "worksets",
        help="benchmark workset 목록",
        parents=[common_parser],
    )
    benchmark_worksets_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_attach_parser = benchmark_subparsers.add_parser(
        "attach",
        help="case에 mode별 결과 연결",
        parents=[common_parser],
    )
    benchmark_attach_parser.add_argument("case_ref", help="case id 또는 name")
    benchmark_attach_parser.add_argument("--mode", choices=["raw_ai", "bridge_only", "cambrian_guided", "cambrian_full", "manual_baseline"], required=True)
    benchmark_attach_parser.add_argument("--session", default=None, help="do session id 또는 path")
    benchmark_attach_parser.add_argument("--reply", default=None, help="bridge reply id 또는 path")
    benchmark_attach_parser.add_argument("--manual-result", default=None, help="manual result yaml/json")
    benchmark_attach_parser.add_argument("--summary", default=None)
    benchmark_attach_parser.add_argument("--verdict", choices=["strong", "good", "mixed", "weak"], default=None)
    benchmark_attach_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_report_parser = benchmark_subparsers.add_parser(
        "report",
        help="workset benchmark 비교 리포트",
        parents=[common_parser],
    )
    benchmark_report_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_report_parser.add_argument("--save", action="store_true", help="benchmark report 저장")
    benchmark_report_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_baseline_save_parser = benchmark_subparsers.add_parser(
        "baseline-save",
        help="현재 benchmark report를 baseline으로 저장",
        parents=[common_parser],
    )
    benchmark_baseline_save_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_baseline_save_parser.add_argument("--report", default=None, help="baseline source report path")
    benchmark_baseline_save_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_baselines_parser = benchmark_subparsers.add_parser(
        "baselines",
        help="benchmark baseline 목록",
        parents=[common_parser],
    )
    benchmark_baselines_parser.add_argument("--workset", default=None, help="workset name filter")
    benchmark_baselines_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_compare_parser = benchmark_subparsers.add_parser(
        "compare",
        help="current benchmark report를 baseline과 비교",
        parents=[common_parser],
    )
    benchmark_compare_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_compare_parser.add_argument("--against", default=None, help="baseline path 또는 baseline id")
    benchmark_compare_parser.add_argument("--save", action="store_true", help="benchmark compare report 저장")
    benchmark_compare_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_replay_parser = benchmark_subparsers.add_parser(
        "replay",
        help="benchmark case를 안전하게 재생",
        parents=[common_parser],
    )
    benchmark_replay_parser.add_argument("case_ref", help="case id 또는 name")
    benchmark_replay_parser.add_argument("--mode", choices=["cambrian_guided", "cambrian_full"], default="cambrian_guided")
    benchmark_replay_parser.add_argument("--save", action="store_true", default=True, help="replay report 저장")
    benchmark_replay_parser.add_argument("--record-result", action="store_true", default=True, help="benchmark result 자동 기록")
    benchmark_replay_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_replay_show_parser = benchmark_subparsers.add_parser(
        "replay-show",
        help="benchmark replay 상세 보기",
        parents=[common_parser],
    )
    benchmark_replay_show_parser.add_argument("replay_ref", help="replay id 또는 path")
    benchmark_replay_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_replays_parser = benchmark_subparsers.add_parser(
        "replays",
        help="benchmark replay 목록",
        parents=[common_parser],
    )
    benchmark_replays_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_replay_workset_parser = benchmark_subparsers.add_parser(
        "replay-workset",
        help="benchmark workset 전체를 안전하게 재생",
        parents=[common_parser],
    )
    benchmark_replay_workset_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_replay_workset_parser.add_argument("--mode", choices=["cambrian_guided", "cambrian_full"], default="cambrian_guided")
    benchmark_replay_workset_parser.add_argument("--save", action="store_true", default=True, help="workset replay report 저장")
    benchmark_replay_workset_parser.add_argument("--record-results", action="store_true", default=True, help="case별 benchmark result 자동 기록")
    benchmark_replay_workset_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_autonomy_board_parser = benchmark_subparsers.add_parser(
        "autonomy-board",
        help="workset autonomy evidence board 보기",
        parents=[common_parser],
    )
    benchmark_autonomy_board_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_autonomy_board_parser.add_argument("--save", action="store_true", help="autonomy board 저장")
    benchmark_autonomy_board_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_workset_replays_parser = benchmark_subparsers.add_parser(
        "workset-replays",
        help="benchmark workset replay 목록",
        parents=[common_parser],
    )
    benchmark_workset_replays_parser.add_argument("--workset", default=None, help="workset name filter")
    benchmark_workset_replays_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_bottlenecks_parser = benchmark_subparsers.add_parser(
        "bottlenecks",
        help="workset autonomy bottleneck 분석",
        parents=[common_parser],
    )
    benchmark_bottlenecks_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_bottlenecks_parser.add_argument("--mode", choices=["all", "cambrian_guided", "cambrian_full"], default="all")
    benchmark_bottlenecks_parser.add_argument("--save", action="store_true", help="bottleneck report 저장")
    benchmark_bottlenecks_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_proof_parser = benchmark_subparsers.add_parser(
        "proof",
        help="benchmark/metrics/autonomy/bottleneck 증거를 한 장짜리 proof pack으로 묶기",
        parents=[common_parser],
    )
    benchmark_proof_parser.add_argument("workset_name", help="workset name 또는 id")
    benchmark_proof_parser.add_argument("--save", action="store_true", help="proof YAML/Markdown report 저장")
    benchmark_proof_parser.add_argument("--format", choices=["yaml", "md", "both"], default="both", help="--save 시 저장 형식")
    benchmark_proof_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    benchmark_proof_show_parser = benchmark_subparsers.add_parser(
        "proof-show",
        help="저장된 benchmark proof pack 보기",
        parents=[common_parser],
    )
    benchmark_proof_show_parser.add_argument("proof_ref", help="proof id 또는 path")
    benchmark_proof_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    feedback_parser = subparsers.add_parser(
        "feedback",
        help="스킬 피드백 저장",
        parents=[common_parser],
    )
    feedback_parser.add_argument("skill_id", help="대상 스킬 ID")
    feedback_parser.add_argument("rating", type=int, help="평점 (1~5)")
    feedback_parser.add_argument("comment", help="피드백 코멘트")

    evolve_parser = subparsers.add_parser(
        "evolve",
        help="Skill evolution or evidence-based project evolution",
        parents=[common_parser],
    )
    evolve_parser.add_argument("skill_id", nargs="?", help="Skill ID or review/propose/preview/apply/rollback")
    evolve_parser.add_argument("proposal_id", nargs="?", help="Proposal ID for preview/apply/rollback")
    evolve_parser.add_argument(
        "--input",
        "-i",
        required=False,
        help="Benchmark input JSON for legacy skill evolution",
    )
    evolve_parser.add_argument("--recent", type=int, default=5, help="Recent job count for review")
    evolve_parser.add_argument("--confirm", action="store_true", help="Confirm proposal apply or rollback")
    evolve_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    authority_parser = subparsers.add_parser(
        "authority",
        help="프로젝트 권한 프로파일 관리",
        parents=[common_parser],
    )
    authority_subparsers = authority_parser.add_subparsers(dest="authority_command", help="authority 하위 명령")
    authority_status_parser = authority_subparsers.add_parser("status", help="현재 권한 상태 보기", parents=[common_parser])
    authority_status_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    authority_init_parser = authority_subparsers.add_parser("init", help="proposal-only 권한 프로파일 생성", parents=[common_parser])
    authority_init_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    authority_grant_parser = authority_subparsers.add_parser("grant", help="명시 권한 부여", parents=[common_parser])
    authority_grant_parser.add_argument("--mode", required=True, choices=["full-authority", "full_authority", "proposal-only", "proposal_only"], help="부여할 권한 모드")
    authority_grant_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    authority_revoke_parser = authority_subparsers.add_parser("revoke", help="proposal-only로 권한 회수", parents=[common_parser])
    authority_revoke_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    auto_parser = subparsers.add_parser(
        "auto",
        help="오토 제품 제작 상태 모델",
        parents=[common_parser],
    )
    auto_subparsers = auto_parser.add_subparsers(dest="auto_command", help="auto 하위 명령")
    auto_init_parser = auto_subparsers.add_parser("init", help="오토 모드 초기화", parents=[common_parser])
    auto_init_parser.add_argument("--goal", required=True, help="오토 모드 목표")
    auto_init_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_next_parser = auto_subparsers.add_parser("next", help="DONE 이후 새 auto iteration 시작", parents=[common_parser])
    auto_next_parser.add_argument("--goal", required=True, help="새 auto iteration 목표")
    auto_next_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_boardroom_parser = auto_subparsers.add_parser("boardroom", help="CEO/CTO/COO/PM 회의 기록 생성", parents=[common_parser])
    auto_boardroom_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_plan_parser = auto_subparsers.add_parser("plan", help="회의 결정을 실행 계획으로 변환", parents=[common_parser])
    auto_plan_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_run_parser = auto_subparsers.add_parser("run", help="bounded auto run 상태 기록", parents=[common_parser])
    auto_run_parser.add_argument("--max-steps", type=int, default=5, dest="max_steps", help="이번 run에서 처리할 최대 step 수")
    auto_run_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_cycle_parser = auto_subparsers.add_parser("cycle", help="report-boardroom-plan-run 1 cycle 실행", parents=[common_parser])
    auto_cycle_parser.add_argument("--max-steps", type=int, default=1, dest="max_steps", help="cycle run에서 처리할 최대 step 수")
    auto_cycle_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_step_parser = auto_subparsers.add_parser("step", help="auto task 결과 수집", parents=[common_parser])
    auto_step_subparsers = auto_step_parser.add_subparsers(dest="auto_step_command", help="auto step 하위 명령")
    auto_step_ingest_parser = auto_step_subparsers.add_parser("ingest", help="Codex/Claude step 결과 수집", parents=[common_parser])
    auto_step_ingest_parser.add_argument("task_ref", help="task id 또는 .cambrian/auto/tasks/*.yaml")
    auto_step_ingest_parser.add_argument("--result", required=True, dest="result_path", help="step 결과 YAML/JSON 파일")
    auto_step_ingest_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_input_parser = auto_subparsers.add_parser("input", help="auto 입력 요청 처리", parents=[common_parser])
    auto_input_subparsers = auto_input_parser.add_subparsers(dest="auto_input_command", help="auto input 하위 명령")
    auto_input_list_parser = auto_input_subparsers.add_parser("list", help="현재 필요한 human input 목록 보기", parents=[common_parser])
    auto_input_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_input_answer_parser = auto_input_subparsers.add_parser("answer", help="필수 human input 값 기록", parents=[common_parser])
    auto_input_answer_parser.add_argument("--field", required=True, help="입력 필드명")
    auto_input_answer_parser.add_argument("--value", required=True, help="입력 값")
    auto_input_answer_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_input_defer_parser = auto_input_subparsers.add_parser("defer", help="검증이 어려운 human input을 보류", parents=[common_parser])
    auto_input_defer_parser.add_argument("--field", required=True, help="입력 필드명")
    auto_input_defer_parser.add_argument("--reason", required=True, help="보류 사유")
    auto_input_defer_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_status_parser = auto_subparsers.add_parser("status", help="오토 상태 보기", parents=[common_parser])
    auto_status_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_pause_parser = auto_subparsers.add_parser("pause", help="오토 모드 일시정지", parents=[common_parser])
    auto_pause_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_resume_parser = auto_subparsers.add_parser("resume", help="오토 모드 재개", parents=[common_parser])
    auto_resume_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    auto_report_parser = auto_subparsers.add_parser("report", help="오토 모드 보고서 생성", parents=[common_parser])
    auto_report_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    auto_release_gate_parser = auto_subparsers.add_parser("release-gate", help="auto release gate evidence package 생성", parents=[common_parser])
    auto_release_gate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")


    project_parser = subparsers.add_parser(
        "project",
        help="Project harness profile commands",
        parents=[common_parser],
    )
    project_subparsers = project_parser.add_subparsers(dest="project_command", help="project subcommand")
    project_scan_parser = project_subparsers.add_parser("scan", help="Scan project profile", parents=[common_parser])
    project_scan_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    harness_parser = subparsers.add_parser(
        "harness",
        help="고급: project operating profile 관리",
        parents=[common_parser],
    )
    harness_subparsers = harness_parser.add_subparsers(
        dest="harness_command",
        help="harness ?섏쐞 紐낅졊",
    )
    harness_fit_parser = harness_subparsers.add_parser(
        "fit",
        help="?꾨줈?앺듃 ?섎꽕??留욎텣怨?agent registry ?앹꽦",
        parents=[common_parser],
    )
    harness_fit_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")
    harness_show_parser = harness_subparsers.add_parser(
        "show",
        help="?꾩옱 harness profile 蹂닿린",
        parents=[common_parser],
    )
    harness_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")
    harness_doctor_parser = harness_subparsers.add_parser(
        "doctor",
        help="harness source refs? active agent ?곹깭 ?먭?",
        parents=[common_parser],
    )
    harness_doctor_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")

    harness_plan_parser = harness_subparsers.add_parser(
        "plan",
        help="인터뷰 답변 기반 custom harness plan을 만든다",
        parents=[common_parser],
    )
    harness_plan_parser.add_argument("--seed-preset", default=None, help="선택 참고용 preset id")
    harness_plan_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    harness_design_parser = harness_subparsers.add_parser(
        "design",
        help="인터뷰 답변 기반 custom harness design을 만든다",
        parents=[common_parser],
    )
    harness_design_parser.add_argument("--seed-preset", default=None, help="선택 참고용 preset id")
    harness_design_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    harness_install_parser = harness_subparsers.add_parser(
        "install",
        help="승인된 custom harness plan을 설치한다",
        parents=[common_parser],
    )
    harness_install_parser.add_argument("--confirm", action="store_true", help="검토한 plan 설치를 승인한다")
    harness_install_parser.add_argument("--seed-preset", default=None, help="선택 참고용 preset id")
    harness_install_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    harness_engineer_parser = harness_subparsers.add_parser(
        "engineer",
        help="설치 전 하네스 설계 품질 검수와 dry-run",
        parents=[common_parser],
    )
    harness_engineer_subparsers = harness_engineer_parser.add_subparsers(
        dest="harness_engineer_command",
        help="engineer 하위 명령",
    )
    harness_engineer_design_parser = harness_engineer_subparsers.add_parser(
        "design",
        help="profile과 interview answers로 설계 후보를 만든다",
        parents=[common_parser],
    )
    harness_engineer_design_parser.add_argument("--seed-preset", default=None, help="선택 참고용 preset id")
    harness_engineer_design_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    harness_engineer_review_parser = harness_engineer_subparsers.add_parser(
        "review",
        help="설계 후보 품질을 검수한다",
        parents=[common_parser],
    )
    harness_engineer_review_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    harness_engineer_dry_run_parser = harness_engineer_subparsers.add_parser(
        "dry-run",
        help="실제 job 생성 없이 투입될 agent와 skill을 시뮬레이션한다",
        parents=[common_parser],
    )
    harness_engineer_dry_run_parser.add_argument("request", help="dry-run 작업 요청")
    harness_engineer_dry_run_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    harness_interview_parser = harness_subparsers.add_parser(
        "interview",
        help="custom harness 생성을 위한 질문/답변 세션",
        parents=[common_parser],
    )
    harness_interview_subparsers = harness_interview_parser.add_subparsers(
        dest="harness_interview_command",
        help="interview 하위 명령",
    )
    harness_interview_start_parser = harness_interview_subparsers.add_parser(
        "start",
        help="프로젝트에 맞는 하네스 생성 질문을 만든다",
        parents=[common_parser],
    )
    harness_interview_start_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    harness_interview_answer_parser = harness_interview_subparsers.add_parser(
        "answer",
        help="answers.yaml을 검증하고 plan 준비 상태를 확인한다",
        parents=[common_parser],
    )
    harness_interview_answer_parser.add_argument("--answers", required=True, help="answers.yaml 경로")
    harness_interview_answer_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    harness_suggest_parser = harness_subparsers.add_parser(
        "suggest",
        help="harness 조정 제안을 봅니다",
        parents=[common_parser],
    )
    harness_suggest_parser.add_argument("--request", type=str, default=None, help="request-aware harness suggestion")
    harness_suggest_parser.add_argument("--save", action="store_true", help="suggestion report를 저장합니다")
    harness_suggest_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    harness_accept_parser = harness_subparsers.add_parser(
        "accept",
        help="harness suggestion을 명시적으로 받아들입니다",
        parents=[common_parser],
    )
    harness_accept_parser.add_argument("suggestion_id", help="suggestion id")
    harness_accept_parser.add_argument("--resolution", type=str, default=None, help="accept 이유 또는 메모")
    harness_accept_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    harness_dismiss_parser = harness_subparsers.add_parser(
        "dismiss",
        help="harness suggestion을 기각합니다",
        parents=[common_parser],
    )
    harness_dismiss_parser.add_argument("suggestion_id", help="suggestion id")
    harness_dismiss_parser.add_argument("--resolution", type=str, default=None, help="dismiss 이유")
    harness_dismiss_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    harness_decisions_parser = harness_subparsers.add_parser(
        "decisions",
        help="기록된 harness decision을 봅니다",
        parents=[common_parser],
    )
    harness_decisions_parser.add_argument("--status", choices=["accepted", "dismissed"], default=None, help="decision status filter")
    harness_decisions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    workforce_parser = subparsers.add_parser(
        "workforce",
        help="custom harness에 맞는 AI 인력 구성을 만든다",
        parents=[common_parser],
    )
    workforce_subparsers = workforce_parser.add_subparsers(
        dest="workforce_command",
        help="workforce 하위 명령",
    )
    workforce_generate_parser = workforce_subparsers.add_parser(
        "generate",
        help="프로젝트와 인터뷰 답변 기반 AI 인력 draft를 만든다",
        parents=[common_parser],
    )
    workforce_generate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    lane_parser = subparsers.add_parser(
        "lane",
        help="현재 Cambrian strongest lane profile을 봅니다",
        parents=[common_parser],
    )
    lane_subparsers = lane_parser.add_subparsers(
        dest="lane_command",
        help="lane 하위 명령",
    )
    lane_show_parser = lane_subparsers.add_parser(
        "show",
        help="현재 win lane profile을 계산하고 저장합니다",
        parents=[common_parser],
    )
    lane_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    agent_parser = subparsers.add_parser(
        "agent",
        help="고급: local worker registry 관리",
        parents=[common_parser],
    )
    agent_subparsers = agent_parser.add_subparsers(
        dest="agent_command",
        help="agent ?섏쐞 紐낅졊",
    )
    agent_dispatch_parser = agent_subparsers.add_parser(
        "dispatch",
        help="현재 프로젝트 하네스에 맞춰 에이전트 작업을 시작한다",
        parents=[common_parser],
    )
    agent_dispatch_parser.add_argument("request", help="에이전트에게 맡길 작업 요청")
    agent_dispatch_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    agent_run_parser = agent_subparsers.add_parser(
        "run",
        help="생성된 특정 agent를 명시적으로 호출해 작업을 시작한다",
        parents=[common_parser],
    )
    agent_run_parser.add_argument("agent_id", help="실행할 generated agent id")
    agent_run_parser.add_argument("request", help="agent에게 맡길 작업 요청")
    agent_run_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    agent_list_parser = agent_subparsers.add_parser(
        "list",
        help="?ъ슜 媛??agent passport 紐⑸줉",
        parents=[common_parser],
    )
    agent_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")
    agent_show_parser = agent_subparsers.add_parser(
        "show",
        help="?뱀젙 agent passport ?곸꽭 蹂닿린",
        parents=[common_parser],
    )
    agent_show_parser.add_argument("agent_id", help="agent id")
    agent_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")
    agent_recommend_parser = agent_subparsers.add_parser(
        "recommend",
        help="?붿껌怨??섎꽕??湲곗? agent ?붿쿇",
        parents=[common_parser],
    )
    agent_recommend_parser.add_argument("request", help="?먯뿰???붿껌")
    agent_recommend_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")
    agent_history_parser = agent_subparsers.add_parser(
        "history",
        help="agent 로컬 경력 보기",
        parents=[common_parser],
    )
    agent_history_parser.add_argument("agent_id", help="agent id")
    agent_history_parser.add_argument("--limit", type=int, default=5, help="출력할 record 수")
    agent_history_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    agent_review_parser = agent_subparsers.add_parser(
        "review",
        help="agent 현장 평가를 남깁니다",
        parents=[common_parser],
    )
    agent_review_parser.add_argument("agent_id", help="agent id")
    agent_review_parser.add_argument("text", help="review text")
    agent_review_parser.add_argument("--rating", default="good", help="strong|good|mixed|weak")
    agent_review_parser.add_argument("--kind", dest="review_kind", default="performance", help="performance|risk|praise|caution|fit")
    agent_review_parser.add_argument("--tag", action="append", default=[], dest="review_tags", help="review tag")
    agent_review_parser.add_argument("--session", default=None, help="session id or path")
    agent_review_parser.add_argument("--artifact", action="append", default=[], dest="review_artifacts", help="linked artifact path")
    agent_review_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    agent_reviews_parser = agent_subparsers.add_parser(
        "reviews",
        help="agent review 목록을 봅니다",
        parents=[common_parser],
    )
    agent_reviews_parser.add_argument("agent_id", help="agent id")
    agent_reviews_parser.add_argument("--rating", default=None, help="rating filter")
    agent_reviews_parser.add_argument("--status", default=None, help="open|acknowledged")
    agent_reviews_parser.add_argument("--limit", type=int, default=5, help="출력할 review 수")
    agent_reviews_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    agent_trial_parser = agent_subparsers.add_parser(
        "trial",
        help="agent shadow trial run",
        parents=[common_parser],
    )
    agent_trial_parser.add_argument("agent_id", help="shadow agent id")
    agent_trial_parser.add_argument("request", help="request to trial")
    agent_trial_parser.add_argument("--lead", dest="lead_agent_id", default=None, help="current lead agent id")
    agent_trial_parser.add_argument("--save", action="store_true", help="save trial report")
    agent_trial_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    agent_trial_show_parser = agent_subparsers.add_parser(
        "trial-show",
        help="show an agent trial report",
        parents=[common_parser],
    )
    agent_trial_show_parser.add_argument("trial_ref", help="trial id or path")
    agent_trial_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    agent_export_parser = agent_subparsers.add_parser(
        "export",
        help="agent passport export",
        parents=[common_parser],
    )
    agent_export_parser.add_argument("agent_id", help="agent id")
    agent_export_parser.add_argument("--out", help="export path")
    agent_export_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    agent_import_parser = agent_subparsers.add_parser(
        "import",
        help="import external agent passport",
        parents=[common_parser],
    )
    agent_import_parser.add_argument("passport_path", help="passport YAML file")
    agent_import_parser.add_argument("--equip", action="store_true", help="equip after import")
    agent_import_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    agent_equip_parser = agent_subparsers.add_parser(
        "equip",
        help="agent瑜??꾩옱 harness??옣李⑺븯湲?",
        parents=[common_parser],
    )
    agent_equip_parser.add_argument("agent_id", help="agent id")
    agent_equip_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")
    agent_hire_parser = agent_subparsers.add_parser(
        "hire",
        help="agent를 현재 harness에 채용합니다 (equip alias)",
        parents=[common_parser],
    )
    agent_hire_parser.add_argument("agent_id", help="agent id")
    agent_hire_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    agent_unequip_parser = agent_subparsers.add_parser(
        "unequip",
        help="agent瑜??꾩옱 harness?먯꽌 ?댁젣?섍린",
        parents=[common_parser],
    )
    agent_unequip_parser.add_argument("agent_id", help="agent id")
    agent_unequip_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 異쒕젰")

    agent_fire_parser = agent_subparsers.add_parser(
        "fire",
        help="agent를 현재 harness에서 해제합니다 (unequip alias)",
        parents=[common_parser],
    )
    agent_fire_parser.add_argument("agent_id", help="agent id")
    agent_fire_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    job_parser = subparsers.add_parser(
        "job",
        help="에이전트 작업 응답 ingest와 validate를 실행한다",
        parents=[common_parser],
    )
    job_subparsers = job_parser.add_subparsers(
        dest="job_command",
        help="job 하위 명령",
    )
    job_start_parser = job_subparsers.add_parser(
        "start",
        help="설치된 workforce에서 필요한 인력을 골라 작업을 시작한다",
        parents=[common_parser],
    )
    job_start_parser.add_argument("request", help="작업 요청")
    job_start_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    job_ingest_parser = job_subparsers.add_parser(
        "ingest",
        help="AI reply 파일을 현재 job에 붙인다",
        parents=[common_parser],
    )
    job_ingest_parser.add_argument("job_ref", help="job id/path/latest")
    job_ingest_parser.add_argument("reply_file", help="AI reply YAML/JSON/text file")
    job_ingest_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    job_validate_parser = job_subparsers.add_parser(
        "validate",
        help="job을 validation 단계로 이어간다",
        parents=[common_parser],
    )
    job_validate_parser.add_argument("job_ref", help="job id/path/latest")
    job_validate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    job_complete_parser = job_subparsers.add_parser(
        "complete",
        help="job 결과를 사람이 outcome/evidence로 기록한다",
        parents=[common_parser],
    )
    job_complete_parser.add_argument("job_ref", help="job id/path/latest")
    job_complete_parser.add_argument(
        "--outcome",
        required=True,
        choices=["success", "partial", "failed", "rejected", "needs_more_info"],
        help="사람이 판정한 작업 결과",
    )
    job_complete_parser.add_argument("--notes", default="", help="작업 결과와 배운 점")
    job_complete_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    dispatch_parser = subparsers.add_parser(
        "dispatch",
        help="현재 하네스의 staffing 추천 보드를 봅니다",
        parents=[common_parser],
    )
    dispatch_subparsers = dispatch_parser.add_subparsers(
        dest="dispatch_command",
        help="dispatch 하위 명령",
    )
    dispatch_board_parser = dispatch_subparsers.add_parser(
        "board",
        help="현재 프로젝트 하네스 기준 배치 보드를 봅니다",
        parents=[common_parser],
    )
    dispatch_board_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    dispatch_board_parser.add_argument("--save", action="store_true", help="dispatch board를 저장합니다")
    dispatch_recommend_parser = dispatch_subparsers.add_parser(
        "recommend",
        help="특정 요청 기준 배치 추천을 봅니다",
        parents=[common_parser],
    )
    dispatch_recommend_parser.add_argument("request", help="자연어 작업 요청")
    dispatch_recommend_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    dispatch_accept_parser = dispatch_subparsers.add_parser(
        "accept",
        help="accept a staffing recommendation",
        parents=[common_parser],
    )
    dispatch_accept_parser.add_argument("agent_id", help="agent id")
    dispatch_accept_parser.add_argument("--decision", default="hire", help="hire|fire|keep|prefer_lead|prefer_support|keep_as_backup|watch_candidate")
    dispatch_accept_parser.add_argument("--from", dest="source_ref", default=None, help="source report path")
    dispatch_accept_parser.add_argument("--resolution", default=None, help="decision note")
    dispatch_accept_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    dispatch_dismiss_parser = dispatch_subparsers.add_parser(
        "dismiss",
        help="dismiss a staffing recommendation",
        parents=[common_parser],
    )
    dispatch_dismiss_parser.add_argument("agent_id", help="agent id")
    dispatch_dismiss_parser.add_argument("--decision", default="hire", help="hire|fire|keep|prefer_lead|prefer_support|keep_as_backup|watch_candidate")
    dispatch_dismiss_parser.add_argument("--from", dest="source_ref", default=None, help="source report path")
    dispatch_dismiss_parser.add_argument("--resolution", default=None, help="decision note")
    dispatch_dismiss_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    dispatch_decisions_parser = dispatch_subparsers.add_parser(
        "decisions",
        help="list staffing decisions",
        parents=[common_parser],
    )
    dispatch_decisions_parser.add_argument("--status", choices=["accepted", "dismissed"], default=None)
    dispatch_decisions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    team_parser = subparsers.add_parser(
        "team",
        help="agent team preset 관리",
        parents=[common_parser],
    )
    team_subparsers = team_parser.add_subparsers(
        dest="team_command",
        help="team 하위 명령",
    )
    team_save_parser = team_subparsers.add_parser(
        "save",
        help="현재 active agent 조합을 team preset으로 저장",
        parents=[common_parser],
    )
    team_save_parser.add_argument("name", help="team name")
    team_save_parser.add_argument("--description", default=None, help="team description")
    team_save_parser.add_argument("--tag", action="append", default=[], dest="team_tags", help="team tag")
    team_save_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_list_parser = team_subparsers.add_parser(
        "list",
        help="저장된 team preset 목록",
        parents=[common_parser],
    )
    team_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_show_parser = team_subparsers.add_parser(
        "show",
        help="team preset 상세 보기",
        parents=[common_parser],
    )
    team_show_parser.add_argument("name", help="team name or id")
    team_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_apply_parser = team_subparsers.add_parser(
        "apply",
        help="team preset을 현재 active agent 조합으로 적용",
        parents=[common_parser],
    )
    team_apply_parser.add_argument("name", help="team name or id")
    team_apply_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_recommend_parser = team_subparsers.add_parser(
        "recommend",
        help="요청에 맞는 team preset 추천",
        parents=[common_parser],
    )
    team_recommend_parser.add_argument("request", help="작업 요청")
    team_recommend_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_trial_parser = team_subparsers.add_parser(
        "trial",
        help="저장된 team preset을 shadow로 시험 비교",
        parents=[common_parser],
    )
    team_trial_parser.add_argument("name", help="shadow team name or id")
    team_trial_parser.add_argument("request", help="작업 요청")
    team_trial_parser.add_argument("--against", default=None, help="비교 기준 team name or id")
    team_trial_parser.add_argument("--save", action="store_true", dest="save_report", help="trial report 저장")
    team_trial_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_trial_show_parser = team_subparsers.add_parser(
        "trial-show",
        help="team trial report 상세 보기",
        parents=[common_parser],
    )
    team_trial_show_parser.add_argument("trial_ref", help="trial id 또는 .cambrian/agents/team_trials/ 내부 경로")
    team_trial_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_accept_parser = team_subparsers.add_parser(
        "accept",
        help="team 추천/시험근무 결과를 명시적으로 받아들임",
        parents=[common_parser],
    )
    team_accept_parser.add_argument("name", help="team name or id")
    team_accept_parser.add_argument("--decision", default="keep_team", help="apply_team|keep_team|keep_as_backup|watch_team")
    team_accept_parser.add_argument("--from", dest="source_ref", default=None, help="source report path")
    team_accept_parser.add_argument("--resolution", default=None, help="decision note")
    team_accept_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_dismiss_parser = team_subparsers.add_parser(
        "dismiss",
        help="team 추천을 기각함",
        parents=[common_parser],
    )
    team_dismiss_parser.add_argument("name", help="team name or id")
    team_dismiss_parser.add_argument("--from", dest="source_ref", default=None, help="source report path")
    team_dismiss_parser.add_argument("--resolution", default=None, help="decision note")
    team_dismiss_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    team_decisions_parser = team_subparsers.add_parser(
        "decisions",
        help="team staffing decisions 목록",
        parents=[common_parser],
    )
    team_decisions_parser.add_argument("--status", choices=["accepted", "dismissed"], default=None)
    team_decisions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    history_parser = subparsers.add_parser(
        "history",
        help="진화 이력 조회",
        parents=[common_parser],
    )
    history_parser.add_argument("skill_id", help="스킬 ID")
    history_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="최대 반환 개수 (기본값: 10)",
    )
    history_parser.add_argument(
        "--detail",
        type=int,
        default=None,
        metavar="RECORD_ID",
        help="특정 진화 기록의 상세 정보 (diff + reasoning + 피드백)",
    )

    rollback_parser = subparsers.add_parser(
        "rollback",
        help="이전 버전으로 롤백",
        parents=[common_parser],
    )
    rollback_parser.add_argument("skill_id", help="스킬 ID")
    rollback_parser.add_argument("record_id", type=int, help="롤백 대상 진화 기록 ID")

    export_parser = subparsers.add_parser(
        "export",
        help="스킬을 .cambrian 패키지로 내보내기",
        parents=[common_parser],
    )
    export_parser.add_argument("skill_id", help="내보낼 스킬 ID")
    export_parser.add_argument(
        "-o", "--output",
        type=str,
        default=".",
        help="출력 디렉토리 (기본값: 현재 디렉토리)",
    )

    import_parser = subparsers.add_parser(
        "import",
        help=".cambrian 패키지에서 스킬 가져오기",
        parents=[common_parser],
    )
    import_parser.add_argument("path", help="패키지 경로 (.cambrian 파일)")

    critique_parser = subparsers.add_parser(
        "critique",
        help="스킬 비판적 분석",
        parents=[common_parser],
    )
    critique_parser.add_argument("skill_id", help="분석할 스킬 ID")

    init_parser = subparsers.add_parser(
        "init",
        help="시작: 프로젝트에 Cambrian 맞추기",
        parents=[common_parser],
    )
    init_parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="초기화 기준 프로젝트 디렉토리 (기본값: 현재 디렉토리)",
    )
    init_parser.add_argument("--name", type=str, default=None, help="프로젝트 이름")
    init_parser.add_argument(
        "--type", type=str, default=None, dest="project_type", help="프로젝트 타입",
    )
    init_parser.add_argument("--stack", type=str, default=None, help="스택")
    init_parser.add_argument(
        "--test-cmd", type=str, default=None, dest="test_cmd", help="테스트 명령",
    )
    init_parser.add_argument(
        "--non-interactive",
        action="store_true",
        dest="non_interactive",
        help="비상호작용 모드",
    )
    init_parser.add_argument(
        "--wizard",
        action="store_true",
        help="프로젝트 인터뷰 wizard 실행",
    )
    init_parser.add_argument(
        "--answers-file",
        type=str,
        default=None,
        dest="answers_file",
        help="wizard 답변 YAML 파일",
    )
    init_parser.add_argument(
        "--force", action="store_true", help="기존 .cambrian 설정 덮어쓰기",
    )
    init_parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="초기 bootstrap에 사용할 harness template 이름",
    )
    init_parser.add_argument(
        "--use-recommended-template",
        action="store_true",
        help="현재 프로젝트 신호로 추천된 template를 init bootstrap에 사용",
    )
    init_parser.add_argument(
        "--skip-template",
        action="store_true",
        help="template 추천/선택 없이 기존 init 흐름으로 진행",
    )
    init_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    demo_parser = subparsers.add_parser(
        "demo",
        help="첫 실행용 demo 프로젝트 생성",
        parents=[common_parser],
    )
    demo_subparsers = demo_parser.add_subparsers(
        dest="demo_command",
        help="demo 하위 명령",
    )
    demo_create_parser = demo_subparsers.add_parser(
        "create",
        help="샘플 demo 프로젝트 생성",
        parents=[common_parser],
    )
    demo_create_parser.add_argument("demo_name", help="demo 이름")
    demo_create_parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="demo 프로젝트를 만들 경로",
    )
    demo_create_parser.add_argument(
        "--force",
        action="store_true",
        help="기존 비어 있지 않은 demo 디렉터리를 덮어쓰기",
    )
    demo_create_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    install_parser = subparsers.add_parser(
        "install",
        help="local pack manifest 설치와 provenance 관리",
        parents=[common_parser],
    )
    install_subparsers = install_parser.add_subparsers(
        dest="install_command",
        help="install 하위 명령",
    )
    install_pack_parser = install_subparsers.add_parser(
        "pack",
        help="local catalog pack id로 안전하게 설치",
        parents=[common_parser],
    )
    install_pack_parser.add_argument("pack_ref", help="pack id 또는 name")
    install_pack_parser.add_argument("--registry", default=None, help="sync된 registry 이름")
    install_pack_parser.add_argument("--version", default=None, help="설치할 pack version")
    install_pack_parser.add_argument("--no-deps", action="store_true", help="dependency 자동 설치 계획을 사용하지 않음")
    install_pack_parser.add_argument("--confirm-deps", action="store_true", help="dependency graph 설치를 명시 확인")
    install_pack_parser.add_argument("--dry-run", action="store_true", help="설치 전 plan만 출력")
    install_pack_parser.add_argument("--require-trusted", action="store_true", help="trusted source가 아니면 설치 차단")
    install_pack_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_plan_parser = install_subparsers.add_parser(
        "plan",
        help="namespace/version/dependency-aware install plan 보기",
        parents=[common_parser],
    )
    install_plan_parser.add_argument("pack_ref", help="pack id, namespace/id, 또는 pack@version")
    install_plan_parser.add_argument("--registry", default=None, help="우선 검색할 registry 이름")
    install_plan_parser.add_argument("--version", default=None, help="요청 version override")
    install_plan_parser.add_argument("--no-deps", action="store_true", help="dependency를 plan에 포함하지 않음")
    install_plan_parser.add_argument("--save", action="store_true", help="install graph 저장")
    install_plan_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_manifest_parser = install_subparsers.add_parser(
        "manifest",
        help="local pack manifest를 안전하게 설치",
        parents=[common_parser],
    )
    install_manifest_parser.add_argument("path", help="pack manifest YAML path")
    install_manifest_parser.add_argument("--dry-run", action="store_true", help="설치 전 plan만 출력")
    install_manifest_parser.add_argument("--require-trusted", action="store_true", help="trusted source가 아니면 설치 차단")
    install_manifest_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_list_parser = install_subparsers.add_parser(
        "list",
        help="설치된 pack 목록 보기",
        parents=[common_parser],
    )
    install_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_show_parser = install_subparsers.add_parser(
        "show",
        help="설치된 pack 상세 보기",
        parents=[common_parser],
    )
    install_show_parser.add_argument("pack_ref", help="pack id 또는 name")
    install_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_diff_parser = install_subparsers.add_parser(
        "diff",
        help="설치된 pack과 incoming manifest/catalog 버전 비교",
        parents=[common_parser],
    )
    install_diff_parser.add_argument("pack_ref", help="pack id 또는 name")
    install_diff_parser.add_argument("--manifest", default=None, help="비교할 incoming manifest path")
    install_diff_parser.add_argument("--save", action="store_true", help="diff report 저장")
    install_diff_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_update_parser = install_subparsers.add_parser(
        "update",
        help="설치된 pack 업데이트 preview 또는 confirm 실행",
        parents=[common_parser],
    )
    install_update_parser.add_argument("pack_ref", help="pack id 또는 name")
    install_update_parser.add_argument("--manifest", default=None, help="업데이트할 incoming manifest path")
    install_update_parser.add_argument("--dry-run", action="store_true", help="preview만 출력")
    install_update_parser.add_argument("--confirm", action="store_true", help="실제 update 실행")
    install_update_parser.add_argument("--require-trusted", action="store_true", help="trusted source가 아니면 update 차단")
    install_update_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_verify_parser = install_subparsers.add_parser(
        "verify",
        help="설치된 pack manifest digest와 artifact refs 검증",
        parents=[common_parser],
    )
    install_verify_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id 또는 name")
    install_verify_parser.add_argument("--save", action="store_true", help="verification report 저장")
    install_verify_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    install_doctor_parser = install_subparsers.add_parser(
        "doctor",
        help="설치된 pack 참조 무결성 검사",
        parents=[common_parser],
    )
    install_doctor_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="installed pack 제거 preview와 confirm 실행",
        parents=[common_parser],
    )
    uninstall_subparsers = uninstall_parser.add_subparsers(
        dest="uninstall_command",
        help="uninstall 하위 명령",
    )
    uninstall_pack_parser = uninstall_subparsers.add_parser(
        "pack",
        help="installed pack 제거 plan 또는 confirm 실행",
        parents=[common_parser],
    )
    uninstall_pack_parser.add_argument("pack_ref", help="pack id 또는 name")
    uninstall_pack_parser.add_argument("--confirm", action="store_true", help="실제 uninstall 실행")
    uninstall_pack_parser.add_argument("--force", action="store_true", help="blocking reference가 있어도 de-register")
    uninstall_pack_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    pack_parser = subparsers.add_parser(
        "pack",
        help="local pack catalog 탐색과 추천",
        parents=[common_parser],
    )
    pack_subparsers = pack_parser.add_subparsers(
        dest="pack_command",
        help="pack 하위 명령",
    )
    pack_list_parser = pack_subparsers.add_parser(
        "list",
        help="설치 가능한 local pack 목록",
        parents=[common_parser],
    )
    pack_list_parser.add_argument("--kind", choices=["worker", "team", "template", "lane"], default=None)
    pack_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_show_parser = pack_subparsers.add_parser(
        "show",
        help="local pack 상세 보기",
        parents=[common_parser],
    )
    pack_show_parser.add_argument("pack_ref", help="pack id 또는 name")
    pack_show_parser.add_argument("--registry", default=None, help="sync된 registry에서 pack 상세 보기")
    pack_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_search_parser = pack_subparsers.add_parser(
        "search",
        help="local catalog와 sync된 registry cache에서 pack 검색",
        parents=[common_parser],
    )
    pack_search_parser.add_argument("query", nargs="?", default=None, help="검색어")
    pack_search_parser.add_argument("--registry", default=None, help="검색할 registry 이름")
    pack_search_parser.add_argument("--kind", choices=["worker", "team", "template", "lane"], default=None)
    pack_search_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_recommend_parser = pack_subparsers.add_parser(
        "recommend",
        help="현재 프로젝트에 맞는 local pack 추천",
        parents=[common_parser],
    )
    pack_recommend_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_activate_parser = pack_subparsers.add_parser(
        "activate",
        help="설치된 pack을 현재 작업 context로 명시 활성화",
        parents=[common_parser],
    )
    pack_activate_parser.add_argument("pack_ref", help="설치된 pack id/ref")
    pack_activate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_active_parser = pack_subparsers.add_parser(
        "active",
        help="현재 active pack context 보기",
        parents=[common_parser],
    )
    pack_active_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_next_parser = pack_subparsers.add_parser(
        "next",
        help="active pack 기준 첫 작업 명령 안내",
        parents=[common_parser],
    )
    pack_next_parser.add_argument("pack_ref", nargs="?", default=None, help="설치된 pack id/ref")
    pack_next_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_doctor_parser = pack_subparsers.add_parser(
        "doctor",
        help="pack의 현재 프로젝트 readiness와 fit 점검",
        parents=[common_parser],
    )
    pack_doctor_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_doctor_parser.add_argument("--registry", default=None, help="sync된 registry에서 preinstall doctor")
    pack_doctor_parser.add_argument("--save", action="store_true", help="readiness report 저장")
    pack_doctor_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_readiness_parser = pack_subparsers.add_parser(
        "readiness",
        help="pack readiness report 보기",
        parents=[common_parser],
    )
    pack_readiness_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_readiness_parser.add_argument("--registry", default=None, help="sync된 registry에서 preinstall readiness")
    pack_readiness_parser.add_argument("--save", action="store_true", help="readiness report 저장")
    pack_readiness_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_setup_parser = pack_subparsers.add_parser(
        "setup",
        help="pack readiness blocker를 guided setup plan으로 변환",
        parents=[common_parser],
    )
    pack_setup_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_setup_parser.add_argument("--save", action="store_true", help="setup plan 저장")
    pack_setup_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_setup_show_parser = pack_subparsers.add_parser(
        "setup-show",
        help="pack setup plan 보기",
        parents=[common_parser],
    )
    pack_setup_show_parser.add_argument("setup_ref", help="setup plan id/path/latest")
    pack_setup_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_setup_apply_parser = pack_subparsers.add_parser(
        "setup-apply",
        help="safe Cambrian-state setup step만 적용",
        parents=[common_parser],
    )
    pack_setup_apply_parser.add_argument("setup_ref", help="setup plan id/path/latest")
    pack_setup_apply_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_start_parser = pack_subparsers.add_parser(
        "start",
        help="active 또는 명시 pack에 first job handoff 시작",
        parents=[common_parser],
    )
    pack_start_parser.add_argument("start_args", nargs="+", help="request 또는 pack ref + request")
    pack_start_parser.add_argument("--pack", dest="pack_ref_option", default=None, help="작업을 맡길 installed pack id/ref")
    pack_start_parser.add_argument("--mode", choices=["bridge", "do", "safe-autonomy"], default="bridge", help="job entry mode")
    pack_start_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_jobs_parser = pack_subparsers.add_parser(
        "jobs",
        help="최근 pack job 목록 보기",
        parents=[common_parser],
    )
    pack_jobs_parser.add_argument("--pack", dest="pack_ref_option", default=None, help="pack id/ref 필터")
    pack_jobs_parser.add_argument("--limit", type=int, default=20, help="표시할 job 수")
    pack_jobs_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_show_parser = pack_subparsers.add_parser(
        "job-show",
        help="pack job 상세 보기",
        parents=[common_parser],
    )
    pack_job_show_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_next_parser = pack_subparsers.add_parser(
        "job-next",
        help="pack job 다음 명령 보기",
        parents=[common_parser],
    )
    pack_job_next_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_next_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_paste_parser = pack_subparsers.add_parser(
        "job-paste",
        help="AI reply를 pack job에 붙여 bridge fast path로 라우팅",
        parents=[common_parser],
    )
    pack_job_paste_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_paste_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_ingest_parser = pack_subparsers.add_parser(
        "job-ingest",
        help="AI reply 파일을 pack job에 붙여 bridge fast path로 라우팅",
        parents=[common_parser],
    )
    pack_job_ingest_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_ingest_parser.add_argument("reply_file", help="AI reply YAML/JSON/text file")
    pack_job_ingest_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_validate_parser = pack_subparsers.add_parser(
        "job-validate",
        help="validation-ready pack job을 continue --validate로 이어감",
        parents=[common_parser],
    )
    pack_job_validate_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_validate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_apply_parser = pack_subparsers.add_parser(
        "job-apply",
        help="validated pack job proposal apply preview/confirm",
        parents=[common_parser],
    )
    pack_job_apply_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_apply_parser.add_argument("--confirm", action="store_true", help="실제 source mutation을 명시 승인")
    pack_job_apply_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_adopt_parser = pack_subparsers.add_parser(
        "job-adopt",
        help="pack job 결과를 accepted/rejected/skipped로 명시 기록",
        parents=[common_parser],
    )
    pack_job_adopt_parser.add_argument("job_ref", help="job id/path/latest")
    adopt_group = pack_job_adopt_parser.add_mutually_exclusive_group(required=True)
    adopt_group.add_argument("--accepted", action="store_true", help="pack job 결과를 채택")
    adopt_group.add_argument("--rejected", action="store_true", help="pack job 결과를 기각")
    adopt_group.add_argument("--skipped", action="store_true", help="pack job 결과 채택 판단을 건너뜀")
    pack_job_adopt_parser.add_argument("--reason", default=None, help="채택/기각/스킵 이유")
    pack_job_adopt_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_job_retro_parser = pack_subparsers.add_parser(
        "job-retro",
        help="완료된 pack job 회고 artifact 생성",
        parents=[common_parser],
    )
    pack_job_retro_parser.add_argument("job_ref", help="job id/path/latest")
    pack_job_retro_parser.add_argument("--save", action="store_true", help="retrospective 저장")
    pack_job_retro_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_retrospectives_parser = pack_subparsers.add_parser(
        "retrospectives",
        help="pack job retrospective 목록 보기",
        parents=[common_parser],
    )
    pack_retrospectives_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_retrospectives_parser.add_argument("--limit", type=int, default=20, help="표시할 retrospective 수")
    pack_retrospectives_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_retro_summary_parser = pack_subparsers.add_parser(
        "retro-summary",
        help="pack 단위 retrospective summary 생성",
        parents=[common_parser],
    )
    pack_retro_summary_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_retro_summary_parser.add_argument("--save", action="store_true", help="summary 저장")
    pack_retro_summary_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_improve_parser = pack_subparsers.add_parser(
        "improve",
        help="retrospective/proof evidence에서 pack improvement queue 생성",
        parents=[common_parser],
    )
    pack_improve_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_improve_parser.add_argument("--save", action="store_true", help="queue 저장")
    pack_improve_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_improvements_parser = pack_subparsers.add_parser(
        "improvements",
        help="pack improvement queue 목록 보기",
        parents=[common_parser],
    )
    pack_improvements_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_improvements_parser.add_argument("--status", choices=["open", "accepted", "dismissed", "deferred"], default=None, help="상태 필터")
    pack_improvements_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_improvement_show_parser = pack_subparsers.add_parser(
        "improvement-show",
        help="pack improvement item 상세 보기",
        parents=[common_parser],
    )
    pack_improvement_show_parser.add_argument("item_ref", help="item id/path")
    pack_improvement_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_improvement_accept_parser = pack_subparsers.add_parser(
        "improvement-accept",
        help="pack improvement item을 채택 decision으로 기록",
        parents=[common_parser],
    )
    pack_improvement_accept_parser.add_argument("item_ref", help="item id/path")
    pack_improvement_accept_parser.add_argument("--resolution", default=None, help="채택 메모")
    pack_improvement_accept_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_improvement_dismiss_parser = pack_subparsers.add_parser(
        "improvement-dismiss",
        help="pack improvement item을 기각 decision으로 기록",
        parents=[common_parser],
    )
    pack_improvement_dismiss_parser.add_argument("item_ref", help="item id/path")
    pack_improvement_dismiss_parser.add_argument("--resolution", default=None, help="기각 메모")
    pack_improvement_dismiss_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_derivative_plan_parser = pack_subparsers.add_parser(
        "derivative-plan",
        help="accepted improvements를 다음 pack version 계획으로 묶기",
        parents=[common_parser],
    )
    pack_derivative_plan_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_derivative_plan_parser.add_argument("--save", action="store_true", help="derivative plan 저장")
    pack_derivative_plan_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_derivative_show_parser = pack_subparsers.add_parser(
        "derivative-show",
        help="pack derivative plan 상세 보기",
        parents=[common_parser],
    )
    pack_derivative_show_parser.add_argument("plan_ref", help="plan id/path/latest")
    pack_derivative_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_derivative_create_parser = pack_subparsers.add_parser(
        "derivative-create",
        help="derivative plan에서 vNext pack draft 생성",
        parents=[common_parser],
    )
    pack_derivative_create_parser.add_argument("plan_ref", help="plan id/path/latest")
    pack_derivative_create_parser.add_argument("--as", dest="target_pack_id", required=True, help="새 pack id")
    pack_derivative_create_parser.add_argument("--version", default=None, help="새 draft version")
    pack_derivative_create_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_derivative_workbench_parser = pack_subparsers.add_parser(
        "derivative-workbench",
        help="derivative plan을 vNext workbench로 변환",
        parents=[common_parser],
    )
    pack_derivative_workbench_parser.add_argument("plan_ref", help="plan id/path/latest")
    pack_derivative_workbench_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_workorders_parser = pack_subparsers.add_parser(
        "workorders",
        help="pack vNext work order 목록 보기",
        parents=[common_parser],
    )
    pack_workorders_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_workorders_parser.add_argument("--status", choices=["open", "done", "skipped", "blocked"], default=None, help="상태 필터")
    pack_workorders_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_workorder_show_parser = pack_subparsers.add_parser(
        "workorder-show",
        help="pack vNext work order 상세 보기",
        parents=[common_parser],
    )
    pack_workorder_show_parser.add_argument("workorder_ref", help="workorder id/path/latest")
    pack_workorder_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_workorder_done_parser = pack_subparsers.add_parser(
        "workorder-done",
        help="pack vNext work order를 완료로 기록",
        parents=[common_parser],
    )
    pack_workorder_done_parser.add_argument("workorder_ref", help="workorder id/path/latest")
    pack_workorder_done_parser.add_argument("--evidence", action="append", default=[], help="완료 근거 artifact ref")
    pack_workorder_done_parser.add_argument("--note", default=None, help="완료 메모")
    pack_workorder_done_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_workorder_skip_parser = pack_subparsers.add_parser(
        "workorder-skip",
        help="pack vNext work order를 스킵으로 기록",
        parents=[common_parser],
    )
    pack_workorder_skip_parser.add_argument("workorder_ref", help="workorder id/path/latest")
    pack_workorder_skip_parser.add_argument("--note", required=True, help="스킵 메모")
    pack_workorder_skip_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_rc_parser = pack_subparsers.add_parser(
        "rc",
        help="vNext draft/workspace release candidate 생성",
        parents=[common_parser],
    )
    pack_rc_parser.add_argument("draft_or_workspace", help="draft path 또는 derivative workspace path/id")
    pack_rc_parser.add_argument("--allow-unresolved", action="store_true", help="open required workorder를 candidate warning으로 허용")
    pack_rc_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_rc_show_parser = pack_subparsers.add_parser(
        "rc-show",
        help="pack release candidate 상세 보기",
        parents=[common_parser],
    )
    pack_rc_show_parser.add_argument("rc_ref", help="rc id/path/latest")
    pack_rc_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_release_local_parser = pack_subparsers.add_parser(
        "release-local",
        help="release candidate를 local catalog에 preview/release",
        parents=[common_parser],
    )
    pack_release_local_parser.add_argument("rc_ref", help="rc id/path/latest")
    pack_release_local_parser.add_argument("--confirm", action="store_true", help="실제 local catalog update 실행")
    pack_release_local_parser.add_argument("--no-supersede", action="store_true", help="source pack supersede record 생략")
    pack_release_local_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_rollout_parser = pack_subparsers.add_parser(
        "rollout",
        help="새 local release의 안전 rollout plan 생성",
        parents=[common_parser],
    )
    pack_rollout_parser.add_argument("new_pack_ref", help="새 pack id/ref")
    pack_rollout_parser.add_argument("--save", action="store_true", help="rollout plan 저장")
    pack_rollout_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_rollout_show_parser = pack_subparsers.add_parser(
        "rollout-show",
        help="pack rollout plan 상세 보기",
        parents=[common_parser],
    )
    pack_rollout_show_parser.add_argument("rollout_ref", help="rollout id/path/latest")
    pack_rollout_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_rollout_apply_parser = pack_subparsers.add_parser(
        "rollout-apply",
        help="rollout plan의 safe Cambrian-state step을 명시 적용",
        parents=[common_parser],
    )
    pack_rollout_apply_parser.add_argument("rollout_ref", help="rollout id/path/latest")
    pack_rollout_apply_parser.add_argument("--confirm", action="store_true", help="실제 install/activate 상태 변경 실행")
    pack_rollout_apply_parser.add_argument("--install", action="store_true", help="새 pack install 실행")
    pack_rollout_apply_parser.add_argument("--activate", action="store_true", help="새 pack active 전환 실행")
    pack_rollout_apply_parser.add_argument("--mark-old-backup", action="store_true", help="이전 pack을 rollback 후보로 기록")
    pack_rollout_apply_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_deactivate_parser = pack_subparsers.add_parser(
        "deactivate",
        help="active pack context 해제",
        parents=[common_parser],
    )
    pack_deactivate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_usage_parser = pack_subparsers.add_parser(
        "usage",
        help="pack 사용 이벤트와 outcome 요약 보기",
        parents=[common_parser],
    )
    pack_usage_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_usage_parser.add_argument("--save", action="store_true", help="usage summary 저장")
    pack_usage_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_events_parser = pack_subparsers.add_parser(
        "events",
        help="pack raw usage event 목록 보기",
        parents=[common_parser],
    )
    pack_events_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_events_parser.add_argument("--limit", type=int, default=20, help="표시할 event 수")
    pack_events_parser.add_argument(
        "--kind",
        choices=["activated", "surfaced", "used", "benchmark_used", "deactivated"],
        default=None,
        help="event kind 필터",
    )
    pack_events_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_outcomes_parser = pack_subparsers.add_parser(
        "outcomes",
        help="pack outcome attribution 요약 보기",
        parents=[common_parser],
    )
    pack_outcomes_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_outcomes_parser.add_argument("--save", action="store_true", help="usage outcome summary 저장")
    pack_outcomes_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_proof_parser = pack_subparsers.add_parser(
        "proof",
        help="pack usage/outcome 기반 local proof card 생성",
        parents=[common_parser],
    )
    pack_proof_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_proof_parser.add_argument("--save", action="store_true", help="proof card YAML/Markdown 저장")
    pack_proof_parser.add_argument("--format", choices=["yaml", "md", "both"], default="both", help="저장 형식")
    pack_proof_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_proof_show_parser = pack_subparsers.add_parser(
        "proof-show",
        help="저장된 pack proof card 다시 보기",
        parents=[common_parser],
    )
    pack_proof_show_parser.add_argument("proof_ref", help="proof id 또는 path")
    pack_proof_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_proof_export_parser = pack_subparsers.add_parser(
        "proof-export",
        help="local pack proof card를 privacy-safe public snapshot으로 export",
        parents=[common_parser],
    )
    pack_proof_export_parser.add_argument("pack_ref", nargs="?", default=None, help="pack id/ref")
    pack_proof_export_parser.add_argument("--proof", default=None, help="source proof card path")
    pack_proof_export_parser.add_argument("--out", default=None, help="public-safe copy output path")
    pack_proof_export_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_proof_export_show_parser = pack_subparsers.add_parser(
        "proof-export-show",
        help="저장된 privacy-safe pack proof export 다시 보기",
        parents=[common_parser],
    )
    pack_proof_export_show_parser.add_argument("export_ref", help="proof export id 또는 path")
    pack_proof_export_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_verify_parser = pack_subparsers.add_parser(
        "verify",
        help="catalog pack 또는 local manifest digest 검증",
        parents=[common_parser],
    )
    pack_verify_parser.add_argument("pack_ref", help="pack id/name 또는 manifest path")
    pack_verify_parser.add_argument("--save", action="store_true", help="verification report 저장")
    pack_verify_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_draft_parser = pack_subparsers.add_parser(
        "draft",
        help="로컬 worker/team/template/lane refs로 pack draft 생성",
        parents=[common_parser],
    )
    pack_draft_parser.add_argument("pack_id", help="새 pack id")
    pack_draft_parser.add_argument("--kind", choices=["worker", "team", "template", "lane"], required=True)
    pack_draft_parser.add_argument("--name", dest="pack_name", default=None, help="표시 이름")
    pack_draft_parser.add_argument("--version", default=None, help="pack version")
    pack_draft_parser.add_argument("--description", default=None, help="pack 설명")
    pack_draft_parser.add_argument("--tag", action="append", default=[], dest="tags", help="pack tag")
    pack_draft_parser.add_argument("--worker", action="append", default=[], dest="workers", help="worker/agent ref")
    pack_draft_parser.add_argument("--team", action="append", default=[], dest="teams", help="team ref")
    pack_draft_parser.add_argument("--template", action="append", default=[], dest="templates", help="template ref")
    pack_draft_parser.add_argument("--benchmark", action="append", default=[], dest="benchmarks", help="benchmark workset ref")
    pack_draft_parser.add_argument("--lane", default=None, dest="lane_ref", help="lane id")
    pack_draft_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_validate_parser = pack_subparsers.add_parser(
        "validate",
        help="pack draft 또는 manifest 검증",
        parents=[common_parser],
    )
    pack_validate_parser.add_argument("target", help="draft path/pack id 또는 manifest path")
    pack_validate_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_build_parser = pack_subparsers.add_parser(
        "build",
        help="pack draft를 installable manifest로 빌드",
        parents=[common_parser],
    )
    pack_build_parser.add_argument("target", help="draft path 또는 pack id")
    pack_build_parser.add_argument("--out", default=None, help="출력 manifest path")
    pack_build_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_publish_parser = pack_subparsers.add_parser(
        "publish-local",
        help="installable manifest를 local catalog에 preview/publish",
        parents=[common_parser],
    )
    pack_publish_parser.add_argument("manifest_path", help="publish할 .cambrian-pack.yaml path")
    pack_publish_parser.add_argument("--confirm", action="store_true", help="실제 catalog update 실행")
    pack_publish_parser.add_argument("--require-proof", action="store_true", help="proof evidence 없으면 publish 차단")
    pack_publish_parser.add_argument("--release-check", default=None, help="기존 release report path 재사용")
    pack_publish_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_release_parser = pack_subparsers.add_parser(
        "release-check",
        help="pack publish 전 proof/maturity release gate 실행",
        parents=[common_parser],
    )
    pack_release_parser.add_argument("target", help="manifest path 또는 local catalog pack id")
    pack_release_parser.add_argument("--require-proof", action="store_true", help="proof evidence 없으면 blocked")
    pack_release_parser.add_argument("--save", action="store_true", help="release report 저장")
    pack_release_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    pack_web_sync_parser = pack_subparsers.add_parser(
        "web-sync",
        help="local catalog를 static web hiring desk asset으로 동기화",
        parents=[common_parser],
    )
    pack_web_sync_parser.add_argument("--catalog", default=None, help="동기화할 packs/catalog.yaml path")
    pack_web_sync_parser.add_argument("--out", default=None, help="web output directory")
    pack_web_sync_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    registry_parser = subparsers.add_parser(
        "registry",
        help="static pack registry source 등록과 sync",
        parents=[common_parser],
    )
    registry_subparsers = registry_parser.add_subparsers(
        dest="registry_command",
        help="registry 하위 명령",
    )
    registry_add_parser = registry_subparsers.add_parser(
        "add",
        help="static registry catalog URL/path 등록",
        parents=[common_parser],
    )
    registry_add_parser.add_argument("name", help="registry 이름")
    registry_add_parser.add_argument("source_ref", help="catalog JSON/YAML URL 또는 path")
    registry_add_parser.add_argument(
        "--trust-level",
        choices=["trusted", "local", "remote_static", "unknown", "untrusted"],
        default=None,
        help="registry source trust level",
    )
    registry_add_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    registry_list_parser = registry_subparsers.add_parser(
        "list",
        help="등록된 registry source 목록",
        parents=[common_parser],
    )
    registry_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    registry_sync_parser = registry_subparsers.add_parser(
        "sync",
        help="registry catalog를 local cache로 가져오기",
        parents=[common_parser],
    )
    registry_sync_parser.add_argument("name", help="registry 이름")
    registry_sync_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    registry_export_parser = registry_subparsers.add_parser(
        "export",
        help="local catalog를 static registry bundle로 export",
        parents=[common_parser],
    )
    registry_export_parser.add_argument("--out", required=True, help="export output directory")
    registry_export_parser.add_argument("--registry-name", default=None, help="bundle registry name")
    registry_export_parser.add_argument("--namespace", default=None, help="exported pack namespace")
    registry_export_parser.add_argument("--include-unproven", action="store_true", help="draft/unproven pack도 포함")
    registry_export_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    registry_export_check_parser = registry_subparsers.add_parser(
        "export-check",
        help="static registry bundle 무결성과 privacy-safe 여부 검증",
        parents=[common_parser],
    )
    registry_export_check_parser.add_argument("bundle_dir", help="exported registry bundle directory")
    registry_export_check_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")

    metrics_parser = subparsers.add_parser(
        "metrics",
        help="주간 운영 지표 대시보드",
        parents=[common_parser],
    )
    metrics_subparsers = metrics_parser.add_subparsers(
        dest="metrics_command",
        help="metrics 하위 명령",
    )
    metrics_week_parser = metrics_subparsers.add_parser(
        "week",
        help="주간 운영 지표 계산",
        parents=[common_parser],
    )
    metrics_week_parser.add_argument("--start", default=None, help="시작일 YYYY-MM-DD")
    metrics_week_parser.add_argument("--end", default=None, help="종료일 YYYY-MM-DD")
    metrics_week_parser.add_argument("--save", action="store_true", help="weekly metrics report 저장")
    metrics_week_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")


    status_parser = subparsers.add_parser(
        "status",
        help="프로젝트 메모리와 최근 여정 조회",
        parents=[common_parser],
    )
    status_parser.add_argument(
        "--timeline",
        action="store_true",
        dest="timeline",
        help="최근 work session 타임라인 보기",
    )
    status_parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="특정 session id 또는 artifact 경로 보기",
    )
    status_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="타임라인에 보여줄 최대 session 수",
    )
    status_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    status_parser.add_argument(
        "--summary",
        action="store_true",
        dest="summary_output",
        help="상세 status 대신 compact usage summary 보기",
    )

    summary_parser = subparsers.add_parser(
        "summary",
        help="로컬 artifact 기반 프로젝트 사용 요약 보기",
        parents=[common_parser],
    )
    summary_parser.add_argument("--save", action="store_true", help="usage summary YAML 저장")
    summary_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="출력 usage_summary.yaml 경로",
    )
    summary_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="active work / recent journey 최대 표시 수",
    )
    summary_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="설치 및 project mode 환경 점검",
        parents=[common_parser],
    )
    doctor_parser.add_argument(
        "--workspace",
        type=str,
        default=".",
        help="점검할 workspace 경로",
    )
    doctor_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    alpha_parser = subparsers.add_parser(
        "alpha",
        help="project mode alpha readiness 점검",
        parents=[common_parser],
    )
    alpha_subparsers = alpha_parser.add_subparsers(
        dest="alpha_command",
        help="alpha 하위 명령",
    )
    alpha_check_parser = alpha_subparsers.add_parser(
        "check",
        help="alpha readiness audit 실행",
        parents=[common_parser],
    )
    alpha_check_parser.add_argument("--save", action="store_true", help="alpha readiness YAML 저장")
    alpha_check_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="alpha_readiness.yaml 출력 경로",
    )
    alpha_check_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    template_parser = subparsers.add_parser(
        "template",
        help="하네스/팀 운영 템플릿 저장과 적용",
        parents=[common_parser],
    )
    template_subparsers = template_parser.add_subparsers(
        dest="template_command",
        help="template 하위 명령",
    )
    template_save_parser = template_subparsers.add_parser(
        "save",
        help="현재 하네스와 팀 정책을 reusable template으로 저장",
        parents=[common_parser],
    )
    template_save_parser.add_argument("name", help="template name")
    template_save_parser.add_argument("--description", default=None, help="template description")
    template_save_parser.add_argument("--tag", action="append", default=[], dest="template_tags", help="template tag")
    template_save_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_list_parser = template_subparsers.add_parser(
        "list",
        help="저장된 template 목록",
        parents=[common_parser],
    )
    template_list_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_show_parser = template_subparsers.add_parser(
        "show",
        help="template 상세 보기",
        parents=[common_parser],
    )
    template_show_parser.add_argument("name", help="template name or id")
    template_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_apply_parser = template_subparsers.add_parser(
        "apply",
        help="template을 현재 프로젝트의 안전한 초기 운영값으로 적용",
        parents=[common_parser],
    )
    template_apply_parser.add_argument("name", help="template name or id")
    template_apply_parser.add_argument("--force", action="store_true", help="이미 적용된 template origin 교체 허용")
    template_apply_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_diff_parser = template_subparsers.add_parser(
        "diff",
        help="현재 하네스와 template 적용 preview 차이를 비교",
        parents=[common_parser],
    )
    template_diff_parser.add_argument("name", help="template name or id")
    template_diff_parser.add_argument("--save", action="store_true", help="diff report 저장")
    template_diff_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_review_parser = template_subparsers.add_parser(
        "review",
        help="template 적용 전 승인 검토 문서를 생성",
        parents=[common_parser],
    )
    template_review_parser.add_argument("name", help="template name or id")
    template_review_parser.add_argument("--save", action="store_true", help="review artifact 저장")
    template_review_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_accept_parser = template_subparsers.add_parser(
        "accept",
        help="template를 적용 후보로 승인 기록",
        parents=[common_parser],
    )
    template_accept_parser.add_argument("name", help="template name or id")
    template_accept_parser.add_argument("--resolution", default=None, help="accept 이유 또는 메모")
    template_accept_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_dismiss_parser = template_subparsers.add_parser(
        "dismiss",
        help="template를 이번 프로젝트에서 기각 기록",
        parents=[common_parser],
    )
    template_dismiss_parser.add_argument("name", help="template name or id")
    template_dismiss_parser.add_argument("--resolution", default=None, help="dismiss 이유")
    template_dismiss_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_decisions_parser = template_subparsers.add_parser(
        "decisions",
        help="template approval decision 목록",
        parents=[common_parser],
    )
    template_decisions_parser.add_argument("--status", choices=["accepted", "dismissed"], default=None)
    template_decisions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_recommend_parser = template_subparsers.add_parser(
        "recommend",
        help="현재 프로젝트에 가장 잘 맞는 template 추천",
        parents=[common_parser],
    )
    template_recommend_parser.add_argument("--request", default=None, help="request-aware template recommendation")
    template_recommend_parser.add_argument("--save", action="store_true", help="recommendation report 저장")
    template_recommend_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_board_parser = template_subparsers.add_parser(
        "board",
        help="local template library standing board 보기",
        parents=[common_parser],
    )
    template_board_parser.add_argument("--request", default=None, help="request-aware template library board")
    template_board_parser.add_argument("--save", action="store_true", help="library board report 저장")
    template_board_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_parser = template_subparsers.add_parser(
        "qualify",
        help="template derivative를 parent/reference와 같은 workset에서 안전 비교",
        parents=[common_parser],
    )
    template_qualify_parser.add_argument("name", help="candidate template name or id")
    template_qualify_parser.add_argument("--workset", required=True, help="benchmark workset name")
    template_qualify_parser.add_argument("--against", default=None, help="reference template name or id")
    template_qualify_parser.add_argument("--mode", choices=["guided", "full", "both"], default="both")
    template_qualify_parser.add_argument("--save", action="store_true", help="qualification report 저장")
    template_qualify_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_show_parser = template_subparsers.add_parser(
        "qualify-show",
        help="template qualification 상세 보기",
        parents=[common_parser],
    )
    template_qualify_show_parser.add_argument("qualification_ref", help="qualification id 또는 path")
    template_qualify_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_accept_parser = template_subparsers.add_parser(
        "qualify-accept",
        help="candidate_stronger qualification을 운영 결정으로 채택",
        parents=[common_parser],
    )
    template_qualify_accept_parser.add_argument("qualification_ref", help="qualification id 또는 path")
    template_qualify_accept_parser.add_argument("--set-lane-default", action="store_true", help="strongest lane 기본 템플릿으로 지정")
    template_qualify_accept_parser.add_argument(
        "--parent-action",
        choices=["keep_as_backup", "retire", "none"],
        default="keep_as_backup",
        help="reference/parent template 처리 방식",
    )
    template_qualify_accept_parser.add_argument("--resolution", default=None, help="accept 이유 또는 메모")
    template_qualify_accept_parser.add_argument("--force", action="store_true", help="candidate_stronger가 아니어도 경고와 함께 accept")
    template_qualify_accept_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_dismiss_parser = template_subparsers.add_parser(
        "qualify-dismiss",
        help="qualification 채택을 기각",
        parents=[common_parser],
    )
    template_qualify_dismiss_parser.add_argument("qualification_ref", help="qualification id 또는 path")
    template_qualify_dismiss_parser.add_argument("--resolution", default=None, help="dismiss 이유 또는 메모")
    template_qualify_dismiss_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_decisions_parser = template_subparsers.add_parser(
        "qualify-decisions",
        help="qualification 기반 운영 결정 목록",
        parents=[common_parser],
    )
    template_qualify_decisions_parser.add_argument("--status", choices=["accepted", "dismissed"], default=None, help="결정 상태 필터")
    template_qualify_decisions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_adoptions_parser = template_subparsers.add_parser(
        "qualify-adoptions",
        help="qualification accept로 적용된 adoption snapshot 목록",
        parents=[common_parser],
    )
    template_qualify_adoptions_parser.add_argument("--status", choices=["applied", "reverted"], default=None, help="adoption 상태 필터")
    template_qualify_adoptions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_revert_parser = template_subparsers.add_parser(
        "qualify-revert",
        help="qualification adoption을 snapshot 기준으로 되돌리기",
        parents=[common_parser],
    )
    template_qualify_revert_parser.add_argument("adoption_ref", help="adoption id 또는 path")
    template_qualify_revert_parser.add_argument("--resolution", default=None, help="revert 이유 또는 메모")
    template_qualify_revert_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_stage_parser = template_subparsers.add_parser(
        "qualify-stage",
        help="candidate_stronger qualification을 안전한 lane canary로 stage",
        parents=[common_parser],
    )
    template_qualify_stage_parser.add_argument("qualification_ref", help="qualification id 또는 path")
    template_qualify_stage_parser.add_argument("--reason", default=None, help="canary stage 이유")
    template_qualify_stage_parser.add_argument("--force", action="store_true", help="candidate_stronger가 아니어도 경고와 함께 stage")
    template_qualify_stage_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_parser = template_subparsers.add_parser(
        "canary",
        help="strongest lane canary template 상태 보기",
        parents=[common_parser],
    )
    template_canary_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_ledger_parser = template_subparsers.add_parser(
        "canary-ledger",
        help="active canary template exposure/selection ledger 보기",
        parents=[common_parser],
    )
    template_canary_ledger_parser.add_argument("name", nargs="?", default=None, help="canary template name")
    template_canary_ledger_parser.add_argument("--save", action="store_true", help="canary ledger summary 저장")
    template_canary_ledger_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_events_parser = template_subparsers.add_parser(
        "canary-events",
        help="canary raw exposure/selection events 보기",
        parents=[common_parser],
    )
    template_canary_events_parser.add_argument("name", nargs="?", default=None, help="canary template name")
    template_canary_events_parser.add_argument("--limit", type=int, default=20, help="표시할 최근 event 수")
    template_canary_events_parser.add_argument(
        "--kind",
        choices=["surfaced", "selected", "skipped", "applied", "replayed", "validated", "blocked", "bootstrapped"],
        default=None,
        help="event kind 필터",
    )
    template_canary_events_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_outcomes_parser = template_subparsers.add_parser(
        "canary-outcomes",
        help="canary 선택 이후 validated/adopted outcome attribution 보기",
        parents=[common_parser],
    )
    template_canary_outcomes_parser.add_argument("name", nargs="?", default=None, help="canary template name")
    template_canary_outcomes_parser.add_argument("--save", action="store_true", help="canary outcome attribution 저장")
    template_canary_outcomes_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_links_parser = template_subparsers.add_parser(
        "canary-links",
        help="canary selected-to-outcome attribution link 목록 보기",
        parents=[common_parser],
    )
    template_canary_links_parser.add_argument("name", nargs="?", default=None, help="canary template name")
    template_canary_links_parser.add_argument("--limit", type=int, default=20, help="표시할 최근 link 수")
    template_canary_links_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_review_parser = template_subparsers.add_parser(
        "canary-review",
        help="canary evidence freshness review 보기",
        parents=[common_parser],
    )
    template_canary_review_parser.add_argument("name", nargs="?", default=None, help="canary template name")
    template_canary_review_parser.add_argument("--save", action="store_true", help="canary review report 저장")
    template_canary_review_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_review_show_parser = template_subparsers.add_parser(
        "canary-review-show",
        help="canary freshness review 상세 보기",
        parents=[common_parser],
    )
    template_canary_review_show_parser.add_argument("review_ref", help="canary review id 또는 path")
    template_canary_review_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_report_parser = template_subparsers.add_parser(
        "canary-report",
        help="active canary template burn-in evidence report 생성",
        parents=[common_parser],
    )
    template_canary_report_parser.add_argument("name", nargs="?", default=None, help="canary template name")
    template_canary_report_parser.add_argument("--workset", default=None, help="burn-in evidence workset hint")
    template_canary_report_parser.add_argument("--save", action="store_true", help="canary report 저장")
    template_canary_report_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_report_show_parser = template_subparsers.add_parser(
        "canary-report-show",
        help="canary burn-in report 상세 보기",
        parents=[common_parser],
    )
    template_canary_report_show_parser.add_argument("report_ref", help="canary report id 또는 path")
    template_canary_report_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_canary_promote_parser = template_subparsers.add_parser(
        "canary-promote",
        help="promote_ready canary를 stable lane default로 승격",
        parents=[common_parser],
    )
    template_canary_promote_parser.add_argument("name", help="canary template name")
    template_canary_promote_parser.add_argument(
        "--previous-default-action",
        choices=["keep_as_backup", "retire", "none"],
        default="keep_as_backup",
        help="기존 stable default 처리 방식",
    )
    template_canary_promote_parser.add_argument("--resolution", default=None, help="promotion 이유 또는 메모")
    template_canary_promote_parser.add_argument("--force", action="store_true", help="warming/review_due gate를 경고와 함께 승격")
    template_canary_promote_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_qualify_unstage_parser = template_subparsers.add_parser(
        "qualify-unstage",
        help="active lane canary template 제거",
        parents=[common_parser],
    )
    template_qualify_unstage_parser.add_argument("qualification_ref", help="qualification id 또는 path")
    template_qualify_unstage_parser.add_argument("--resolution", default=None, help="unstage 이유 또는 메모")
    template_qualify_unstage_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_challenge_matrix_parser = template_subparsers.add_parser(
        "challenge-matrix",
        help="stable/canary/queued challengers를 같은 workset에서 replay 비교",
        parents=[common_parser],
    )
    template_challenge_matrix_parser.add_argument("--workset", required=True, help="benchmark workset name")
    template_challenge_matrix_parser.add_argument("--mode", choices=["guided", "full", "both"], default="both")
    template_challenge_matrix_parser.add_argument("--save", action="store_true", help="challenge matrix report 저장")
    template_challenge_matrix_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_challenge_matrix_show_parser = template_subparsers.add_parser(
        "challenge-matrix-show",
        help="challenge matrix report 상세 보기",
        parents=[common_parser],
    )
    template_challenge_matrix_show_parser.add_argument("matrix_ref", help="challenge matrix id 또는 path")
    template_challenge_matrix_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_challenge_board_parser = template_subparsers.add_parser(
        "challenge-board",
        help="matrix-backed challenger board 보기",
        parents=[common_parser],
    )
    template_challenge_board_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_challengers_parser = template_subparsers.add_parser(
        "challengers",
        help="queued challenger와 matrix rank 보기",
        parents=[common_parser],
    )
    template_challengers_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_lineage_parser = template_subparsers.add_parser(
        "lineage",
        help="template parent/root lineage와 qualification 요약 보기",
        parents=[common_parser],
    )
    template_lineage_parser.add_argument("name", help="template name or id")
    template_lineage_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    for library_decision_command, library_decision_help in [
        ("promote", "template를 local library preferred로 승격 기록"),
        ("keep", "template를 local library 유지 상태로 기록"),
        ("backup", "template를 local library backup으로 기록"),
        ("watch", "template를 local library watch 대상으로 기록"),
        ("retire", "template를 local library retire 후보로 기록"),
    ]:
        library_decision_parser = template_subparsers.add_parser(
            library_decision_command,
            help=library_decision_help,
            parents=[common_parser],
        )
        library_decision_parser.add_argument("name", help="template name or id")
        library_decision_parser.add_argument("--resolution", default=None, help="decision 이유 또는 메모")
        library_decision_parser.add_argument("--from", dest="source_ref", default=None, help="source board/history path")
        library_decision_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_library_decisions_parser = template_subparsers.add_parser(
        "library-decisions",
        help="template library curation decision 목록",
        parents=[common_parser],
    )
    template_library_decisions_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_export_parser = template_subparsers.add_parser(
        "export",
        help="template를 portable YAML 파일로 내보내기",
        parents=[common_parser],
    )
    template_export_parser.add_argument("name", help="template name or id")
    template_export_parser.add_argument("--out", default=None, help="export output path")
    template_export_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_import_parser = template_subparsers.add_parser(
        "import",
        help="portable template YAML 파일을 현재 프로젝트 local library로 가져오기",
        parents=[common_parser],
    )
    template_import_parser.add_argument("file", help="template export YAML path")
    template_import_parser.add_argument("--as", dest="as_name", default=None, help="import under a new template name")
    template_import_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_history_parser = template_subparsers.add_parser(
        "history",
        help="template passport history 보기",
        parents=[common_parser],
    )
    template_history_parser.add_argument("name", help="template name or id")
    template_history_parser.add_argument("--limit", type=int, default=12, help="출력할 recent record 수")
    template_history_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_retrospective_parser = template_subparsers.add_parser(
        "retrospective",
        help="template 사용 후 retrospective 남기기",
        parents=[common_parser],
    )
    template_retrospective_parser.add_argument("name", help="template name or id")
    template_retrospective_parser.add_argument("text", help="retrospective text")
    template_retrospective_parser.add_argument("--rating", choices=["strong", "good", "mixed", "weak"], default="good")
    template_retrospective_parser.add_argument("--kind", choices=["bootstrap", "fit", "safety", "team", "policy"], default="fit")
    template_retrospective_parser.add_argument("--tag", action="append", default=[], dest="retrospective_tags")
    template_retrospective_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    template_retrospectives_parser = template_subparsers.add_parser(
        "retrospectives",
        help="template retrospective 목록 보기",
        parents=[common_parser],
    )
    template_retrospectives_parser.add_argument("name", help="template name or id")
    template_retrospectives_parser.add_argument("--rating", choices=["strong", "good", "mixed", "weak"], default=None)
    template_retrospectives_parser.add_argument("--status", choices=["open", "acknowledged"], default=None)
    template_retrospectives_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    bridge_parser = subparsers.add_parser(
        "bridge",
        help="AI 비종속 prompt packet/reply ingest 브리지",
        parents=[common_parser],
    )
    bridge_subparsers = bridge_parser.add_subparsers(
        dest="bridge_command",
        help="bridge 하위 명령",
    )
    bridge_prepare_parser = bridge_subparsers.add_parser(
        "prepare",
        help="AI에 붙여넣을 Cambrian 작업 패킷 생성",
        parents=[common_parser],
    )
    bridge_prepare_parser.add_argument("request", help="작업 요청")
    bridge_prepare_parser.add_argument("--session", default=None, help="연결할 session id 또는 path")
    bridge_prepare_parser.add_argument("--format", choices=["yaml", "md"], default="yaml", help="출력 형식")
    bridge_prepare_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_paste_parser = bridge_subparsers.add_parser(
        "paste",
        help="stdin으로 AI reply를 붙여넣고 safe fast path로 라우팅",
        parents=[common_parser],
        description="AI가 반환한 YAML/JSON reply를 파일 저장 없이 붙여넣어 Cambrian bridge fast path로 처리합니다.",
        epilog=(
            "Fast path:\n"
            "  cambrian bridge prepare \"로그인 에러 수정해\"\n"
            "  cambrian bridge paste --packet packet-...\n\n"
            "Input 종료:\n"
            "  Windows/PowerShell: Ctrl+Z then Enter\n"
            "  Unix/macOS: Ctrl+D"
        ),
    )
    bridge_paste_parser.add_argument("--packet", default=None, help="연결할 packet id 또는 path")
    bridge_paste_parser.add_argument("--session", default=None, help="연결할 session id 또는 path")
    bridge_paste_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_show_parser = bridge_subparsers.add_parser(
        "show",
        help="bridge packet 보기",
        parents=[common_parser],
    )
    bridge_show_parser.add_argument("packet_ref", help="packet id 또는 path")
    bridge_show_parser.add_argument("--format", choices=["text", "md"], default="text", help="출력 형식")
    bridge_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_ingest_parser = bridge_subparsers.add_parser(
        "ingest",
        help="AI structured reply를 Cambrian reply artifact로 저장",
        parents=[common_parser],
    )
    bridge_ingest_parser.add_argument("file", help="YAML/JSON/markdown reply file")
    bridge_ingest_parser.add_argument("--packet", default=None, help="연결할 packet id 또는 path")
    bridge_ingest_parser.add_argument("--session", default=None, help="연결할 session id 또는 path")
    bridge_ingest_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_ingest_parser.add_argument("--auto-route", action="store_true", dest="auto_route", help="ingest 후 response_kind별 fast path를 실행")
    bridge_reply_show_parser = bridge_subparsers.add_parser(
        "reply-show",
        help="ingested bridge reply 보기",
        parents=[common_parser],
    )
    bridge_reply_show_parser.add_argument("reply_ref", help="reply id 또는 path")
    bridge_reply_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_review_parser = bridge_subparsers.add_parser(
        "review",
        help="ingested bridge reply를 검토하고 safe handoff option을 봅니다",
        parents=[common_parser],
    )
    bridge_review_parser.add_argument("reply_ref", help="reply id 또는 path")
    bridge_review_parser.add_argument("--save", action="store_true", help="review artifact 저장")
    bridge_review_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_handoff_parser = bridge_subparsers.add_parser(
        "handoff",
        help="bridge reply/materialization을 안전한 다음 artifact로 넘깁니다",
        parents=[common_parser],
    )
    bridge_handoff_parser.add_argument("handoff_ref", help="reply/materialization id 또는 path")
    bridge_handoff_parser.add_argument(
        "--as",
        dest="handoff_kind",
        choices=["patch_intent", "context_hint", "checklist"],
        required=True,
        help="handoff artifact kind",
    )
    bridge_handoff_parser.add_argument("--session", default=None, help="연결할 do session id 또는 path")
    bridge_handoff_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_resume_parser = bridge_subparsers.add_parser(
        "resume",
        help="bridge reply에서 이어갈 do session과 다음 명령을 보여줍니다",
        parents=[common_parser],
    )
    bridge_resume_parser.add_argument("reply_ref", help="reply id 또는 path")
    bridge_resume_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_materialize_parser = bridge_subparsers.add_parser(
        "materialize",
        help="analysis/review/plan bridge reply를 읽기용 artifact로 변환",
        parents=[common_parser],
    )
    bridge_materialize_parser.add_argument("reply_ref", help="reply id 또는 path")
    bridge_materialize_parser.add_argument("--as", dest="materialization_kind", choices=["analysis_brief", "review_note", "plan_record"], default=None)
    bridge_materialize_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_materialize_show_parser = bridge_subparsers.add_parser(
        "materialize-show",
        help="bridge materialization 상세 보기",
        parents=[common_parser],
    )
    bridge_materialize_show_parser.add_argument("materialization_ref", help="materialization id 또는 path")
    bridge_materialize_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_materializations_parser = bridge_subparsers.add_parser(
        "materializations",
        help="bridge materialization 목록",
        parents=[common_parser],
    )
    bridge_materializations_parser.add_argument("--kind", choices=["analysis_brief", "review_note", "plan_record"], default=None)
    bridge_materializations_parser.add_argument("--limit", type=int, default=10)
    bridge_materializations_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_context_hints_parser = bridge_subparsers.add_parser(
        "context-hints",
        help="bridge analysis context hint 목록",
        parents=[common_parser],
    )
    bridge_context_hints_parser.add_argument("--limit", type=int, default=10)
    bridge_context_hints_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_context_hint_show_parser = bridge_subparsers.add_parser(
        "context-hint-show",
        help="bridge context hint 상세 보기",
        parents=[common_parser],
    )
    bridge_context_hint_show_parser.add_argument("hint_ref", help="context hint id 또는 path")
    bridge_context_hint_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_checklists_parser = bridge_subparsers.add_parser(
        "checklists",
        help="bridge plan checklist 목록",
        parents=[common_parser],
    )
    bridge_checklists_parser.add_argument("--status", choices=["open", "in_progress", "blocked", "completed"], default=None)
    bridge_checklists_parser.add_argument("--limit", type=int, default=10)
    bridge_checklists_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_checklist_show_parser = bridge_subparsers.add_parser(
        "checklist-show",
        help="bridge checklist 상세 보기",
        parents=[common_parser],
    )
    bridge_checklist_show_parser.add_argument("checklist_ref", help="checklist id 또는 path")
    bridge_checklist_show_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    bridge_checklist_step_parser = bridge_subparsers.add_parser(
        "checklist-step",
        help="bridge checklist step 상태 변경",
        parents=[common_parser],
    )
    bridge_checklist_step_parser.add_argument("checklist_ref", help="checklist id 또는 path")
    bridge_checklist_step_parser.add_argument("step_id", help="step id")
    bridge_checklist_step_parser.add_argument("--done", action="store_true")
    bridge_checklist_step_parser.add_argument("--blocked", action="store_true")
    bridge_checklist_step_parser.add_argument("--skip", action="store_true")
    bridge_checklist_step_parser.add_argument("--todo", action="store_true")
    bridge_checklist_step_parser.add_argument("--note", default=None)
    bridge_checklist_step_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")

    notes_parser = subparsers.add_parser(
        "notes",
        help="프로젝트 로컬 사용자 notes 관리",
        parents=[common_parser],
    )
    notes_subparsers = notes_parser.add_subparsers(
        dest="notes_command",
        help="notes 하위 명령",
    )
    notes_add_parser = notes_subparsers.add_parser(
        "add",
        help="사용자 note 저장",
        parents=[common_parser],
    )
    notes_add_parser.add_argument("text", help="남길 note 문장")
    notes_add_parser.add_argument(
        "--kind",
        choices=["note", "confusion", "bug", "idea", "success", "friction"],
        default="note",
        help="note kind",
    )
    notes_add_parser.add_argument(
        "--severity",
        choices=["low", "medium", "high"],
        default="medium",
        help="severity",
    )
    notes_add_parser.add_argument(
        "--tag",
        action="append",
        default=[],
        dest="note_tags",
        help="note tag (반복 가능)",
    )
    notes_add_parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="연결할 session id 또는 session artifact 경로",
    )
    notes_add_parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        dest="artifact_refs",
        help="연결할 artifact 경로 (반복 가능)",
    )
    notes_add_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    notes_list_parser = notes_subparsers.add_parser(
        "list",
        help="사용자 note 목록 보기",
        parents=[common_parser],
    )
    notes_list_parser.add_argument(
        "--status",
        choices=["open", "resolved"],
        default=None,
        help="status 필터 (기본: open)",
    )
    notes_list_parser.add_argument(
        "--kind",
        choices=["note", "confusion", "bug", "idea", "success", "friction"],
        default=None,
        help="kind 필터",
    )
    notes_list_parser.add_argument(
        "--severity",
        choices=["low", "medium", "high"],
        default=None,
        help="severity 필터",
    )
    notes_list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="최대 표시 개수",
    )
    notes_list_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    notes_show_parser = notes_subparsers.add_parser(
        "show",
        help="사용자 note 상세 보기",
        parents=[common_parser],
    )
    notes_show_parser.add_argument("note_ref", help="note id 또는 note artifact 경로")
    notes_show_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    notes_resolve_parser = notes_subparsers.add_parser(
        "resolve",
        help="사용자 note 해결 처리",
        parents=[common_parser],
    )
    notes_resolve_parser.add_argument("note_ref", help="note id 또는 note artifact 경로")
    notes_resolve_parser.add_argument(
        "--resolution",
        type=str,
        default=None,
        help="해결 메모",
    )
    notes_resolve_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    memory_parser = subparsers.add_parser(
        "memory",
        help="프로젝트 기억 기반 추천과 조회",
        parents=[common_parser],
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_command",
        help="memory 하위 명령",
    )
    memory_recommend_parser = memory_subparsers.add_parser(
        "recommend",
        help="요청별 memory-aware 스킬 추천 보기",
        parents=[common_parser],
    )
    memory_recommend_parser.add_argument("request", help="자연어 작업 요청")
    memory_recommend_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="최대 relevant lesson 수",
    )
    memory_recommend_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    memory_rebuild_parser = memory_subparsers.add_parser(
        "rebuild",
        help="source artifact에서 project memory를 다시 생성",
        parents=[common_parser],
    )
    memory_rebuild_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="출력 lessons.yaml 경로",
    )
    memory_rebuild_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="최대 lesson 수",
    )
    memory_rebuild_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    memory_list_parser = memory_subparsers.add_parser(
        "list",
        help="현재 project memory lesson 목록",
        parents=[common_parser],
    )
    memory_list_parser.add_argument("--kind", type=str, default=None, help="lesson kind 필터")
    memory_list_parser.add_argument("--tag", type=str, default=None, help="lesson tag 필터")
    memory_list_parser.add_argument("--limit", type=int, default=None, help="최대 표시 개수")
    memory_list_parser.add_argument(
        "--include-suppressed",
        action="store_true",
        dest="include_suppressed",
        help="suppressed lesson 포함",
    )
    memory_list_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    memory_show_parser = memory_subparsers.add_parser(
        "show",
        help="lesson 상세 보기",
        parents=[common_parser],
    )
    memory_show_parser.add_argument("lesson_id", help="조회할 lesson id")
    memory_show_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    memory_review_parser = memory_subparsers.add_parser(
        "review",
        help="project memory를 pinned/active/suppressed 기준으로 검토",
        parents=[common_parser],
    )
    memory_review_parser.add_argument(
        "--include-suppressed",
        action="store_true",
        dest="include_suppressed",
        help="suppressed lesson 포함",
    )
    memory_review_parser.add_argument("--kind", type=str, default=None, help="lesson kind 필터")
    memory_review_parser.add_argument("--tag", type=str, default=None, help="lesson tag 필터")
    memory_review_parser.add_argument("--limit", type=int, default=None, help="최대 표시 개수")
    memory_review_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )
    memory_pin_parser = memory_subparsers.add_parser(
        "pin",
        help="lesson을 pinned 상태로 고정",
        parents=[common_parser],
    )
    memory_pin_parser.add_argument("lesson_id", help="pin할 lesson id")
    memory_pin_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    memory_unpin_parser = memory_subparsers.add_parser(
        "unpin",
        help="lesson pin 해제",
        parents=[common_parser],
    )
    memory_unpin_parser.add_argument("lesson_id", help="unpin할 lesson id")
    memory_unpin_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    memory_suppress_parser = memory_subparsers.add_parser(
        "suppress",
        help="lesson을 routing에서 제외",
        parents=[common_parser],
    )
    memory_suppress_parser.add_argument("lesson_id", help="suppress할 lesson id")
    memory_suppress_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    memory_unsuppress_parser = memory_subparsers.add_parser(
        "unsuppress",
        help="lesson suppress 해제",
        parents=[common_parser],
    )
    memory_unsuppress_parser.add_argument("lesson_id", help="unsuppress할 lesson id")
    memory_unsuppress_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    memory_note_parser = memory_subparsers.add_parser(
        "note",
        help="lesson에 사용자 note를 붙이거나 지움",
        parents=[common_parser],
    )
    memory_note_parser.add_argument("lesson_id", help="note를 붙일 lesson id")
    memory_note_parser.add_argument("--note", type=str, default=None, help="저장할 note 문구")
    memory_note_parser.add_argument("--clear", action="store_true", help="기존 note 제거")
    memory_note_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON 출력")
    memory_hygiene_parser = memory_subparsers.add_parser(
        "hygiene",
        help="project memory의 stale/conflict/orphan 상태 점검",
        parents=[common_parser],
    )
    memory_hygiene_parser.add_argument("--save", action="store_true", help="hygiene report 저장")
    memory_hygiene_parser.add_argument("--out", type=str, default=None, help="출력 hygiene.yaml 경로")
    memory_hygiene_parser.add_argument(
        "--include-suppressed",
        action="store_true",
        dest="include_suppressed",
        help="suppressed lesson도 출력",
    )
    memory_hygiene_parser.add_argument(
        "--status",
        type=str,
        default=None,
        choices=["fresh", "watch", "stale", "conflicting", "orphaned", "suppressed"],
        help="특정 hygiene 상태만 표시",
    )
    memory_hygiene_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    do_parser = subparsers.add_parser(
        "do",
        help="프로젝트 기억을 불러와 다음 안전한 작업으로 안내",
        parents=[common_parser],
    )
    do_parser.add_argument("request", help="자연어 작업 요청")
    do_parser.add_argument(
        "--use-suggestion",
        type=int,
        default=None,
        dest="use_suggestion",
        help="추천 source 번호를 바로 선택",
    )
    do_parser.add_argument(
        "--source",
        action="append",
        default=[],
        dest="do_sources",
        help="명시적으로 선택할 source 파일 경로 (반복 가능)",
    )
    do_parser.add_argument(
        "--test",
        action="append",
        default=[],
        dest="do_tests",
        help="명시적으로 선택할 test 파일 경로 (반복 가능)",
    )
    do_parser.add_argument(
        "--execute",
        action="store_true",
        help="diagnose-only 실행까지 이어서 수행",
    )
    do_parser.add_argument(
        "--no-scan",
        action="store_true",
        dest="no_scan",
        help="자동 context scan 없이 다음 선택만 안내",
    )
    do_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )

    do_parser.add_argument(
        "--continue",
        action="store_true",
        dest="continue_session",
        help="최근 work session을 이어서 진행",
    )
    do_parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="이어갈 do session id 또는 artifact 경로",
    )
    do_parser.add_argument(
        "--old-choice",
        type=str,
        default=None,
        dest="old_choice",
        help="patch intent old_text 후보 ID",
    )
    do_parser.add_argument(
        "--old-text",
        type=str,
        default=None,
        dest="old_text",
        help="직접 지정할 old_text",
    )
    do_parser.add_argument(
        "--old-text-file",
        type=str,
        default=None,
        dest="old_text_file",
        help="old_text 파일 경로",
    )
    do_parser.add_argument(
        "--new-text",
        type=str,
        default=None,
        dest="new_text",
        help="직접 지정할 new_text",
    )
    do_parser.add_argument(
        "--new-text-file",
        type=str,
        default=None,
        dest="new_text_file",
        help="new_text 파일 경로",
    )
    do_parser.add_argument(
        "--propose",
        action="store_true",
        help="patch proposal 생성까지 이어서 수행",
    )
    do_parser.add_argument(
        "--validate",
        action="store_true",
        help="patch proposal isolated validation까지 수행",
    )
    do_parser.add_argument(
        "--apply",
        action="store_true",
        dest="apply_patch",
        help="validated proposal을 명시적으로 적용",
    )
    do_parser.add_argument(
        "--reason",
        type=str,
        default=None,
        help="apply 이유",
    )

    clarify_parser = subparsers.add_parser(
        "clarify",
        help="needs_context 요청에 필요한 선택을 채운다",
        parents=[common_parser],
    )
    clarify_parser.add_argument(
        "clarification_ref",
        help="request id, clarification id 또는 clarification artifact 경로",
    )
    clarify_parser.add_argument(
        "--source",
        action="append",
        default=[],
        dest="clarify_sources",
        help="선택할 source 파일 경로 (반복 가능)",
    )
    clarify_parser.add_argument(
        "--test",
        action="append",
        default=[],
        dest="clarify_tests",
        help="선택할 test 파일 경로 (반복 가능)",
    )
    clarify_parser.add_argument(
        "--use-suggestion",
        type=int,
        default=None,
        dest="use_suggestion",
        help="추천 source 번호를 바로 선택",
    )
    clarify_parser.add_argument(
        "--mode",
        choices=["diagnose", "review"],
        default=None,
        help="clarification 이후 모드",
    )
    clarify_parser.add_argument(
        "--execute",
        action="store_true",
        help="ready 상태면 diagnose-only brain run 실행",
    )
    clarify_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )

    context_parser = subparsers.add_parser(
        "context",
        help="프로젝트 문맥 후보 추천",
        parents=[common_parser],
    )
    context_subparsers = context_parser.add_subparsers(
        dest="context_command",
        help="context 하위 명령",
    )
    context_scan_parser = context_subparsers.add_parser(
        "scan",
        help="요청과 관련된 source/test 후보 스캔",
        parents=[common_parser],
    )
    context_scan_parser.add_argument("request", help="사용자 자연어 요청")
    context_scan_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="최대 추천 후보 수",
    )
    context_scan_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="context artifact 저장 경로",
    )
    context_scan_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )

    patch_parser = subparsers.add_parser(
        "patch",
        help="patch intent, proposal, apply 도구",
        parents=[common_parser],
    )
    patch_subparsers = patch_parser.add_subparsers(
        dest="patch_command",
        help="patch 하위 명령",
    )
    patch_intent_parser = patch_subparsers.add_parser(
        "intent",
        help="diagnosis 기반 patch intent form 생성",
        parents=[common_parser],
    )
    patch_intent_parser.add_argument(
        "diagnosis_report",
        help="diagnose report 경로",
    )
    patch_intent_parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="intent 대상 파일",
    )
    patch_intent_parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        dest="patch_intent_out_dir",
        help="patch intent artifact 저장 경로",
    )
    patch_intent_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )
    patch_intent_fill_parser = patch_subparsers.add_parser(
        "intent-fill",
        help="patch intent form에 old/new text 입력",
        parents=[common_parser],
    )
    patch_intent_fill_parser.add_argument(
        "intent_path",
        help="patch intent artifact 경로",
    )
    patch_intent_fill_parser.add_argument(
        "--old-choice",
        type=str,
        default=None,
        dest="old_choice",
        help="old_text 후보 ID",
    )
    patch_intent_fill_parser.add_argument(
        "--old-text",
        type=str,
        default=None,
        dest="old_text",
        help="직접 지정할 old_text",
    )
    patch_intent_fill_parser.add_argument(
        "--old-text-file",
        type=str,
        default=None,
        dest="old_text_file",
        help="old_text 파일 경로",
    )
    patch_intent_fill_parser.add_argument(
        "--new-text",
        type=str,
        default=None,
        dest="new_text",
        help="직접 지정할 new_text",
    )
    patch_intent_fill_parser.add_argument(
        "--new-text-file",
        type=str,
        default=None,
        dest="new_text_file",
        help="new_text 파일 경로",
    )
    patch_intent_fill_parser.add_argument(
        "--propose",
        action="store_true",
        help="입력을 저장한 뒤 patch proposal 생성",
    )
    patch_intent_fill_parser.add_argument(
        "--execute",
        action="store_true",
        help="proposal 생성 후 isolated validation 까지 수행",
    )
    patch_intent_fill_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )
    patch_propose_parser = patch_subparsers.add_parser(
        "propose",
        help="diagnosis 기반 patch proposal 생성",
        parents=[common_parser],
    )
    patch_propose_parser.add_argument(
        "--from-diagnosis",
        type=str,
        default=None,
        dest="from_diagnosis",
        help="diagnose report 경로",
    )
    patch_propose_parser.add_argument(
        "--from-context",
        type=str,
        default=None,
        dest="from_context",
        help="context artifact 경로",
    )
    patch_propose_parser.add_argument(
        "--from-intent",
        type=str,
        default=None,
        dest="from_intent",
        help="patch intent artifact 경로",
    )
    patch_propose_parser.add_argument(
        "--request",
        type=str,
        default=None,
        help="원래 사용자 요청 문자열",
    )
    patch_propose_parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="patch 대상 파일",
    )
    patch_propose_parser.add_argument(
        "--test",
        action="append",
        default=[],
        dest="related_tests",
        help="관련 테스트 파일 경로 (반복 가능)",
    )
    patch_propose_parser.add_argument(
        "--old-text",
        type=str,
        default=None,
        dest="old_text",
        help="교체할 기존 문자열",
    )
    patch_propose_parser.add_argument(
        "--new-text",
        type=str,
        default=None,
        dest="new_text",
        help="적용할 새 문자열",
    )
    patch_propose_parser.add_argument(
        "--patch-file",
        type=str,
        default=None,
        dest="patch_file",
        help="향후 확장용 patch 파일 입력",
    )
    patch_propose_parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        dest="patch_out_dir",
        help="proposal artifact 저장 경로",
    )
    patch_propose_parser.add_argument(
        "--workspace",
        type=str,
        default=".",
        help="작업 기준 프로젝트 루트",
    )
    patch_propose_parser.add_argument(
        "--execute",
        action="store_true",
        help="isolated workspace에서 validation 실행",
    )
    patch_propose_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )
    patch_apply_parser = patch_subparsers.add_parser(
        "apply",
        help="검증된 patch proposal을 실제 프로젝트에 적용",
        parents=[common_parser],
    )
    patch_apply_parser.add_argument(
        "proposal_path",
        help="patch proposal artifact 경로",
    )
    patch_apply_parser.add_argument(
        "--workspace",
        type=str,
        default=".",
        help="실제 적용 대상 프로젝트 루트",
    )
    patch_apply_parser.add_argument(
        "--adoptions-dir",
        type=str,
        default=None,
        dest="adoptions_dir",
        help="adoption record 저장 경로",
    )
    patch_apply_parser.add_argument(
        "--reason",
        type=str,
        default="",
        help="사람이 명시적으로 남기는 적용 이유",
    )
    patch_apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="실제 수정 없이 적용 계획만 미리 본다",
    )
    patch_apply_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )

    search_parser = subparsers.add_parser(
        "search",
        help="통합 스킬 검색",
        parents=[common_parser],
    )
    search_parser.add_argument("query", help="검색 쿼리 (자연어)")
    search_parser.add_argument(
        "--domain", "-d", default=None, help="도메인 필터",
    )
    search_parser.add_argument(
        "--tags", "-t", nargs="+", default=None, help="태그 필터",
    )
    search_parser.add_argument(
        "--no-external",
        action="store_true",
        help="외부 디렉토리 제외",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="최대 결과 수 (기본값: 10)",
    )
    search_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="JSON 출력",
    )

    scan_parser = subparsers.add_parser(
        "scan",
        help="프로젝트 분석 + 스킬 추천",
        parents=[common_parser],
    )
    scan_parser.add_argument("path", help="분석할 프로젝트 디렉토리")
    scan_parser.add_argument(
        "--depth", type=int, default=4, help="파일트리 스캔 깊이 (기본: 4)",
    )
    scan_parser.add_argument(
        "--max-queries", type=int, default=10, dest="max_queries",
        help="최대 search 횟수 (기본: 10)",
    )
    scan_parser.add_argument(
        "--top-k", type=int, default=3, dest="top_k",
        help="gap당 추천 스킬 수 (기본: 3)",
    )
    scan_parser.add_argument(
        "--no-search", action="store_true", dest="no_search",
        help="search 미실행 (gap 분석까지만)",
    )
    scan_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    brain_parser = subparsers.add_parser(
        "brain",
        help="고급 실행 하네스 명령",
        parents=[common_parser],
    )
    brain_sub = brain_parser.add_subparsers(dest="brain_command")

    brain_autopsy_p = brain_sub.add_parser(
        "autopsy",
        help="brain/adoption source를 분석해 feedback과 next generation seed를 생성",
    )
    brain_autopsy_p.add_argument(
        "source_path",
        help="brain report.json 또는 adoption record JSON 경로",
    )
    brain_autopsy_p.add_argument(
        "--note", default="", help="사용자 메모",
    )
    brain_autopsy_p.add_argument(
        "--rating", default=None, help="사용자 평점",
    )
    brain_autopsy_p.add_argument(
        "--keep", action="append", default=[],
        help="추가 keep 패턴",
    )
    brain_autopsy_p.add_argument(
        "--avoid", action="append", default=[],
        help="추가 avoid 패턴",
    )
    brain_autopsy_p.add_argument(
        "--out-dir", default=None, dest="feedback_out_dir",
        help="feedback record 저장 경로",
    )
    brain_autopsy_p.add_argument(
        "--next-out-dir", default=None, dest="next_generation_out_dir",
        help="next generation seed 저장 경로",
    )
    brain_autopsy_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    brain_refine_p = brain_sub.add_parser(
        "refine-hypothesis",
        help="seed/pressure/task를 읽어 refined hypothesis artifact 생성",
    )
    brain_refine_p.add_argument(
        "--seed", default=None, dest="generation_seed_path",
        help="next_generation_seed.yaml 경로",
    )
    brain_refine_p.add_argument(
        "--pressure", default=None, dest="selection_pressure_path",
        help="selection pressure 경로",
    )
    brain_refine_p.add_argument(
        "--task", default=None, dest="task_spec_path",
        help="TaskSpec YAML 경로",
    )
    brain_refine_p.add_argument(
        "--out", default=None, dest="refinement_out",
        help="refined hypothesis 출력 경로",
    )
    brain_refine_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    brain_run_p = brain_sub.add_parser(
        "run", help="TaskSpec YAML로 신규 run 시작",
    )
    brain_run_p.add_argument("task_spec", help="TaskSpec YAML 파일 경로")
    brain_run_p.add_argument(
        "--max-iterations", type=int, default=10, dest="max_iterations",
        help="최대 iteration 수 (기본: 10)",
    )
    brain_run_p.add_argument(
        "--runs-dir", default=None, dest="runs_dir",
        help="run 저장 경로 (기본: ./.cambrian/brain/runs)",
    )
    brain_run_p.add_argument(
        "--workspace", default=None,
        help="tester 파일 확인 기준 경로 (기본: 현재 디렉토리)",
    )
    brain_run_p.add_argument(
        "--seed", default=None, dest="generation_seed_path",
        help="next_generation_seed.yaml 경로",
    )
    brain_run_p.add_argument(
        "--pressure", default=None, dest="selection_pressure_path",
        help="selection_pressure.yaml 경로",
    )
    brain_run_p.add_argument(
        "--refinement", default=None, dest="hypothesis_refinement_path",
        help="refined_hypothesis.yaml 경로",
    )
    brain_run_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    brain_resume_p = brain_sub.add_parser(
        "resume", help="중단된 run 재개",
    )
    brain_resume_p.add_argument("run_id", help="재개할 run ID")
    brain_resume_p.add_argument(
        "--runs-dir", default=None, dest="runs_dir",
        help="run 저장 경로 (기본: ./.cambrian/brain/runs)",
    )
    brain_resume_p.add_argument(
        "--workspace", default=None,
        help="tester 파일 확인 기준 경로 (기본: 현재 디렉토리)",
    )
    brain_resume_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    brain_show_p = brain_sub.add_parser(
        "show", help="run 상태 출력",
    )
    brain_show_p.add_argument("run_id", help="조회할 run ID")
    brain_show_p.add_argument(
        "--runs-dir", default=None, dest="runs_dir",
        help="run 저장 경로 (기본: ./.cambrian/brain/runs)",
    )
    brain_show_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    brain_handoff_p = brain_sub.add_parser(
        "handoff",
        help="brain run 결과를 handoff artifact로 생성",
    )
    brain_handoff_p.add_argument("run_id", help="brain run ID")
    brain_handoff_p.add_argument(
        "--runs-dir", default=None, dest="runs_dir",
        help="run 저장 경로 (기본: ./.cambrian/brain/runs)",
    )
    brain_handoff_p.add_argument(
        "--handoffs-dir", default=None, dest="handoffs_dir",
        help="handoff 저장 경로 (기본: ./.cambrian/brain/handoffs)",
    )
    brain_handoff_p.add_argument(
        "--force", action="store_true",
        help="blocked 상태에서도 handoff artifact 생성 (MVP 동작은 동일)",
    )
    brain_handoff_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    evolution_parser = subparsers.add_parser(
        "evolution",
        help="고급 진화 아티팩트 조회 및 재구성",
        parents=[common_parser],
    )
    evolution_sub = evolution_parser.add_subparsers(dest="evolution_command")

    evolution_rebuild_p = evolution_sub.add_parser(
        "rebuild-ledger",
        help="source artifacts를 스캔해 evolution ledger를 재구성",
    )
    evolution_rebuild_p.add_argument(
        "--brain-runs-dir", default=None, dest="brain_runs_dir",
        help="brain runs 디렉토리 (기본: ./.cambrian/brain/runs)",
    )
    evolution_rebuild_p.add_argument(
        "--adoptions-dir", default=None, dest="adoptions_dir",
        help="adoptions 디렉토리 (기본: ./.cambrian/adoptions)",
    )
    evolution_rebuild_p.add_argument(
        "--feedback-dir", default=None, dest="feedback_dir",
        help="feedback 디렉토리 (기본: ./.cambrian/feedback)",
    )
    evolution_rebuild_p.add_argument(
        "--next-generation-dir", default=None, dest="next_generation_dir",
        help="next_generation 디렉토리 (기본: ./.cambrian/next_generation)",
    )
    evolution_rebuild_p.add_argument(
        "--out", default=None, dest="ledger_out",
        help="ledger 출력 경로 (기본: ./.cambrian/evolution/_ledger.json)",
    )
    evolution_rebuild_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    evolution_pressure_p = evolution_sub.add_parser(
        "build-pressure",
        help="ledger에서 selection pressure artifact 생성",
    )
    evolution_pressure_p.add_argument(
        "--ledger", required=True, dest="ledger_path",
        help="입력 ledger 경로",
    )
    evolution_pressure_p.add_argument(
        "--out", required=True, dest="pressure_out",
        help="selection pressure 출력 경로",
    )
    evolution_pressure_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    evolution_list_p = evolution_sub.add_parser(
        "list",
        help="ledger의 generation 목록 출력",
    )
    evolution_list_p.add_argument(
        "--ledger", default=None, dest="ledger_path",
        help="ledger 파일 경로 (기본: ./.cambrian/evolution/_ledger.json)",
    )
    evolution_list_p.add_argument(
        "--outcome", default=None,
        choices=["adopted", "success", "no_winner", "failed", "mixed", "inconclusive"],
        help="outcome 필터",
    )
    evolution_list_p.add_argument(
        "--limit", type=int, default=None,
        help="최대 출력 개수",
    )
    evolution_list_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    evolution_show_p = evolution_sub.add_parser(
        "show",
        help="특정 generation 상세 출력",
    )
    evolution_show_p.add_argument("generation_id", help="조회할 generation ID")
    evolution_show_p.add_argument(
        "--ledger", default=None, dest="ledger_path",
        help="ledger 파일 경로 (기본: ./.cambrian/evolution/_ledger.json)",
    )
    evolution_show_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    evolution_lineage_p = evolution_sub.add_parser(
        "lineage",
        help="generation lineage 출력",
    )
    evolution_lineage_p.add_argument("generation_id", help="기준 generation ID")
    evolution_lineage_p.add_argument(
        "--ledger", default=None, dest="ledger_path",
        help="ledger 파일 경로 (기본: ./.cambrian/evolution/_ledger.json)",
    )
    evolution_lineage_p.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-harness",
        help="프로젝트별 하네스 아티팩트 생성",
        parents=[common_parser],
    )
    bootstrap_parser.add_argument("path", help="분석할 프로젝트 디렉토리")
    bootstrap_parser.add_argument(
        "--depth", type=int, default=4, help="파일트리 스캔 깊이 (기본: 4)",
    )
    bootstrap_parser.add_argument(
        "--no-search", action="store_true", dest="no_search",
        help="search 미실행 (gap 분석까지만)",
    )
    bootstrap_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    fuse_parser = subparsers.add_parser(
        "fuse",
        help="스킬 2개 융합",
        parents=[common_parser],
    )
    fuse_parser.add_argument("skill_a", help="첫 번째 소스 스킬 ID")
    fuse_parser.add_argument("skill_b", help="두 번째 소스 스킬 ID")
    fuse_parser.add_argument(
        "--goal", "-g", required=True, help="융합 목적 설명",
    )
    fuse_parser.add_argument(
        "--output-id", "-o", default=None, dest="output_id",
        help="결과 스킬 ID (미지정 시 자동)",
    )
    fuse_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="생성만, 등록 안 함",
    )
    fuse_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    gen_parser = subparsers.add_parser(
        "generate",
        help="스킬 자동 생성",
        parents=[common_parser],
    )
    gen_parser.add_argument(
        "--goal", "-g", required=True, help="생성할 스킬 목적 설명",
    )
    gen_parser.add_argument(
        "--domain", "-d", required=True, help="스킬 도메인",
    )
    gen_parser.add_argument(
        "--tags", "-t", nargs="+", required=True, help="스킬 태그",
    )
    gen_parser.add_argument(
        "--output-id", "-o", default=None, dest="output_id",
        help="결과 스킬 ID (미지정 시 자동)",
    )
    gen_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="생성만, 등록 안 함",
    )
    gen_parser.add_argument(
        "--skip-search", action="store_true", dest="skip_search",
        help="유사 스킬 사전 검색 스킵",
    )
    gen_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )
    gen_parser.add_argument(
        "--ref", nargs="*", default=None, dest="reference_skills",
        help="few-shot 참고 스킬 ID",
    )

    acq_parser = subparsers.add_parser(
        "acquire",
        help="프로젝트 capability 자동 확보",
        parents=[common_parser],
    )
    acq_parser.add_argument(
        "--project", "-p", default=None, help="프로젝트 디렉토리",
    )
    acq_parser.add_argument(
        "--goal", "-g", default=None, help="원하는 capability 설명",
    )
    acq_parser.add_argument(
        "--domain", "-d", default=None, help="도메인 힌트",
    )
    acq_parser.add_argument(
        "--tags", "-t", nargs="+", default=None, help="태그 힌트",
    )
    acq_parser.add_argument(
        "--mode", choices=["advisory", "execute"], default="advisory",
        dest="acq_mode", help="모드 (기본: advisory)",
    )
    acq_parser.add_argument(
        "--strategy", choices=["conservative", "balanced", "aggressive"],
        default="conservative", help="전략 (기본: conservative)",
    )
    acq_parser.add_argument(
        "--no-fuse", action="store_true", dest="no_fuse",
        help="fuse 비허용",
    )
    acq_parser.add_argument(
        "--no-generate", action="store_true", dest="no_generate",
        help="generate 비허용",
    )
    acq_parser.add_argument(
        "--max-actions", type=int, default=3, dest="max_actions",
        help="최대 처리 gap 수 (기본: 3)",
    )
    acq_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="fuse/generate dry-run",
    )
    acq_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    # === eval-input: 진화 평가용 입력 관리 ===
    eval_input_parser = subparsers.add_parser(
        "eval-input",
        help="진화 평가용 입력(replay set) 관리",
        parents=[common_parser],
    )
    eval_input_sub = eval_input_parser.add_subparsers(
        dest="eval_input_action", help="서브 명령어",
    )

    eval_add_parser = eval_input_sub.add_parser("add", help="평가 입력 추가")
    eval_add_parser.add_argument("skill_id", help="대상 스킬 ID")
    eval_add_parser.add_argument(
        "--input", "-i", required=True, dest="eval_input_data",
        help="JSON 입력 문자열",
    )
    eval_add_parser.add_argument(
        "--desc", default="", help="입력 설명",
    )

    eval_list_parser = eval_input_sub.add_parser("list", help="평가 입력 목록")
    eval_list_parser.add_argument("skill_id", help="대상 스킬 ID")

    eval_remove_parser = eval_input_sub.add_parser("remove", help="평가 입력 삭제")
    eval_remove_parser.add_argument("eval_id", type=int, help="삭제할 입력 ID")

    # === trace: 실행/진화 trace 조회 ===
    trace_parser = subparsers.add_parser(
        "trace",
        help="경쟁 실행/진화 판정 trace 조회",
        parents=[common_parser],
    )
    trace_parser.add_argument(
        "--type", default=None,
        choices=["competitive_run", "evolution_decision", "auto_rollback"],
        help="trace 유형 필터",
    )
    trace_parser.add_argument(
        "--skill", default=None, help="승자 스킬 ID로 필터",
    )
    trace_parser.add_argument(
        "--limit", type=int, default=10, help="최대 결과 수 (기본: 10)",
    )
    trace_parser.add_argument(
        "--detail", type=int, default=None, metavar="TRACE_ID",
        help="특정 trace 상세 조회",
    )

    # === eval: 스킬 평가 실행/추이 보고 ===
    eval_parser = subparsers.add_parser(
        "eval",
        help="스킬 평가 실행 또는 추이 보고",
        parents=[common_parser],
    )
    eval_parser.add_argument("skill_id", help="평가할 스킬 ID")
    eval_parser.add_argument(
        "--report", action="store_true",
        help="최근 evaluation 추이 보고 (실행 없이 저장된 결과만)",
    )
    eval_parser.add_argument(
        "--detail", type=int, default=None, metavar="SNAPSHOT_ID",
        help="특정 스냅샷 상세 (입력별 pass/fail)",
    )
    eval_parser.add_argument(
        "--limit", type=int, default=5,
        help="report 시 최대 스냅샷 수 (기본: 5)",
    )
    eval_parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        dest="max_cases",
        help="평가 최대 케이스 수 (기본: 20)",
    )

    # === scenario: 시나리오 배치 실행 ===
    scenario_parser = subparsers.add_parser(
        "scenario",
        help="시나리오 배치 실행",
        parents=[common_parser],
    )
    scenario_sub = scenario_parser.add_subparsers(
        dest="scenario_command", help="서브 명령어",
    )
    run_sc_parser = scenario_sub.add_parser("run", help="시나리오 실행")
    run_sc_parser.add_argument("spec_file", help="scenario JSON spec 파일 경로")
    run_sc_parser.add_argument(
        "--output", "-o", default=None,
        help="report 저장 경로 (미지정 시 ./reports/<name>_<timestamp>.json)",
    )
    run_sc_parser.add_argument(
        "--notes", default="",
        help="실험 메모 (snapshot에 기록)",
    )

    matrix_parser = scenario_sub.add_parser("matrix", help="다중 policy 배치 실행")
    matrix_parser.add_argument("spec_file", help="scenario JSON spec 파일")
    matrix_parser.add_argument(
        "--policies", nargs="+", required=True,
        help="policy 파일 경로 목록 (첫 번째가 baseline)",
    )
    matrix_parser.add_argument(
        "--baseline", default=None,
        help="baseline policy 경로 (미지정 시 첫 번째 policy)",
    )
    matrix_parser.add_argument(
        "--out-dir", "-o", default=None, dest="out_dir",
        help="결과 저장 디렉토리",
    )
    matrix_parser.add_argument(
        "--notes", default="", help="실험 메모",
    )

    decide_parser = scenario_sub.add_parser(
        "decide", help="matrix 결과에서 champion/promotion 판정",
    )
    decide_parser.add_argument(
        "summary_file", help="_matrix_summary.json 경로",
    )
    decide_parser.add_argument(
        "--output", "-o", default=None, help="decision report 저장 경로",
    )
    decide_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    # === snapshot: 실험 스냅샷 비교 ===
    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help="실험 스냅샷 관리",
        parents=[common_parser],
    )
    snapshot_sub = snapshot_parser.add_subparsers(
        dest="snapshot_command", help="서브 명령어",
    )
    compare_parser = snapshot_sub.add_parser("compare", help="두 스냅샷 비교")
    compare_parser.add_argument("file_a", help="스냅샷 A JSON 파일")
    compare_parser.add_argument("file_b", help="스냅샷 B JSON 파일")
    compare_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    # === outcome: 실행 결과 사용 판정 ===
    outcome_parser = subparsers.add_parser(
        "outcome",
        help="실행 결과에 대한 사용 결과 기록",
        parents=[common_parser],
    )
    outcome_parser.add_argument("skill_id", help="대상 스킬 ID")
    outcome_parser.add_argument(
        "verdict",
        choices=["approved", "edited", "rejected", "redo"],
        help="사용 결과",
    )
    outcome_parser.add_argument(
        "--trace", type=int, default=None,
        help="연결할 run_trace ID (선택)",
    )
    outcome_parser.add_argument(
        "--note", default="",
        help="사람 메모 (선택)",
    )

    # === pilot: 파일럿 KPI 리포트 ===
    pilot_parser = subparsers.add_parser(
        "pilot",
        help="파일럿 KPI 리포트",
        parents=[common_parser],
    )
    pilot_parser.add_argument(
        "--skill", "-s", default=None,
        help="특정 스킬 필터",
    )
    pilot_parser.add_argument(
        "--days", "-d", type=int, default=None,
        help="최근 N일 기준 (미지정 시 전체)",
    )
    pilot_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    # === promote: 스킬 release 상태 승격 ===
    promote_parser = subparsers.add_parser(
        "promote",
        help="스킬을 production으로 승격",
        parents=[common_parser],
    )
    promote_parser.add_argument("skill_id", help="승격할 스킬 ID")
    promote_parser.add_argument(
        "--to", default="production",
        choices=["candidate", "production"],
        help="목표 상태 (기본: production)",
    )
    promote_parser.add_argument(
        "--reason", default="manual promotion",
        help="승격 사유",
    )
    promote_parser.add_argument(
        "--decision", default=None,
        help="decision.json 경로 (champion/gate 검증 적용)",
    )
    promote_parser.add_argument(
        "--out-dir", default="adoptions", dest="adopt_out_dir",
        help="adoption record 저장 디렉토리 (기본: adoptions/)",
    )

    # === unquarantine: 격리 해제 ===
    unq_parser = subparsers.add_parser(
        "unquarantine",
        help="격리된 스킬 해제 (experimental로 복귀)",
        parents=[common_parser],
    )
    unq_parser.add_argument("skill_id", help="해제할 스킬 ID")
    unq_parser.add_argument(
        "--reason", default="manual unquarantine", help="해제 사유",
    )

    # === governance: release governance 이력 조회 ===
    gov_parser = subparsers.add_parser(
        "governance",
        help="release governance 이력 조회",
        parents=[common_parser],
    )
    gov_parser.add_argument(
        "--skill", default=None, help="특정 스킬 필터",
    )
    gov_parser.add_argument(
        "--limit", type=int, default=20, help="최대 결과 수",
    )

    # === adoption: 채택 관리 ===
    adoption_parser = subparsers.add_parser(
        "adoption",
        help="채택 이력 관리",
        parents=[common_parser],
    )
    adoption_sub = adoption_parser.add_subparsers(
        dest="adoption_cmd", help="서브 명령어",
    )

    # adoption rollback
    rb_parser = adoption_sub.add_parser("rollback", help="이전 adoption으로 롤백")
    rb_parser.add_argument(
        "target_path", nargs="?", default=None,
        help="target adoption record 경로",
    )
    rb_parser.add_argument(
        "--previous", action="store_true",
        help="직전 adoption으로 롤백",
    )
    rb_parser.add_argument(
        "--to", default=None, dest="to_run_id",
        help="특정 run_id로 롤백",
    )
    rb_parser.add_argument(
        "--reason", default=None, help="롤백 사유",
    )
    rb_parser.add_argument(
        "--adoptions-dir", default="adoptions", dest="adoptions_dir",
        help="adoption record 디렉토리 (기본: adoptions/)",
    )

    # adoption latest
    adoption_sub.add_parser("latest", help="현재 latest adoption 확인")

    # adoption validate
    val_parser = adoption_sub.add_parser("validate", help="현재 adoption 재검증")
    val_parser.add_argument(
        "--adoption", default=None, dest="adoption_path",
        help="명시 adoption record 경로 (미지정 시 latest)",
    )
    val_parser.add_argument(
        "--spec", default=None, dest="spec_override",
        help="scenario spec override 경로",
    )
    val_parser.add_argument(
        "--out-dir", default="adoptions/validations", dest="val_out_dir",
        help="validation record 저장 디렉토리",
    )
    val_parser.add_argument(
        "--regression-threshold", type=float, default=0.15,
        dest="regression_threshold",
        help="regression 판정 임계값 (기본: 0.15)",
    )

    # adoption rebuild-index
    adoption_sub.add_parser("rebuild-index", help="file → derived index 재구성")

    # adoption list
    list_parser = adoption_sub.add_parser("list", help="채택 기록 목록")
    list_parser.add_argument(
        "--type", default=None,
        choices=["adoption", "rollback", "validation"],
        help="action_type 필터",
    )
    list_parser.add_argument("--skill", default=None, help="스킬 이름 필터")

    # adoption show
    show_parser = adoption_sub.add_parser("show", help="단일 record 조회")
    show_parser.add_argument("target", help="run_id 또는 파일 경로")

    # adoption review — handoff artifact를 candidate로 승격
    review_parser = adoption_sub.add_parser(
        "review",
        help="handoff artifact를 adoption candidate로 검토 승격",
    )
    review_parser.add_argument(
        "handoff_path", help="handoff JSON 파일 경로",
    )
    review_parser.add_argument(
        "--candidates-dir", default=None, dest="candidates_dir",
        help="candidate 저장 경로 (기본: ./.cambrian/adoption_candidates)",
    )
    review_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    accept_gen_parser = adoption_sub.add_parser(
        "accept-generation",
        help="competitive generation winner를 공식 adoption으로 채택",
    )
    accept_gen_parser.add_argument("run_id", help="brain run ID")
    accept_gen_parser.add_argument(
        "--runs-dir", default=None, dest="runs_dir",
        help="brain run 저장 경로 (기본: ./.cambrian/brain/runs)",
    )
    accept_gen_parser.add_argument(
        "--workspace", default=".",
        help="winner를 적용할 실제 project workspace 경로",
    )
    accept_gen_parser.add_argument(
        "--out-dir", default=None, dest="adoption_out_dir",
        help="adoption record 저장 경로 (기본: ./.cambrian/adoptions)",
    )
    accept_gen_parser.add_argument(
        "--reason", required=True,
        help="공식 채택 사유",
    )
    accept_gen_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="실제 적용 없이 검증/미리보기만 수행",
    )
    accept_gen_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="JSON 출력",
    )

    # === lineage: 채택 계보 트리 ===
    lineage_parser = subparsers.add_parser(
        "lineage",
        help="특정 스킬의 채택 계보 트리 출력",
        parents=[common_parser],
    )
    lineage_parser.add_argument("skill_name", help="조회할 스킬 이름")
    lineage_parser.add_argument(
        "--run-id", default=None, dest="run_id",
        help="특정 run_id 기준 (생략 시 가장 최근 채택)",
    )
    lineage_parser.add_argument(
        "--direction", choices=["ancestors", "descendants", "both"],
        default="both", help="조회 방향 (기본: both)",
    )

    # === audit: 감사 로그 ===
    audit_parser = subparsers.add_parser(
        "audit",
        help="채택 이력 감사 로그 조회",
        parents=[common_parser],
    )
    audit_sub = audit_parser.add_subparsers(dest="audit_cmd")
    adopt_audit = audit_sub.add_parser("adoptions", help="채택 이력 테이블 출력")
    adopt_audit.add_argument("--skill", default=None, help="스킬 이름 필터")
    adopt_audit.add_argument("--since", default=None, help="시작일 (ISO)")
    adopt_audit.add_argument("--until", default=None, help="종료일 (ISO)")
    adopt_audit.add_argument("--scenario", default=None, help="시나리오 ID 필터")
    adopt_audit.add_argument("--limit", type=int, default=50, help="최대 출력 건수")
    adopt_audit.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON 출력",
    )

    argv = sys.argv[1:]
    if argv and argv[0] == "do" and "--continue" in argv[1:]:
        options_with_values = {
            "--session",
            "--use-suggestion",
            "--source",
            "--test",
            "--old-choice",
            "--old-text",
            "--old-text-file",
            "--new-text",
            "--new-text-file",
            "--reason",
        }
        has_request = False
        skip_next = False
        for token in argv[1:]:
            if skip_next:
                skip_next = False
                continue
            if token in options_with_values:
                skip_next = True
                continue
            if not token.startswith("-"):
                has_request = True
                break
        if not has_request:
            argv = ["do", "__continue__", *argv[1:]]

    args = parser.parse_args(argv)
    if (
        getattr(args, "command", None) == "do"
        and getattr(args, "continue_session", False)
        and getattr(args, "request", None) == "__continue__"
    ):
        args.request = None

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "run":
            _handle_run(args)
        elif args.command == "skills":
            _handle_skills(args)
        elif args.command == "skill":
            if getattr(args, "skill_id", None) == "generate":
                _handle_skill_generate(args)
            else:
                _handle_skill(args)
        elif args.command == "absorb":
            _handle_absorb(args)
        elif args.command == "remove":
            _handle_remove(args)
        elif args.command == "stats":
            _handle_stats(args)
        elif args.command == "benchmark":
            _handle_benchmark(args)
        elif args.command == "feedback":
            _handle_feedback(args)
        elif args.command == "evolve":
            _handle_evolve(args)
        elif args.command == "authority":
            _handle_authority(args)
        elif args.command == "auto":
            _handle_auto(args)
        elif args.command == "project":
            _handle_project(args)
        elif args.command == "harness":
            _handle_harness(args)
        elif args.command == "workforce":
            _handle_workforce(args)
        elif args.command == "lane":
            _handle_lane(args)
        elif args.command == "agent":
            _handle_agent(args)
        elif args.command == "job":
            _handle_job(args)
        elif args.command == "dispatch":
            _handle_dispatch(args)
        elif args.command == "team":
            _handle_team(args)
        elif args.command == "history":
            _handle_history(args)
        elif args.command == "rollback":
            _handle_rollback(args)
        elif args.command == "export":
            _handle_export(args)
        elif args.command == "import":
            _handle_import(args)
        elif args.command == "critique":
            _handle_critique(args)
        elif args.command == "init":
            _handle_init(args)
        elif args.command == "demo":
            _handle_demo(args)
        elif args.command == "pack":
            _handle_pack(args)
        elif args.command == "registry":
            _handle_registry(args)
        elif args.command == "install":
            _handle_install(args)
        elif args.command == "uninstall":
            _handle_uninstall(args)
        elif args.command == "metrics":
            _handle_metrics(args)
        elif args.command == "status":
            _handle_status(args)
        elif args.command == "summary":
            _handle_summary(args)
        elif args.command == "template":
            _handle_template(args)
        elif args.command == "bridge":
            _handle_bridge(args)
        elif args.command == "notes":
            _handle_notes(args)
        elif args.command == "doctor":
            _handle_doctor(args)
        elif args.command == "alpha":
            _handle_alpha(args)
        elif args.command == "memory":
            _handle_memory(args)
        elif args.command == "do":
            _handle_do_v2(args)
        elif args.command == "clarify":
            _handle_clarify(args)
        elif args.command == "context":
            _handle_context(args)
        elif args.command == "patch":
            _handle_patch(args)
        elif args.command == "search":
            _handle_search(args)
        elif args.command == "scan":
            _handle_scan(args)
        elif args.command == "bootstrap-harness":
            _handle_bootstrap_harness(args)
        elif args.command == "brain":
            _handle_brain(args)
        elif args.command == "evolution":
            _handle_evolution(args)
        elif args.command == "fuse":
            _handle_fuse(args)
        elif args.command == "generate":
            _handle_generate(args)
        elif args.command == "acquire":
            _handle_acquire(args)
        elif args.command == "eval-input":
            _handle_eval_input(args)
        elif args.command == "trace":
            _handle_trace(args)
        elif args.command == "eval":
            _handle_eval(args)
        elif args.command == "scenario":
            _handle_scenario(args)
        elif args.command == "snapshot":
            _handle_snapshot(args)
        elif args.command == "outcome":
            _handle_outcome(args)
        elif args.command == "pilot":
            _handle_pilot(args)
        elif args.command == "promote":
            _handle_promote(args)
        elif args.command == "unquarantine":
            _handle_unquarantine(args)
        elif args.command == "governance":
            _handle_governance(args)
        elif args.command == "adoption":
            _handle_adoption(args)
        elif args.command == "lineage":
            _handle_lineage(args)
        elif args.command == "audit":
            _handle_audit(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _create_engine(args: argparse.Namespace) -> CambrianEngine:
    """args에서 공통 옵션을 추출해 CambrianEngine을 생성한다.

    Args:
        args: argparse가 파싱한 네임스페이스

    Returns:
        생성된 CambrianEngine
    """
    from engine.llm import create_provider

    provider = None
    provider_name = getattr(args, "provider", None)
    llm_model = getattr(args, "llm_model", None)
    if provider_name or llm_model:
        provider = create_provider(provider=provider_name, model=llm_model)

    # schemas: CLI 인자가 없거나 경로가 존재하지 않으면 번들 데이터로 fallback
    schemas_dir = Path(args.schemas)
    if not schemas_dir.exists():
        from engine._data_path import get_bundled_schemas_dir
        schemas_dir = get_bundled_schemas_dir()

    # skills: CLI 인자가 없거나 경로가 존재하지 않으면 번들 데이터로 fallback
    skills_dir = Path(args.skills)
    if not skills_dir.exists():
        from engine._data_path import get_bundled_skills_dir
        skills_dir = get_bundled_skills_dir()

    return CambrianEngine(
        schemas_dir=str(schemas_dir),
        skills_dir=str(skills_dir),
        skill_pool_dir=args.pool,
        db_path=args.db,
        external_skill_dirs=args.external if args.external else None,
        provider=provider,
        policy_path=getattr(args, "policy", None),
    )


def _handle_run(args: argparse.Namespace) -> None:
    """cambrian run 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    if getattr(args, "request", None):
        from engine.project_mode import ProjectRunPreparer, render_run_summary

        result = ProjectRunPreparer().prepare(
            project_root=Path.cwd(),
            user_request=args.request,
            skill_ids=list(getattr(args, "skills_override", []) or []),
            target=getattr(args, "target", None),
            source_paths=list(getattr(args, "source_paths_override", []) or []),
            tests=list(getattr(args, "related_tests_override", []) or []),
            output_paths=list(getattr(args, "output_paths_override", []) or []),
            action=getattr(args, "action", "none"),
            content=getattr(args, "content", None),
            content_file=getattr(args, "content_file", None),
            old_text=getattr(args, "old_text", None),
            new_text=getattr(args, "new_text", None),
            use_top_context=bool(getattr(args, "use_top_context", False)),
            context_path=getattr(args, "context_path", None),
            diagnose_only=bool(getattr(args, "diagnose_only", False)),
            no_scan=bool(getattr(args, "no_scan", False)),
            execute=bool(getattr(args, "execute", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            max_variants=getattr(args, "project_max_variants", None),
            max_iterations=getattr(args, "project_max_iterations", None),
            out_dir=getattr(args, "project_out_dir", None),
        )

        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return

        print(render_run_summary(result))
        return

    if not args.domain or not args.tags:
        print(
            "프로젝트 모드 요청 문자열 또는 기존 --domain/--tags 조합이 필요합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        if getattr(args, 'input_file', None):
            input_data = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
        elif getattr(args, 'input', None):
            input_data = json.loads(args.input)
        else:
            print("입력 데이터 필요: -i (JSON 문자열) 또는 -f (파일 경로)", file=sys.stderr)
            sys.exit(1)
    except (json.JSONDecodeError, OSError) as e:
        print(f"입력 데이터 오류: {e}", file=sys.stderr)
        sys.exit(1)

    engine = _create_engine(args)
    max_cand = getattr(args, "max_candidates", None)
    if max_cand is not None:
        engine.MAX_CANDIDATES_PER_RUN = max(1, max_cand)
    result = engine.run_task(
        domain=args.domain,
        tags=args.tags,
        input_data=input_data,
        max_retries=args.retries,
    )

    if result.success:
        print("[OK] Success")
        print(json.dumps(result.output, indent=2, ensure_ascii=False))
        print(f"  Time: {result.execution_time_ms}ms")
        print(f"  Skill: {result.skill_id}")
    else:
        print("[FAIL] Failed")
        print(f"  Error: {result.error}")
        print(f"  Exit code: {result.exit_code}")
        print(f"  Time: {result.execution_time_ms}ms")
        print(f"  Skill: {result.skill_id}")
        sys.exit(1)

    if getattr(args, "auto_evolve", False) and result.success:
        suggestion = engine.get_evolution_suggestion()
        if suggestion:
            print(f"\n[EVOLVE] fitness < 0.3 -- auto-evolving '{suggestion}'...")
            try:
                record = engine.evolve(suggestion, input_data)
                status = "adopted" if record.adopted else "discarded"
                print(f"[EVOLVE] Evolution {status}")
                print(f"  Parent fitness: {record.parent_fitness:.4f}")
                print(f"  Child fitness:  {record.child_fitness:.4f}")
            except RuntimeError as exc:
                print(f"[EVOLVE] Skipped: {exc}")


def _handle_skills(args: argparse.Namespace) -> None:
    """cambrian skills 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    skills = engine.list_skills()

    if not skills:
        print("No skills registered.")
        return

    print(
        f"{'ID':<20} {'DOMAIN':<12} {'STATUS':<10} "
        f"{'FITNESS':<8} {'EXECUTIONS'}"
    )
    print("-" * 61)
    for skill in skills:
        executions = (
            f"{skill['successful_executions']}/{skill['total_executions']}"
        )
        print(
            f"{skill['id']:<20} {skill['domain']:<12} {skill['status']:<10} "
            f"{skill['fitness_score']:<8.4f} {executions}"
        )


def _handle_skill(args: argparse.Namespace) -> None:
    """cambrian skill <id> 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)

    try:
        skill = engine.get_registry().get(args.skill_id)
    except SkillNotFoundError:
        print(f"Skill '{args.skill_id}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Skill: {skill['id']} (v{skill['version']})")
    print(f"Name: {skill['name']}")
    print(f"Description: {skill['description']}")
    print(f"Domain: {skill['domain']}")
    print(f"Tags: {', '.join(skill['tags'])}")
    print(f"Mode: {skill['mode']}")
    print(f"Language: {skill['language']}")
    print(f"Status: {skill['status']}")
    print(f"Fitness: {skill['fitness_score']:.4f}")
    print(
        f"Executions: {skill['successful_executions']}/"
        f"{skill['total_executions']}"
    )
    print(f"Path: {skill['skill_path']}")


def _handle_absorb(args: argparse.Namespace) -> None:
    """cambrian absorb <path> 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)

    try:
        skill = engine.absorb_skill(args.path)
        print(f"[OK] Absorbed skill '{skill.id}' into pool")
    except SecurityViolationError as exc:
        print("[FAIL] Security violation:", file=sys.stderr)
        for violation in exc.violations:
            print(f"  - {violation}", file=sys.stderr)
        sys.exit(1)
    except SkillValidationError as exc:
        print("[FAIL] Validation failed:", file=sys.stderr)
        for error in exc.errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)


def _handle_remove(args: argparse.Namespace) -> None:
    """cambrian remove <id> 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)

    try:
        engine.remove_skill(args.skill_id)
        print(f"[OK] Removed skill '{args.skill_id}'")
    except SkillNotFoundError:
        print(f"[FAIL] Skill '{args.skill_id}' not found.", file=sys.stderr)
        sys.exit(1)


def _handle_benchmark(args: argparse.Namespace) -> None:
    """cambrian benchmark 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    if getattr(args, "benchmark_command", None):
        _handle_project_benchmark(args)
        return
    if not args.domain or not args.tags or not args.input:
        print("기존 skill benchmark에는 --domain, --tags, --input 이 필요합니다.", file=sys.stderr)
        print("작업셋 비교는 예: cambrian benchmark case-add \"로그인 에러 수정\"", file=sys.stderr)
        sys.exit(1)
    try:
        input_data = json.loads(args.input)
    except json.JSONDecodeError:
        print("Invalid JSON input", file=sys.stderr)
        sys.exit(1)

    if not isinstance(input_data, dict):
        print("--input must be a JSON object.", file=sys.stderr)
        sys.exit(1)

    engine = _create_engine(args)
    report = engine.benchmark(
        domain=args.domain,
        tags=args.tags,
        input_data=input_data,
    )

    if report.total_candidates == 0:
        print("No matching skills found.")
        return

    print(f"Benchmark: domain={report.domain} tags={report.tags}")
    print("-" * 56)
    print(f"{'RANK':<5} {'SKILL_ID':<20} {'OK':<5} {'TIME(ms)':<10} FITNESS")
    for entry in report.entries:
        ok = "[OK]" if entry.success else "[FAIL]"
        print(
            f"{entry.rank:<5} "
            f"{entry.skill_id:<20} "
            f"{ok:<5} "
            f"{entry.execution_time_ms:<10} "
            f"{entry.fitness_score:.4f}"
        )
    print("-" * 56)
    print(f"Best: {report.best_skill_id} | {report.successful_count}/{report.total_candidates} succeeded")


def _handle_project_benchmark(args: argparse.Namespace) -> None:
    """반복 작업 benchmark workset 명령을 처리한다."""
    from engine.project_benchmarks import (
        BenchmarkReportBuilder,
        BenchmarkResultRecorder,
        BenchmarkStore,
        case_path,
        create_benchmark_case,
        create_benchmark_workset,
        render_attach_result,
        render_cases,
        render_report,
        render_worksets,
        report_path,
        workset_path,
    )
    from engine.project_benchmark_compare import (
        BenchmarkBaselineBuilder,
        BenchmarkBaselineStore,
        BenchmarkCompareBuilder,
        BenchmarkCompareStore,
        baseline_path,
        compare_path,
        default_baselines_dir,
        render_baseline_saved,
        render_baselines,
        render_compare_report,
        resolve_report_for_baseline,
    )
    from engine.project_benchmark_replay import (
        BenchmarkReplayRunner,
        BenchmarkReplayStore,
        default_replay_path,
        default_replays_dir,
        render_replay_report,
        render_replays,
        resolve_replay_path,
        save_replay_result,
    )
    from engine.project_benchmark_workset_replay import (
        AutonomyEvidenceBoardBuilder,
        AutonomyEvidenceBoardStore,
        WorksetReplayRunner,
        WorksetReplayStore,
        default_autonomy_board_path,
        default_workset_replay_path,
        default_workset_replays_dir,
        render_autonomy_board,
        render_workset_replay,
    )
    from engine.project_autonomy_bottlenecks import (
        AutonomyBottleneckAnalyzer,
        AutonomyBottleneckStore,
        default_bottleneck_report_path,
        render_bottleneck_report,
    )
    from engine.project_benchmark_proof import (
        BenchmarkProofBuilder,
        BenchmarkProofStore,
        default_proof_yaml_path,
        proof_markdown_path,
        render_proof_pack,
        resolve_proof_path,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "benchmark_command", None)
    store = BenchmarkStore()

    if command == "case-add":
        case = create_benchmark_case(
            request=args.request,
            name=getattr(args, "name", None),
            request_class=getattr(args, "request_class", "unknown"),
            description=getattr(args, "description", None),
            tags=list(getattr(args, "benchmark_tags", []) or []),
            expected_focus=list(getattr(args, "expected_focus", []) or []),
        )
        saved = store.save_case(case, case_path(root, case))
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "saved", "case": case.to_dict(), "saved_path": str(saved.resolve())}, indent=2, ensure_ascii=False))
            return
        print("Benchmark case saved.")
        print("")
        print("Case:")
        print(f"  {case.name}")
        print("")
        print("Saved:")
        print(f"  {_relative_cli(saved, root)}")
        return

    if command == "cases":
        cases = store.list_cases(root)
        request_class = getattr(args, "request_class", None)
        if request_class:
            cases = [case for case in cases if case.request_class == request_class]
        if getattr(args, "json_output", False):
            print(json.dumps({"cases": [case.to_dict() for case in cases]}, indent=2, ensure_ascii=False))
            return
        print(render_cases(cases))
        return

    if command == "workset-save":
        workset = create_benchmark_workset(
            project_root=root,
            name=args.name,
            case_refs=list(getattr(args, "case_refs", []) or []),
            description=getattr(args, "description", None),
            tags=list(getattr(args, "benchmark_tags", []) or []),
        )
        saved = store.save_workset(workset, workset_path(root, workset))
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "saved", "workset": workset.to_dict(), "saved_path": str(saved.resolve())}, indent=2, ensure_ascii=False))
            return
        print("Benchmark workset saved.")
        print("")
        print("Workset:")
        print(f"  {workset.name}")
        print("")
        print("Cases:")
        for case_id in workset.case_ids:
            print(f"  - {case_id}")
        if workset.warnings:
            print("")
            print("Warnings:")
            for warning in workset.warnings:
                print(f"  - {warning}")
        print("")
        print("Saved:")
        print(f"  {_relative_cli(saved, root)}")
        return

    if command == "worksets":
        worksets = store.list_worksets(root)
        if getattr(args, "json_output", False):
            print(json.dumps({"worksets": [workset.to_dict() for workset in worksets]}, indent=2, ensure_ascii=False))
            return
        print(render_worksets(worksets))
        return

    if command == "attach":
        result, saved = BenchmarkResultRecorder().record(
            root,
            case_ref=args.case_ref,
            mode=args.mode,
            session_ref=getattr(args, "session", None),
            reply_ref=getattr(args, "reply", None),
            manual_result_ref=getattr(args, "manual_result", None),
            summary=getattr(args, "summary", None),
            verdict=getattr(args, "verdict", None),
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "recorded", "result": result.to_dict(), "saved_path": str(saved.resolve())}, indent=2, ensure_ascii=False))
            return
        print(render_attach_result(result, saved, root))
        return

    if command == "report":
        report = BenchmarkReportBuilder().build(root, args.workset_name)
        saved = None
        if getattr(args, "save", False):
            saved = store.save_report(report, report_path(root, report))
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["saved_path"] = str(saved.resolve()) if saved else None
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_report(report))
        if saved is not None:
            print("")
            print("Saved:")
            print(f"  {_relative_cli(saved, root)}")
        return

    if command == "baseline-save":
        source_report = resolve_report_for_baseline(root, args.workset_name, getattr(args, "report", None))
        snapshot = BenchmarkBaselineBuilder().from_report(source_report)
        saved = BenchmarkBaselineStore().save(snapshot, baseline_path(root, snapshot))
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "saved", "baseline": snapshot.to_dict(), "saved_path": str(saved.resolve())}, indent=2, ensure_ascii=False))
            return
        print(render_baseline_saved(snapshot, saved, root))
        return

    if command == "baselines":
        baselines = BenchmarkBaselineStore().list(default_baselines_dir(root))
        workset_name = getattr(args, "workset", None)
        if workset_name:
            baselines = [baseline for baseline in baselines if baseline.workset_name == workset_name]
        if getattr(args, "json_output", False):
            print(json.dumps({"baselines": [baseline.to_dict() for baseline in baselines]}, indent=2, ensure_ascii=False))
            return
        print(render_baselines(baselines))
        return

    if command == "compare":
        baseline_ref = getattr(args, "against", None)
        report = BenchmarkCompareBuilder().build(
            root,
            args.workset_name,
            baseline_path=Path(baseline_ref) if baseline_ref else None,
        )
        saved = None
        if getattr(args, "save", False):
            saved = BenchmarkCompareStore().save(report, compare_path(root, report))
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["saved_path"] = str(saved.resolve()) if saved else None
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_compare_report(report))
        if saved is not None:
            print("")
            print("Saved:")
            print(f"  {_relative_cli(saved, root)}")
        return

    if command == "replay":
        report = BenchmarkReplayRunner().run(root, args.case_ref, args.mode)
        saved = None
        result_saved = None
        if getattr(args, "save", True):
            saved = BenchmarkReplayStore().save(report, default_replay_path(root, report))
        if getattr(args, "record_result", True):
            replay_ref = _relative_cli(saved, root) if saved is not None else None
            result_saved = save_replay_result(root, report, replay_ref)
        try:
            from engine.project_pack_usage import safe_record_pack_usage_event

            safe_record_pack_usage_event(
                root,
                event_kind="benchmark_used",
                surface_kind="benchmark_replay",
                request=report.request,
                request_class=report.request_class,
                linked_session_id=report.linked_session_id,
                linked_session_ref=report.linked_session_ref,
                linked_bridge_reply_ref=report.linked_bridge_reply_ref,
                linked_benchmark_replay_ref=_relative_cli(saved, root) if saved is not None else None,
                linked_benchmark_result_ref=_relative_cli(result_saved, root) if result_saved is not None else None,
                summary="active pack used in benchmark replay",
            )
        except Exception as exc:
            logger.warning("pack usage benchmark replay event failed: %s", exc)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["saved_path"] = str(saved.resolve()) if saved else None
            payload["result_path"] = str(result_saved.resolve()) if result_saved else None
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(
            render_replay_report(
                report,
                saved_path=_relative_cli(saved, root) if saved is not None else None,
                result_path=_relative_cli(result_saved, root) if result_saved is not None else None,
            )
        )
        return

    if command == "replay-show":
        replay_path = resolve_replay_path(root, args.replay_ref)
        report = BenchmarkReplayStore().load(replay_path)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_replay_report(report, saved_path=_relative_cli(replay_path, root)))
        return

    if command == "replays":
        reports = BenchmarkReplayStore().list(default_replays_dir(root))
        if getattr(args, "json_output", False):
            print(json.dumps({"replays": [report.to_dict() for report in reports]}, indent=2, ensure_ascii=False))
            return
        print(render_replays(reports))
        return

    if command == "replay-workset":
        report = WorksetReplayRunner().run(
            root,
            args.workset_name,
            args.mode,
            record_results=getattr(args, "record_results", True),
        )
        saved = None
        if getattr(args, "save", True):
            saved = WorksetReplayStore().save(report, default_workset_replay_path(root, report))
        try:
            from engine.project_pack_usage import safe_record_pack_usage_event

            safe_record_pack_usage_event(
                root,
                event_kind="benchmark_used",
                surface_kind="benchmark_replay",
                request=report.workset_name,
                request_class="benchmark_workset",
                linked_benchmark_replay_ref=_relative_cli(saved, root) if saved is not None else None,
                summary="active pack used in benchmark workset replay",
            )
        except Exception as exc:
            logger.warning("pack usage benchmark workset replay event failed: %s", exc)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            if saved is not None:
                payload["saved_path"] = str(saved.resolve())
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_workset_replay(report, saved_path=_relative_cli(saved, root) if saved is not None else None))
        return

    if command == "autonomy-board":
        board = AutonomyEvidenceBoardBuilder().build(root, args.workset_name)
        saved = None
        if getattr(args, "save", False):
            saved = AutonomyEvidenceBoardStore().save(board, default_autonomy_board_path(root, board))
        if getattr(args, "json_output", False):
            payload = board.to_dict()
            if saved is not None:
                payload["saved_path"] = str(saved.resolve())
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_autonomy_board(board, saved_path=_relative_cli(saved, root) if saved is not None else None))
        return

    if command == "workset-replays":
        reports = WorksetReplayStore().list(default_workset_replays_dir(root))
        workset_name = getattr(args, "workset", None)
        if workset_name:
            reports = [report for report in reports if report.workset_name == workset_name]
        if getattr(args, "json_output", False):
            print(json.dumps({"workset_replays": [report.to_dict() for report in reports]}, indent=2, ensure_ascii=False))
            return
        if not reports:
            print("Benchmark Workset Replays")
            print("==================================================")
            print("")
            print("Recent:")
            print("  none")
            return
        lines = [
            "Benchmark Workset Replays",
            "==================================================",
            "",
            "Recent:",
        ]
        for index, report in enumerate(reports[:20], start=1):
            validated = report.summary.get("validated_proposal_rate")
            validated_text = "n/a" if validated is None else f"{float(validated) * 100:.0f}%"
            lines.append(f"  {index}. {report.workset_name} [{report.mode}] validated {validated_text}")
        print("\n".join(lines))
        return

    if command == "proof":
        report = BenchmarkProofBuilder().build(root, args.workset_name)
        saved_yaml = None
        saved_md = None
        if getattr(args, "save", False):
            save_format = getattr(args, "format", "both")
            yaml_path = default_proof_yaml_path(root, report)
            if save_format in {"yaml", "both"}:
                saved_yaml = BenchmarkProofStore().save_yaml(report, yaml_path)
            if save_format in {"md", "both"}:
                if saved_yaml is None:
                    saved_yaml = yaml_path
                saved_md = BenchmarkProofStore().save_markdown(report, proof_markdown_path(saved_yaml))
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["saved_yaml_path"] = str(saved_yaml.resolve()) if saved_yaml else None
            payload["saved_markdown_path"] = str(saved_md.resolve()) if saved_md else None
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_proof_pack(report))
        if saved_yaml is not None or saved_md is not None:
            print("")
            print("Saved:")
            if saved_yaml is not None:
                print(f"  yaml: {_relative_cli(saved_yaml, root)}")
            if saved_md is not None:
                print(f"  md  : {_relative_cli(saved_md, root)}")
        return

    if command == "proof-show":
        try:
            proof_path = resolve_proof_path(root, str(getattr(args, "proof_ref")))
            report = BenchmarkProofStore().load_yaml(proof_path)
        except FileNotFoundError as exc:
            print(f"Benchmark proof not found: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["saved_path"] = _relative_cli(proof_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_proof_pack(report))
        return

    if command == "bottlenecks":
        report = AutonomyBottleneckAnalyzer().build(root, args.workset_name, mode=args.mode)
        saved = None
        if getattr(args, "save", False):
            saved = AutonomyBottleneckStore().save(report, default_bottleneck_report_path(root, report))
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            if saved is not None:
                payload["saved_path"] = str(saved.resolve())
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bottleneck_report(report, saved_path=_relative_cli(saved, root) if saved is not None else None))
        return

    print("benchmark 하위 명령이 올바르지 않습니다.", file=sys.stderr)
    sys.exit(1)


def _relative_cli(path: Path, root: Path) -> str:
    """CLI 출력용 상대 경로."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _handle_feedback(args: argparse.Namespace) -> None:
    """cambrian feedback 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    feedback_id = engine.feedback(args.skill_id, args.rating, args.comment)
    print(
        f"[OK] Feedback #{feedback_id} saved for '{args.skill_id}'"
        f" (rating: {args.rating}/5)"
    )


def _handle_evolve(args: argparse.Namespace) -> None:
    mode = getattr(args, "skill_id", None)
    if mode in {"review", "propose", "preview", "apply", "rollback"}:
        from engine.project_evolution import (
            apply_evolution,
            preview_evolution,
            propose_evolution,
            review_evidence,
            rollback_evolution,
        )

        root = Path.cwd().resolve()
        if mode == "review":
            result = review_evidence(root, recent=int(getattr(args, "recent", 5) or 5))
        elif mode == "propose":
            result = propose_evolution(root)
        elif mode == "preview":
            result = preview_evolution(root, str(getattr(args, "proposal_id", "") or ""))
        elif mode == "apply":
            result = apply_evolution(root, str(getattr(args, "proposal_id", "") or ""), confirm=bool(getattr(args, "confirm", False)))
        else:
            result = rollback_evolution(root, str(getattr(args, "proposal_id", "") or ""), confirm=bool(getattr(args, "confirm", False)))
        payload = result.to_dict()
        _emit_cli_payload(payload, bool(getattr(args, "json_output", False)))
        _exit_if_blocked(payload)
        return

    if not getattr(args, "input", None):
        print("--input is required for legacy skill evolution", file=sys.stderr)
        sys.exit(1)
    try:
        input_data = json.loads(args.input)
    except json.JSONDecodeError:
        print("Invalid JSON input", file=sys.stderr)
        sys.exit(1)

    if not isinstance(input_data, dict):
        print("--input must be a JSON object.", file=sys.stderr)
        sys.exit(1)

    engine = _create_engine(args)
    record = engine.evolve(args.skill_id, input_data)

    status = "adopted" if record.adopted else "discarded"
    print(f"[OK] Evolution complete ? variant {status}")
    print(f"  Skill: {record.skill_id}")
    print(f"  Parent fitness: {record.parent_fitness:.4f}")
    print(f"  Child fitness:  {record.child_fitness:.4f}")
    print(f"  Record ID: {record.id}")


def _handle_authority(args: argparse.Namespace) -> None:
    """cambrian authority 명령을 처리한다."""
    from engine.project_authority import (
        authority_status,
        grant_authority,
        init_authority,
        render_authority_result,
        revoke_authority,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "authority_command", None)
    try:
        if command == "status":
            payload = authority_status(root)
        elif command == "init":
            payload = init_authority(root)
        elif command == "grant":
            payload = grant_authority(root, str(getattr(args, "mode", "")))
        elif command == "revoke":
            payload = revoke_authority(root)
        else:
            print("authority 하위 명령이 필요합니다. 예: cambrian authority status --json", file=sys.stderr)
            sys.exit(1)
    except ValueError as exc:
        payload = {"ok": False, "errors": [str(exc)]}

    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if not payload.get("ok"):
            sys.exit(1)
        return
    print(render_authority_result(payload))
    if not payload.get("ok"):
        sys.exit(1)


def _handle_auto(args: argparse.Namespace) -> None:
    """cambrian auto 명령을 처리한다."""
    from engine.project_auto_mode import (
        answer_auto_input,
        auto_report,
        auto_status,
        create_auto_plan,
        defer_auto_input,
        init_auto_mode,
        ingest_auto_step_result,
        list_auto_inputs,
        pause_auto,
        render_auto_result,
        resume_auto,
        run_auto_cycle,
        run_auto_plan,
        run_boardroom,
        run_release_gate,
        start_next_auto_iteration,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "auto_command", None)
    if command == "init":
        payload = init_auto_mode(root, str(getattr(args, "goal", "")))
    elif command == "next":
        payload = start_next_auto_iteration(root, str(getattr(args, "goal", "")))
    elif command == "boardroom":
        payload = run_boardroom(root)
    elif command == "plan":
        payload = create_auto_plan(root)
    elif command == "run":
        payload = run_auto_plan(root, max_steps=int(getattr(args, "max_steps", 5) or 5))
    elif command == "cycle":
        payload = run_auto_cycle(root, max_steps=int(getattr(args, "max_steps", 1) or 1))
    elif command == "step":
        step_command = getattr(args, "auto_step_command", None)
        if step_command == "ingest":
            payload = ingest_auto_step_result(
                root,
                str(getattr(args, "task_ref", "")),
                Path(str(getattr(args, "result_path", ""))),
            )
        else:
            print("auto step 하위 명령이 필요합니다. 예: cambrian auto step ingest <task> --result result.yaml --json", file=sys.stderr)
            sys.exit(1)
    elif command == "input":
        input_command = getattr(args, "auto_input_command", None)
        if input_command == "list":
            payload = list_auto_inputs(root)
        elif input_command == "answer":
            payload = answer_auto_input(
                root,
                str(getattr(args, "field", "")),
                str(getattr(args, "value", "")),
            )
        elif input_command == "defer":
            payload = defer_auto_input(
                root,
                str(getattr(args, "field", "")),
                str(getattr(args, "reason", "")),
            )
        else:
            print("auto input 하위 명령이 필요합니다. 예: cambrian auto input list --json", file=sys.stderr)
            sys.exit(1)
    elif command == "status":
        payload = auto_status(root)
    elif command == "pause":
        payload = pause_auto(root)
    elif command == "resume":
        payload = resume_auto(root)
    elif command == "report":
        payload = auto_report(root)
    elif command == "release-gate":
        payload = run_release_gate(root)
    else:
        print("auto 하위 명령이 필요합니다. 예: cambrian auto init --goal \"제품 목표\" --json", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if not payload.get("ok"):
            sys.exit(1)
        return
    print(render_auto_result(payload))
    if not payload.get("ok"):
        sys.exit(1)


def _handle_history(args: argparse.Namespace) -> None:
    """cambrian history 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    registry = engine.get_registry()

    if getattr(args, "detail", None) is not None:
        _handle_history_detail(registry, args.skill_id, args.detail)
        return

    history = registry.get_evolution_history(args.skill_id, limit=args.limit)

    if not history:
        print(f"No evolution history for '{args.skill_id}'.")
        return

    print(f"Evolution history for '{args.skill_id}':")
    print(f"{'ID':<5} {'ADOPT':<6} {'SCORE':<18} {'REASONING':<35} {'DATE'}")
    print("-" * 85)
    for item in history:
        adopted_str = "YES" if item["adopted"] else "NO"
        score_str = f"{item['parent_fitness']:.1f} -> {item['child_fitness']:.1f}"
        reasoning = item.get("judge_reasoning", "") or ""
        short_reason = (reasoning[:32] + "...") if len(reasoning) > 35 else reasoning
        date_str = item["created_at"][:10]
        print(
            f"{item['id']:<5} {adopted_str:<6} {score_str:<18} "
            f"{short_reason:<35} {date_str}"
        )


def _handle_history_detail(
    registry: "SkillRegistry",
    skill_id: str,
    record_id: int,
) -> None:
    """진화 기록 상세를 출력한다.

    Args:
        registry: SkillRegistry 인스턴스
        skill_id: 스킬 ID
        record_id: 진화 기록 ID
    """
    import difflib

    history = registry.get_evolution_history(skill_id, limit=100)
    record = next((h for h in history if h["id"] == record_id), None)

    if record is None:
        print(
            f"Record #{record_id} not found for '{skill_id}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    adopted_str = "YES" if record["adopted"] else "NO"
    print(f"=== Evolution Record #{record_id} ===")
    print(f"Skill:          {record['skill_id']}")
    print(f"Adopted:        {adopted_str}")
    print(f"Parent fitness: {record['parent_fitness']:.4f}")
    print(f"Child fitness:  {record['child_fitness']:.4f}")
    print(f"Created at:     {record['created_at']}")

    # diff
    print("\n--- SKILL.md diff (parent → child) ---")
    parent_lines = record["parent_skill_md"].splitlines(keepends=True)
    child_lines = record["child_skill_md"].splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        parent_lines,
        child_lines,
        fromfile="parent/SKILL.md",
        tofile="child/SKILL.md",
        lineterm="",
    ))
    if diff:
        print("".join(diff))
    else:
        print("(no changes)")

    # judge reasoning
    reasoning = record.get("judge_reasoning", "") or ""
    print("\n--- Judge Reasoning ---")
    if reasoning:
        for segment in reasoning.split(" | "):
            print(f"  {segment}")
    else:
        print("  (none)")

    # feedback
    try:
        import json as _json
        feedback_ids = _json.loads(record.get("feedback_ids", "[]"))
        if feedback_ids:
            feedbacks = registry.get_feedback_by_ids(feedback_ids)
            print(f"\n--- Feedback used ({len(feedbacks)} items) ---")
            for fb in feedbacks:
                print(f"  [{fb['id']}] rating={fb['rating']}/5 | {fb['comment']}")
        else:
            print("\n--- Feedback used (0 items) ---")
    except Exception:
        pass


def _handle_rollback(args: argparse.Namespace) -> None:
    """cambrian rollback 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    registry = engine.get_registry()

    history = registry.get_evolution_history(args.skill_id, limit=100)
    record = next((item for item in history if item["id"] == args.record_id), None)

    if record is None:
        print(
            f"[FAIL] Evolution record #{args.record_id} not found for '{args.skill_id}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not record["adopted"]:
        print(
            f"[FAIL] Record #{args.record_id} was not adopted; rollback not applicable.",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_data = registry.get(args.skill_id)
    skill_path = Path(skill_data["skill_path"])
    skill_md_path = skill_path / "SKILL.md"
    skill_md_path.write_text(record["parent_skill_md"], encoding="utf-8")

    print(f"[OK] Rolled back '{args.skill_id}' to record #{args.record_id} parent state")


def _handle_stats(args: argparse.Namespace) -> None:
    """cambrian stats 처리. --skill이 있으면 스킬별 상세, 없으면 글로벌.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)

    if getattr(args, "skill", None):
        _handle_skill_stats(engine, args.skill)
    else:
        _handle_global_stats(engine)


def _handle_global_stats(engine: "CambrianEngine") -> None:
    """글로벌 엔진 통계를 출력한다.

    Args:
        engine: CambrianEngine 인스턴스
    """
    skills = engine.list_skills()

    counts: dict[str, int] = {"active": 0, "newborn": 0, "dormant": 0, "fossil": 0}
    for skill in skills:
        status = skill["status"]
        if status in counts:
            counts[status] += 1

    print("Cambrian Engine Stats")
    print("═" * 50)
    print(
        f"\nSkills: {len(skills)} total "
        f"({counts['active']} active, {counts['newborn']} newborn, "
        f"{counts['dormant']} dormant, {counts['fossil']} fossil)"
    )

    # Top Performers (fitness 상위 5개, fossil 제외)
    non_fossil = [s for s in skills if s["status"] != "fossil"]
    top = sorted(non_fossil, key=lambda s: s["fitness_score"], reverse=True)[:5]
    if top:
        print("\nTop Performers (by fitness):")
        print(
            f"  {'SKILL_ID':<22} {'FITNESS':<9} {'SUCCESS_RATE':<14} "
            f"{'EXECUTIONS':<12} STATUS"
        )
        for s in top:
            total = s["total_executions"]
            rate = (
                f"{s['successful_executions'] / total * 100:.0f}%"
                if total > 0 else "N/A"
            )
            print(
                f"  {s['id']:<22} {s['fitness_score']:<9.4f} {rate:<14} "
                f"{total:<12} {s['status']}"
            )

    # Recent Activity
    print("\nRecent Activity:")
    registry = engine.get_registry()

    try:
        comp_traces = registry.get_run_traces(trace_type="competitive_run", limit=1000)
        print(f"  Competitive runs:    {len(comp_traces)}")
    except Exception:
        print("  Competitive runs:    (not tracked)")

    try:
        cursor = registry._conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN adopted=1 THEN 1 ELSE 0 END) as adopted "
            "FROM evolution_history"
        )
        evo_row = cursor.fetchone()
        evo_total = evo_row["total"] if evo_row else 0
        evo_adopted = evo_row["adopted"] if evo_row else 0
        evo_discarded = evo_total - evo_adopted
        print(
            f"  Evolution attempts:  {evo_total} "
            f"({evo_adopted} adopted, {evo_discarded} discarded)"
        )
    except Exception:
        print("  Evolution attempts:  (not tracked)")

    try:
        rb_traces = registry.get_run_traces(trace_type="auto_rollback", limit=1000)
        print(f"  Auto-rollbacks:      {len(rb_traces)}")
    except Exception:
        print("  Auto-rollbacks:      (not tracked)")

    try:
        cursor = registry._conn.execute(
            "SELECT COUNT(*) as cnt, AVG(rating) as avg_r FROM feedback"
        )
        fb_row = cursor.fetchone()
        fb_count = fb_row["cnt"] if fb_row else 0
        fb_avg = fb_row["avg_r"] if fb_row and fb_row["avg_r"] else 0.0
        if fb_count > 0:
            print(f"  Avg feedback:        {fb_avg:.1f}/5 ({fb_count} ratings)")
        else:
            print("  Avg feedback:        (no feedback)")
    except Exception:
        print("  Avg feedback:        (not tracked)")

    # Release States 요약
    release_counts: dict[str, int] = {
        "production": 0, "candidate": 0, "experimental": 0, "quarantined": 0,
    }
    for skill in skills:
        rs = skill.get("release_state", "experimental")
        if rs in release_counts:
            release_counts[rs] += 1
    print(
        f"\nRelease States:"
        f"\n  Production: {release_counts['production']} | "
        f"Candidate: {release_counts['candidate']} | "
        f"Experimental: {release_counts['experimental']} | "
        f"Quarantined: {release_counts['quarantined']}"
    )

    # Policy 표시
    policy = engine.get_policy()
    print(f"\nPolicy:")
    print(f"  Source: {policy.policy_source}")
    print(
        f"  Budget: candidates={policy.max_candidates_per_run}, "
        f"mode_a={policy.max_mode_a_per_run}, "
        f"eval_cases={policy.max_eval_cases}"
    )
    print(
        f"  Governance: promote≥{policy.promote_min_executions}exec/"
        f"{policy.promote_min_fitness:.2f}fit, "
        f"demote<{policy.demote_fitness_threshold:.2f}, "
        f"rollback<{policy.rollback_fitness_threshold:.2f}"
    )
    print(
        f"  Evolution: margin={policy.adoption_margin:.2f}, "
        f"trials={policy.trial_count}"
    )

    # Pilot 요약
    try:
        pilot = registry.get_pilot_kpi()
        if pilot["total"] > 0:
            print(
                f"\nPilot: {pilot['total']} outcomes, "
                f"{pilot['net_useful_rate'] * 100:.1f}% net useful "
                f"({pilot['approved']} approved, {pilot['edited']} edited, "
                f"{pilot['rejected']} rejected, {pilot['redo']} redo)"
            )
        else:
            print("\nPilot: no outcomes recorded")
    except Exception:
        print("\nPilot: no outcomes recorded")


def _handle_skill_stats(engine: "CambrianEngine", skill_id: str) -> None:
    """스킬별 상세 통계를 출력한다.

    Args:
        engine: CambrianEngine 인스턴스
        skill_id: 대상 스킬 ID
    """
    try:
        stats = engine.get_skill_stats(skill_id)
    except Exception:
        print(f"Skill '{skill_id}' not found.", file=sys.stderr)
        sys.exit(1)

    s = stats["skill"]
    t = stats["trace"]
    e = stats["evolution"]

    print(f"Skill Stats: {skill_id}")
    print("═" * 50)

    # Identity
    print("\nIdentity:")
    print(f"  Name:        {s['name']}")
    print(f"  Domain:      {s['domain']}")
    tags = s["tags"] if isinstance(s["tags"], list) else []
    print(f"  Tags:        {', '.join(tags) if tags else '(none)'}")
    print(f"  Mode:        {s['mode']}")
    print(f"  Status:      {s['status']}")
    print(f"  Release:     {s.get('release_state', 'experimental')}")
    print(f"  Version:     {s['version']}")

    # Performance
    print("\nPerformance:")
    print(f"  Fitness:     {s['fitness_score']:.4f}")
    total = s["total_executions"]
    succ = s["successful_executions"]
    if total > 0:
        rate = f"{succ / total * 100:.1f}%"
        print(f"  Executions:  {total} ({succ} success, {total - succ} fail) → {rate} success rate")
    else:
        print(f"  Executions:  0 → N/A success rate")
    judge = s.get("avg_judge_score")
    if judge is not None:
        print(f"  Avg judge:   {judge:.1f}/10")
    print(f"  Last used:   {s.get('last_used') or '(never)'}")

    # Competitive Runs
    print("\nCompetitive Runs (recent 20):")
    if t["participated"] > 0:
        print(f"  Participated: {t['participated']} times")
        print(f"  Won:          {t['won']} times → {t['win_rate'] * 100:.1f}% win rate")
        print(f"  Avg latency:  {t['avg_execution_ms']}ms")
        run_total = t["success_in_runs"] + t["fail_in_runs"]
        if run_total > 0:
            run_rate = t["success_in_runs"] / run_total * 100
            print(f"  Run success:  {t['success_in_runs']}/{run_total} ({run_rate:.1f}%)")
    else:
        print("  (no competitive run data)")

    # Evolution
    print("\nEvolution:")
    if e["total_evolutions"] > 0:
        print(
            f"  Total:      {e['total_evolutions']} attempts "
            f"({e['adopted_count']} adopted, {e['discarded_count']} discarded) "
            f"→ {e['adoption_rate'] * 100:.1f}% adoption"
        )
        if e["last_evolution_adopted"] is not None:
            adopted_str = "adopted" if e["last_evolution_adopted"] else "discarded"
            print(
                f"  Last:       {adopted_str} "
                f"(fitness {e['last_parent_fitness']:.2f} → {e['last_child_fitness']:.2f})"
            )
    else:
        print("  (no evolution history)")

    # Safety
    print("\nSafety:")
    print(f"  Rollbacks:  {stats['rollback_count']}")
    if stats["feedback_count"] > 0:
        print(
            f"  Feedback:   {stats['avg_feedback_rating']}/5 avg "
            f"({stats['feedback_count']} ratings)"
        )
    else:
        print("  Feedback:   (no feedback)")


def _handle_scenario(args: argparse.Namespace) -> None:
    """cambrian scenario 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from datetime import datetime as _dt
    from engine.scenario import ScenarioRunner

    cmd = getattr(args, "scenario_command", None)
    if cmd == "matrix":
        _handle_scenario_matrix(args)
        return
    if cmd == "decide":
        _handle_scenario_decide(args)
        return
    if cmd != "run":
        print("Usage: cambrian scenario run <spec.json>")
        sys.exit(1)

    spec_path = Path(args.spec_file)
    if not spec_path.exists():
        print(f"Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    engine = _create_engine(args)
    runner = ScenarioRunner(engine)
    report = runner.run_scenario(
        spec,
        scenario_path=str(spec_path.resolve()),
        notes=getattr(args, "notes", ""),
    )

    # stdout 요약
    _print_scenario_summary(report)

    # report 파일 저장
    output_path = getattr(args, "output", None)
    if output_path is None:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(
            reports_dir / f"{spec.get('name', 'scenario')}_{timestamp}.json"
        )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nReport saved: {out}")


def _print_scenario_summary(report: dict) -> None:
    """scenario 실행 결과 요약을 출력한다.

    Args:
        report: ScenarioRunner.run_scenario() 반환값
    """
    name = report.get("scenario_name", "scenario")

    if not report.get("success"):
        print(f"Scenario: {name}")
        print("═" * 50)
        print("\n[FAIL] Spec validation error:")
        for err in report.get("errors", []):
            print(f"  - {err}")
        return

    total = report["total_inputs"]
    succ = report["successful_inputs"]
    fail = report["failed_inputs"]
    rate = report["success_rate"] * 100
    avg_ms = report["avg_execution_ms"]
    winner = report.get("winner_skill")

    print(f"Scenario: {name}")
    print("═" * 50)
    print(f"\nInputs:   {total} total, {succ} success, {fail} fail → {rate:.1f}%")
    print(f"Avg time: {avg_ms}ms")
    if winner:
        win_count = sum(
            1 for r in report["run_results"]
            if r["success"] and r["skill_id"] == winner
        )
        print(f"Winner:   {winner} (selected {win_count}/{succ} times)")
    else:
        print("Winner:   (none)")

    # Run Results 테이블
    print(f"\nRun Results:")
    print(f"  {'#':<4} {'OK':<6} {'SKILL':<20} {'TIME':<8} ERROR")
    for r in report["run_results"]:
        ok_str = "[OK]" if r["success"] else "[FAIL]"
        skill_str = r["skill_id"] or "-"
        time_str = f"{r['execution_time_ms']}ms"
        err_str = r.get("error", "")[:50]
        print(f"  {r['index']:<4} {ok_str:<6} {skill_str:<20} {time_str:<8} {err_str}")

    # Eval
    eval_r = report.get("eval_result")
    if eval_r:
        if "error" in eval_r:
            print(f"\nEval: error — {eval_r['error'][:80]}")
        elif "pass_rate" in eval_r:
            verdict = eval_r.get("verdict", "")
            print(f"\nEval: pass_rate {eval_r['pass_rate'] * 100:.1f}%, verdict: {verdict}")
        else:
            print(f"\nEval: {eval_r}")

    # Evolve
    evolve_r = report.get("evolve_result")
    if evolve_r:
        if "skipped" in evolve_r:
            print(f"Evolve: skipped ({evolve_r['skipped']})")
        elif "error" in evolve_r:
            print(f"Evolve: error — {evolve_r['error'][:80]}")
        elif "adopted" in evolve_r:
            adopted_str = "adopted" if evolve_r["adopted"] else "discarded"
            print(
                f"Evolve: {adopted_str} "
                f"(fitness {evolve_r['parent_fitness']:.4f} → {evolve_r['child_fitness']:.4f})"
            )

    # Re-eval
    re_eval_r = report.get("re_eval_result")
    if re_eval_r and "pass_rate" in re_eval_r:
        print(f"Re-eval: pass_rate {re_eval_r['pass_rate'] * 100:.1f}%, verdict: {re_eval_r.get('verdict', '')}")

    # Promote recommendation
    rec = report.get("promote_recommendation")
    if rec:
        print(f"\nPromote Recommendation:")
        print(
            f"  {rec['skill_id']}: {rec.get('release_state', '?')} → "
            f"{rec['recommendation']}"
        )
        if rec.get("eligible"):
            print(
                f"  fitness={rec.get('fitness', 0):.4f}, "
                f"executions={rec.get('executions', 0)}, "
                f"success_rate={rec.get('success_rate', 0) * 100:.1f}%"
            )
            print(f"  → Run: cambrian promote {rec['skill_id']}")


def _handle_scenario_matrix(args: argparse.Namespace) -> None:
    """cambrian scenario matrix 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.scenario import ScenarioRunner

    spec_path = Path(args.spec_file)
    if not spec_path.exists():
        print(f"Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    policy_paths = args.policies

    # 실행 전 전체 policy 파일 존재 검증
    for pp in policy_paths:
        if not Path(pp).exists():
            print(f"Policy file not found: {pp}", file=sys.stderr)
            sys.exit(1)

    baseline = getattr(args, "baseline", None)
    if baseline and baseline not in policy_paths:
        print(
            f"Baseline '{baseline}' is not in policies list.",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(policy_paths) == 1:
        print("[WARN] Only 1 policy — no comparison possible.")

    engine = _create_engine(args)
    runner = ScenarioRunner(engine)

    out_dir = getattr(args, "out_dir", None)
    summary = runner.run_matrix(
        spec=spec,
        policy_paths=policy_paths,
        baseline_path=baseline,
        scenario_path=str(spec_path.resolve()),
        notes=getattr(args, "notes", ""),
        out_dir=Path(out_dir) if out_dir else None,
    )

    if not summary.get("success", True):
        print("[FAIL] Matrix run failed:")
        for err in summary.get("errors", []):
            print(f"  - {err}")
        sys.exit(1)

    # stdout 요약
    _print_matrix_summary(summary)
    print(f"\nResults saved: {summary.get('scenario_path', '')}")


def _print_matrix_summary(summary: dict) -> None:
    """matrix 실행 결과 요약을 출력한다.

    Args:
        summary: run_matrix() 반환값
    """
    name = summary.get("scenario_name", "matrix")
    profiles = summary.get("profiles", [])
    baseline = summary.get("baseline_policy", "")

    print(f"Matrix Run: {name} ({len(profiles)} policies)")
    print("═" * 55)
    print(f"\nBaseline: {Path(baseline).name}")
    print(
        f"\n{'PROFILE':<22} {'SUCCESS':>7} {'EVAL':>7} {'AVG_MS':>7} "
        f"{'PROMOTE':<18} VERDICT"
    )
    for p in profiles:
        pname = Path(p["policy_path"]).stem
        if p["is_baseline"]:
            pname += " (base)"

        if p.get("verdict_vs_baseline") == "error":
            print(f"  {pname:<20} {'[ERROR]':>7} {'-':>7} {'-':>7} {'-':<18} error")
            continue

        sr = f"{p['success_rate'] * 100:.1f}%" if p["success_rate"] else "0.0%"
        ep = f"{p['eval_pass_rate'] * 100:.1f}%" if p.get("eval_pass_rate") is not None else "-"
        ms = f"{p['avg_execution_ms']}ms"
        prom = p.get("promote_recommendation") or "-"
        verdict = p.get("verdict_vs_baseline") or "-"

        # verdict 아이콘
        icon = {"improved": "↑", "regressed": "↓", "mixed": "↔", "equivalent": "="}.get(verdict, "")
        verdict_str = f"{verdict} {icon}" if icon else verdict

        print(
            f"  {pname:<20} {sr:>7} {ep:>7} {ms:>7} {prom:<18} {verdict_str}"
        )

    print(f"\nOverall: {summary.get('overall_verdict', '')}")


def _handle_scenario_decide(args: argparse.Namespace) -> None:
    """cambrian scenario decide 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.decision import MatrixDecider

    summary_path = Path(args.summary_file)
    if not summary_path.exists():
        print(f"File not found: {summary_path}", file=sys.stderr)
        sys.exit(1)

    try:
        matrix_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        decider = MatrixDecider()
        decision = decider.decide(matrix_summary)
        decision["matrix_summary_path"] = str(summary_path.resolve())
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        print(json.dumps(decision, indent=2, ensure_ascii=False))
    else:
        _print_decision_report(decision)

    # output 저장
    output_path = getattr(args, "output", None)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(decision, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nDecision saved: {out}")


def _print_decision_report(decision: dict) -> None:
    """decision report를 사람이 읽기 좋게 출력한다.

    Args:
        decision: MatrixDecider.decide() 반환값
    """
    name = decision.get("scenario_name", "")
    baseline = decision.get("baseline_policy", "")
    profiles = decision.get("profiles", [])
    champion = decision.get("champion")
    promotion = decision.get("promotion", {})

    print(f"Matrix Decision: {name}")
    print("═" * 55)
    print(f"\nBaseline: {Path(baseline).name if baseline else '-'}")

    print(
        f"\n{'PROFILE':<22} {'ROLE':<13} {'SUCCESS':>7} {'EVAL':>7} "
        f"{'AVG_MS':>7} VERDICT"
    )
    for p in profiles:
        pname = Path(p.get("policy_path", "")).stem or "?"
        role = p.get("role", "?")
        if role == "champion":
            role = "★ champion"

        sr = f"{p['success_rate'] * 100:.1f}%" if p.get("success_rate") else "-"
        ep = (
            f"{p['eval_pass_rate'] * 100:.1f}%"
            if p.get("eval_pass_rate") is not None else "-"
        )
        ms = f"{p['avg_execution_ms']}ms" if p.get("avg_execution_ms") else "-"
        verdict = p.get("verdict_vs_baseline") or "-"
        print(
            f"  {pname:<20} {role:<13} {sr:>7} {ep:>7} {ms:>7} {verdict}"
        )

    # Champion
    if champion:
        print(f"\nChampion: {Path(champion['policy_path']).name}")
        print(f"  {champion['selection_reason']}")
    else:
        print("\nChampion: (none)")

    # Baseline Decision
    bd = decision.get("baseline_decision", "")
    print(f"\nBaseline Decision: {bd}")

    # Promotion
    if promotion.get("recommend_promote"):
        print(f"\nPromotion: ✓ RECOMMEND")
        print(f"  {promotion['reason']}")
        print(
            f"  → To promote: cambrian promote <skill_id> "
            f"--reason \"champion: {Path(promotion.get('recommended_policy', '')).stem}\""
        )
    else:
        print(f"\nPromotion: ✗ NOT RECOMMENDED")
        print(f"  {promotion.get('reason', '')}")


def _handle_snapshot(args: argparse.Namespace) -> None:
    """cambrian snapshot 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.snapshot import SnapshotComparer

    if getattr(args, "snapshot_command", None) != "compare":
        print("Usage: cambrian snapshot compare <file_a> <file_b>")
        sys.exit(1)

    path_a = Path(args.file_a)
    path_b = Path(args.file_b)

    if not path_a.exists():
        print(f"File not found: {path_a}", file=sys.stderr)
        sys.exit(1)
    if not path_b.exists():
        print(f"File not found: {path_b}", file=sys.stderr)
        sys.exit(1)

    try:
        snap_a = json.loads(path_a.read_text(encoding="utf-8"))
        snap_b = json.loads(path_b.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    comparer = SnapshotComparer()
    result = comparer.compare(snap_a, snap_b)

    if getattr(args, "json_output", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(comparer.format_comparison(result))


def _handle_outcome(args: argparse.Namespace) -> None:
    """cambrian outcome 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    try:
        oid = engine.record_outcome(
            skill_id=args.skill_id,
            verdict=args.verdict,
            run_trace_id=getattr(args, "trace", None),
            human_note=getattr(args, "note", ""),
        )
        print(f"[OK] Outcome #{oid} recorded: {args.skill_id} → {args.verdict}")
    except SkillNotFoundError:
        print(f"Skill '{args.skill_id}' not found.", file=sys.stderr)
        sys.exit(1)


def _handle_pilot(args: argparse.Namespace) -> None:
    """cambrian pilot 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    report = engine.get_pilot_report(
        skill_id=getattr(args, "skill", None),
        days=getattr(args, "days", None),
    )

    if getattr(args, "json_output", False):
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    _print_pilot_report(report)


def _print_pilot_report(report: dict) -> None:
    """파일럿 리포트를 사람이 읽기 좋은 형태로 출력한다.

    Args:
        report: get_pilot_report() 반환값
    """
    g = report["global"]
    period = report.get("period_days")
    skill_filter = report.get("skill_filter")

    if g["total"] == 0:
        print("No pilot outcomes recorded yet.")
        print(
            "Record outcomes with: "
            "cambrian outcome <skill_id> approved|edited|rejected|redo"
        )
        return

    # 헤더
    period_str = f"last {period} days" if period else "all time"
    if skill_filter:
        print(f"Pilot Report: {skill_filter} ({period_str})")
    else:
        print(f"Pilot Report ({period_str})")
    print("═" * 50)

    # Overall KPI
    print(f"\nOverall KPI:")
    print(f"  Total outcomes:   {g['total']}")
    print(
        f"  Approved:         {g['approved']}"
        f"  ({g['acceptance_rate'] * 100:.1f}%)"
    )
    print(
        f"  Edited:           {g['edited']}"
        f"  ({g['edit_rate'] * 100:.1f}%)"
    )
    print(
        f"  Rejected:         {g['rejected']}"
        f"  ({g['reject_rate'] * 100:.1f}%)"
    )
    print(
        f"  Redo:             {g['redo']}"
        f"  ({g['redo_rate'] * 100:.1f}%)"
    )
    net = g["approved"] + g["edited"]
    print(f"  ─────────────────────────────")
    print(
        f"  Net useful:       {net}"
        f"  ({g['net_useful_rate'] * 100:.1f}%)"
    )

    # By Skill (글로벌 리포트일 때만)
    by_skill = report.get("by_skill", [])
    if by_skill:
        print(
            f"\n{'SKILL':<22} {'TOTAL':>5}  {'APPROVED':>8}  "
            f"{'EDITED':>6}  {'REJECTED':>8}  {'REDO':>4}  {'NET_USEFUL':>10}"
        )
        for s in by_skill:
            t = s["total"]
            print(
                f"  {s['skill_id']:<20} {t:>5}  "
                f"{s['approved']:>3} ({s['approved']*100//t:>2}%)  "
                f"{s['edited']:>3} ({s['edited']*100//t:>2}%)  "
                f"{s['rejected']:>3} ({s['rejected']*100//t:>2}%)  "
                f"{s['redo']:>4}  "
                f"{s['net_useful_rate']*100:>6.1f}%"
            )


def _handle_promote(args: argparse.Namespace) -> None:
    """cambrian promote 처리.

    --decision 지정 시 decision guardrail 적용 후 기존 governance 검증.
    promote 성공 시 adoption record 저장.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    import hashlib as _hashlib
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    engine = _create_engine(args)
    registry = engine.get_registry()

    # ── decision-backed guardrail ──
    decision_data = None
    decision_path = getattr(args, "decision", None)

    if decision_path:
        from engine.decision import MatrixDecider

        dp = Path(decision_path)
        if not dp.exists():
            print(f"Decision file not found: {dp}", file=sys.stderr)
            sys.exit(1)
        try:
            decision_data = json.loads(dp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Invalid decision JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        passed, reason = MatrixDecider.validate_for_promote(decision_data)
        if not passed:
            print(f"[BLOCKED] {reason}", file=sys.stderr)
            sys.exit(1)

    # ── 기존 governance 검증 ──
    try:
        skill_data = registry.get(args.skill_id)
    except SkillNotFoundError:
        print(f"Skill '{args.skill_id}' not found.", file=sys.stderr)
        sys.exit(1)

    current = skill_data.get("release_state", "experimental")
    target = getattr(args, "to", "production")

    if current == "quarantined":
        print(
            "[FAIL] Cannot promote quarantined skill. "
            "Use 'cambrian unquarantine' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    policy = engine.get_policy()
    q_count = 0
    if target == "production":
        min_exec = policy.promote_min_executions
        min_fit = policy.promote_min_fitness
        q_block = policy.quarantine_block_count
        if skill_data["total_executions"] < min_exec:
            print(
                f"[FAIL] Cannot promote: total_executions="
                f"{skill_data['total_executions']} < {min_exec}",
                file=sys.stderr,
            )
            sys.exit(1)
        if skill_data["fitness_score"] < min_fit:
            print(
                f"[FAIL] Cannot promote: fitness="
                f"{skill_data['fitness_score']:.4f} < {min_fit}",
                file=sys.stderr,
            )
            sys.exit(1)
        q_count = registry.get_quarantine_count(args.skill_id)
        if q_count >= q_block:
            print(
                f"[FAIL] Cannot promote: quarantined {q_count} times "
                f"(max {q_block - 1})",
                file=sys.stderr,
            )
            sys.exit(1)

    # ── promote 실행 ──
    registry.update_release_state(
        args.skill_id,
        new_state=target,
        reason=args.reason,
        triggered_by="manual",
    )

    # ── adoption record 생성 ──
    out_dir = Path(getattr(args, "adopt_out_dir", "adoptions"))
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _dt.now(_tz.utc)
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")

    decision_prov = None
    if decision_data and decision_path:
        raw = Path(decision_path).read_text(encoding="utf-8")
        d_hash = "sha256:" + _hashlib.sha256(raw.encode()).hexdigest()[:16]
        decision_prov = {
            "decision_file": str(Path(decision_path).resolve()),
            "decision_hash": d_hash,
            "matrix_summary_path": decision_data.get(
                "matrix_summary_path", ""
            ),
            "champion_policy": (
                decision_data.get("champion") or {}
            ).get("policy_path", ""),
            "baseline_decision": decision_data.get("baseline_decision", ""),
            "recommend_promote": (
                decision_data.get("promotion", {}).get("recommend_promote", False)
            ),
            "gate_reason": decision_data.get("promotion", {}).get("reason", ""),
        }

    record = {
        "_adoption_version": "1.0.0",
        "timestamp": timestamp.isoformat(),
        "skill_id": args.skill_id,
        "promoted_to": target,
        "previous_release_state": current,
        "decision_provenance": decision_prov,
        "human_provenance": {
            "reason": args.reason,
            "operator": "",
        },
        "governance_check": {
            "fitness_score": skill_data.get("fitness_score", 0),
            "total_executions": skill_data.get("total_executions", 0),
            "quarantine_count": q_count,
            "governance_passed": True,
        },
    }

    filename = f"adoption_{ts_str}_{args.skill_id}.json"
    filepath = out_dir / filename
    try:
        filepath.write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # _latest.json 갱신
        latest = {
            "latest_adoption": filename,
            "skill_id": args.skill_id,
            "promoted_to": target,
            "timestamp": timestamp.isoformat(),
        }
        (out_dir / "_latest.json").write_text(
            json.dumps(latest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"  [WARN] Adoption record 저장 실패: {exc}", file=sys.stderr)

    # ── lineage 기록 ──
    try:
        import uuid as _uuid
        run_id = str(_uuid.uuid4())[:8]

        # 직전 채택 정보에서 parent 추출
        latest_path = out_dir / "_latest.json"
        parent_skill: str | None = None
        parent_run: str | None = None
        if latest_path.exists():
            prev = json.loads(latest_path.read_text(encoding="utf-8"))
            if prev.get("skill_id") == args.skill_id:
                parent_skill = prev.get("skill_id")
                parent_run = prev.get("run_id")

        # _latest.json에 run_id 추가 갱신
        latest_data = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
        latest_data["run_id"] = run_id
        latest_path.write_text(
            json.dumps(latest_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        registry.add_lineage(
            child_skill_name=args.skill_id,
            child_run_id=run_id,
            parent_skill_name=parent_skill,
            parent_run_id=parent_run,
            scenario_id=None,
            policy_hash=None,
            notes=args.reason,
        )
    except Exception:
        pass  # lineage 실패가 promote를 중단하지 않음

    # ── stdout ──
    print(f"[OK] '{args.skill_id}' promoted: {current} → {target}")
    if decision_data:
        champion = decision_data.get("champion") or {}
        print(f"  Decision: champion={champion.get('policy_path', '?')}")
    print(f"  Reason: {args.reason}")
    print(f"  Adoption record: {filepath}")


def _handle_unquarantine(args: argparse.Namespace) -> None:
    """cambrian unquarantine 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    registry = engine.get_registry()

    try:
        skill_data = registry.get(args.skill_id)
    except SkillNotFoundError:
        print(f"Skill '{args.skill_id}' not found.", file=sys.stderr)
        sys.exit(1)

    current = skill_data.get("release_state", "experimental")
    if current != "quarantined":
        print(
            f"Skill '{args.skill_id}' is not quarantined (current: {current}).",
            file=sys.stderr,
        )
        sys.exit(1)

    registry.update_release_state(
        args.skill_id,
        new_state="experimental",
        reason=args.reason,
        triggered_by="manual",
    )
    print(f"[OK] '{args.skill_id}' unquarantined → experimental")


def _handle_governance(args: argparse.Namespace) -> None:
    """cambrian governance 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    registry = engine.get_registry()
    logs = registry.get_governance_log(
        skill_id=getattr(args, "skill", None),
        limit=args.limit,
    )

    if not logs:
        print("No governance history.")
        return

    print(
        f"{'ID':<5} {'SKILL':<20} {'FROM':<14} {'TO':<14} "
        f"{'BY':<8} {'REASON':<30} {'DATE'}"
    )
    print("─" * 105)
    for log in logs:
        print(
            f"{log['id']:<5} {log['skill_id']:<20} "
            f"{log['from_state']:<14} {log['to_state']:<14} "
            f"{log['triggered_by']:<8} "
            f"{log['reason'][:28]:<30} {log['created_at'][:16]}"
        )


def _handle_adoption(args: argparse.Namespace) -> None:
    """cambrian adoption 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    cmd = getattr(args, "adoption_cmd", None)
    if cmd == "rollback":
        _handle_adoption_rollback(args)
    elif cmd == "latest":
        _handle_adoption_latest(args)
    elif cmd == "validate":
        _handle_adoption_validate(args)
    elif cmd == "rebuild-index":
        _handle_adoption_rebuild_index(args)
    elif cmd == "list":
        _handle_adoption_list(args)
    elif cmd == "show":
        _handle_adoption_show(args)
    elif cmd == "review":
        _handle_adoption_review(args)
    elif cmd == "accept-generation":
        _handle_adoption_accept_generation(args)
    else:
        print(
            "Usage: cambrian adoption "
            "rollback|latest|validate|rebuild-index|list|show|review|accept-generation"
        )
        sys.exit(1)


def _handle_adoption_rollback(args: argparse.Namespace) -> None:
    """cambrian adoption rollback 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.rollback import RollbackError, execute_rollback, resolve_previous_adoption

    adoptions_dir = getattr(args, "adoptions_dir", "adoptions")
    latest_path = Path(adoptions_dir) / "_latest.json"

    if not latest_path.exists():
        print("[rollback] ✗ 실패 — _latest.json 없음 (채택 기록 없음)", file=sys.stderr)
        sys.exit(1)

    target_path = getattr(args, "target_path", None)
    use_previous = getattr(args, "previous", False)
    to_run_id = getattr(args, "to_run_id", None)

    # --previous: lineage에서 직전 찾기
    if use_previous and not target_path:
        current_latest = json.loads(latest_path.read_text(encoding="utf-8"))
        current_run_id = current_latest.get("run_id")
        skill_name = current_latest.get("skill_id") or current_latest.get("skill_name")

        if not current_run_id or not skill_name:
            print("[rollback] ✗ 실패 — latest에 run_id/skill 정보 없음", file=sys.stderr)
            sys.exit(1)

        engine = _create_engine(args)
        registry = engine.get_registry()
        resolved = resolve_previous_adoption(
            skill_name, current_run_id, registry._conn, adoptions_dir,
        )
        if not resolved:
            print("[rollback] ✗ 실패 — 직전 adoption 기록을 찾을 수 없음", file=sys.stderr)
            sys.exit(1)
        target_path = resolved

    # --to <run_id>: adoptions 디렉토리에서 검색
    if to_run_id and not target_path:
        adopt_dir = Path(adoptions_dir)
        found = None
        if adopt_dir.exists():
            for f in adopt_dir.glob("adoption_*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if data.get("run_id") == to_run_id:
                        found = str(f)
                        break
                except Exception:
                    continue
        if not found:
            print(f"[rollback] ✗ 실패 — run_id '{to_run_id}' 에 해당하는 record 없음", file=sys.stderr)
            sys.exit(1)
        target_path = found

    if not target_path:
        print("Usage: cambrian adoption rollback <path> | --previous | --to <run_id>", file=sys.stderr)
        sys.exit(1)

    # DB 연결 (lineage 기록용)
    db_conn = None
    try:
        engine = _create_engine(args)
        db_conn = engine.get_registry()._conn
    except Exception:
        pass

    try:
        record = execute_rollback(
            target_path=target_path,
            current_latest_path=str(latest_path),
            human_reason=getattr(args, "reason", None),
            adoptions_dir=adoptions_dir,
            db_conn=db_conn,
        )

        prev = record["previous_latest"]
        tgt = record["target_adoption"]
        print("[rollback] ✓ 성공")
        print(f"  skill      : {record['skill_name']}")
        print(f"  이전 latest : {prev['run_id'][:8]} ({prev['adopted_at'][:16]})")
        print(f"  복원 target : {tgt['run_id'][:8]} ({tgt['adopted_at'][:16]})")
        print(f"  record 저장 : {record.get('_record_path', '')}")
        print(f"  이유        : {record['human_reason'] or '미지정'}")

    except RollbackError as exc:
        print(f"[rollback] ✗ 실패 — {exc}", file=sys.stderr)
        print("현재 상태는 변경되지 않았습니다.", file=sys.stderr)
        sys.exit(1)


def _handle_adoption_latest(args: argparse.Namespace) -> None:
    """cambrian adoption latest 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    adoptions_dir = getattr(args, "adoptions_dir", "adoptions")
    latest_path = Path(adoptions_dir) / "_latest.json"

    if not latest_path.exists():
        print("[adoption] latest 없음 (채택 기록 없음)")
        return

    data = json.loads(latest_path.read_text(encoding="utf-8"))
    print(f"Latest Adoption:")
    print(f"  skill    : {data.get('skill_id') or data.get('skill_name', '?')}")
    print(f"  run_id   : {data.get('run_id', '?')}")
    print(f"  promoted : {data.get('promoted_to', '?')}")
    print(f"  timestamp: {data.get('timestamp', '?')}")
    action = data.get("action")
    if action:
        print(f"  action   : {action}")


def _handle_adoption_validate(args: argparse.Namespace) -> None:
    """cambrian adoption validate 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.validation import (
        ValidationError,
        compute_verdict,
        load_comparison_basis,
        run_fresh_validation,
        save_validation_record,
    )

    adoptions_dir = getattr(args, "adoptions_dir", "adoptions")
    val_out_dir = getattr(args, "val_out_dir", "adoptions/validations")

    # 1. adoption 로드
    adoption_path = getattr(args, "adoption_path", None)
    if adoption_path:
        p = Path(adoption_path)
        if not p.exists():
            print(f"[validate] ✗ error — adoption 파일 없음: {p}", file=sys.stderr)
            sys.exit(1)
        try:
            adoption = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[validate] ✗ error — {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        latest_path = Path(adoptions_dir) / "_latest.json"
        if not latest_path.exists():
            print("[validate] ✗ error — _latest.json 없음 (채택 기록 없음)", file=sys.stderr)
            sys.exit(1)
        adoption = json.loads(latest_path.read_text(encoding="utf-8"))

    skill_name = adoption.get("skill_id") or adoption.get("skill_name") or "unknown"
    run_id = adoption.get("run_id", "?")
    adopted_at = adoption.get("timestamp") or adoption.get("adopted_at") or ""

    # 2. comparison basis
    basis = load_comparison_basis(adoption, adoptions_dir)

    # 3. fresh run
    scenario_ref = adoption.get("scenario_ref") or adoption.get("scenario_id")
    spec_override = getattr(args, "spec_override", None)

    fresh_run = None
    try:
        engine = _create_engine(args)
        fresh_run = run_fresh_validation(
            scenario_ref=scenario_ref,
            spec_override=spec_override,
            skill_name=skill_name,
            engine=engine,
        )
    except ValidationError as exc:
        # fresh run 실패 → basis만으로 inconclusive 또는 error
        if basis["basis_metrics"] and not spec_override and not scenario_ref:
            # spec 없으면 inconclusive
            fresh_run = {"run_id": "", "report_path": None, "fresh_metrics": {}}
        else:
            # error verdict
            record = {
                "schema_version": "1.0",
                "action_type": "validation",
                "skill_name": skill_name,
                "timestamp": "",
                "target_adoption": {"run_id": run_id, "adopted_at": adopted_at, "record_path": ""},
                "scenario_ref": scenario_ref,
                "spec_override": spec_override,
                "comparison_basis": basis,
                "fresh_run": None,
                "metric_deltas": {},
                "verdict": "error",
                "verdict_reason": str(exc),
                "recommended_action": "investigate",
                "notes": None,
                "operator": "cli",
            }
            try:
                rp = save_validation_record(record, val_out_dir)
                print(f"  record 저장   : {rp}")
            except Exception:
                pass
            print(f"[validate] ✗ error — {exc}", file=sys.stderr)
            print("현재 adoption 상태는 변경되지 않았습니다.", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"[validate] ✗ error — {exc}", file=sys.stderr)
        print("현재 adoption 상태는 변경되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    # 4. verdict
    reg_threshold = getattr(args, "regression_threshold", 0.15)
    verdict_result = compute_verdict(
        basis["basis_metrics"],
        fresh_run["fresh_metrics"],
        regression_threshold=reg_threshold,
    )

    # 5. validation record 저장
    from datetime import datetime as _dt, timezone as _tz
    record = {
        "schema_version": "1.0",
        "action_type": "validation",
        "skill_name": skill_name,
        "timestamp": _dt.now(_tz.utc).isoformat(),
        "target_adoption": {
            "run_id": run_id,
            "adopted_at": adopted_at,
            "record_path": str(adoption_path or ""),
        },
        "scenario_ref": scenario_ref,
        "spec_override": spec_override,
        "comparison_basis": basis,
        "fresh_run": fresh_run,
        "metric_deltas": verdict_result["metric_deltas"],
        "verdict": verdict_result["verdict"],
        "verdict_reason": verdict_result["verdict_reason"],
        "recommended_action": verdict_result["recommended_action"],
        "notes": None,
        "operator": "cli",
    }

    record_path = ""
    try:
        record_path = save_validation_record(record, val_out_dir)
    except Exception as exc:
        print(f"  [WARN] record 저장 실패: {exc}", file=sys.stderr)

    # 6. CLI 출력
    verdict = verdict_result["verdict"]

    if verdict == "inconclusive":
        print(f"[validate] ⚠ inconclusive")
        print(f"  reason: {verdict_result['verdict_reason']}")
        print("  채택 기록을 확인하거나 --spec으로 직접 비교 기준을 제공하라.")
        if record_path:
            print(f"  record 저장   : {record_path}")
        return

    icon_map = {"worse": "⚠", "better": "✓", "neutral": "─", "unknown": "?"}

    print(f"[validate] ✓ 재검증 완료")
    print(f"  skill         : {skill_name}")
    print(f"  adoption      : {run_id[:8]} ({adopted_at[:16]})")
    print(f"  비교 기준     : {basis['source']} ({basis.get('ref_path') or 'inline'})")
    print(f"  fresh run     : {fresh_run['run_id']}")
    print()
    print(f"  metric 비교:")
    for name, delta in verdict_result["metric_deltas"].items():
        icon = icon_map.get(delta["direction"], "?")
        basis_v = delta.get("basis")
        fresh_v = delta.get("fresh")
        pct = delta.get("delta_pct", 0) * 100
        basis_s = f"{basis_v:.4f}" if basis_v is not None else "?"
        fresh_s = f"{fresh_v:.4f}" if fresh_v is not None else "?"
        print(f"    {name:<16}: {basis_s} → {fresh_s}  ({pct:+.1f}%)  {icon}")
    print()
    print(f"  verdict       : {verdict}")
    print(f"  추천 행동     : {verdict_result['recommended_action']} ({verdict_result['verdict_reason']})")
    if record_path:
        print(f"  record 저장   : {record_path}")


def _handle_adoption_rebuild_index(args: argparse.Namespace) -> None:
    """cambrian adoption rebuild-index 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.provenance import check_mismatch, rebuild_derived_index

    adoptions_dir = getattr(args, "adoptions_dir", "adoptions")
    engine = _create_engine(args)
    conn = engine.get_registry()._conn

    print("[rebuild-index] adoption files → derived index 재구성 중...")
    result = rebuild_derived_index(adoptions_dir, conn)
    print(
        f"  삽입: {result['inserted']}건  "
        f"스킵: {result['skipped']}건  "
        f"오류: {result['errors']}건"
    )

    mismatches = check_mismatch(adoptions_dir, conn)
    if mismatches:
        print(f"  [경고] 여전히 {len(mismatches)}건 불일치")
    else:
        print("  [OK] file ↔ index 일치 확인")


def _handle_adoption_list(args: argparse.Namespace) -> None:
    """cambrian adoption list 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.provenance import scan_adoption_files

    adoptions_dir = getattr(args, "adoptions_dir", "adoptions")
    records = scan_adoption_files(adoptions_dir)

    # 필터
    type_filter = getattr(args, "type", None)
    skill_filter = getattr(args, "skill", None)

    filtered = []
    for r in records:
        if r.get("_error"):
            continue
        if type_filter and r.get("action_type") != type_filter:
            continue
        skill = r.get("skill_name") or r.get("skill_id") or ""
        if skill_filter and skill != skill_filter:
            continue
        filtered.append(r)

    if not filtered:
        print("[adoption list] 조건에 맞는 기록 없음")
        return

    print(
        f"\n{'adopted_at':20} {'action_type':12} {'skill_name':20} {'run_id':10}"
    )
    print("─" * 64)
    for r in filtered:
        at = (r.get("adopted_at") or r.get("timestamp") or "")[:19]
        action = r.get("action_type") or "adoption"
        skill = r.get("skill_name") or r.get("skill_id") or "?"
        rid = (r.get("run_id") or "?")[:8]
        print(f"{at:20} {action:12} {skill:20} {rid:10}")
    print(f"\n총 {len(filtered)}건")

    # 에러 파일 경고
    err_count = sum(1 for r in records if r.get("_error"))
    if err_count:
        print(f"  [경고] 파싱 실패 파일 {err_count}건")


def _handle_adoption_show(args: argparse.Namespace) -> None:
    """cambrian adoption show 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.provenance import load_adoption_record, scan_adoption_files

    target = args.target
    adoptions_dir = getattr(args, "adoptions_dir", "adoptions")

    # 파일 경로인지 run_id인지 판별
    if Path(target).exists():
        try:
            data = load_adoption_record(target)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except ValueError as exc:
            print(f"[show] 오류: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        # run_id로 검색
        records = scan_adoption_files(adoptions_dir)
        found = None
        for r in records:
            if not r.get("_error") and r.get("run_id", "").startswith(target):
                found = r
                break
        if found:
            print(json.dumps(found, indent=2, ensure_ascii=False))
        else:
            print(f"[show] run_id '{target}'에 해당하는 record 없음", file=sys.stderr)
            sys.exit(1)


def _handle_lineage(args: argparse.Namespace) -> None:
    """cambrian lineage 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    registry = engine.get_registry()

    skill_name = args.skill_name
    run_id = getattr(args, "run_id", None)

    # run_id 미지정 시 가장 최근 채택 조회
    if not run_id:
        history = registry.get_adoption_history(skill_name=skill_name, limit=1)
        if not history:
            print(f"[lineage] 채택 기록 없음: {skill_name}")
            return
        run_id = history[0]["child_run_id"]

    print(f"\n=== Lineage: {skill_name} (run_id={run_id[:8]}...) ===\n")

    direction = getattr(args, "direction", "both")

    if direction in ("ancestors", "both"):
        ancestors = registry.get_ancestors(skill_name, run_id)
        if ancestors:
            print("◀ ANCESTORS (최신→최초)")
            for i, a in enumerate(ancestors):
                indent = "  " * i
                parent_label = (
                    f"← {a['parent_skill_name']}"
                    if a["parent_skill_name"] else "← [origin]"
                )
                print(
                    f"{indent}[{a['adopted_at'][:16]}] "
                    f"{a['skill_name']} ({a['run_id'][:8]}) {parent_label}"
                )
        else:
            print("◀ ANCESTORS: 없음 (최초 채택)")

    if direction in ("descendants", "both"):
        descendants = registry.get_descendants(run_id)
        if descendants:
            print("\n▶ DESCENDANTS")
            _print_lineage_tree(descendants, indent=0)
        else:
            print("\n▶ DESCENDANTS: 없음 (말단 노드)")

    print()


def _print_lineage_tree(nodes: list[dict], indent: int) -> None:
    """lineage 트리를 ASCII로 출력한다.

    Args:
        nodes: 자손 노드 리스트
        indent: 들여쓰기 수준
    """
    for node in nodes:
        prefix = "  " * indent + ("└─ " if indent > 0 else "")
        print(
            f"{prefix}[{node['adopted_at'][:16]}] "
            f"{node['skill_name']} ({node['run_id'][:8]})"
        )
        if node.get("children"):
            _print_lineage_tree(node["children"], indent + 1)


def _handle_audit(args: argparse.Namespace) -> None:
    """cambrian audit 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    audit_cmd = getattr(args, "audit_cmd", None)
    if audit_cmd != "adoptions":
        print("Usage: cambrian audit adoptions [--skill X] [--since Y] [--limit N]")
        sys.exit(1)

    engine = _create_engine(args)
    registry = engine.get_registry()

    records = registry.get_adoption_history(
        skill_name=getattr(args, "skill", None),
        since=getattr(args, "since", None),
        until=getattr(args, "until", None),
        scenario_id=getattr(args, "scenario", None),
        limit=getattr(args, "limit", 50),
    )

    if not records:
        print("[audit] 조건에 맞는 채택 기록 없음")
        return

    if getattr(args, "json_output", False):
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return

    header = (
        f"{'adopted_at':20} {'skill_name':20} {'parent':20} "
        f"{'scenario':15} {'policy':8}"
    )
    print(f"\n{header}")
    print("─" * len(header))
    for r in records:
        parent = r.get("parent_skill_name") or "—"
        scenario = (r.get("scenario_id") or "—")[:14]
        policy = (r.get("policy_hash") or "—")[:7]
        print(
            f"{r['adopted_at'][:19]:20} "
            f"{r['child_skill_name']:20} {parent:20} "
            f"{scenario:15} {policy:8}"
        )
    print(f"\n총 {len(records)}건\n")


def _handle_export(args: argparse.Namespace) -> None:
    """cambrian export 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.portability import SkillPorter

    engine = _create_engine(args)
    porter = SkillPorter(engine.get_loader(), engine.get_registry(), args.pool)

    try:
        zip_path = porter.export_skill(args.skill_id, Path(args.output))
        print(f"[OK] Exported '{args.skill_id}' to {zip_path}")
    except Exception as exc:
        print(f"[FAIL] Export failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_import(args: argparse.Namespace) -> None:
    """cambrian import 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.portability import SkillPorter

    engine = _create_engine(args)
    porter = SkillPorter(engine.get_loader(), engine.get_registry(), args.pool)

    try:
        skill_id = porter.import_skill(Path(args.path))
        print(f"[OK] Imported skill '{skill_id}'")
    except Exception as exc:
        print(f"[FAIL] Import failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_critique(args: argparse.Namespace) -> None:
    """cambrian critique 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    findings = engine.critique(args.skill_id)

    print(f"Critique: {args.skill_id}")
    print("─" * 40)

    if not findings:
        print("No issues found.")
        return

    high_count = 0
    medium_count = 0
    low_count = 0
    auto_saved = 0

    for finding in findings:
        severity = finding["severity"].upper()
        category = finding["category"]
        text = finding["finding"]
        suggestion = finding["suggestion"]
        print(f"[{severity}] {category}: {text}")
        if suggestion:
            print(f"  → Suggestion: {suggestion}")

        if severity == "HIGH":
            high_count += 1
            auto_saved += 1
        elif severity == "MEDIUM":
            medium_count += 1
        else:
            low_count += 1

    print("─" * 40)
    print(
        f"{len(findings)} findings "
        f"({high_count} high, {medium_count} medium, {low_count} low)"
    )
    if auto_saved > 0:
        print(f"{auto_saved} auto-feedback saved (high severity)")


def _handle_init(args: argparse.Namespace) -> None:
    """cambrian init 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    import shutil

    from engine._data_path import (
        get_bundled_policy_path,
        get_bundled_schemas_dir,
        get_bundled_skills_dir,
    )
    from engine.project_mode import ProjectInitializer, render_init_summary
    from engine.project_template_bootstrap import (
        apply_template_bootstrap,
        render_initialized_template_block,
        render_template_bootstrap_apply,
        template_init_defaults,
    )
    from engine.project_template_bootstrap_select import (
        BootstrapTemplateChoice,
        TemplateBootstrapSelector,
        default_template_bootstrap_choice_path,
        render_bootstrap_choice_result,
        render_bootstrap_recommendation_prompt,
        save_template_bootstrap_choice,
    )
    from engine.project_template_bootstrap_compare import render_bootstrap_template_compare
    from engine.project_wizard import (
        ProjectWizard,
        ProjectWizardResult,
        load_answers_file,
        render_wizard_summary,
    )

    target = Path(args.dir).resolve()
    result: object
    is_wizard = bool(getattr(args, "wizard", False))
    explicit_template_name = str(getattr(args, "template", "") or "").strip() or None
    use_recommended_template = bool(getattr(args, "use_recommended_template", False))
    skip_template = bool(getattr(args, "skip_template", False))
    template_name = explicit_template_name
    template_defaults: dict = {}
    template_bootstrap_result: dict | None = None
    template_choice: BootstrapTemplateChoice | None = None
    selector = TemplateBootstrapSelector()
    answers_file = getattr(args, "answers_file", None)
    preloaded_answers: dict | None = None
    answers_file_error: Exception | None = None
    if answers_file:
        try:
            preloaded_answers = load_answers_file(Path(answers_file).resolve())
        except (OSError, ValueError, yaml.YAMLError) as exc:
            answers_file_error = exc
    answers_selection_mode = str(
        (preloaded_answers or {}).get("template_selection_mode", "")
        if isinstance(preloaded_answers, dict)
        else ""
    ).strip()
    answers_selected_template = str(
        (preloaded_answers or {}).get("selected_template_name", "")
        if isinstance(preloaded_answers, dict)
        else ""
    ).strip() or None
    answers_manual_template = (
        answers_selected_template
        if answers_selection_mode == "manual_choice" and answers_selected_template
        else None
    )
    answers_use_recommended = answers_selection_mode == "recommended"
    answers_skip_template = answers_selection_mode in {"skipped", "skip"}
    cli_selection_flags = [
        bool(explicit_template_name),
        use_recommended_template,
        skip_template,
    ]

    if sum(1 for item in cli_selection_flags if item) > 1:
        print(
            "Template bootstrap option conflict.\n\nUse only one of:\n"
            "  --template <name>\n"
            "  --use-recommended-template\n"
            "  --skip-template",
            file=sys.stderr,
        )
        sys.exit(1)

    selection_requested = any(cli_selection_flags) or bool(
        answers_manual_template or answers_use_recommended or answers_skip_template
    )
    if selection_requested and (target / ".cambrian" / "project.yaml").exists():
        blocked_name = template_name or "recommended-template"
        next_actions = [
            f"cambrian template diff {blocked_name}",
            f"cambrian template review {blocked_name}",
            f"cambrian template accept {blocked_name}",
            f"cambrian template apply {blocked_name}",
        ]
        if getattr(args, "json_output", False):
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "template_name": template_name,
                        "errors": ["Cambrian is already fitted to this project."],
                        "next_actions": next_actions,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(render_initialized_template_block(blocked_name), file=sys.stderr)
        sys.exit(1)

    def _save_choice(choice: BootstrapTemplateChoice) -> None:
        choice_path = save_template_bootstrap_choice(target, choice)
        if choice.errors:
            if getattr(args, "json_output", False):
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "template_bootstrap_choice": choice.to_dict(),
                            "choice_path": str(choice_path.relative_to(target)).replace("\\", "/"),
                            "errors": choice.errors,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(render_bootstrap_choice_result(choice), file=sys.stderr)
                print()
                print("Run:", file=sys.stderr)
                print("  cambrian template list", file=sys.stderr)
            sys.exit(1)

    def _recommend_choice_context() -> dict:
        try:
            return selector.recommend_for_bootstrap(target)
        except Exception as exc:
            logging.getLogger(__name__).warning("template bootstrap recommendation failed: %s", exc)
            return {
                "report": None,
                "saved_path": None,
                "compare": None,
                "compare_path": None,
                "template_library_policy_context": {},
                "best_template_name": None,
                "available_templates": [],
                "considered_templates": [],
                "warnings": [f"template recommendation failed: {exc}"],
                "errors": [],
            }

    def _selection_refs(context: dict) -> tuple[str | None, str | None]:
        saved_path = context.get("saved_path")
        compare_path = context.get("compare_path")
        source_ref = (
            str(saved_path.relative_to(target)).replace("\\", "/")
            if isinstance(saved_path, Path)
            else None
        )
        compare_ref = (
            str(compare_path.relative_to(target)).replace("\\", "/")
            if isinstance(compare_path, Path)
            else None
        )
        return source_ref, compare_ref

    def _policy_context(context: dict) -> dict:
        value = context.get("template_library_policy_context")
        return dict(value) if isinstance(value, dict) else {}

    if explicit_template_name:
        context = _recommend_choice_context()
        source_ref, compare_ref = _selection_refs(context)
        template_choice = selector.choose(
            target,
            recommended_template_name=context.get("best_template_name"),
            selected_template_name=explicit_template_name,
            use_recommended=False,
            skip_template=False,
            available_templates=list(context.get("available_templates", []) or []),
            considered_templates=list(context.get("considered_templates", []) or []),
            source_recommendation_ref=source_ref,
            source_compare_ref=compare_ref,
            template_library_policy_context=_policy_context(context),
            selection_mode="explicit",
        )
        template_choice.warnings.extend(str(item) for item in context.get("warnings", []) if item)
        _save_choice(template_choice)
        template_name = template_choice.selected_template_name
    elif answers_manual_template:
        context = _recommend_choice_context()
        source_ref, compare_ref = _selection_refs(context)
        template_choice = selector.choose(
            target,
            recommended_template_name=context.get("best_template_name"),
            selected_template_name=answers_manual_template,
            use_recommended=False,
            skip_template=False,
            available_templates=list(context.get("available_templates", []) or []),
            considered_templates=list(context.get("considered_templates", []) or []),
            source_recommendation_ref=source_ref,
            source_compare_ref=compare_ref,
            template_library_policy_context=_policy_context(context),
            selection_mode="manual_choice",
        )
        template_choice.warnings.extend(str(item) for item in context.get("warnings", []) if item)
        _save_choice(template_choice)
        template_name = template_choice.selected_template_name
    elif use_recommended_template or answers_use_recommended:
        context = _recommend_choice_context()
        source_ref, compare_ref = _selection_refs(context)
        template_choice = selector.choose(
            target,
            recommended_template_name=context.get("best_template_name"),
            selected_template_name=None,
            use_recommended=True,
            skip_template=False,
            available_templates=list(context.get("available_templates", []) or []),
            considered_templates=list(context.get("considered_templates", []) or []),
            source_recommendation_ref=source_ref,
            source_compare_ref=compare_ref,
            template_library_policy_context=_policy_context(context),
        )
        template_choice.warnings.extend(str(item) for item in context.get("warnings", []) if item)
        _save_choice(template_choice)
        template_name = template_choice.selected_template_name
    elif skip_template or answers_skip_template:
        context = _recommend_choice_context()
        source_ref, compare_ref = _selection_refs(context)
        template_choice = selector.choose(
            target,
            recommended_template_name=context.get("best_template_name"),
            selected_template_name=None,
            use_recommended=False,
            skip_template=True,
            available_templates=list(context.get("available_templates", []) or []),
            considered_templates=list(context.get("considered_templates", []) or []),
            source_recommendation_ref=source_ref,
            source_compare_ref=compare_ref,
            template_library_policy_context=_policy_context(context),
        )
        template_choice.warnings.extend(str(item) for item in context.get("warnings", []) if item)
        _save_choice(template_choice)
        template_name = None
    elif is_wizard and not getattr(args, "non_interactive", False) and not getattr(args, "answers_file", None):
        context = _recommend_choice_context()
        report = context.get("report")
        available = list(context.get("available_templates", []) or [])
        considered = list(context.get("considered_templates", []) or [])
        if report is not None and available:
            source_ref, compare_ref = _selection_refs(context)
            while True:
                print(render_bootstrap_recommendation_prompt(report))
                answer = input("Select template option [1/2/3/4, default 4]: ").strip()
                if answer == "3":
                    compare = context.get("compare")
                    if compare is not None:
                        print()
                        print(render_bootstrap_template_compare(compare))
                        print()
                    continue
                break
            if answer == "1":
                template_choice = selector.choose(
                    target,
                    recommended_template_name=context.get("best_template_name"),
                    selected_template_name=None,
                    use_recommended=True,
                    skip_template=False,
                    available_templates=available,
                    considered_templates=considered,
                    source_recommendation_ref=source_ref,
                    source_compare_ref=compare_ref,
                    template_library_policy_context=_policy_context(context),
                )
            elif answer == "2":
                shortlist = considered or available
                print("Template shortlist:")
                for index, name in enumerate(shortlist[:4], start=1):
                    print(f"  {index}. {name}")
                selected_answer = input("Template name or number: ").strip()
                if selected_answer.isdigit() and 1 <= int(selected_answer) <= len(shortlist[:4]):
                    selected = shortlist[int(selected_answer) - 1]
                else:
                    selected = selected_answer
                template_choice = selector.choose(
                    target,
                    recommended_template_name=context.get("best_template_name"),
                    selected_template_name=selected,
                    use_recommended=False,
                    skip_template=False,
                    available_templates=available,
                    considered_templates=considered,
                    source_recommendation_ref=source_ref,
                    source_compare_ref=compare_ref,
                    template_library_policy_context=_policy_context(context),
                    selection_mode="manual_choice",
                )
            else:
                template_choice = selector.choose(
                    target,
                    recommended_template_name=context.get("best_template_name"),
                    selected_template_name=None,
                    use_recommended=False,
                    skip_template=True,
                    available_templates=available,
                    considered_templates=considered,
                    source_recommendation_ref=source_ref,
                    source_compare_ref=compare_ref,
                    template_library_policy_context=_policy_context(context),
                )
            template_choice.warnings.extend(str(item) for item in context.get("warnings", []) if item)
            _save_choice(template_choice)
            template_name = template_choice.selected_template_name

    if template_name:
        try:
            template_defaults = template_init_defaults(target, template_name)
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            print(f"Template bootstrap blocked: {exc}", file=sys.stderr)
            sys.exit(1)

    def _template_answers() -> dict:
        answers: dict = {}
        if getattr(args, "name", None):
            answers["project_name"] = getattr(args, "name")
        if getattr(args, "project_type", None):
            answers["project_type"] = getattr(args, "project_type")
        elif template_defaults.get("project_type"):
            answers["project_type"] = template_defaults.get("project_type")
        if getattr(args, "stack", None):
            answers["stack"] = getattr(args, "stack")
        elif template_defaults.get("stack"):
            answers["stack"] = template_defaults.get("stack")
        if getattr(args, "test_cmd", None):
            answers["test_command"] = getattr(args, "test_cmd")
        elif template_defaults.get("test_command"):
            answers["test_command"] = template_defaults.get("test_command")
        if template_defaults.get("primary_use_cases"):
            answers["primary_use_cases"] = template_defaults.get("primary_use_cases")
        if template_defaults.get("mode"):
            answers["mode"] = template_defaults.get("mode")
        return {key: value for key, value in answers.items() if value is not None}

    if is_wizard:
        answers_payload: dict | None = None
        answers_file = getattr(args, "answers_file", None)
        if answers_file:
            if answers_file_error is not None:
                result = ProjectWizardResult(
                    status="blocked",
                    answers=None,
                    created_files=[],
                    skipped_files=[],
                    warnings=[],
                    errors=[f"answers-file 로드 실패: {answers_file_error}"],
                    next_actions=["answers-file 경로와 YAML 형식을 확인하세요."],
                )
            else:
                answers_payload = preloaded_answers or {}
                answers_payload = {
                    **_template_answers(),
                    **answers_payload,
                }
                detected = ProjectInitializer._detect(target)
                result = ProjectWizard().run(
                    project_root=target,
                    detected=detected,
                    answers=answers_payload,
                    force=bool(getattr(args, "force", False)),
                    interactive=False,
                )
        elif getattr(args, "non_interactive", False):
            if template_name or skip_template:
                detected = ProjectInitializer._detect(target)
                result = ProjectWizard().run(
                    project_root=target,
                    detected=detected,
                    answers=_template_answers(),
                    force=bool(getattr(args, "force", False)),
                    interactive=False,
                )
            else:
                result = ProjectWizardResult(
                    status="blocked",
                    answers=None,
                    created_files=[],
                    skipped_files=[],
                    warnings=[],
                    errors=["--wizard 와 --non-interactive 를 함께 쓰려면 --answers-file 이 필요합니다."],
                    next_actions=["cambrian init --wizard --answers-file answers.yaml"],
                )
        else:
            detected = ProjectInitializer._detect(target)
            answers_payload = {
                **_template_answers(),
                "project_name": getattr(args, "name", None) or _template_answers().get("project_name"),
                "project_type": getattr(args, "project_type", None) or _template_answers().get("project_type"),
                "stack": getattr(args, "stack", None) or _template_answers().get("stack"),
                "test_command": getattr(args, "test_cmd", None) or _template_answers().get("test_command"),
            }
            result = ProjectWizard().run(
                project_root=target,
                detected=detected,
                answers={key: value for key, value in answers_payload.items() if value is not None},
                force=bool(getattr(args, "force", False)),
                interactive=True,
            )
    else:
        result = ProjectInitializer().init(
            project_root=target,
            name=getattr(args, "name", None),
            project_type=getattr(args, "project_type", None) or template_defaults.get("project_type"),
            stack=getattr(args, "stack", None) or template_defaults.get("stack"),
            test_cmd=getattr(args, "test_cmd", None) or template_defaults.get("test_command"),
            force=bool(getattr(args, "force", False)),
        )

    if template_name and getattr(result, "status", None) in {"initialized", "completed"}:
        try:
            template_bootstrap_result = apply_template_bootstrap(target, template_name)
        except Exception as exc:
            message = f"template bootstrap failed: {exc}"
            if hasattr(result, "warnings"):
                result.warnings.append(message)
            logging.getLogger(__name__).warning(message)
        else:
            if hasattr(result, "warnings"):
                result.warnings.extend(template_bootstrap_result.get("warnings", []))
            record_path = template_bootstrap_result.get("bootstrap_record_path")
            if record_path:
                if hasattr(result, "created_files"):
                    result.created_files.append(record_path)
                elif hasattr(result, "config_paths") and isinstance(result.config_paths, dict):
                    result.config_paths["template_bootstrap"] = str(target / record_path)

    # 기존 init 테스트 호환: 별도 대상 디렉토리를 줄 때는 예전 스캐폴드도 유지한다.
    if template_choice is not None and getattr(result, "status", None) in {"initialized", "completed"}:
        choice_rel = str(default_template_bootstrap_choice_path(target).relative_to(target)).replace("\\", "/")
        if hasattr(result, "created_files") and choice_rel not in result.created_files:
            result.created_files.append(choice_rel)
        elif hasattr(result, "config_paths") and isinstance(result.config_paths, dict):
            result.config_paths["template_bootstrap_choice"] = str(target / choice_rel)

    if getattr(result, "status", None) in {"initialized", "completed"} and target != Path.cwd().resolve():
        src_skills = Path(args.skills)
        if not src_skills.exists():
            src_skills = get_bundled_skills_dir()
        dst_skills = target / "skills"
        if src_skills.exists() and not dst_skills.exists():
            shutil.copytree(src_skills, dst_skills)

        src_schemas = Path(args.schemas)
        if not src_schemas.exists():
            src_schemas = get_bundled_schemas_dir()
        dst_schemas = target / "schemas"
        if src_schemas.exists() and not dst_schemas.exists():
            shutil.copytree(src_schemas, dst_schemas)

        (target / "skill_pool").mkdir(exist_ok=True)

        config_path = target / "cambrian.yaml"
        if not config_path.exists():
            _atomic_write_yaml = yaml.safe_dump(
                {
                    "provider": "anthropic",
                    "model": None,
                    "db_path": "skill_pool/registry.db",
                    "skills_dir": "skills",
                    "schemas_dir": "schemas",
                    "skill_pool_dir": "skill_pool",
                },
                allow_unicode=True,
                sort_keys=False,
            )
            config_path.write_text(_atomic_write_yaml, encoding="utf-8")

        policy_dst = target / "cambrian_policy.json"
        if not policy_dst.exists():
            bundled_policy = get_bundled_policy_path()
            if bundled_policy.exists():
                shutil.copy2(bundled_policy, policy_dst)

    if getattr(args, "json_output", False):
        payload = result.to_dict()
        if template_choice is not None:
            payload["template_bootstrap_choice"] = template_choice.to_dict()
        if template_bootstrap_result:
            payload["template_bootstrap"] = template_bootstrap_result
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if is_wizard:
        print(render_wizard_summary(result))
        if template_choice is not None:
            print()
            print(render_bootstrap_choice_result(template_choice))
        if template_bootstrap_result:
            print()
            print(render_template_bootstrap_apply(template_bootstrap_result))
        return

    print(render_init_summary(result))
    if template_choice is not None:
        print()
        print(render_bootstrap_choice_result(template_choice))
    if template_bootstrap_result:
        print()
        print(render_template_bootstrap_apply(template_bootstrap_result))


def _handle_template(args: argparse.Namespace) -> None:
    """cambrian template 처리."""
    from engine.project_templates import (
        HarnessTemplateApplier,
        HarnessTemplateBuilder,
        HarnessTemplateStore,
        default_templates_path,
        render_template_apply,
        render_template_list,
        render_template_show,
    )
    from engine.project_template_recommend import (
        TemplateRecommendationBuilder,
        TemplateRecommendationStore,
        default_request_template_recommendation_path,
        default_template_recommendation_path,
        render_template_recommendation,
    )
    from engine.project_template_diff import (
        TemplateDiffBuilder,
        TemplateDiffStore,
        default_template_diff_path,
        render_template_diff,
    )
    from engine.project_template_apply_guardrails import (
        TemplateApplyGuardrailBuilder,
        TemplateApplyGuardrailStore,
        default_template_apply_guardrails_path,
        load_template_apply_guardrail_summary,
        render_template_apply_guardrails,
        render_template_apply_guardrail_summary,
    )
    from engine.project_template_decisions import (
        TemplateDecisionStore,
        TemplateReviewBuilder,
        TemplateReviewStore,
        build_template_decision,
        default_template_decisions_path,
        default_template_reviews_dir,
        load_template_decision_summary,
        render_template_decision,
        render_template_decision_summary,
        render_template_decisions,
        render_template_review,
    )
    from engine.project_template_transfer import (
        HarnessTemplateExporter,
        HarnessTemplateImporter,
        imported_template_record_path,
        render_template_export,
        render_template_import,
    )
    from engine.project_template_history import (
        TemplateHistoryBuilder,
        TemplatePassportStore,
        TemplateRetrospectiveStore,
        build_template_retrospective,
        default_template_passport_path,
        default_template_retrospectives_dir,
        load_template_history_summary,
        render_template_history,
        render_template_history_summary,
        render_template_retrospective_saved,
        render_template_retrospectives,
    )
    from engine.project_template_library import (
        TemplateLibraryBoardBuilder,
        TemplateLibraryBoardStore,
        default_template_library_board_path,
        load_template_library_standing_summary,
        render_template_library_board,
        render_template_library_standing,
    )
    from engine.project_template_library_decisions import (
        TemplateLibraryDecisionStore,
        build_template_library_decision,
        default_template_library_decisions_path,
        load_template_library_decision_summary,
        render_template_library_decision,
        render_template_library_decision_summary,
        render_template_library_decisions,
    )
    from engine.project_template_library_policy import (
        build_and_save_template_library_policy_overlay,
        load_template_library_policy_summary,
        render_template_library_policy_summary,
    )
    from engine.project_template_qualification import (
        TemplateQualificationBuilder,
        TemplateQualificationStore,
        default_template_qualification_path,
        load_latest_template_qualification_summary,
        render_template_lineage,
        render_template_qualification,
        render_template_qualification_summary,
        resolve_template_qualification_path,
    )
    from engine.project_template_qualification_decisions import (
        QualificationAcceptBlockedError,
        TemplateQualificationDecisionStore,
        accept_qualification,
        dismiss_qualification,
        load_lane_playbook_summary,
        load_qualification_decision_summary,
        qualification_decisions_path,
        render_lane_playbook_summary,
        render_qualification_accepted,
        render_qualification_decisions,
        render_qualification_dismissed,
    )
    from engine.project_template_qualification_rollback import (
        QualificationAdoptionRollbackBlockedError,
        TemplateQualificationAdoptionStore,
        load_qualification_adoption_summary,
        qualification_adoptions_dir,
        render_qualification_adoption_summary,
        render_qualification_adoptions,
        render_qualification_reverted,
        revert_qualification_adoption,
    )
    from engine.project_template_canary import (
        TemplateCanaryStageBlockedError,
        active_canary_stage,
        load_template_canary_summary,
        qualification_stages_path,
        render_template_canary,
        render_template_canary_cleared,
        render_template_canary_staged,
        render_template_canary_summary,
        stage_qualification_as_canary,
        unstage_qualification_canary,
    )
    from engine.project_template_canary_report import (
        CanaryPromotionBlockedError,
        CanaryReportBlockedError,
        TemplateCanaryReportBuilder,
        TemplateCanaryReportStore,
        default_canary_report_path,
        load_latest_canary_report_summary,
        promote_canary_template,
        render_canary_promoted,
        render_canary_report,
        render_canary_report_summary,
        resolve_canary_report_path,
    )
    from engine.project_template_canary_ledger import (
        CanaryEventStore,
        CanaryLedgerBlockedError,
        CanaryLedgerBuilder,
        CanaryLedgerStore,
        canary_events_dir,
        default_canary_ledger_path,
        load_canary_ledger_summary,
        record_canary_recommendation_surface,
        render_canary_events,
        render_canary_ledger,
        render_canary_ledger_summary,
    )
    from engine.project_template_canary_outcomes import (
        CanaryOutcomeBlockedError,
        CanaryOutcomeLinkBuilder,
        CanaryOutcomeSummaryBuilder,
        build_and_save_canary_outcomes,
        load_canary_outcome_summary,
        render_canary_links,
        render_canary_outcome_summary,
        render_canary_outcomes,
    )
    from engine.project_template_canary_review import (
        CanaryReviewBlockedError,
        TemplateCanaryReviewBuilder,
        TemplateCanaryReviewStore,
        default_canary_review_path,
        load_canary_review_summary,
        render_canary_review,
        render_canary_review_summary,
        resolve_canary_review_path,
    )
    from engine.project_template_challenge_matrix import (
        TemplateChallengeMatrixBuilder,
        TemplateChallengeMatrixStore,
        build_challenge_board_summary,
        default_challenge_matrix_path,
        load_challenge_matrix_summary,
        load_challenger_queue_summary,
        render_challenge_board,
        render_challenge_matrix,
        render_challenge_matrix_summary,
        render_challengers,
        resolve_challenge_matrix_path,
    )

    root = Path.cwd()
    command = getattr(args, "template_command", None)
    if not command:
        print("template 하위 명령이 필요합니다. 예: cambrian template list", file=sys.stderr)
        sys.exit(1)
    templates_path = default_templates_path(root)
    store = HarnessTemplateStore()
    template_decisions_path = default_template_decisions_path(root)

    if command == "save":
        try:
            template = HarnessTemplateBuilder().from_current_project(
                root,
                str(getattr(args, "name")),
                description=getattr(args, "description", None),
                tags=list(getattr(args, "template_tags", []) or []),
            )
            saved_path = store.add(templates_path, template)
        except FileNotFoundError:
            print("Template save requires a fitted harness.\n\nRun:\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template save blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {"status": "saved", "template": template.to_dict(), "saved_path": str(saved_path)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print("Template saved.")
        print()
        print(render_template_show(template))
        print()
        print(f"Saved:\n  {saved_path}")
        return

    if command == "list":
        model = store.load(templates_path)
        if getattr(args, "json_output", False):
            print(json.dumps(model.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_template_list(model))
        return

    if command == "show":
        model = store.load(templates_path)
        try:
            template = store.find(model, str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        decision_summary = load_template_decision_summary(root, template.name)
        guardrail_summary = load_template_apply_guardrail_summary(root)
        if guardrail_summary.get("template_name") != template.name:
            guardrail_summary = {}
        history_summary = load_template_history_summary(root, template.name)
        library_standing = load_template_library_standing_summary(root, template.name)
        library_decision_summary = load_template_library_decision_summary(root, template.name)
        library_policy_summary = load_template_library_policy_summary(root, template.name)
        qualification_summary = load_latest_template_qualification_summary(root, template.name)
        qualification_decision_summary = load_qualification_decision_summary(root, template.name)
        qualification_adoption_summary = load_qualification_adoption_summary(root, template.name)
        template_canary_summary = load_template_canary_summary(root, template.name)
        canary_report_summary = load_latest_canary_report_summary(root, template.name)
        canary_ledger_summary = load_canary_ledger_summary(root, template.name)
        canary_outcome_summary = load_canary_outcome_summary(root, template.name)
        canary_review_summary = load_canary_review_summary(root, template.name)
        challenge_matrix_summary = load_challenge_matrix_summary(root, template.name)
        if getattr(args, "json_output", False):
            payload = template.to_dict()
            payload["decision_summary"] = decision_summary
            payload["apply_guardrail_summary"] = guardrail_summary
            payload["history_summary"] = history_summary
            payload["library_standing"] = library_standing
            payload["library_decision_summary"] = library_decision_summary
            payload["library_policy_summary"] = library_policy_summary
            payload["qualification_summary"] = qualification_summary
            payload["qualification_decision_summary"] = qualification_decision_summary
            payload["qualification_adoption_summary"] = qualification_adoption_summary
            payload["template_canary_summary"] = template_canary_summary
            payload["canary_report_summary"] = canary_report_summary
            payload["canary_ledger_summary"] = canary_ledger_summary
            payload["canary_outcome_summary"] = canary_outcome_summary
            payload["canary_review_summary"] = canary_review_summary
            payload["challenge_matrix_summary"] = challenge_matrix_summary
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_show(template))
        if qualification_summary:
            print()
            print(render_template_qualification_summary(qualification_summary))
        if qualification_decision_summary and qualification_decision_summary.get("latest_status"):
            print()
            print("Qualification decision:")
            print(f"  status : {qualification_decision_summary.get('latest_status')}")
            print(f"  verdict: {qualification_decision_summary.get('latest_verdict') or 'unknown'}")
            actions = qualification_decision_summary.get("latest_actions") if isinstance(qualification_decision_summary.get("latest_actions"), dict) else {}
            if actions.get("set_lane_default"):
                print("  lane   : default switched")
        if qualification_adoption_summary:
            print()
            print(render_qualification_adoption_summary(qualification_adoption_summary))
        if template_canary_summary:
            print()
            print(render_template_canary_summary(template_canary_summary))
        if canary_report_summary:
            print()
            print(render_canary_report_summary(canary_report_summary))
        if canary_ledger_summary:
            print()
            print(render_canary_ledger_summary(canary_ledger_summary))
        if canary_outcome_summary:
            print()
            print(render_canary_outcome_summary(canary_outcome_summary))
        if canary_review_summary:
            print()
            print(render_canary_review_summary(canary_review_summary))
        if challenge_matrix_summary:
            print()
            print(render_challenge_matrix_summary(challenge_matrix_summary))
        if history_summary and history_summary.get("template_name"):
            print()
            print(render_template_history_summary(history_summary))
        if library_standing:
            print()
            print(render_template_library_standing(library_standing))
        if library_decision_summary and library_decision_summary.get("latest_kind"):
            print()
            print(render_template_library_decision_summary(library_decision_summary))
        if library_policy_summary and library_policy_summary.get("standing"):
            print()
            print(render_template_library_policy_summary(library_policy_summary))
        if decision_summary.get("latest_status"):
            print()
            print(render_template_decision_summary(decision_summary))
        if guardrail_summary:
            print()
            print(render_template_apply_guardrail_summary(guardrail_summary))
        return

    if command == "apply":
        template_name = str(getattr(args, "name"))
        guardrail_report = TemplateApplyGuardrailBuilder().build(root, template_name)
        guardrail_path = TemplateApplyGuardrailStore().save(
            guardrail_report,
            default_template_apply_guardrails_path(root),
        )
        force = bool(getattr(args, "force", False))
        hard_blocked = guardrail_report.status == "blocked"
        warning_blocked = guardrail_report.status == "safe_with_warnings" and not force
        if hard_blocked or warning_blocked:
            payload = {
                "status": "blocked",
                "guardrails": guardrail_report.to_dict(),
                "guardrails_path": str(guardrail_path.relative_to(root)).replace("\\", "/"),
                "force_allowed": guardrail_report.status == "safe_with_warnings",
            }
            if getattr(args, "json_output", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(render_template_apply_guardrails(guardrail_report))
                print()
                print("Saved:")
                print(f"  {guardrail_path.relative_to(root)}")
            sys.exit(1)
        try:
            result = HarnessTemplateApplier().apply(
                root,
                template_name,
                force=force,
            )
        except FileNotFoundError as exc:
            print(f"Template apply requires an initialized project: {exc}", file=sys.stderr)
            sys.exit(1)
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template apply blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        result["guardrails"] = guardrail_report.to_dict()
        result["guardrails_path"] = str(guardrail_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        print(render_template_apply_guardrails(guardrail_report))
        print()
        print("Applying template...")
        print()
        print(render_template_apply(result))
        return

    if command == "recommend":
        request = getattr(args, "request", None)
        report = TemplateRecommendationBuilder().build(root, request=request)
        saved_path = None
        if bool(getattr(args, "save", False)):
            target_path = (
                default_request_template_recommendation_path(root)
                if request
                else default_template_recommendation_path(root)
            )
            saved_path = TemplateRecommendationStore().save(report, target_path)
        canary_events = []
        try:
            canary_events = record_canary_recommendation_surface(
                root,
                report,
                surface_kind="recommend",
                source_ref=str(saved_path.relative_to(root)).replace("\\", "/") if saved_path is not None else None,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("canary recommend ledger event failed: %s", exc)
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if canary_events:
            payload["canary_events"] = [event.to_dict() for event in canary_events]
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_recommendation(report))
        if saved_path is not None:
            print()
            print("Saved:")
            print(f"  {saved_path.relative_to(root)}")
        return

    if command == "board":
        request = getattr(args, "request", None)
        report = TemplateLibraryBoardBuilder().build(root, request=request)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateLibraryBoardStore().save(report, default_template_library_board_path(root))
        canary_events = []
        try:
            canary_events = record_canary_recommendation_surface(
                root,
                report,
                surface_kind="board",
                source_ref=str(saved_path.relative_to(root)).replace("\\", "/") if saved_path is not None else None,
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("canary board ledger event failed: %s", exc)
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if canary_events:
            payload["canary_events"] = [event.to_dict() for event in canary_events]
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_library_board(report))
        if saved_path is not None:
            print()
            print("Saved:")
            print(f"  {saved_path.relative_to(root)}")
        return

    if command == "qualify":
        modes = ["both"] if getattr(args, "mode", "both") == "both" else [str(getattr(args, "mode"))]
        try:
            report = TemplateQualificationBuilder().build(
                root,
                str(getattr(args, "name")),
                str(getattr(args, "workset")),
                reference_template_name=getattr(args, "against", None),
                modes=modes,
            )
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Template qualification blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateQualificationStore().save(report, default_template_qualification_path(root, report))
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_qualification(
            report,
            saved_path=str(saved_path.relative_to(root)).replace("\\", "/") if saved_path is not None else None,
        ))
        return

    if command == "qualify-show":
        try:
            qualification_path = resolve_template_qualification_path(root, str(getattr(args, "qualification_ref")))
        except FileNotFoundError as exc:
            print(f"Template qualification not found: {exc}", file=sys.stderr)
            sys.exit(1)
        report = TemplateQualificationStore().load(qualification_path)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["qualification_path"] = str(qualification_path.relative_to(root)).replace("\\", "/")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_qualification(report, saved_path=str(qualification_path.relative_to(root)).replace("\\", "/")))
        return

    if command == "qualify-accept":
        try:
            decision, playbook, library_decisions, adoption, adoption_path = accept_qualification(
                root,
                str(getattr(args, "qualification_ref")),
                set_lane_default=bool(getattr(args, "set_lane_default", False)),
                parent_action=str(getattr(args, "parent_action", "keep_as_backup")),
                resolution=getattr(args, "resolution", None),
                force=bool(getattr(args, "force", False)),
            )
        except QualificationAcceptBlockedError as exc:
            print(
                "Qualification verdict is not candidate_stronger.\n\n"
                f"Current verdict:\n  {exc.verdict or 'unknown'}\n\n"
                "Use:\n"
                f"  cambrian template qualify-show {exc.qualification_ref}\n"
                "or:\n"
                f"  cambrian template qualify-accept {exc.qualification_ref} --force",
                file=sys.stderr,
            )
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template qualification accept blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {
            "status": "accepted",
            "decision": decision.to_dict(),
            "lane_playbook": playbook.to_dict() if playbook is not None else None,
            "library_decisions": [item.to_dict() for item in library_decisions],
            "adoption": adoption.to_dict(),
            "adoption_path": str(adoption_path.relative_to(root)).replace("\\", "/"),
            "decisions_path": str(qualification_decisions_path(root).relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_qualification_accepted(
            decision,
            playbook,
            library_decisions,
            adoption_ref=str(adoption_path.relative_to(root)).replace("\\", "/"),
        ))
        return

    if command == "qualify-dismiss":
        try:
            decision = dismiss_qualification(
                root,
                str(getattr(args, "qualification_ref")),
                resolution=getattr(args, "resolution", None),
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template qualification dismiss blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {
            "status": "dismissed",
            "decision": decision.to_dict(),
            "decisions_path": str(qualification_decisions_path(root).relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_qualification_dismissed(decision))
        return

    if command == "qualify-decisions":
        model = TemplateQualificationDecisionStore().load(qualification_decisions_path(root))
        decisions = list(model.decisions)
        status_filter = getattr(args, "status", None)
        if status_filter:
            decisions = [decision for decision in decisions if decision.status == status_filter]
        if getattr(args, "json_output", False):
            payload = model.to_dict()
            if status_filter:
                payload["decisions"] = [decision.to_dict() for decision in decisions]
            payload["lane_playbook_summary"] = load_lane_playbook_summary(root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_qualification_decisions(decisions))
        lane_summary = load_lane_playbook_summary(root)
        if lane_summary:
            print()
            print(render_lane_playbook_summary(lane_summary))
        return

    if command == "qualify-adoptions":
        adoptions = TemplateQualificationAdoptionStore().list(qualification_adoptions_dir(root))
        status_filter = getattr(args, "status", None)
        if status_filter:
            adoptions = [adoption for adoption in adoptions if adoption.status == status_filter]
        if getattr(args, "json_output", False):
            print(json.dumps({
                "schema_version": "1.0.0",
                "adoptions": [adoption.to_dict() for adoption in adoptions],
            }, indent=2, ensure_ascii=False))
            return
        print(render_qualification_adoptions(adoptions))
        return

    if command == "qualify-revert":
        try:
            rollback, adoption, rollback_path, library_decisions = revert_qualification_adoption(
                root,
                str(getattr(args, "adoption_ref")),
                resolution=getattr(args, "resolution", None),
            )
        except QualificationAdoptionRollbackBlockedError as exc:
            print(f"Template qualification rollback blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template qualification rollback failed: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {
            "status": "reverted",
            "rollback": rollback.to_dict(),
            "adoption": adoption.to_dict(),
            "library_decisions": [item.to_dict() for item in library_decisions],
            "rollback_path": str(rollback_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_qualification_reverted(rollback, rollback_path, root))
        return

    if command == "qualify-stage":
        try:
            stage, playbook, stages_path = stage_qualification_as_canary(
                root,
                str(getattr(args, "qualification_ref")),
                reason=getattr(args, "reason", None),
                force=bool(getattr(args, "force", False)),
            )
        except TemplateCanaryStageBlockedError as exc:
            print(
                "Template canary stage blocked.\n\n"
                f"Why:\n  {exc}\n\n"
                "Use:\n"
                "  cambrian template canary\n"
                "  cambrian template qualify-unstage <qualification>\n"
                "or:\n"
                f"  cambrian template qualify-stage {exc.qualification_ref or '<qualification>'} --force",
                file=sys.stderr,
            )
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary stage failed: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {
            "status": "active",
            "stage": stage.to_dict(),
            "lane_playbook": playbook.to_dict(),
            "stages_path": str(stages_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_canary_staged(stage, playbook, stages_path, root))
        return

    if command == "canary":
        stage = active_canary_stage(root)
        playbook = None
        try:
            from engine.project_template_qualification_decisions import LanePlaybookStore, lane_playbook_path

            playbook = LanePlaybookStore().load(lane_playbook_path(root))
        except Exception:
            playbook = None
        payload = {
            "stage": stage.to_dict() if stage is not None else None,
            "lane_playbook": playbook.to_dict() if playbook is not None else None,
            "stages_path": str(qualification_stages_path(root).relative_to(root)).replace("\\", "/"),
            "canary_ledger_summary": load_canary_ledger_summary(root),
            "canary_outcome_summary": load_canary_outcome_summary(root),
            "canary_review_summary": load_canary_review_summary(root),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_canary(stage, playbook))
        ledger_summary = payload.get("canary_ledger_summary") if isinstance(payload.get("canary_ledger_summary"), dict) else {}
        if ledger_summary:
            print()
            print(render_canary_ledger_summary(ledger_summary))
        outcome_summary = payload.get("canary_outcome_summary") if isinstance(payload.get("canary_outcome_summary"), dict) else {}
        if outcome_summary:
            print()
            print(render_canary_outcome_summary(outcome_summary))
        review_summary = payload.get("canary_review_summary") if isinstance(payload.get("canary_review_summary"), dict) else {}
        if review_summary:
            print()
            print(render_canary_review_summary(review_summary))
        return

    if command == "canary-ledger":
        try:
            summary = CanaryLedgerBuilder().build(root, template_name=getattr(args, "name", None))
        except CanaryLedgerBlockedError as exc:
            print(f"Template canary ledger blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary ledger failed: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = CanaryLedgerStore().save(summary, default_canary_ledger_path(root, summary))
        payload = summary.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_ledger(
            summary,
            str(saved_path.relative_to(root)).replace("\\", "/") if saved_path is not None else None,
        ))
        return

    if command == "canary-events":
        events = CanaryEventStore().list_events(canary_events_dir(root), getattr(args, "name", None))
        kind_filter = getattr(args, "kind", None)
        if kind_filter:
            events = [event for event in events if event.event_kind == kind_filter]
        limit = int(getattr(args, "limit", 20) or 20)
        if getattr(args, "json_output", False):
            print(json.dumps({
                "schema_version": "1.0.0",
                "events": [event.to_dict() for event in events[: max(1, limit)]],
            }, indent=2, ensure_ascii=False))
            return
        print(render_canary_events(events, limit=limit))
        return

    if command == "canary-outcomes":
        try:
            if bool(getattr(args, "save", False)):
                summary, links, summary_path = build_and_save_canary_outcomes(root, getattr(args, "name", None))
            else:
                summary = CanaryOutcomeSummaryBuilder().build(root, template_name=getattr(args, "name", None))
                links = CanaryOutcomeLinkBuilder().build_links(root, summary.template_name)
                summary_path = None
        except CanaryOutcomeBlockedError as exc:
            print(f"Template canary outcomes blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary outcomes failed: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = summary.to_dict()
        payload["links"] = [link.to_dict() for link in links]
        if summary_path is not None:
            payload["saved_path"] = str(summary_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_outcomes(
            summary,
            str(summary_path.relative_to(root)).replace("\\", "/") if summary_path is not None else None,
        ))
        return

    if command == "canary-links":
        try:
            summary = CanaryOutcomeSummaryBuilder().build(root, template_name=getattr(args, "name", None))
            links = CanaryOutcomeLinkBuilder().build_links(root, summary.template_name)
        except CanaryOutcomeBlockedError as exc:
            print(f"Template canary links blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary links failed: {exc}", file=sys.stderr)
            sys.exit(1)
        limit = int(getattr(args, "limit", 20) or 20)
        if getattr(args, "json_output", False):
            print(json.dumps({
                "schema_version": "1.0.0",
                "template_name": summary.template_name,
                "links": [link.to_dict() for link in links[: max(1, limit)]],
            }, indent=2, ensure_ascii=False))
            return
        print(render_canary_links(links, limit=limit))
        return

    if command == "canary-review":
        try:
            report = TemplateCanaryReviewBuilder().build(root, template_name=getattr(args, "name", None))
        except CanaryReviewBlockedError as exc:
            print(
                f"Template canary review blocked: {exc}\n\nRun:\n  cambrian template canary",
                file=sys.stderr,
            )
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary review failed: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateCanaryReviewStore().save(report, default_canary_review_path(root, report))
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_review(
            report,
            str(saved_path.relative_to(root)).replace("\\", "/") if saved_path is not None else None,
        ))
        return

    if command == "canary-review-show":
        try:
            review_path = resolve_canary_review_path(root, str(getattr(args, "review_ref")))
            report = TemplateCanaryReviewStore().load(review_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Template canary review show failed: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["path"] = str(review_path.relative_to(root)).replace("\\", "/")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_review(report, str(review_path.relative_to(root)).replace("\\", "/")))
        return

    if command == "canary-report":
        try:
            report = TemplateCanaryReportBuilder().build(
                root,
                template_name=getattr(args, "name", None),
                workset_name=getattr(args, "workset", None),
            )
        except CanaryReportBlockedError as exc:
            print(
                f"Template canary report blocked: {exc}\n\nRun:\n  cambrian template canary",
                file=sys.stderr,
            )
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary report failed: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateCanaryReportStore().save(report, default_canary_report_path(root, report))
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_report(report, str(saved_path.relative_to(root)).replace("\\", "/") if saved_path else None))
        return

    if command == "canary-report-show":
        try:
            report_path = resolve_canary_report_path(root, str(getattr(args, "report_ref")))
            report = TemplateCanaryReportStore().load(report_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Template canary report show failed: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["path"] = str(report_path.relative_to(root)).replace("\\", "/")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_report(report, str(report_path.relative_to(root)).replace("\\", "/")))
        return

    if command == "canary-promote":
        try:
            payload = promote_canary_template(
                root,
                str(getattr(args, "name")),
                previous_default_action=str(getattr(args, "previous_default_action") or "keep_as_backup"),
                resolution=getattr(args, "resolution", None),
                force=bool(getattr(args, "force", False)),
            )
        except CanaryPromotionBlockedError as exc:
            print(
                f"Template canary promotion blocked: {exc}\n\n"
                f"Verdict:\n  {exc.verdict or 'unknown'}",
                file=sys.stderr,
            )
            if exc.next_action:
                print(f"\nUse:\n  {exc.next_action}", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary promotion failed: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_canary_promoted(payload))
        return

    if command == "qualify-unstage":
        try:
            stage, playbook, _stages_path = unstage_qualification_canary(
                root,
                str(getattr(args, "qualification_ref")),
                resolution=getattr(args, "resolution", None),
            )
        except TemplateCanaryStageBlockedError as exc:
            print(f"Template canary unstage blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template canary unstage failed: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {
            "status": "cleared",
            "stage": stage.to_dict(),
            "lane_playbook": playbook.to_dict(),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_canary_cleared(stage, playbook))
        return

    if command == "challenge-matrix":
        try:
            mode_arg = str(getattr(args, "mode", "both") or "both")
            modes = ["cambrian_guided", "cambrian_full"] if mode_arg == "both" else [mode_arg]
            report = TemplateChallengeMatrixBuilder().build(
                root,
                str(getattr(args, "workset")),
                modes=modes,
            )
        except (FileNotFoundError, KeyError, ValueError) as exc:
            print(f"Template challenge matrix failed: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateChallengeMatrixStore().save(report, default_challenge_matrix_path(root, report))
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_challenge_matrix(
            report,
            str(saved_path.relative_to(root)).replace("\\", "/") if saved_path is not None else None,
        ))
        return

    if command == "challenge-matrix-show":
        try:
            matrix_path = resolve_challenge_matrix_path(root, str(getattr(args, "matrix_ref")))
            report = TemplateChallengeMatrixStore().load(matrix_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Template challenge matrix show failed: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = report.to_dict()
            payload["path"] = str(matrix_path.relative_to(root)).replace("\\", "/")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_challenge_matrix(report, str(matrix_path.relative_to(root)).replace("\\", "/")))
        return

    if command == "challenge-board":
        summary = build_challenge_board_summary(root)
        if getattr(args, "json_output", False):
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return
        print(render_challenge_board(summary))
        return

    if command == "challengers":
        summary = load_challenger_queue_summary(root)
        if getattr(args, "json_output", False):
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return
        print(render_challengers(summary))
        return

    if command == "lineage":
        model = store.load(templates_path)
        try:
            template = store.find(model, str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        qualification_summary = load_latest_template_qualification_summary(root, template.name)
        qualification_decision_summary = load_qualification_decision_summary(root, template.name)
        qualification_adoption_summary = load_qualification_adoption_summary(root, template.name)
        template_canary_summary = load_template_canary_summary(root, template.name)
        canary_report_summary = load_latest_canary_report_summary(root, template.name)
        canary_ledger_summary = load_canary_ledger_summary(root, template.name)
        canary_outcome_summary = load_canary_outcome_summary(root, template.name)
        canary_review_summary = load_canary_review_summary(root, template.name)
        challenge_matrix_summary = load_challenge_matrix_summary(root, template.name)
        if getattr(args, "json_output", False):
            print(json.dumps({
                "template": template.to_dict(),
                "qualification_summary": qualification_summary,
                "qualification_decision_summary": qualification_decision_summary,
                "qualification_adoption_summary": qualification_adoption_summary,
                "template_canary_summary": template_canary_summary,
                "canary_report_summary": canary_report_summary,
                "canary_ledger_summary": canary_ledger_summary,
                "canary_outcome_summary": canary_outcome_summary,
                "canary_review_summary": canary_review_summary,
                "challenge_matrix_summary": challenge_matrix_summary,
            }, indent=2, ensure_ascii=False))
            return
        print(render_template_lineage(root, template, qualification_summary))
        if qualification_decision_summary and qualification_decision_summary.get("latest_status"):
            print()
            print("Latest qualification decision:")
            print(f"  accepted: {'yes' if qualification_decision_summary.get('latest_status') == 'accepted' else 'no'}")
            print(f"  status  : {qualification_decision_summary.get('latest_status')}")
        if qualification_adoption_summary:
            print()
            print(render_qualification_adoption_summary(qualification_adoption_summary))
        if template_canary_summary:
            print()
            print(render_template_canary_summary(template_canary_summary))
        if canary_report_summary:
            print()
            print(render_canary_report_summary(canary_report_summary))
        if canary_ledger_summary:
            print()
            print(render_canary_ledger_summary(canary_ledger_summary))
        if canary_outcome_summary:
            print()
            print(render_canary_outcome_summary(canary_outcome_summary))
        if canary_review_summary:
            print()
            print(render_canary_review_summary(canary_review_summary))
        if challenge_matrix_summary:
            print()
            print(render_challenge_matrix_summary(challenge_matrix_summary))
        return

    if command in {"promote", "keep", "backup", "watch", "retire"}:
        try:
            decision = build_template_library_decision(
                root,
                str(getattr(args, "name")),
                command,
                source_ref=getattr(args, "source_ref", None),
                resolution=getattr(args, "resolution", None),
            )
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template library decision blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        recorded_path = TemplateLibraryDecisionStore().add(default_template_library_decisions_path(root), decision)
        policy_overlay, policy_path = build_and_save_template_library_policy_overlay(root)
        payload = {
            "status": "recorded",
            "decision": decision.to_dict(),
            "recorded_path": str(recorded_path.relative_to(root)).replace("\\", "/"),
            "policy_overlay": policy_overlay.to_dict(),
            "policy_overlay_path": str(policy_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_library_decision(decision, payload["recorded_path"]))
        return

    if command == "library-decisions":
        model = TemplateLibraryDecisionStore().load(default_template_library_decisions_path(root))
        if getattr(args, "json_output", False):
            print(json.dumps(model.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_template_library_decisions(model))
        return

    if command == "diff":
        try:
            report = TemplateDiffBuilder().build(root, str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateDiffStore().save(report, default_template_diff_path(root))
        payload = report.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_diff(report))
        if saved_path is not None:
            print()
            print("Saved:")
            print(f"  {saved_path.relative_to(root)}")
        return

    if command == "review":
        try:
            review = TemplateReviewBuilder().build(root, str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        saved_path = None
        if bool(getattr(args, "save", False)):
            saved_path = TemplateReviewStore().save(review, default_template_reviews_dir(root))
        payload = review.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_review(review))
        if saved_path is not None:
            print()
            print("Saved:")
            print(f"  {saved_path.relative_to(root)}")
        return

    if command in {"accept", "dismiss"}:
        try:
            decision = build_template_decision(
                root,
                str(getattr(args, "name")),
                status="accepted" if command == "accept" else "dismissed",
                resolution=getattr(args, "resolution", None),
            )
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template decision blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        recorded_path = TemplateDecisionStore().add(template_decisions_path, decision)
        payload = {
            "status": decision.status,
            "decision": decision.to_dict(),
            "recorded_path": str(recorded_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_decision(decision, payload["recorded_path"]))
        return

    if command == "decisions":
        model = TemplateDecisionStore().load(template_decisions_path)
        status_filter = getattr(args, "status", None)
        if getattr(args, "json_output", False):
            payload = model.to_dict()
            if status_filter:
                payload["decisions"] = [
                    decision
                    for decision in payload["decisions"]
                    if decision.get("status") == status_filter
                ]
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_decisions(model, status=status_filter))
        return

    if command == "export":
        try:
            out_arg = getattr(args, "out", None)
            exported_path = HarnessTemplateExporter().export(
                root,
                str(getattr(args, "name")),
                out_path=Path(str(out_arg)) if out_arg else None,
            )
            exported_payload = yaml.safe_load(exported_path.read_text(encoding="utf-8")) or {}
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template export blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {
            "status": "exported",
            "exported_path": str(exported_path),
            "template": exported_payload,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_export(exported_path, exported_payload))
        return

    if command == "import":
        try:
            record = HarnessTemplateImporter().import_template(
                root,
                Path(str(getattr(args, "file"))),
                as_name=getattr(args, "as_name", None),
            )
        except FileNotFoundError as exc:
            print(f"Template import file not found: {exc}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template import blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        imported_path = imported_template_record_path(root, record.name)
        payload = {
            "status": "imported",
            "record": record.to_dict(),
            "imported_path": str(imported_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_import(record, imported_path, root))
        return

    if command == "history":
        try:
            passport = TemplateHistoryBuilder().build_passport(root, str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        saved_path = TemplatePassportStore().save(passport, default_template_passport_path(root, passport.template_name))
        payload = passport.to_dict()
        payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_history(passport, limit=int(getattr(args, "limit", 12) or 12)))
        print()
        print("Saved:")
        print(f"  {saved_path.relative_to(root)}")
        return

    if command == "retrospective":
        try:
            retrospective = build_template_retrospective(
                root,
                str(getattr(args, "name")),
                str(getattr(args, "text")),
                rating=str(getattr(args, "rating", "good")),
                kind=str(getattr(args, "kind", "fit")),
                tags=list(getattr(args, "retrospective_tags", []) or []),
            )
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Template retrospective blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = TemplateRetrospectiveStore().add(retrospective, default_template_retrospectives_dir(root))
        payload = retrospective.to_dict()
        payload["saved_path"] = str(saved_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_template_retrospective_saved(retrospective, saved_path, root))
        return

    if command == "retrospectives":
        try:
            template = store.find(store.load(templates_path), str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Template not found: {exc.args[0]}\n\nRun:\n  cambrian template list", file=sys.stderr)
            sys.exit(1)
        retrospectives = TemplateRetrospectiveStore().list(default_template_retrospectives_dir(root), template.name)
        rating_filter = getattr(args, "rating", None)
        status_filter = getattr(args, "status", None)
        filtered = [
            item
            for item in retrospectives
            if (rating_filter is None or item.rating == rating_filter)
            and (status_filter is None or item.status == status_filter)
        ]
        if getattr(args, "json_output", False):
            print(json.dumps([item.to_dict() for item in filtered], indent=2, ensure_ascii=False))
            return
        print(render_template_retrospectives(retrospectives, template.name, rating=rating_filter, status=status_filter))
        return

    print("template 하위 명령이 필요합니다. 예: cambrian template save auth-bug-template", file=sys.stderr)
    sys.exit(1)


def _handle_bridge(args: argparse.Namespace) -> None:
    """AI bridge 명령을 처리한다."""
    from engine.project_bridge import (
        ProjectBridgeBuilder,
        ProjectBridgeReplyParser,
        ProjectBridgeStore,
        default_bridge_packet_path,
        default_bridge_reply_path,
        render_bridge_packet,
        render_bridge_packet_markdown,
        render_bridge_packet_prepared,
        render_bridge_reply,
        render_bridge_reply_ingested,
        resolve_bridge_packet_path,
        resolve_bridge_reply_path,
    )
    from engine.project_bridge_handoff import (
        BridgeHandoffStore,
        BridgeReplyHandoff,
        BridgeReplyReviewStore,
        BridgeReplyReviewer,
        default_bridge_handoff_path,
        default_bridge_review_path,
        load_bridge_reply_activity,
        render_bridge_handoff,
        render_bridge_reply_review,
    )
    from engine.project_bridge_checklists import (
        BridgeChecklistBuilder,
        BridgeChecklistStore,
        default_bridge_checklist_path,
        default_bridge_checklists_dir,
        load_bridge_checklist_activity,
        render_bridge_checklist,
        render_bridge_checklist_created,
        render_bridge_checklist_step_updated,
        render_bridge_checklists,
        resolve_bridge_checklist_path,
    )
    from engine.project_bridge_context import (
        BridgeContextHintBuilder,
        BridgeContextHintStore,
        default_bridge_context_hint_path,
        default_bridge_context_hints_dir,
        load_bridge_context_hint_activity,
        render_bridge_context_hint,
        render_bridge_context_hint_created,
        render_bridge_context_hints,
        resolve_bridge_context_hint_path,
    )
    from engine.project_bridge_materialize import (
        BridgeMaterializationStore,
        BridgeMaterializer,
        default_bridge_materialized_dir,
        default_bridge_materialized_path,
        load_bridge_materialization_activity,
        render_bridge_materialization_show,
        render_bridge_materializations,
        render_bridge_materialized,
        resolve_bridge_materialization_path,
    )
    from engine.project_bridge_resume import (
        BridgeSessionCoordinator,
        render_bridge_resume_hint,
        resolve_bridge_resume_target,
    )
    from engine.project_bridge_fastpath import (
        BridgeFastPathCoordinator,
        default_bridge_fastpath_path,
        load_bridge_fastpath_activity,
        render_bridge_fastpath,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "bridge_command", None)
    store = ProjectBridgeStore()

    if not command:
        print("bridge 하위 명령이 필요합니다. 예: cambrian bridge prepare \"로그인 에러 수정\"", file=sys.stderr)
        sys.exit(1)

    if command == "prepare":
        packet = ProjectBridgeBuilder().build_packet(
            root,
            str(getattr(args, "request", "")),
            session_ref=getattr(args, "session", None),
        )
        saved_path = store.save_packet(packet, default_bridge_packet_path(root, packet))
        saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
        payload = {
            "status": "prepared",
            "packet": packet.to_dict(),
            "saved_path": saved_ref,
        }
        try:
            from engine.project_pack_usage import safe_record_pack_usage_event

            safe_record_pack_usage_event(
                root,
                event_kind="used",
                surface_kind="bridge_prepare",
                request=packet.request,
                request_class=packet.request_intent,
                linked_bridge_packet_ref=saved_ref,
                summary="active pack used in bridge prepare",
            )
        except Exception as exc:
            logger.warning("pack usage bridge prepare event failed: %s", exc)
        if getattr(args, "format", "yaml") == "md":
            payload["markdown"] = render_bridge_packet_markdown(packet)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        if getattr(args, "format", "yaml") == "md":
            print(render_bridge_packet_markdown(packet))
            print()
            print("Saved:")
            print(f"  {saved_ref}")
            return
        print(render_bridge_packet_prepared(packet, saved_ref))
        try:
            from engine.project_pack_activation import current_active_pack, render_active_pack_bridge_hint

            hint = render_active_pack_bridge_hint(current_active_pack(root))
            if hint:
                print(hint)
        except Exception as exc:
            logger.warning("active pack bridge hint failed: %s", exc)
        return

    if command == "show":
        try:
            packet_path = resolve_bridge_packet_path(root, str(getattr(args, "packet_ref")))
            packet = store.load_packet(packet_path)
        except FileNotFoundError as exc:
            print(f"Bridge packet not found: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(packet.to_dict(), indent=2, ensure_ascii=False))
            return
        if getattr(args, "format", "text") == "md":
            print(render_bridge_packet_markdown(packet))
            return
        print(render_bridge_packet(packet))
        return

    if command == "paste":
        text = sys.stdin.read()
        if not text.strip():
            print("Bridge paste blocked: stdin reply text is empty", file=sys.stderr)
            sys.exit(1)
        record = BridgeFastPathCoordinator().run_text(
            root,
            text,
            packet_ref=getattr(args, "packet", None),
            session_ref=getattr(args, "session", None),
        )
        saved_path = default_bridge_fastpath_path(root, record)
        saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
        payload = record.to_dict()
        payload["saved_path"] = saved_ref
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(render_bridge_fastpath(record, saved_ref))
        if record.status == "blocked" or record.errors:
            sys.exit(1)
        return

    if command == "ingest":
        source_path = Path(str(getattr(args, "file"))).expanduser()
        if not source_path.is_absolute():
            source_path = root / source_path
        if not source_path.exists():
            print(f"Bridge reply file not found: {source_path}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "auto_route", False):
            record = BridgeFastPathCoordinator().run_file(
                root,
                source_path,
                packet_ref=getattr(args, "packet", None),
                session_ref=getattr(args, "session", None),
            )
            saved_path = default_bridge_fastpath_path(root, record)
            saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
            payload = record.to_dict()
            payload["saved_path"] = saved_ref
            if getattr(args, "json_output", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(render_bridge_fastpath(record, saved_ref))
            if record.status == "blocked" or record.errors:
                sys.exit(1)
            return
        try:
            reply = ProjectBridgeReplyParser().parse_reply(source_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"Bridge reply blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        packet_ref = getattr(args, "packet", None)
        if packet_ref:
            try:
                packet_path = resolve_bridge_packet_path(root, str(packet_ref))
                packet = store.load_packet(packet_path)
            except FileNotFoundError as exc:
                print(f"Bridge packet not found: {exc}", file=sys.stderr)
                sys.exit(1)
            reply.packet_id = packet.packet_id
            reply.project_name = packet.project_name
            reply.request = packet.request
            reply.linked_request_ref = str(packet_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "session", None):
            reply.linked_session_id = str(getattr(args, "session"))
        try:
            reply.source_reply_path = str(source_path.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            reply.source_reply_path = str(source_path.resolve())
        if reply.errors:
            if getattr(args, "json_output", False):
                print(
                    json.dumps(
                        {"status": "blocked", "errors": reply.errors, "reply": reply.to_dict()},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print("Bridge reply blocked:", file=sys.stderr)
                for error in reply.errors:
                    print(f"  - {error}", file=sys.stderr)
            sys.exit(1)
        saved_path = store.save_reply(reply, default_bridge_reply_path(root, reply))
        saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
        payload = {
            "status": "ingested",
            "reply": reply.to_dict(),
            "saved_path": saved_ref,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bridge_reply_ingested(reply, saved_ref))
        return

    if command == "reply-show":
        try:
            reply_path = resolve_bridge_reply_path(root, str(getattr(args, "reply_ref")))
            reply = store.load_reply(reply_path)
        except FileNotFoundError as exc:
            print(f"Bridge reply not found: {exc}", file=sys.stderr)
            sys.exit(1)
        activity = load_bridge_reply_activity(root, reply.reply_id)
        activity.update(load_bridge_materialization_activity(root, reply.reply_id))
        activity.update(load_bridge_context_hint_activity(root, reply_id=reply.reply_id))
        activity.update(load_bridge_checklist_activity(root, reply_id=reply.reply_id))
        activity.update(load_bridge_fastpath_activity(root, reply_id=reply.reply_id))
        if getattr(args, "json_output", False):
            payload = reply.to_dict()
            payload["activity"] = activity
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bridge_reply(reply, activity=activity))
        return

    if command == "review":
        try:
            reply_path = resolve_bridge_reply_path(root, str(getattr(args, "reply_ref")))
        except FileNotFoundError as exc:
            print(f"Bridge reply not found: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            review = BridgeReplyReviewer().review(root, reply_path)
        except ValueError as exc:
            print(f"Bridge reply review blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_ref = None
        if getattr(args, "save", False):
            saved_path = BridgeReplyReviewStore().save(review, default_bridge_review_path(root, review))
            saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
        payload = review.to_dict()
        if saved_ref:
            payload["saved_path"] = saved_ref
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bridge_reply_review(review, saved_path=saved_ref))
        return

    if command == "resume":
        try:
            target_path = resolve_bridge_resume_target(root, str(getattr(args, "reply_ref")))
        except FileNotFoundError as exc:
            print(f"Bridge resume target not found: {exc}", file=sys.stderr)
            sys.exit(1)
        hint = BridgeSessionCoordinator().build_resume_hint(root, target_path)
        if getattr(args, "json_output", False):
            print(json.dumps(hint.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_bridge_resume_hint(hint))
        return

    if command == "materialize":
        try:
            reply_path = resolve_bridge_reply_path(root, str(getattr(args, "reply_ref")))
        except FileNotFoundError as exc:
            print(f"Bridge reply not found: {exc}", file=sys.stderr)
            sys.exit(1)
        record = BridgeMaterializer().materialize(
            root,
            reply_path,
            as_kind=getattr(args, "materialization_kind", None),
        )
        if record.errors:
            if getattr(args, "json_output", False):
                print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            else:
                print(render_bridge_materialized(record), file=sys.stderr)
            sys.exit(1)
        saved_path = BridgeMaterializationStore().save_record(record, default_bridge_materialized_path(root, record))
        saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
        payload = record.to_dict()
        payload["saved_path"] = saved_ref
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bridge_materialized(record, saved_ref))
        return

    if command == "materialize-show":
        try:
            materialization_path = resolve_bridge_materialization_path(root, str(getattr(args, "materialization_ref")))
            record = BridgeMaterializationStore().load_record(materialization_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Bridge materialization not found: {exc}", file=sys.stderr)
            sys.exit(1)
        activity = load_bridge_context_hint_activity(root, materialization_id=record.materialization_id)
        activity.update(load_bridge_checklist_activity(root, materialization_id=record.materialization_id))
        if getattr(args, "json_output", False):
            payload = record.to_dict()
            payload["activity"] = activity
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bridge_materialization_show(record, activity=activity))
        return

    if command == "materializations":
        records = BridgeMaterializationStore().list_records(default_bridge_materialized_dir(root))
        kind_filter = getattr(args, "kind", None)
        filtered = [record for record in records if kind_filter is None or record.materialization_kind == kind_filter]
        limit = int(getattr(args, "limit", 10) or 10)
        if getattr(args, "json_output", False):
            print(json.dumps([record.to_dict() for record in filtered[:limit]], indent=2, ensure_ascii=False))
            return
        print(render_bridge_materializations(records, kind=kind_filter, limit=limit))
        return

    if command == "context-hints":
        hints = BridgeContextHintStore().list_hints(default_bridge_context_hints_dir(root))
        limit = int(getattr(args, "limit", 10) or 10)
        if getattr(args, "json_output", False):
            print(json.dumps([hint.to_dict() for hint in hints[:limit]], indent=2, ensure_ascii=False))
            return
        print(render_bridge_context_hints(hints, limit=limit))
        return

    if command == "context-hint-show":
        try:
            hint_path = resolve_bridge_context_hint_path(root, str(getattr(args, "hint_ref")))
            hint = BridgeContextHintStore().load_hint(hint_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Bridge context hint not found: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(hint.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_bridge_context_hint(hint))
        return

    if command == "checklists":
        checklists = BridgeChecklistStore().list(default_bridge_checklists_dir(root))
        status_filter = getattr(args, "status", None)
        filtered = [item for item in checklists if status_filter is None or item.overall_status == status_filter]
        limit = int(getattr(args, "limit", 10) or 10)
        if getattr(args, "json_output", False):
            print(json.dumps([item.to_dict() for item in filtered[:limit]], indent=2, ensure_ascii=False))
            return
        print(render_bridge_checklists(checklists, status=status_filter, limit=limit))
        return

    if command == "checklist-show":
        try:
            checklist_path = resolve_bridge_checklist_path(root, str(getattr(args, "checklist_ref")))
            checklist = BridgeChecklistStore().load(checklist_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Bridge checklist not found: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(checklist.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_bridge_checklist(checklist))
        return

    if command == "checklist-step":
        flags = [
            ("done", bool(getattr(args, "done", False))),
            ("blocked", bool(getattr(args, "blocked", False))),
            ("skipped", bool(getattr(args, "skip", False))),
            ("todo", bool(getattr(args, "todo", False))),
        ]
        selected = [status for status, enabled in flags if enabled]
        if len(selected) != 1:
            print("Exactly one step status flag is required: --done/--blocked/--skip/--todo", file=sys.stderr)
            sys.exit(1)
        try:
            checklist_path = resolve_bridge_checklist_path(root, str(getattr(args, "checklist_ref")))
            BridgeChecklistStore().update_step(
                checklist_path,
                str(getattr(args, "step_id")),
                selected[0],
                note=getattr(args, "note", None),
            )
            checklist = BridgeChecklistStore().load(checklist_path)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            print(f"Bridge checklist step update blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_ref = str(checklist_path.relative_to(root)).replace("\\", "/")
        if getattr(args, "json_output", False):
            payload = checklist.to_dict()
            payload["saved_path"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_bridge_checklist_step_updated(checklist, str(getattr(args, "step_id")), saved_ref))
        return

    if command == "handoff":
        handoff_kind = str(getattr(args, "handoff_kind", "") or "")
        target_ref = str(getattr(args, "handoff_ref"))
        if handoff_kind == "patch_intent":
            try:
                reply_path = resolve_bridge_reply_path(root, target_ref)
            except FileNotFoundError as exc:
                print(f"Bridge reply not found: {exc}", file=sys.stderr)
                sys.exit(1)
            record = BridgeReplyHandoff().to_patch_intent(root, reply_path)
            saved_path = BridgeHandoffStore().save(record, default_bridge_handoff_path(root, record))
            saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
            link_payload = None
            if record.status == "created":
                try:
                    link = BridgeSessionCoordinator().ensure_linked_session(
                        root,
                        reply_path,
                        record,
                        patch_intent_ref=record.target_artifact_ref,
                        explicit_session_ref=getattr(args, "session", None),
                    )
                except (FileNotFoundError, ValueError) as exc:
                    print(f"Bridge session link blocked: {exc}", file=sys.stderr)
                    sys.exit(1)
                link_payload = link.to_dict()
            payload = record.to_dict()
            payload["saved_path"] = saved_ref
            if link_payload:
                payload["bridge_link"] = link_payload
            if getattr(args, "json_output", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                if record.status != "created":
                    sys.exit(1)
                return
            print(render_bridge_handoff(record, saved_path=saved_ref))
            if link_payload:
                print()
                print("Linked session:")
                print(f"  {link_payload.get('session_id')}")
                print()
                print("Next:")
                for command_text in link_payload.get("next_commands", [])[:2]:
                    print(f"  {command_text}")
            if record.status != "created":
                sys.exit(1)
            return

        if handoff_kind == "context_hint":
            try:
                materialization_path = resolve_bridge_materialization_path(root, target_ref)
                hint = BridgeContextHintBuilder().from_materialization(root, materialization_path)
                saved_path = BridgeContextHintStore().save_hint(hint, default_bridge_context_hint_path(root, hint))
            except (FileNotFoundError, ValueError) as exc:
                print(f"Bridge context hint handoff blocked: {exc}", file=sys.stderr)
                sys.exit(1)
            saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
            payload = hint.to_dict()
            payload["saved_path"] = saved_ref
            if getattr(args, "json_output", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return
            print(render_bridge_context_hint_created(hint, saved_ref))
            return

        if handoff_kind == "checklist":
            try:
                materialization_path = resolve_bridge_materialization_path(root, target_ref)
                checklist = BridgeChecklistBuilder().from_materialization(
                    root,
                    materialization_path,
                    session_ref=getattr(args, "session", None),
                )
                saved_path = BridgeChecklistStore().save(checklist, default_bridge_checklist_path(root, checklist))
            except (FileNotFoundError, ValueError) as exc:
                print(f"Bridge checklist handoff blocked: {exc}", file=sys.stderr)
                sys.exit(1)
            saved_ref = str(saved_path.relative_to(root)).replace("\\", "/")
            payload = checklist.to_dict()
            payload["saved_path"] = saved_ref
            if getattr(args, "json_output", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return
            print(render_bridge_checklist_created(checklist, saved_ref))
            return

    print("bridge 하위 명령이 올바르지 않습니다. 예: cambrian bridge prepare \"로그인 에러 수정\"", file=sys.stderr)
    sys.exit(1)


def _handle_install(args: argparse.Namespace) -> None:
    """cambrian install 처리."""
    from engine.project_pack_lifecycle import (
        PackDiffBuilder,
        PackUpdater,
        render_pack_diff,
        render_pack_update,
        save_pack_diff,
    )
    from engine.project_pack_trust import (
        PackVerifier,
        render_installed_verify_reports,
        render_pack_verify,
        save_pack_verification,
    )
    from engine.project_pack_install import (
        IncompatibleHarnessError,
        InstalledPackStore,
        PackInstaller,
        build_install_doctor_report,
        default_installed_packs_path,
        render_install_doctor,
        render_install_plan,
        render_install_result,
        render_installed_pack_list,
        render_installed_pack_show,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "install_command", None)
    if command is None:
        print("install 하위 명령이 필요합니다. 예: cambrian install manifest <path>", file=sys.stderr)
        sys.exit(1)

    if command == "plan":
        from engine.project_pack_dependencies import (
            PackDependencyResolver,
            render_install_graph,
            save_install_graph,
        )

        graph = PackDependencyResolver().resolve(
            root,
            str(getattr(args, "pack_ref")),
            registry_name=getattr(args, "registry", None),
            version=getattr(args, "version", None),
            include_deps=not bool(getattr(args, "no_deps", False)),
        )
        if getattr(args, "save", False):
            save_install_graph(root, graph)
        if getattr(args, "json_output", False):
            print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_install_graph(graph))
        if not graph.safe_to_install:
            sys.exit(1)
        return

    if command == "manifest":
        installer = PackInstaller()
        try:
            plan = installer.install(
                root,
                Path(str(getattr(args, "path"))),
                dry_run=bool(getattr(args, "dry_run", False)),
                source_kind_override="local_file",
                source_ref_override=str(Path(str(getattr(args, "path"))).resolve()),
                require_trusted=bool(getattr(args, "require_trusted", False)),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack install blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = plan.to_dict()
        payload["dry_run"] = bool(getattr(args, "dry_run", False))
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            if getattr(args, "dry_run", False):
                print(render_install_plan(plan))
            elif plan.safe_to_install:
                print(render_install_result(plan))
            else:
                print(render_install_plan(plan), file=sys.stderr)
        if not plan.safe_to_install:
            sys.exit(1)
        return

    if command == "pack":
        from engine.project_pack_dependencies import (
            PackDependencyGraphInstaller,
            PackDependencyResolver,
            render_graph_install_result,
            render_install_graph,
            save_install_graph,
        )

        pack_ref_text = str(getattr(args, "pack_ref"))
        registry_name = getattr(args, "registry", None)
        graph = PackDependencyResolver().resolve(
            root,
            pack_ref_text,
            registry_name=str(registry_name) if registry_name else None,
            version=getattr(args, "version", None),
            include_deps=not bool(getattr(args, "no_deps", False)),
        )
        graph_has_dependencies = len(graph.install_order) > 1 or any(node.dependencies for node in graph.nodes)
        explicit_graph_ref = "/" in pack_ref_text or "@" in pack_ref_text or bool(getattr(args, "version", None))
        force_graph_path = graph_has_dependencies or explicit_graph_ref or bool(getattr(args, "confirm_deps", False)) or bool(getattr(args, "no_deps", False))
        ambiguous_conflict = any("ambiguous" in item for item in graph.conflicts)
        if graph.conflicts and (force_graph_path or ambiguous_conflict):
            if getattr(args, "json_output", False):
                print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False))
            else:
                print(render_install_graph(graph), file=sys.stderr)
            sys.exit(1)
        if force_graph_path:
            if not graph.safe_to_install:
                if getattr(args, "json_output", False):
                    print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False))
                else:
                    print(render_install_graph(graph), file=sys.stderr)
                sys.exit(1)
            if graph_has_dependencies and not getattr(args, "confirm_deps", False):
                if getattr(args, "json_output", False):
                    payload = graph.to_dict()
                    payload["requires_confirm_deps"] = True
                    print(json.dumps(payload, indent=2, ensure_ascii=False))
                else:
                    print(render_install_graph(graph))
                    print()
                    print("Next:")
                    print(f"  cambrian install pack {pack_ref_text} --confirm-deps")
                if not getattr(args, "dry_run", False):
                    sys.exit(1)
                return
            if getattr(args, "dry_run", False):
                if getattr(args, "json_output", False):
                    print(json.dumps(graph.to_dict(), indent=2, ensure_ascii=False))
                else:
                    print(render_install_graph(graph))
                return
            graph_ref = save_install_graph(root, graph)
            result = PackDependencyGraphInstaller().install(
                root,
                graph,
                dry_run=False,
                require_trusted=bool(getattr(args, "require_trusted", False)),
                graph_ref=graph_ref,
            )
            if getattr(args, "json_output", False):
                print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            else:
                print(render_graph_install_result(result))
            if result.errors:
                sys.exit(1)
            return
        if registry_name:
            from engine.project_pack_registry import RegistryPackInstaller

            try:
                pack, manifest_path, plan = RegistryPackInstaller().install(
                    root,
                    pack_ref_text,
                    str(registry_name),
                    dry_run=bool(getattr(args, "dry_run", False)),
                    require_trusted=bool(getattr(args, "require_trusted", False)),
                )
            except (KeyError, FileNotFoundError, ValueError) as exc:
                print(f"Pack install blocked: {exc}", file=sys.stderr)
                sys.exit(1)
            payload = plan.to_dict()
            payload["dry_run"] = bool(getattr(args, "dry_run", False))
            payload["registry_name"] = pack.registry_name
            payload["registry_source_ref"] = pack.registry_source_ref
            payload["manifest_path"] = _relative_cli(manifest_path, root)
            payload["manifest_sha256"] = pack.manifest_sha256
            if getattr(args, "json_output", False):
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print("Installing pack from static registry.")
                print()
                print("Pack:")
                print(f"  {pack.pack_id}")
                print()
                print("Registry:")
                print(f"  {pack.registry_name}")
                print()
                print("Manifest:")
                print(f"  {payload['manifest_path']}")
                print()
                print("Integrity:")
                print(f"  sha256: {pack.manifest_sha256 or 'unknown'}")
                print()
                if getattr(args, "dry_run", False):
                    print(render_install_plan(plan))
                elif plan.safe_to_install:
                    print(render_install_result(plan))
                else:
                    print(render_install_plan(plan), file=sys.stderr)
            if not plan.safe_to_install:
                sys.exit(1)
            return

        from engine.project_pack_catalog import (
            PackCatalogResolver,
            PackFitAnalyzer,
            default_pack_catalog_path,
            load_default_catalog,
            local_catalog_source_ref,
        )

        repo_root = Path(__file__).resolve().parents[1]
        catalog = load_default_catalog(repo_root)
        if catalog.errors:
            print(f"Pack catalog blocked: {catalog.errors[0]}", file=sys.stderr)
            sys.exit(1)
        resolver = PackCatalogResolver()
        try:
            entry = resolver.find_entry(catalog, pack_ref_text)
            manifest_path = resolver.resolve_manifest_path(repo_root, entry)
            fit = PackFitAnalyzer().analyze(root, entry)
            plan = PackInstaller().install(
                root,
                manifest_path,
                dry_run=bool(getattr(args, "dry_run", False)),
                source_kind_override="local_catalog",
                source_ref_override=local_catalog_source_ref(repo_root, entry),
                expected_sha256=entry.manifest_sha256,
                require_trusted=bool(getattr(args, "require_trusted", False)),
                trust_level_override=entry.trust_level,
            )
        except IncompatibleHarnessError as exc:
            if getattr(args, "json_output", False):
                print(json.dumps(exc.to_dict(), indent=2, ensure_ascii=False))
            else:
                issue = exc.issue
                print(f"Cannot install {issue.pack} for this project.", file=sys.stderr)
                print("", file=sys.stderr)
                print("Reason:", file=sys.stderr)
                print(
                    f"  {issue.pack} supports {issue.required.get('language') or 'unknown'} + {issue.required.get('test_framework') or 'unknown'}.",
                    file=sys.stderr,
                )
                print(
                    f"  Current project appears to be {issue.detected.get('language') or 'unknown'} + {issue.detected.get('test_framework') or 'unknown'}.",
                    file=sys.stderr,
                )
                if issue.recommended_harness:
                    print("", file=sys.stderr)
                    print("Recommended:", file=sys.stderr)
                    for command_text in issue.next_commands:
                        print(f"  {command_text}", file=sys.stderr)
            sys.exit(1)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack install blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = plan.to_dict()
        payload["dry_run"] = bool(getattr(args, "dry_run", False))
        payload["catalog_ref"] = f"{_relative_cli(default_pack_catalog_path(repo_root), repo_root)}#{entry.pack_id}"
        payload["manifest_path"] = _relative_cli(manifest_path, repo_root)
        payload["fit"] = fit.to_dict()
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("Installing pack from local catalog.")
            print()
            print("Pack:")
            print(f"  {entry.pack_id}")
            print()
            print("Manifest:")
            print(f"  {payload['manifest_path']}")
            print()
            print("Fit:")
            print(f"  {fit.fit_status}")
            print()
            if getattr(args, "dry_run", False):
                print(render_install_plan(plan))
            elif plan.safe_to_install:
                print(render_install_result(plan))
            else:
                print(render_install_plan(plan), file=sys.stderr)
        if not plan.safe_to_install:
            sys.exit(1)
        return

    if command == "diff":
        try:
            report = PackDiffBuilder().build(
                root,
                str(getattr(args, "pack_ref")),
                Path(str(getattr(args, "manifest"))) if getattr(args, "manifest", None) else None,
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack diff blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "save", False):
            save_pack_diff(root, report)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_diff(report))
        if not report.safe_to_update:
            sys.exit(1)
        return

    if command == "update":
        incoming_manifest = Path(str(getattr(args, "manifest"))) if getattr(args, "manifest", None) else None
        if not bool(getattr(args, "confirm", False)) or bool(getattr(args, "dry_run", False)):
            try:
                report = PackDiffBuilder().build(root, str(getattr(args, "pack_ref")), incoming_manifest)
            except (KeyError, FileNotFoundError, ValueError) as exc:
                print(f"Pack update blocked: {exc}", file=sys.stderr)
                sys.exit(1)
            if getattr(args, "json_output", False):
                payload = report.to_dict()
                payload["preview_only"] = True
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return
            print(render_pack_diff(report))
            print()
            print("Update preview only. 실제 업데이트는 --confirm이 필요합니다.")
            if not report.safe_to_update:
                sys.exit(1)
            return
        try:
            record = PackUpdater().update(
                root,
                str(getattr(args, "pack_ref")),
                incoming_manifest_path=incoming_manifest,
                confirm=True,
                require_trusted=bool(getattr(args, "require_trusted", False)),
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack update blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_update(record))
        if record.status != "updated":
            sys.exit(1)
        return

    if command == "verify":
        verifier = PackVerifier()
        pack_ref = getattr(args, "pack_ref", None)
        try:
            if pack_ref:
                reports = [verifier.verify_installed_pack(root, str(pack_ref))]
            else:
                reports = verifier.verify_all_installed(root)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Install verify blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "save", False):
            for report in reports:
                save_pack_verification(root, report)
        if getattr(args, "json_output", False):
            print(json.dumps([report.to_dict() for report in reports], indent=2, ensure_ascii=False))
            return
        if pack_ref and reports:
            print(render_pack_verify(reports[0]))
        else:
            print(render_installed_verify_reports(reports))
        if any(report.status == "failed" for report in reports):
            sys.exit(1)
        return

    store = InstalledPackStore()
    index = store.load(default_installed_packs_path(root))
    if command == "list":
        if getattr(args, "json_output", False):
            print(json.dumps(index.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_installed_pack_list(index))
        return

    if command == "show":
        try:
            record = store.find(index, str(getattr(args, "pack_ref")))
        except KeyError as exc:
            print(f"Installed pack not found: {exc.args[0]}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_installed_pack_show(record))
        return

    if command == "doctor":
        report = build_install_doctor_report(root)
        if getattr(args, "json_output", False):
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return
        print(render_install_doctor(report))
        if report.get("errors"):
            sys.exit(1)
        return

    print("알 수 없는 install 하위 명령입니다.", file=sys.stderr)
    sys.exit(1)


def _handle_uninstall(args: argparse.Namespace) -> None:
    """cambrian uninstall 처리."""
    from engine.project_pack_lifecycle import (
        PackUninstallPlanner,
        PackUninstaller,
        render_uninstall_plan,
        render_uninstall_record,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "uninstall_command", None)
    if command is None:
        print("uninstall 하위 명령이 필요합니다. 예: cambrian uninstall pack <pack-id>", file=sys.stderr)
        sys.exit(1)
    if command != "pack":
        print("알 수 없는 uninstall 하위 명령입니다.", file=sys.stderr)
        sys.exit(1)

    pack_ref = str(getattr(args, "pack_ref"))
    if not bool(getattr(args, "confirm", False)):
        try:
            plan = PackUninstallPlanner().build_plan(root, pack_ref)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack uninstall blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["preview_only"] = True
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_uninstall_plan(plan))
        print()
        print("Uninstall preview only. 실제 제거는 --confirm이 필요합니다.")
        return

    try:
        record = PackUninstaller().uninstall(
            root,
            pack_ref,
            confirm=True,
            force=bool(getattr(args, "force", False)),
        )
    except (KeyError, FileNotFoundError, ValueError) as exc:
        print(f"Pack uninstall blocked: {exc}", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "json_output", False):
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return
    print(render_uninstall_record(record))
    if record.status != "uninstalled":
        sys.exit(1)


def _handle_registry(args: argparse.Namespace) -> None:
    """cambrian registry 처리."""
    from engine.project_pack_registry import (
        PackRegistryStore,
        PackRegistrySyncer,
        create_registry_source,
        default_registry_index_path,
        registry_payload,
        render_registry_added,
        render_registry_list,
        render_registry_sync,
    )
    from engine.project_pack_registry_export import (
        RegistryBundleChecker,
        RegistryBundleExporter,
        render_registry_export,
        render_registry_export_check,
    )

    root = Path.cwd().resolve()
    command = getattr(args, "registry_command", None)
    if command is None:
        print("registry 하위 명령이 필요합니다. 예: cambrian registry add local-web web/assets/catalog.json", file=sys.stderr)
        sys.exit(1)

    store = PackRegistryStore()
    index_path = default_registry_index_path(root)

    if command == "export":
        bundle = RegistryBundleExporter().export(
            root,
            Path(str(getattr(args, "out"))),
            registry_name=getattr(args, "registry_name", None),
            namespace=getattr(args, "namespace", None),
            include_unproven=bool(getattr(args, "include_unproven", False)),
        )
        if getattr(args, "json_output", False):
            print(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_registry_export(bundle))
        if bundle.status != "exported":
            sys.exit(1)
        return

    if command == "export-check":
        report = RegistryBundleChecker().check(Path(str(getattr(args, "bundle_dir"))))
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_registry_export_check(report))
        if report.status == "failed":
            sys.exit(1)
        return

    if command == "add":
        source = create_registry_source(
            str(getattr(args, "name")),
            str(getattr(args, "source_ref")),
            trust_level=getattr(args, "trust_level", None),
        )
        store.add(index_path, source)
        if getattr(args, "json_output", False):
            print(json.dumps(source.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_registry_added(source))
        return

    if command == "list":
        index = store.load(index_path)
        if getattr(args, "json_output", False):
            print(json.dumps(registry_payload(index), indent=2, ensure_ascii=False))
            return
        print(render_registry_list(index))
        return

    if command == "sync":
        report = PackRegistrySyncer().sync(root, str(getattr(args, "name")))
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_registry_sync(report))
        if report.status != "synced":
            sys.exit(1)
        return

    print("알 수 없는 registry 하위 명령입니다.", file=sys.stderr)
    sys.exit(1)


def _handle_pack(args: argparse.Namespace) -> None:
    """cambrian pack 처리."""
    root = Path.cwd().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    command = getattr(args, "pack_command", None)
    if command is None:
        print("pack 하위 명령이 필요합니다. 예: cambrian pack list", file=sys.stderr)
        sys.exit(1)

    launch_commands = {
        "list",
        "show",
        "doctor",
        "readiness",
        "start",
        "job-paste",
        "job-ingest",
        "job-validate",
        "activate",
        "active",
        "next",
        "proof",
    }
    if command in launch_commands:
        _handle_pack_launch_path(args, root, repo_root, command)
        return

    from engine.project_pack_authoring import (
        PackBuilder,
        PackDraftBuilder,
        PackLocalPublisher,
        PackValidator,
        load_pack_draft,
        render_pack_built,
        render_pack_draft_created,
        render_pack_publish,
        render_pack_validate,
        resolve_draft_path,
        save_pack_draft,
    )
    from engine.project_pack_catalog import (
        PackCatalogResolver,
        PackFitAnalyzer,
        default_pack_catalog_path,
        best_recommendation,
        catalog_payload,
        load_default_catalog,
        manifest_for_entry,
        render_pack_list,
        render_pack_recommend,
        render_pack_show,
    )
    from engine.project_pack_trust import PackVerifier, render_pack_verify, save_pack_verification
    from engine.project_pack_release import (
        PackReleaseChecker,
        PackWebSyncer,
        render_pack_release_report,
        render_pack_web_sync,
        save_pack_release_report,
    )
    from engine.project_pack_proof import (
        PackProofBuilder,
        PackProofStore,
        latest_pack_proof_card,
        render_pack_proof_card,
        render_pack_proof_compact,
        resolve_pack_proof_path,
        save_pack_proof_card,
    )
    from engine.project_pack_proof_export import (
        PackProofExportStore,
        PackProofExporter,
        render_pack_proof_export,
        resolve_pack_proof_export_path,
    )
    from engine.project_pack_registry import (
        PackRegistryResolver,
        SyncedRegistryPack,
        pack_search_payload,
        registry_pack_show_payload,
        render_pack_search,
        render_registry_pack_show,
    )
    from engine.project_pack_activation import (
        PackActivationStore,
        PackActivator,
        PackNextGuideBuilder,
        current_active_pack,
        default_active_pack_path,
        render_active_pack,
        render_pack_activated,
        render_pack_deactivated,
        render_pack_next,
    )
    from engine.project_pack_usage import (
        PackOutcomeLinkBuilder,
        PackUsageEventStore,
        PackUsageSummaryBuilder,
        PackUsageSummaryStore,
        default_usage_events_dir,
        default_usage_summary_path,
        render_pack_events,
        render_pack_outcomes,
        render_pack_usage,
        render_pack_usage_compact,
        safe_record_pack_usage_event,
        safe_record_pack_usage_from_context,
        save_pack_outcome_links,
    )
    from engine.project_pack_readiness import (
        PackReadinessBuilder,
        latest_pack_readiness,
        render_pack_readiness,
        render_pack_readiness_compact,
        save_pack_readiness_report,
    )
    from engine.project_pack_setup import (
        PackSetupApplier,
        PackSetupPlanner,
        PackSetupStore,
        latest_pack_setup_plan,
        render_pack_setup_compact,
        render_pack_setup_plan,
        render_pack_setup_prompt,
        render_pack_setup_run,
        resolve_pack_setup_plan_path,
        save_pack_setup_plan,
    )
    from engine.project_pack_jobs import (
        PackJobNextBuilder,
        PackJobStarter,
        PackJobStore,
        default_pack_jobs_dir,
        render_pack_job,
        render_pack_job_next,
        render_pack_job_started,
        render_pack_jobs,
        resolve_pack_job_path,
    )
    from engine.project_pack_job_reply import (
        PackJobReplyHandler,
        PackJobValidator,
        render_pack_job_reply_result,
        render_pack_job_validation_result,
    )
    from engine.project_pack_job_apply import (
        PackJobAdoptionHandler,
        PackJobApplyHandler,
        render_pack_job_adoption_record,
        render_pack_job_apply_preview,
        render_pack_job_apply_record,
    )
    from engine.project_pack_retrospective import (
        PackJobRetrospectiveBuilder,
        PackRetrospectiveStore,
        PackRetrospectiveSummaryBuilder,
        default_job_retrospectives_dir,
        latest_pack_retro_summary,
        render_pack_job_retrospective,
        render_pack_retro_summary,
        render_pack_retro_summary_compact,
        render_pack_retrospectives,
        save_pack_job_retrospective,
        save_pack_retro_summary,
    )
    from engine.project_pack_improvements import (
        PackImprovementQueueBuilder,
        PackImprovementStore,
        default_pack_improvement_items_dir,
        default_pack_improvement_queue_path,
        latest_pack_improvement_queue,
        record_pack_improvement_decision,
        render_pack_improvement_decision,
        render_pack_improvement_compact,
        render_pack_improvement_item,
        render_pack_improvement_queue,
        render_pack_improvements,
        save_pack_improvement_queue,
        resolve_pack_improvement_item_path,
    )
    from engine.project_pack_derivatives import (
        PackDerivativeCreator,
        PackDerivativePlanner,
        PackDerivativeStore,
        latest_pack_derivative_plan,
        render_pack_derivative_compact,
        render_pack_derivative_plan,
        render_pack_derivative_workspace,
        resolve_pack_derivative_plan_path,
        save_pack_derivative_plan,
        save_pack_derivative_workspace,
    )
    from engine.project_pack_vnext_workbench import (
        PackVNextWorkbenchBuilder,
        PackWorkOrderStore,
        default_pack_vnext_workorders_dir,
        latest_pack_vnext_workbench,
        record_pack_workorder_decision,
        render_pack_vnext_compact,
        render_pack_vnext_workbench,
        render_pack_workorder,
        render_pack_workorder_decision,
        render_pack_workorders,
        resolve_pack_workorder_path,
        save_pack_vnext_workbench,
    )
    from engine.project_pack_release_candidate import (
        PackLocalReleaser,
        PackReleaseCandidateBuilder,
        PackReleaseCandidateStore,
        latest_pack_local_release,
        latest_pack_rc,
        release_check_target_from_rc,
        render_pack_local_release,
        render_pack_rc,
        render_pack_rc_compact,
        render_status_pack_rc,
        resolve_pack_rc_path,
        save_pack_local_release,
        save_pack_rc,
    )
    from engine.project_pack_rollout import (
        PackRolloutApplier,
        PackRolloutPlanner,
        PackRolloutStore,
        latest_pack_rollout,
        render_pack_rollout_apply_record,
        render_pack_rollout_compact,
        render_pack_rollout_plan,
        render_pack_upgrade_available,
        resolve_pack_rollout_path,
        save_pack_rollout_apply_record,
        save_pack_rollout_plan,
    )

    if command == "draft":
        refs = {
            "workers": getattr(args, "workers", []),
            "teams": getattr(args, "teams", []),
            "templates": getattr(args, "templates", []),
            "benchmarks": getattr(args, "benchmarks", []),
            "lane": getattr(args, "lane_ref", None),
        }
        draft = PackDraftBuilder().create(
            root,
            str(getattr(args, "pack_id")),
            str(getattr(args, "kind")),
            refs,
            pack_name=getattr(args, "pack_name", None),
            version=getattr(args, "version", None),
            description=getattr(args, "description", None),
            tags=list(getattr(args, "tags", []) or []),
        )
        draft_ref = save_pack_draft(root, draft)
        if getattr(args, "json_output", False):
            payload = draft.to_dict()
            payload["draft_ref"] = draft_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_draft_created(draft, draft_ref))
        if draft.errors:
            sys.exit(1)
        return

    if command == "validate":
        target = str(getattr(args, "target"))
        try:
            target_path = Path(target)
            if not target_path.exists():
                target_path = resolve_draft_path(root, target)
            payload = yaml.safe_load(target_path.read_text(encoding="utf-8")) or {}
            if isinstance(payload, dict) and payload.get("draft_id"):
                report = PackValidator().validate_draft(root, load_pack_draft(target_path))
            else:
                report = PackValidator().validate_manifest(root, target_path)
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            print(f"Pack validate blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_validate(report))
        if report.errors:
            sys.exit(1)
        return

    if command == "build":
        try:
            report = PackBuilder().build(
                root,
                str(getattr(args, "target")),
                out_path=Path(str(getattr(args, "out"))) if getattr(args, "out", None) else None,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack build blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_built(report))
        if report.status != "built":
            sys.exit(1)
        return

    if command == "publish-local":
        record = PackLocalPublisher().publish(
            root,
            Path(str(getattr(args, "manifest_path"))),
            confirm=bool(getattr(args, "confirm", False)),
            require_proof=bool(getattr(args, "require_proof", False)),
            release_check_path=Path(str(getattr(args, "release_check"))) if getattr(args, "release_check", None) else None,
        )
        if getattr(args, "json_output", False):
            print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_publish(record, confirm=bool(getattr(args, "confirm", False))))
        if record.status == "blocked":
            sys.exit(1)
        return

    if command == "release-check":
        target = release_check_target_from_rc(root, str(getattr(args, "target")))
        report = PackReleaseChecker().check(
            root,
            target,
            require_proof=bool(getattr(args, "require_proof", False)),
        )
        if getattr(args, "save", False):
            save_pack_release_report(root, report)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_release_report(report))
        if not report.safe_to_publish:
            sys.exit(1)
        return

    if command == "rc":
        try:
            rc = PackReleaseCandidateBuilder().build(
                root,
                str(getattr(args, "draft_or_workspace")),
                allow_unresolved=bool(getattr(args, "allow_unresolved", False)),
            )
            saved_ref = save_pack_rc(root, rc)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack RC blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = rc.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if rc.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_rc(rc))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        if rc.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "rc-show":
        try:
            rc_path = resolve_pack_rc_path(root, str(getattr(args, "rc_ref")))
            rc = PackReleaseCandidateStore().load_rc(rc_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack RC show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = rc.to_dict()
            payload["path"] = _relative_cli(rc_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_rc(rc))
        return

    if command == "release-local":
        try:
            record = PackLocalReleaser().release(
                root,
                str(getattr(args, "rc_ref")),
                confirm=bool(getattr(args, "confirm", False)),
                supersede_previous=not bool(getattr(args, "no_supersede", False)),
            )
            saved_ref = save_pack_local_release(root, record)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack release-local blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = record.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if record.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_local_release(record, confirm=bool(getattr(args, "confirm", False))))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        if record.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "rollout":
        plan = PackRolloutPlanner().build(root, str(getattr(args, "new_pack_ref")))
        saved_ref = save_pack_rollout_plan(root, plan)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if plan.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_rollout_plan(plan))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        if plan.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "rollout-show":
        try:
            rollout_path = resolve_pack_rollout_path(root, str(getattr(args, "rollout_ref")))
            plan = PackRolloutStore().load_plan(rollout_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack rollout show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["path"] = _relative_cli(rollout_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_rollout_plan(plan))
        return

    if command == "rollout-apply":
        try:
            record = PackRolloutApplier().apply(
                root,
                str(getattr(args, "rollout_ref")),
                confirm=bool(getattr(args, "confirm", False)),
                install=bool(getattr(args, "install", False)),
                activate=bool(getattr(args, "activate", False)),
                mark_old_backup=bool(getattr(args, "mark_old_backup", False)),
            )
            saved_ref = save_pack_rollout_apply_record(root, record)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack rollout apply blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = record.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if record.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_rollout_apply_record(record))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        if record.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "web-sync":
        record = PackWebSyncer().sync(
            root,
            catalog_path=Path(str(getattr(args, "catalog"))) if getattr(args, "catalog", None) else None,
            web_dir=Path(str(getattr(args, "out"))) if getattr(args, "out", None) else None,
        )
        if getattr(args, "json_output", False):
            print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_web_sync(record))
        if record.status == "failed":
            sys.exit(1)
        return

    if command in {"doctor", "readiness"}:
        pack_ref = getattr(args, "pack_ref", None)
        registry_name = getattr(args, "registry", None)
        try:
            report = PackReadinessBuilder().build(
                root,
                str(pack_ref) if pack_ref else None,
                registry_name=str(registry_name) if registry_name else None,
            )
        except KeyError as exc:
            print(f"Pack doctor blocked: {exc.args[0]}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "save", False):
            save_pack_readiness_report(root, report)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_readiness(report))
        setup_plan = latest_pack_setup_plan(root, report.pack_id)
        setup_text = render_pack_setup_compact(setup_plan) or render_pack_setup_prompt(report)
        if setup_text:
            print(setup_text)
        return

    if command == "setup":
        pack_ref = getattr(args, "pack_ref", None)
        try:
            plan = PackSetupPlanner().build(root, str(pack_ref) if pack_ref else None)
            saved_ref = save_pack_setup_plan(root, plan)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack setup blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_setup_plan(plan))
        return

    if command == "setup-show":
        try:
            setup_path = resolve_pack_setup_plan_path(root, str(getattr(args, "setup_ref")))
            plan = PackSetupStore().load_plan(setup_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack setup show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["path"] = _relative_cli(setup_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_setup_plan(plan))
        return

    if command == "setup-apply":
        try:
            run = PackSetupApplier().apply(root, Path(str(getattr(args, "setup_ref"))))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack setup apply blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(run.to_dict(), indent=2, ensure_ascii=False))
            if run.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_setup_run(run))
        if run.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "start":
        try:
            pack_ref, request = _parse_pack_start_args(args)
            result = PackJobStarter().start(
                root,
                request,
                pack_ref=pack_ref,
                mode=str(getattr(args, "mode", "bridge") or "bridge"),
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack start blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.job.status == "blocked":
                sys.exit(1)
            return
        print(render_pack_job_started(result))
        if result.job.status == "blocked":
            sys.exit(1)
        return

    if command == "jobs":
        pack_ref = getattr(args, "pack_ref_option", None)
        limit = int(getattr(args, "limit", 20) or 20)
        jobs = PackJobStore().list(default_pack_jobs_dir(root), pack_id=str(pack_ref) if pack_ref else None)
        if getattr(args, "json_output", False):
            print(json.dumps({"jobs": [job.to_dict() for job in jobs[:limit]]}, indent=2, ensure_ascii=False))
            return
        print(render_pack_jobs(jobs, limit=limit))
        return

    if command == "job-paste":
        reply_text = sys.stdin.read()
        try:
            result = PackJobReplyHandler().paste(root, str(getattr(args, "job_ref")), reply_text)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job paste blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_job_reply_result(result))
        if result.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "job-ingest":
        try:
            result = PackJobReplyHandler().ingest(
                root,
                str(getattr(args, "job_ref")),
                Path(str(getattr(args, "reply_file"))),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job ingest blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_job_reply_result(result))
        if result.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "job-validate":
        try:
            result = PackJobValidator().validate(root, str(getattr(args, "job_ref")))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job validate blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.validation_status in {"blocked", "failed", "not_ready"}:
                sys.exit(1)
            return
        print(render_pack_job_validation_result(result))
        if result.validation_status in {"blocked", "failed", "not_ready"}:
            sys.exit(1)
        return

    if command == "job-apply":
        try:
            handler = PackJobApplyHandler()
            if bool(getattr(args, "confirm", False)):
                record = handler.apply(root, str(getattr(args, "job_ref")), confirm=True)
                if getattr(args, "json_output", False):
                    print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
                    if record.status in {"blocked", "failed"}:
                        sys.exit(1)
                    return
                print(render_pack_job_apply_record(record))
                if record.status in {"blocked", "failed"}:
                    sys.exit(1)
                return
            preview = handler.preview(root, str(getattr(args, "job_ref")))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job apply blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(preview.to_dict(), indent=2, ensure_ascii=False))
            if not preview.safe_to_apply:
                sys.exit(1)
            return
        print(render_pack_job_apply_preview(preview))
        if not preview.safe_to_apply:
            sys.exit(1)
        return

    if command == "job-adopt":
        decision = "accepted" if getattr(args, "accepted", False) else "rejected" if getattr(args, "rejected", False) else "skipped"
        try:
            record = PackJobAdoptionHandler().adopt(
                root,
                str(getattr(args, "job_ref")),
                decision,
                reason=getattr(args, "reason", None),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job adoption blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            if record.errors:
                sys.exit(1)
            return
        print(render_pack_job_adoption_record(record))
        if record.errors:
            sys.exit(1)
        return

    if command == "job-retro":
        try:
            retro = PackJobRetrospectiveBuilder().build(root, str(getattr(args, "job_ref")))
            saved_ref = save_pack_job_retrospective(root, retro)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job retrospective blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = retro.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_job_retrospective(retro))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        return

    if command == "retrospectives":
        pack_ref = getattr(args, "pack_ref", None)
        limit = int(getattr(args, "limit", 20) or 20)
        retros = PackRetrospectiveStore().list_job_retros(
            default_job_retrospectives_dir(root),
            str(pack_ref) if pack_ref else None,
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"retrospectives": [retro.to_dict() for retro in retros[:limit]]}, indent=2, ensure_ascii=False))
            return
        print(render_pack_retrospectives(retros, limit=limit))
        return

    if command == "retro-summary":
        pack_ref = getattr(args, "pack_ref", None)
        summary = PackRetrospectiveSummaryBuilder().build(root, str(pack_ref) if pack_ref else None)
        saved_ref = save_pack_retro_summary(root, summary) if getattr(args, "save", False) else None
        if getattr(args, "json_output", False):
            payload = summary.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_retro_summary(summary))
        if saved_ref:
            print("")
            print("Saved:")
            print(f"  {saved_ref}")
        return

    if command == "improve":
        pack_ref = getattr(args, "pack_ref", None)
        queue = PackImprovementQueueBuilder().build(root, str(pack_ref) if pack_ref else None)
        saved_ref = save_pack_improvement_queue(root, queue)
        if getattr(args, "json_output", False):
            payload = queue.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_improvement_queue(queue))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        return

    if command == "improvements":
        pack_ref = getattr(args, "pack_ref", None)
        status_filter = getattr(args, "status", None)
        store = PackImprovementStore()
        if latest_pack_improvement_queue(root, str(pack_ref) if pack_ref else None) is None:
            queue = PackImprovementQueueBuilder().build(root, str(pack_ref) if pack_ref else None)
            save_pack_improvement_queue(root, queue)
        items = store.list_items(
            default_pack_improvement_items_dir(root),
            pack_id=str(pack_ref) if pack_ref else None,
            status=str(status_filter) if status_filter else None,
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"items": [item.to_dict() for item in items]}, indent=2, ensure_ascii=False))
            return
        print(render_pack_improvements(items, status=str(status_filter) if status_filter else None))
        return

    if command == "improvement-show":
        try:
            item_path = resolve_pack_improvement_item_path(root, str(getattr(args, "item_ref")))
            item = PackImprovementStore().load_item(item_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack improvement show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = item.to_dict()
            payload["path"] = _relative_cli(item_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_improvement_item(item))
        return

    if command in {"improvement-accept", "improvement-dismiss"}:
        status = "accepted" if command == "improvement-accept" else "dismissed"
        try:
            decision, item, item_ref = record_pack_improvement_decision(
                root,
                str(getattr(args, "item_ref")),
                status,
                resolution=getattr(args, "resolution", None),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack improvement decision blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps({"decision": decision.to_dict(), "item": item.to_dict(), "item_ref": item_ref}, indent=2, ensure_ascii=False))
            return
        print(render_pack_improvement_decision(decision, item))
        return

    if command == "derivative-plan":
        pack_ref = getattr(args, "pack_ref", None)
        plan = PackDerivativePlanner().build(root, str(pack_ref) if pack_ref else None)
        saved_ref = save_pack_derivative_plan(root, plan)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_derivative_plan(plan))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        return

    if command == "derivative-show":
        try:
            plan_path = resolve_pack_derivative_plan_path(root, str(getattr(args, "plan_ref")))
            plan = PackDerivativeStore().load_plan(plan_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack derivative show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = plan.to_dict()
            payload["path"] = _relative_cli(plan_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_derivative_plan(plan))
        return

    if command == "derivative-create":
        try:
            workspace = PackDerivativeCreator().create(
                root,
                Path(str(getattr(args, "plan_ref"))),
                str(getattr(args, "target_pack_id")),
                version=getattr(args, "version", None),
            )
            saved_ref = save_pack_derivative_workspace(root, workspace)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack derivative create blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = workspace.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if workspace.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_derivative_workspace(workspace))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        if workspace.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "derivative-workbench":
        try:
            workbench = PackVNextWorkbenchBuilder().build(root, Path(str(getattr(args, "plan_ref"))))
            saved_ref = save_pack_vnext_workbench(root, workbench)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack derivative workbench blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = workbench.to_dict()
            payload["saved_ref"] = saved_ref
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_vnext_workbench(workbench))
        print("")
        print("Saved:")
        print(f"  {saved_ref}")
        return

    if command == "workorders":
        pack_ref = getattr(args, "pack_ref", None)
        status_filter = getattr(args, "status", None)
        orders = PackWorkOrderStore().list_workorders(
            default_pack_vnext_workorders_dir(root),
            pack_id=str(pack_ref) if pack_ref else None,
            status=str(status_filter) if status_filter else None,
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"items": [order.to_dict() for order in orders]}, indent=2, ensure_ascii=False))
            return
        print(render_pack_workorders(orders, status=str(status_filter) if status_filter else None))
        return

    if command == "workorder-show":
        try:
            order_path = resolve_pack_workorder_path(root, str(getattr(args, "workorder_ref")))
            order = PackWorkOrderStore().load_workorder(order_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack workorder show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = order.to_dict()
            payload["path"] = _relative_cli(order_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_workorder(order))
        return

    if command in {"workorder-done", "workorder-skip"}:
        status = "done" if command == "workorder-done" else "skipped"
        try:
            decision, order, order_ref = record_pack_workorder_decision(
                root,
                str(getattr(args, "workorder_ref")),
                status,
                note=getattr(args, "note", None),
                evidence_refs=list(getattr(args, "evidence", []) or []),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack workorder decision blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps({"decision": decision.to_dict(), "workorder": order.to_dict(), "workorder_ref": order_ref}, indent=2, ensure_ascii=False))
            return
        print(render_pack_workorder_decision(decision, order))
        return

    if command == "job-show":
        try:
            job_path = resolve_pack_job_path(root, str(getattr(args, "job_ref")))
            job = PackJobStore().load(job_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = job.to_dict()
            payload["path"] = _relative_cli(job_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_job(job))
        return

    if command == "job-next":
        try:
            job_path = resolve_pack_job_path(root, str(getattr(args, "job_ref")))
            job = PackJobStore().load(job_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job next blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        actions = PackJobNextBuilder().build(root, job)
        if getattr(args, "json_output", False):
            print(json.dumps({"job": job.to_dict(), "next_actions": actions}, indent=2, ensure_ascii=False))
            return
        print(render_pack_job_next(job, actions))
        return

    if command == "activate":
        pack_ref = str(getattr(args, "pack_ref"))
        try:
            readiness = PackReadinessBuilder().build(root, pack_ref)
            if readiness.readiness_status == "blocked":
                if not readiness.installed:
                    print("Pack is not installed.", file=sys.stderr)
                print(render_pack_readiness(readiness), file=sys.stderr)
                sys.exit(1)
            context = PackActivator().activate(root, pack_ref)
            guide = PackNextGuideBuilder().build(root)
        except KeyError as exc:
            print(str(exc.args[0]), file=sys.stderr)
            sys.exit(1)
        safe_record_pack_usage_from_context(
            root,
            context,
            event_kind="activated",
            surface_kind="pack_active",
            summary="pack activated as current work context",
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"active_pack": context.to_dict(), "next": guide.to_dict(), "readiness": readiness.to_dict()}, indent=2, ensure_ascii=False))
            return
        print(render_pack_activated(context, guide))
        compact_readiness = render_pack_readiness_compact(readiness)
        if compact_readiness and readiness.readiness_status != "ready":
            print(compact_readiness)
        return

    if command == "active":
        context = current_active_pack(root)
        guide = PackNextGuideBuilder().build(root) if context is not None else None
        if getattr(args, "json_output", False):
            print(json.dumps({"active_pack": context.to_dict() if context else None}, indent=2, ensure_ascii=False))
            return
        print(render_active_pack(context, guide))
        if context is not None:
            upgrade_hint = render_pack_upgrade_available(latest_pack_local_release(root, context.pack_id), context.pack_id)
            if upgrade_hint:
                print(upgrade_hint)
        return

    if command == "next":
        pack_ref = getattr(args, "pack_ref", None)
        try:
            guide = PackNextGuideBuilder().build(root, str(pack_ref) if pack_ref else None)
            readiness = PackReadinessBuilder().build(root, str(pack_ref) if pack_ref else None)
        except KeyError as exc:
            print(str(exc.args[0]), file=sys.stderr)
            sys.exit(1)
        safe_record_pack_usage_event(
            root,
            event_kind="surfaced",
            surface_kind="pack_next",
            summary="pack next guide surfaced",
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"next": guide.to_dict(), "readiness": readiness.to_dict()}, indent=2, ensure_ascii=False))
            return
        compact_readiness = render_pack_readiness_compact(readiness)
        if compact_readiness and readiness.readiness_status != "ready":
            print(compact_readiness)
            setup_plan = latest_pack_setup_plan(root, readiness.pack_id)
            setup_text = render_pack_setup_compact(setup_plan) or render_pack_setup_prompt(readiness)
            if setup_text:
                print(setup_text)
        print(render_pack_next(guide))
        if guide.errors:
            sys.exit(1)
        return

    if command == "deactivate":
        context = PackActivator().deactivate(root)
        safe_record_pack_usage_from_context(
            root,
            context,
            event_kind="deactivated",
            surface_kind="pack_active",
            summary="pack deactivated as current work context",
        )
        if getattr(args, "json_output", False):
            print(json.dumps(context.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_deactivated(context))
        return

    if command == "usage":
        pack_ref = getattr(args, "pack_ref", None)
        summary = PackUsageSummaryBuilder().build(root, str(pack_ref) if pack_ref else None)
        saved_path = None
        if getattr(args, "save", False):
            saved_path = PackUsageSummaryStore().save(summary, default_usage_summary_path(root, summary))
        if getattr(args, "json_output", False):
            payload = summary.to_dict()
            payload["saved_path"] = str(saved_path.resolve()) if saved_path else None
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_usage(summary))
        if saved_path is not None:
            print("")
            print("Saved:")
            print(f"  {_relative_cli(saved_path, root)}")
        return

    if command == "events":
        pack_ref = getattr(args, "pack_ref", None)
        events = PackUsageEventStore().list_events(default_usage_events_dir(root), str(pack_ref) if pack_ref else None)
        kind = getattr(args, "kind", None)
        if kind:
            events = [event for event in events if event.event_kind == kind]
        limit = int(getattr(args, "limit", 20) or 20)
        if getattr(args, "json_output", False):
            print(json.dumps({"events": [event.to_dict() for event in events[:limit]]}, indent=2, ensure_ascii=False))
            return
        print(render_pack_events(events, limit=limit))
        return

    if command == "outcomes":
        pack_ref = getattr(args, "pack_ref", None)
        links = PackOutcomeLinkBuilder().build_links(root, str(pack_ref) if pack_ref else None)
        saved_link_refs = save_pack_outcome_links(root, links) if getattr(args, "save", False) else []
        summary = PackUsageSummaryBuilder().build(root, str(pack_ref) if pack_ref else None)
        saved_path = None
        if getattr(args, "save", False):
            saved_path = PackUsageSummaryStore().save(summary, default_usage_summary_path(root, summary))
        if getattr(args, "json_output", False):
            payload = summary.to_dict()
            payload["outcome_links"] = [link.to_dict() for link in links]
            payload["saved_link_refs"] = saved_link_refs
            payload["saved_path"] = str(saved_path.resolve()) if saved_path else None
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_outcomes(summary))
        if saved_path is not None:
            print("")
            print("Saved:")
            print(f"  {_relative_cli(saved_path, root)}")
        return

    if command == "proof":
        pack_ref = getattr(args, "pack_ref", None)
        try:
            card = PackProofBuilder().build(root, str(pack_ref) if pack_ref else None)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack proof blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_paths: dict[str, str] = {}
        if getattr(args, "save", False):
            saved_paths = save_pack_proof_card(root, card, format_kind=str(getattr(args, "format", "both")))
        if getattr(args, "json_output", False):
            payload = card.to_dict()
            payload["saved_paths"] = saved_paths
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_proof_card(card))
        if saved_paths:
            print("")
            print("Saved:")
            for item in saved_paths.values():
                print(f"  {item}")
        return

    if command == "proof-show":
        try:
            proof_path = resolve_pack_proof_path(root, str(getattr(args, "proof_ref")))
            card = PackProofStore().load_yaml(proof_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack proof show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = card.to_dict()
            payload["path"] = _relative_cli(proof_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_proof_card(card))
        return

    if command == "proof-export":
        pack_ref = getattr(args, "pack_ref", None)
        proof_ref = getattr(args, "proof", None)
        out_ref = getattr(args, "out", None)
        try:
            snapshot = PackProofExporter().export(
                root,
                str(pack_ref) if pack_ref else None,
                source_proof_path=Path(str(proof_ref)) if proof_ref else None,
                out_path=Path(str(out_ref)) if out_ref else None,
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack proof export blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
            if snapshot.privacy_classification == "blocked_sensitive":
                sys.exit(1)
            return
        print(render_pack_proof_export(snapshot))
        if snapshot.privacy_classification == "blocked_sensitive":
            sys.exit(1)
        return

    if command == "proof-export-show":
        try:
            export_path = resolve_pack_proof_export_path(root, str(getattr(args, "export_ref")))
            snapshot = PackProofExportStore().load_yaml(export_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack proof export show blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            payload = snapshot.to_dict()
            payload["path"] = _relative_cli(export_path, root)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_proof_export(snapshot))
        return

    if command == "search":
        query = getattr(args, "query", None)
        registry_name = getattr(args, "registry", None)
        kind = getattr(args, "kind", None)
        registry_packs = PackRegistryResolver().search(
            root,
            query=str(query) if query else None,
            registry_name=str(registry_name) if registry_name else None,
            kind=kind,
        )
        local_packs: list[SyncedRegistryPack] = []
        if not registry_name:
            catalog = load_default_catalog(repo_root)
            if not catalog.errors:
                needle = str(query or "").strip().lower()
                for entry in catalog.entries:
                    if kind and entry.pack_kind != kind:
                        continue
                    haystack = " ".join([entry.pack_id, entry.pack_name, entry.description or "", " ".join(entry.tags)]).lower()
                    if needle and needle not in haystack:
                        continue
                    local_packs.append(
                        SyncedRegistryPack(
                            pack_id=entry.pack_id,
                            pack_name=entry.pack_name,
                            pack_kind=entry.pack_kind,
                            version=entry.version,
                            namespace=entry.namespace or "local",
                            description=entry.description,
                            tags=list(entry.tags),
                            maturity=entry.maturity,
                            proof_status=entry.proof_status,
                            compatibility=dict(entry.compatibility),
                            known_limits=list(entry.known_limits),
                            manifest_ref=entry.manifest_path,
                            manifest_sha256=entry.manifest_sha256,
                            registry_name="local",
                            registry_source_ref="packs/catalog.yaml",
                            dependencies=list(entry.dependencies),
                            trust_level=entry.trust_level or "local",
                            warnings=list(entry.warnings),
                        )
                    )
        packs = [*local_packs, *registry_packs]
        if getattr(args, "json_output", False):
            print(json.dumps(pack_search_payload(packs), indent=2, ensure_ascii=False))
            return
        print(render_pack_search(packs))
        return

    catalog = load_default_catalog(repo_root)
    if catalog.errors:
        print(f"Pack catalog blocked: {catalog.errors[0]}", file=sys.stderr)
        sys.exit(1)

    if command == "list":
        kind = getattr(args, "kind", None)
        payload = catalog_payload(catalog, root, repo_root, kind=kind)
        latest_rc_for_list = latest_pack_rc(root)
        latest_release_for_list = latest_pack_local_release(root)
        if latest_rc_for_list is not None:
            payload["latest_release_candidate"] = latest_rc_for_list.to_dict()
        if latest_release_for_list is not None:
            payload["latest_local_release"] = latest_release_for_list.to_dict()
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        entries = [PackCatalogResolver().find_entry(catalog, item["entry"]["pack_id"]) for item in payload["packs"]]
        fits = {
            item["entry"]["pack_id"]: PackFitAnalyzer().analyze(root, PackCatalogResolver().find_entry(catalog, item["entry"]["pack_id"]))
            for item in payload["packs"]
        }
        print(render_pack_list(entries, fits))
        compact_rc = render_pack_rc_compact(latest_rc_for_list, latest_release_for_list)
        if compact_rc:
            print(compact_rc)
        return

    if command == "show":
        registry_name = getattr(args, "registry", None)
        if registry_name:
            try:
                pack = PackRegistryResolver().resolve_pack(
                    root,
                    str(getattr(args, "pack_ref")),
                    registry_name=str(registry_name),
                )
                readiness = PackReadinessBuilder().build(
                    root,
                    str(getattr(args, "pack_ref")),
                    registry_name=str(registry_name),
                )
            except KeyError as exc:
                print(f"Registry pack not found: {exc.args[0]}", file=sys.stderr)
                sys.exit(1)
            if getattr(args, "json_output", False):
                payload = registry_pack_show_payload(pack, root)
                payload["readiness"] = readiness.to_dict()
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return
            print(render_registry_pack_show(pack, root))
            compact_readiness = render_pack_readiness_compact(readiness)
            if compact_readiness:
                print(compact_readiness)
            return

        resolver = PackCatalogResolver()
        try:
            entry = resolver.find_entry(catalog, str(getattr(args, "pack_ref")))
            manifest_path, manifest = manifest_for_entry(repo_root, entry)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack not found: {exc}", file=sys.stderr)
            sys.exit(1)
        fit = PackFitAnalyzer().analyze(root, entry)
        payload = {
            "entry": entry.to_dict(),
            "fit": fit.to_dict(),
            "manifest_path": _relative_cli(manifest_path, repo_root),
            "includes": {
                "workers": len(manifest.workers),
                "teams": len(manifest.teams),
                "templates": len(manifest.templates),
                "benchmarks": len(manifest.benchmarks),
            },
        }
        usage_summary = PackUsageSummaryBuilder().build(root, entry.pack_id)
        payload["local_usage"] = usage_summary.to_dict()
        proof_card = latest_pack_proof_card(root, entry.pack_id)
        if proof_card is not None:
            payload["local_proof"] = proof_card.to_dict()
        retro_summary = latest_pack_retro_summary(root, entry.pack_id)
        if retro_summary is not None:
            payload["local_retrospective"] = retro_summary.to_dict()
        improvement_queue = latest_pack_improvement_queue(root, entry.pack_id)
        if improvement_queue is not None:
            payload["local_improvements"] = improvement_queue.to_dict()
        derivative_plan = latest_pack_derivative_plan(root, entry.pack_id)
        if derivative_plan is not None:
            payload["local_derivative"] = derivative_plan.to_dict()
        vnext_workbench = latest_pack_vnext_workbench(root, entry.pack_id)
        if vnext_workbench is not None:
            payload["local_vnext_workbench"] = vnext_workbench.to_dict()
        release_candidate = latest_pack_rc(root, entry.pack_id)
        if release_candidate is not None:
            payload["local_release_candidate"] = release_candidate.to_dict()
        local_release = latest_pack_local_release(root, entry.pack_id)
        if local_release is not None:
            payload["local_release"] = local_release.to_dict()
        rollout_plan = latest_pack_rollout(root, entry.pack_id)
        if rollout_plan is not None:
            payload["local_rollout"] = rollout_plan.to_dict()
        readiness = PackReadinessBuilder().build(root, entry.pack_id)
        payload["readiness"] = readiness.to_dict()
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_show(entry, manifest, fit, manifest_path, repo_root))
        compact_readiness = render_pack_readiness_compact(readiness)
        if compact_readiness:
            print(compact_readiness)
        compact_usage = render_pack_usage_compact(usage_summary)
        if compact_usage:
            print(compact_usage)
        compact_proof = render_pack_proof_compact(proof_card)
        if compact_proof:
            print(compact_proof)
        compact_retro = render_pack_retro_summary_compact(retro_summary)
        if compact_retro:
            print(compact_retro)
        compact_improvement = render_pack_improvement_compact(improvement_queue)
        if compact_improvement:
            print(compact_improvement)
        compact_derivative = render_pack_derivative_compact(derivative_plan)
        if compact_derivative:
            print(compact_derivative)
        compact_vnext = render_pack_vnext_compact(vnext_workbench)
        if compact_vnext:
            print(compact_vnext)
        compact_rc = render_pack_rc_compact(release_candidate, local_release)
        if compact_rc:
            print(compact_rc)
        compact_rollout = render_pack_rollout_compact(rollout_plan)
        if compact_rollout:
            print(compact_rollout)
        return

    if command == "recommend":
        entry, fit = best_recommendation(catalog, root)
        proof_card = latest_pack_proof_card(root, entry.pack_id) if entry else None
        readiness = PackReadinessBuilder().build(root, entry.pack_id) if entry else None
        retro_summary = latest_pack_retro_summary(root, entry.pack_id) if entry else None
        improvement_queue = latest_pack_improvement_queue(root, entry.pack_id) if entry else None
        payload = {
            "entry": entry.to_dict() if entry else None,
            "fit": fit.to_dict() if fit else None,
            "local_proof": proof_card.to_dict() if proof_card else None,
            "readiness": readiness.to_dict() if readiness else None,
            "local_retrospective": retro_summary.to_dict() if retro_summary else None,
            "local_improvements": improvement_queue.to_dict() if improvement_queue else None,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_recommend(entry, fit))
        compact_readiness = render_pack_readiness_compact(readiness)
        if compact_readiness:
            print(compact_readiness)
        compact_proof = render_pack_proof_compact(proof_card)
        if compact_proof:
            print(compact_proof)
        compact_retro = render_pack_retro_summary_compact(retro_summary)
        if compact_retro:
            print(compact_retro)
        compact_improvement = render_pack_improvement_compact(improvement_queue)
        if compact_improvement:
            print(compact_improvement)
        return

    if command == "verify":
        target = str(getattr(args, "pack_ref"))
        verifier = PackVerifier()
        try:
            target_path = Path(target)
            if target_path.exists():
                report = verifier.verify_manifest(target_path)
            else:
                report = verifier.verify_catalog_pack(Path(__file__).resolve().parents[1], target)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack verify blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "save", False):
            save_pack_verification(root, report)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_verify(report))
        if report.status == "failed":
            sys.exit(1)
        return

    print("알 수 없는 pack 하위 명령입니다.", file=sys.stderr)
    sys.exit(1)


def _handle_pack_launch_path(args: argparse.Namespace, root: Path, repo_root: Path, command: str) -> None:
    """출시 골든패스 pack 명령을 가벼운 branch-local import로 처리한다."""
    if command == "list":
        from engine.project_pack_catalog import (
            PackCatalogResolver,
            PackFitAnalyzer,
            catalog_payload,
            load_default_catalog,
            render_pack_list,
        )

        catalog = load_default_catalog(repo_root)
        if catalog.errors:
            print(f"Pack catalog blocked: {catalog.errors[0]}", file=sys.stderr)
            sys.exit(1)
        kind = getattr(args, "kind", None)
        payload = catalog_payload(catalog, root, repo_root, kind=kind)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        entries = [PackCatalogResolver().find_entry(catalog, item["entry"]["pack_id"]) for item in payload["packs"]]
        fits = {
            item["entry"]["pack_id"]: PackFitAnalyzer().analyze(root, PackCatalogResolver().find_entry(catalog, item["entry"]["pack_id"]))
            for item in payload["packs"]
        }
        print(render_pack_list(entries, fits))
        return

    if command == "show":
        from engine.project_pack_catalog import (
            PackCatalogResolver,
            PackFitAnalyzer,
            load_default_catalog,
            manifest_for_entry,
            render_pack_show,
        )
        from engine.project_pack_readiness import PackReadinessBuilder, render_pack_readiness_compact
        from engine.project_pack_usage import PackUsageSummaryBuilder, render_pack_usage_compact
        from engine.project_pack_proof import latest_pack_proof_card, render_pack_proof_compact
        from engine.project_pack_retrospective import latest_pack_retro_summary, render_pack_retro_summary_compact
        from engine.project_pack_improvements import latest_pack_improvement_queue, render_pack_improvement_compact

        registry_name = getattr(args, "registry", None)
        if registry_name:
            from engine.project_pack_registry import PackRegistryResolver, registry_pack_show_payload, render_registry_pack_show

            try:
                pack = PackRegistryResolver().resolve_pack(
                    root,
                    str(getattr(args, "pack_ref")),
                    registry_name=str(registry_name),
                )
                readiness = PackReadinessBuilder().build(
                    root,
                    str(getattr(args, "pack_ref")),
                    registry_name=str(registry_name),
                )
            except KeyError as exc:
                print(f"Registry pack not found: {exc.args[0]}", file=sys.stderr)
                sys.exit(1)
            if getattr(args, "json_output", False):
                payload = registry_pack_show_payload(pack, root)
                payload["readiness"] = readiness.to_dict()
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return
            print(render_registry_pack_show(pack, root))
            compact_readiness = render_pack_readiness_compact(readiness)
            if compact_readiness:
                print(compact_readiness)
            return

        catalog = load_default_catalog(repo_root)
        if catalog.errors:
            print(f"Pack catalog blocked: {catalog.errors[0]}", file=sys.stderr)
            sys.exit(1)
        resolver = PackCatalogResolver()
        try:
            entry = resolver.find_entry(catalog, str(getattr(args, "pack_ref")))
            manifest_path, manifest = manifest_for_entry(repo_root, entry)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack not found: {exc}", file=sys.stderr)
            sys.exit(1)
        fit = PackFitAnalyzer().analyze(root, entry)
        usage_summary = PackUsageSummaryBuilder().build(root, entry.pack_id)
        proof_card = latest_pack_proof_card(root, entry.pack_id)
        retro_summary = latest_pack_retro_summary(root, entry.pack_id)
        improvement_queue = latest_pack_improvement_queue(root, entry.pack_id)
        readiness = PackReadinessBuilder().build(root, entry.pack_id)
        payload = {
            "entry": entry.to_dict(),
            "fit": fit.to_dict(),
            "manifest_path": str(manifest_path.relative_to(repo_root)).replace("\\", "/"),
            "includes": {
                "workers": len(manifest.workers),
                "teams": len(manifest.teams),
                "templates": len(manifest.templates),
                "benchmarks": len(manifest.benchmarks),
            },
            "local_usage": usage_summary.to_dict(),
            "readiness": readiness.to_dict(),
        }
        if proof_card is not None:
            payload["local_proof"] = proof_card.to_dict()
        if retro_summary is not None:
            payload["local_retrospective"] = retro_summary.to_dict()
        if improvement_queue is not None:
            payload["local_improvements"] = improvement_queue.to_dict()
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_show(entry, manifest, fit, manifest_path, repo_root))
        for compact in [
            render_pack_readiness_compact(readiness),
            render_pack_usage_compact(usage_summary),
            render_pack_proof_compact(proof_card),
            render_pack_retro_summary_compact(retro_summary),
            render_pack_improvement_compact(improvement_queue),
        ]:
            if compact:
                print(compact)
        return

    if command in {"doctor", "readiness"}:
        from engine.project_pack_readiness import PackReadinessBuilder, render_pack_readiness, save_pack_readiness_report
        from engine.project_pack_setup import latest_pack_setup_plan, render_pack_setup_compact, render_pack_setup_prompt

        pack_ref = getattr(args, "pack_ref", None)
        registry_name = getattr(args, "registry", None)
        try:
            report = PackReadinessBuilder().build(
                root,
                str(pack_ref) if pack_ref else None,
                registry_name=str(registry_name) if registry_name else None,
            )
        except KeyError as exc:
            print(f"Pack doctor blocked: {exc.args[0]}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "save", False):
            save_pack_readiness_report(root, report)
        if getattr(args, "json_output", False):
            print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_pack_readiness(report))
        setup_plan = latest_pack_setup_plan(root, report.pack_id)
        setup_text = render_pack_setup_compact(setup_plan) or render_pack_setup_prompt(report)
        if setup_text:
            print(setup_text)
        return

    if command == "start":
        from engine.project_pack_jobs import PackJobStarter, render_pack_job_started

        try:
            pack_ref, request = _parse_pack_start_args(args)
            result = PackJobStarter().start(
                root,
                request,
                pack_ref=pack_ref,
                mode=str(getattr(args, "mode", "bridge") or "bridge"),
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack start blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.job.status == "blocked":
                sys.exit(1)
            return
        print(render_pack_job_started(result))
        if result.job.status == "blocked":
            sys.exit(1)
        return

    if command == "job-paste":
        from engine.project_pack_job_reply import PackJobReplyHandler, render_pack_job_reply_result

        reply_text = sys.stdin.read()
        try:
            result = PackJobReplyHandler().paste(root, str(getattr(args, "job_ref")), reply_text)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job paste blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_job_reply_result(result))
        if result.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "job-ingest":
        from engine.project_pack_job_reply import PackJobReplyHandler, render_pack_job_reply_result

        try:
            result = PackJobReplyHandler().ingest(
                root,
                str(getattr(args, "job_ref")),
                Path(str(getattr(args, "reply_file"))),
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job ingest blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.status in {"blocked", "failed"}:
                sys.exit(1)
            return
        print(render_pack_job_reply_result(result))
        if result.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "job-validate":
        from engine.project_pack_job_reply import PackJobValidator, render_pack_job_validation_result

        try:
            result = PackJobValidator().validate(root, str(getattr(args, "job_ref")))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Pack job validate blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.validation_status in {"blocked", "failed", "not_ready"}:
                sys.exit(1)
            return
        print(render_pack_job_validation_result(result))
        if result.validation_status in {"blocked", "failed", "not_ready"}:
            sys.exit(1)
        return

    if command == "activate":
        from engine.project_pack_activation import PackActivator, PackNextGuideBuilder, render_pack_activated
        from engine.project_pack_readiness import PackReadinessBuilder, render_pack_readiness, render_pack_readiness_compact
        from engine.project_pack_usage import safe_record_pack_usage_from_context

        pack_ref = str(getattr(args, "pack_ref"))
        try:
            readiness = PackReadinessBuilder().build(root, pack_ref)
            if readiness.readiness_status == "blocked":
                if not readiness.installed:
                    print("Pack is not installed.", file=sys.stderr)
                print(render_pack_readiness(readiness), file=sys.stderr)
                sys.exit(1)
            context = PackActivator().activate(root, pack_ref)
            guide = PackNextGuideBuilder().build(root)
        except KeyError as exc:
            print(str(exc.args[0]), file=sys.stderr)
            sys.exit(1)
        safe_record_pack_usage_from_context(
            root,
            context,
            event_kind="activated",
            surface_kind="pack_active",
            summary="pack activated as current work context",
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"active_pack": context.to_dict(), "next": guide.to_dict(), "readiness": readiness.to_dict()}, indent=2, ensure_ascii=False))
            return
        print(render_pack_activated(context, guide))
        compact_readiness = render_pack_readiness_compact(readiness)
        if compact_readiness and readiness.readiness_status != "ready":
            print(compact_readiness)
        return

    if command == "active":
        from engine.project_pack_activation import PackNextGuideBuilder, current_active_pack, render_active_pack

        context = current_active_pack(root)
        guide = PackNextGuideBuilder().build(root) if context is not None else None
        if getattr(args, "json_output", False):
            print(json.dumps({"active_pack": context.to_dict() if context else None}, indent=2, ensure_ascii=False))
            return
        print(render_active_pack(context, guide))
        return

    if command == "next":
        from engine.project_pack_activation import PackNextGuideBuilder, render_pack_next
        from engine.project_pack_readiness import PackReadinessBuilder, render_pack_readiness_compact
        from engine.project_pack_setup import latest_pack_setup_plan, render_pack_setup_compact, render_pack_setup_prompt
        from engine.project_pack_usage import safe_record_pack_usage_event

        pack_ref = getattr(args, "pack_ref", None)
        try:
            guide = PackNextGuideBuilder().build(root, str(pack_ref) if pack_ref else None)
            readiness = PackReadinessBuilder().build(root, str(pack_ref) if pack_ref else None)
        except KeyError as exc:
            print(str(exc.args[0]), file=sys.stderr)
            sys.exit(1)
        safe_record_pack_usage_event(
            root,
            event_kind="surfaced",
            surface_kind="pack_next",
            summary="pack next guide surfaced",
        )
        if getattr(args, "json_output", False):
            print(json.dumps({"next": guide.to_dict(), "readiness": readiness.to_dict()}, indent=2, ensure_ascii=False))
            return
        compact_readiness = render_pack_readiness_compact(readiness)
        if compact_readiness and readiness.readiness_status != "ready":
            print(compact_readiness)
            setup_plan = latest_pack_setup_plan(root, readiness.pack_id)
            setup_text = render_pack_setup_compact(setup_plan) or render_pack_setup_prompt(readiness)
            if setup_text:
                print(setup_text)
        print(render_pack_next(guide))
        if guide.errors:
            sys.exit(1)
        return

    if command == "proof":
        from engine.project_pack_proof import PackProofBuilder, render_pack_proof_card, save_pack_proof_card

        pack_ref = getattr(args, "pack_ref", None)
        try:
            card = PackProofBuilder().build(root, str(pack_ref) if pack_ref else None)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            print(f"Pack proof blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_paths: dict[str, str] = {}
        if getattr(args, "save", False):
            saved_paths = save_pack_proof_card(root, card, format_kind=str(getattr(args, "format", "both")))
        if getattr(args, "json_output", False):
            payload = card.to_dict()
            payload["saved_paths"] = saved_paths
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_pack_proof_card(card))
        if saved_paths:
            print("")
            print("Saved:")
            for item in saved_paths.values():
                print(f"  {item}")
        return

    print("알 수 없는 launch pack 명령입니다.", file=sys.stderr)
    sys.exit(1)


def _parse_pack_start_args(args: argparse.Namespace) -> tuple[str | None, str]:
    """pack start 인자를 pack ref와 request로 나눈다."""
    explicit_pack = getattr(args, "pack_ref_option", None)
    raw_args = [str(item) for item in list(getattr(args, "start_args", []) or []) if str(item).strip()]
    if explicit_pack:
        request = " ".join(raw_args).strip()
        if not request:
            raise ValueError("request is required")
        return str(explicit_pack), request
    if not raw_args:
        raise ValueError("request is required")
    if len(raw_args) == 1:
        return None, raw_args[0]
    return raw_args[0], " ".join(raw_args[1:]).strip()


def _handle_metrics(args: argparse.Namespace) -> None:
    """cambrian metrics 처리."""
    from engine.project_metrics import (
        ProjectMetricsBuilder,
        ProjectMetricsStore,
        default_weekly_metrics_path,
        render_weekly_metrics,
    )

    command = getattr(args, "metrics_command", None)
    if command != "week":
        print("metrics 하위 명령이 올바르지 않습니다. 예: cambrian metrics week", file=sys.stderr)
        sys.exit(1)

    root = Path.cwd().resolve()
    report = ProjectMetricsBuilder().build_week(
        root,
        start=getattr(args, "start", None),
        end=getattr(args, "end", None),
    )
    saved_path: Path | None = None
    if getattr(args, "save", False):
        saved_path = ProjectMetricsStore().save(
            report,
            default_weekly_metrics_path(root, report.week_id),
        )

    if getattr(args, "json_output", False):
        payload = report.to_dict()
        payload["saved_path"] = str(saved_path.resolve()) if saved_path else None
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print(render_weekly_metrics(report))
    if saved_path is not None:
        try:
            saved_ref = str(saved_path.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            saved_ref = str(saved_path.resolve())
        print("")
        print("Saved:")
        print(f"  {saved_ref}")



def _handle_status(args: argparse.Namespace) -> None:
    """cambrian status 처리."""
    from engine.project_mode import ProjectStatusReader, render_status_summary
    from engine.project_pack_activation import current_active_pack, render_status_active_pack
    from engine.project_pack_proof import latest_pack_proof_card, render_pack_proof_compact
    from engine.project_pack_readiness import PackReadinessBuilder, render_pack_readiness_compact
    from engine.project_pack_setup import latest_pack_setup_plan, render_pack_setup_compact
    from engine.project_pack_usage import PackUsageSummaryBuilder, render_pack_usage_compact
    from engine.project_pack_jobs import latest_pack_job, render_status_latest_pack_job
    from engine.project_pack_retrospective import (
        latest_pack_retro_summary,
        render_pack_retro_summary_compact,
        render_status_pack_retrospective,
    )
    from engine.project_pack_improvements import latest_pack_improvement_queue, render_status_pack_improvement
    from engine.project_pack_derivatives import (
        accepted_improvement_count,
        latest_pack_derivative_plan,
        render_status_pack_derivative,
    )
    from engine.project_pack_vnext_workbench import latest_pack_vnext_workbench, render_status_pack_vnext
    from engine.project_pack_release_candidate import latest_pack_local_release, latest_pack_rc, render_status_pack_rc
    from engine.project_pack_rollout import latest_pack_rollout, render_pack_upgrade_available, render_status_pack_rollout
    from engine.project_summary import ProjectUsageSummaryBuilder, render_usage_summary
    from engine.project_timeline import (
        ProjectTimelineReader,
        render_project_timeline,
        render_session_timeline,
    )

    project_root = Path.cwd()
    if getattr(args, "session", None):
        try:
            timeline = ProjectTimelineReader().read_session_timeline(
                project_root,
                str(getattr(args, "session")),
            )
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(timeline.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_session_timeline(timeline))
        return

    if getattr(args, "timeline", False):
        view = ProjectTimelineReader().read_project_status(
            project_root,
            limit=int(getattr(args, "limit", 5) or 5),
        )
        if getattr(args, "json_output", False):
            print(json.dumps(view.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_project_timeline(view, limit=int(getattr(args, "limit", 5) or 5)))
        return

    if getattr(args, "summary_output", False):
        summary = ProjectUsageSummaryBuilder().build(
            project_root,
            limit=int(getattr(args, "limit", 5) or 5),
        )
        if getattr(args, "json_output", False):
            print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_usage_summary(summary))
        return

    result = ProjectStatusReader().read(project_root)

    if getattr(args, "json_output", False):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    print(render_status_summary(result))
    active_context = current_active_pack(project_root)
    active_summary = render_status_active_pack(active_context)
    if active_summary:
        print(active_summary)
    if active_context is not None:
        try:
            readiness = PackReadinessBuilder().build(project_root, active_context.pack_id)
            compact_readiness = render_pack_readiness_compact(readiness)
            if compact_readiness:
                print(compact_readiness)
            setup_plan = latest_pack_setup_plan(project_root, active_context.pack_id)
            compact_setup = render_pack_setup_compact(setup_plan)
            if compact_setup:
                print(compact_setup)
        except Exception as exc:
            logger.warning("active pack readiness status failed: %s", exc)
        usage_summary = PackUsageSummaryBuilder().build(project_root, active_context.pack_id)
        compact_usage = render_pack_usage_compact(usage_summary)
        if compact_usage:
            print(compact_usage)
        compact_proof = render_pack_proof_compact(latest_pack_proof_card(project_root, active_context.pack_id))
        if compact_proof:
            print(compact_proof)
        compact_retro = render_pack_retro_summary_compact(latest_pack_retro_summary(project_root, active_context.pack_id))
        if compact_retro:
            print(compact_retro)
        improvement_summary = render_status_pack_improvement(latest_pack_improvement_queue(project_root, active_context.pack_id))
        if improvement_summary:
            print(improvement_summary)
        derivative_summary = render_status_pack_derivative(
            latest_pack_derivative_plan(project_root, active_context.pack_id),
            accepted_improvement_count(project_root, active_context.pack_id),
        )
        if derivative_summary:
            print(derivative_summary)
        vnext_summary = render_status_pack_vnext(latest_pack_vnext_workbench(project_root, active_context.pack_id))
        if vnext_summary:
            print(vnext_summary)
        rc_summary = render_status_pack_rc(
            latest_pack_rc(project_root, active_context.pack_id),
            latest_pack_local_release(project_root, active_context.pack_id),
        )
        if rc_summary:
            print(rc_summary)
        rollout_summary = render_status_pack_rollout(latest_pack_rollout(project_root, active_context.pack_id))
        if rollout_summary:
            print(rollout_summary)
        else:
            upgrade_hint = render_pack_upgrade_available(latest_pack_local_release(project_root, active_context.pack_id), active_context.pack_id)
            if upgrade_hint:
                print(upgrade_hint)
    latest_job_summary = render_status_latest_pack_job(latest_pack_job(project_root))
    if latest_job_summary:
        print(latest_job_summary)
    retro_prompt = render_status_pack_retrospective(project_root, latest_pack_job(project_root))
    if retro_prompt:
        print(retro_prompt)


def _handle_summary(args: argparse.Namespace) -> None:
    """cambrian summary 처리."""
    from engine.project_summary import (
        ProjectUsageSummaryBuilder,
        ProjectUsageSummaryStore,
        default_usage_summary_path,
        render_usage_summary,
    )

    root = Path.cwd()
    summary = ProjectUsageSummaryBuilder().build(
        root,
        limit=int(getattr(args, "limit", 5) or 5),
    )
    if getattr(args, "save", False):
        output_path = (
            Path(str(getattr(args, "out"))).resolve()
            if getattr(args, "out", None)
            else default_usage_summary_path(root)
        )
        ProjectUsageSummaryStore().save(summary, output_path)

    if getattr(args, "json_output", False):
        print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
        return

    print(render_usage_summary(summary))


def _handle_notes(args: argparse.Namespace) -> None:
    """cambrian notes 처리."""
    from engine.project_notes import (
        ProjectNotesBuilder,
        ProjectNotesStore,
        default_notes_dir,
        render_note_add_summary,
        render_note_resolve_summary,
        render_note_show,
        render_notes_list,
    )

    root = Path.cwd()
    store = ProjectNotesStore()
    command = getattr(args, "notes_command", None)
    if not command:
        print("notes 하위 명령이 필요합니다. 예: cambrian notes add \"clarify step was confusing\"", file=sys.stderr)
        sys.exit(1)

    def _relative_note_path(path: Path) -> str:
        if path.is_relative_to(root):
            return str(path.relative_to(root)).replace("\\", "/")
        return str(path)

    if command == "add":
        note = ProjectNotesBuilder().build(
            text=str(getattr(args, "text")),
            project_root=root,
            kind=str(getattr(args, "kind", "note")),
            severity=str(getattr(args, "severity", "medium")),
            tags=list(getattr(args, "note_tags", []) or []),
            session_ref=getattr(args, "session", None),
            artifact_refs=list(getattr(args, "artifact_refs", []) or []),
        )
        note_path = store.add(note, default_notes_dir(root))
        payload = note.to_dict()
        payload["note_path"] = _relative_note_path(note_path)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_note_add_summary(note, payload["note_path"]))
        return

    if command == "list":
        notes = store.list(default_notes_dir(root))
        status_filter = str(getattr(args, "status", None) or "open")
        kind_filter = getattr(args, "kind", None)
        severity_filter = getattr(args, "severity", None)
        filtered = [
            note
            for note in notes
            if note.status == status_filter
            and (kind_filter is None or note.kind == kind_filter)
            and (severity_filter is None or note.severity == severity_filter)
        ][: max(1, int(getattr(args, "limit", 20) or 20))]
        payload = {
            "status_filter": status_filter,
            "kind_filter": kind_filter,
            "severity_filter": severity_filter,
            "count": len(filtered),
            "notes": [note.to_dict() for note in filtered],
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_notes_list(filtered, status_filter=status_filter))
        return

    if command == "show":
        try:
            note_path = store.resolve_path(root, str(getattr(args, "note_ref")))
        except FileNotFoundError:
            print(f"Note not found: {getattr(args, 'note_ref')}\n\nRun:\n  cambrian notes list", file=sys.stderr)
            sys.exit(1)
        note = store.load(note_path)
        payload = note.to_dict()
        payload["note_path"] = _relative_note_path(note_path)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_note_show(note, payload["note_path"]))
        return

    if command == "resolve":
        try:
            note_path = store.resolve_path(root, str(getattr(args, "note_ref")))
        except FileNotFoundError:
            print(f"Note not found: {getattr(args, 'note_ref')}\n\nRun:\n  cambrian notes list", file=sys.stderr)
            sys.exit(1)
        store.resolve(note_path, getattr(args, "resolution", None))
        note = store.load(note_path)
        payload = note.to_dict()
        payload["note_path"] = _relative_note_path(note_path)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_note_resolve_summary(note))
        return

    print("notes 하위 명령이 필요합니다. 예: cambrian notes list", file=sys.stderr)
    sys.exit(1)


def _handle_doctor(args: argparse.Namespace) -> None:
    """cambrian doctor 처리."""
    from engine.project_doctor import ProjectDoctor, render_doctor_report
    from engine.project_errors import hint_for_doctor_report, render_recovery_hint

    workspace = Path(str(getattr(args, "workspace", "."))).resolve()
    report = ProjectDoctor().run(workspace)
    payload = report.to_dict()
    recovery_hint = hint_for_doctor_report(payload)
    _save_recovery_hint(workspace, recovery_hint)
    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    text = render_doctor_report(report)
    if recovery_hint is not None:
        text = "\n\n".join([render_recovery_hint(recovery_hint), text])
    print(text)


def _handle_alpha(args: argparse.Namespace) -> None:
    """cambrian alpha check 처리."""
    from engine.project_alpha_audit import (
        AlphaReadinessStore,
        ProjectAlphaAudit,
        default_alpha_audit_path,
        render_alpha_readiness,
    )
    from engine.project_errors import hint_for_alpha_report, render_recovery_hint

    if getattr(args, "alpha_command", None) != "check":
        print("alpha 하위 명령이 필요합니다. 예: cambrian alpha check --save", file=sys.stderr)
        sys.exit(1)

    root = Path.cwd()
    report = ProjectAlphaAudit().run(root)
    if getattr(args, "save", False):
        output_path = (
            Path(str(getattr(args, "out"))).resolve()
            if getattr(args, "out", None)
            else default_alpha_audit_path(root)
        )
        AlphaReadinessStore().save(report, output_path)
    payload = report.to_dict()
    recovery_hint = hint_for_alpha_report(payload)
    _save_recovery_hint(root, recovery_hint)
    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    text = render_alpha_readiness(report)
    if recovery_hint is not None:
        text = "\n\n".join([text, render_recovery_hint(recovery_hint)])
    print(text)


def _handle_demo(args: argparse.Namespace) -> None:
    """cambrian demo 처리."""
    from engine.demo_project import DemoProjectCreator, render_demo_create_summary

    if getattr(args, "demo_command", None) != "create":
        print(
            "demo 하위 명령이 필요합니다. 예: cambrian demo create login-bug --out ./demo",
            file=sys.stderr,
        )
        sys.exit(1)

    result = DemoProjectCreator().create(
        str(getattr(args, "demo_name")),
        Path(str(getattr(args, "out"))),
        force=bool(getattr(args, "force", False)),
    )
    if getattr(args, "json_output", False):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    print(render_demo_create_summary(result))
    if result.status in {"blocked", "error"}:
        sys.exit(1)


def _handle_memory(args: argparse.Namespace) -> None:
    """cambrian memory 처리."""
    from engine.project_memory import (
        ProjectMemory,
        ProjectMemoryBuilder,
        ProjectMemoryStore,
        default_memory_path,
        find_memory_lesson,
        list_memory_lessons,
        load_project_memory,
        render_memory_list,
        render_memory_rebuild_summary,
        render_memory_review,
        render_memory_show,
    )
    from engine.project_memory_hygiene import (
        MemoryHygieneChecker,
        MemoryHygieneStore,
        default_memory_hygiene_path,
        hygiene_index,
        load_memory_hygiene,
        render_memory_hygiene,
    )
    from engine.project_memory_overrides import (
        MemoryOverrideStore,
        default_memory_overrides_path,
    )
    from engine.project_memory_router import render_memory_recommendation
    from engine.project_mode import ProjectRunPreparer
    from engine.project_router import ProjectSkillRouter

    root = Path.cwd()
    command = getattr(args, "memory_command", None)
    if not command:
        print("memory 하위 명령이 필요합니다. 예: cambrian memory hygiene", file=sys.stderr)
        sys.exit(1)

    def _load_memory_or_exit() -> ProjectMemory:
        memory = load_project_memory(root)
        if memory is None:
            print("Project memory가 아직 없습니다. 먼저 `cambrian memory rebuild`를 실행하세요.", file=sys.stderr)
            sys.exit(1)
        return memory

    def _load_hygiene_map() -> dict[str, dict]:
        report = load_memory_hygiene(root)
        if report is None:
            return {}
        return {item.lesson_id: item.to_dict() for item in report.items}

    def _require_lesson(memory: ProjectMemory, lesson_id: str):
        lesson = find_memory_lesson(memory, lesson_id)
        if lesson is None:
            print(f"Lesson not found: {lesson_id}\n\nRun:\n  cambrian memory list", file=sys.stderr)
            sys.exit(1)
        return lesson

    if command == "recommend":
        try:
            configs = ProjectRunPreparer._load_configs(root)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        intent = ProjectSkillRouter().route(
            user_request=str(getattr(args, "request")),
            project_config=configs["project"],
            rules=configs["rules"],
            skills=configs["skills"],
            profile=configs["profile"],
            explicit_options={"project_root": str(root)},
        )
        memory_context = dict(intent.memory_context or {})
        relevant_lessons = list(memory_context.get("relevant_lessons", []))
        routes = [route.to_dict() for route in intent.routes]
        next_actions = list(memory_context.get("next_actions", []))
        next_actions.append(f'cambrian do "{getattr(args, "request")}"')

        payload = {
            "request": str(getattr(args, "request")),
            "memory_context": memory_context,
            "relevant_lessons": relevant_lessons[: int(getattr(args, "limit", 5) or 5)],
            "routes": routes,
            "selected_skills": intent.selected_skills(),
            "warnings": list(intent.safety_warnings),
            "next_actions": list(dict.fromkeys(next_actions)),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(
            render_memory_recommendation(
                user_request=payload["request"],
                relevant_lessons=payload["relevant_lessons"],
                routes=payload["routes"],
                next_actions=payload["next_actions"],
            )
        )
        return

    if command == "rebuild":
        output_path = Path(getattr(args, "out", None)).resolve() if getattr(args, "out", None) else default_memory_path(root)
        memory = ProjectMemoryBuilder().build(root, limit=getattr(args, "limit", None))
        ProjectMemoryStore().save(memory, output_path)
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "rebuilt", "output": str(output_path), "memory": memory.to_dict()}, indent=2, ensure_ascii=False))
            return
        print(render_memory_rebuild_summary(memory, str(output_path)))
        return

    if command == "hygiene":
        checker = MemoryHygieneChecker()
        report = checker.check(root)
        report_path = Path(getattr(args, "out", None)).resolve() if getattr(args, "out", None) else default_memory_hygiene_path(root)
        MemoryHygieneStore().save(report, report_path)
        items = report.items
        status_filter = getattr(args, "status", None)
        if status_filter:
            items = [item for item in items if item.status == status_filter]
        if not getattr(args, "include_suppressed", False):
            items = [item for item in items if item.status != "suppressed"]
        filtered_report = MemoryHygieneStore().load(report_path)
        filtered_report.items = items
        filtered_report.summary = {
            **report.summary,
            "displayed": len(items),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(filtered_report.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_memory_hygiene(filtered_report, include_suppressed=bool(getattr(args, "include_suppressed", False))))
        return

    memory = _load_memory_or_exit()
    hygiene_map = _load_hygiene_map()

    if command in {"list", "review"}:
        lessons = list_memory_lessons(
            memory,
            include_suppressed=bool(getattr(args, "include_suppressed", False)),
            kind=getattr(args, "kind", None),
            tag=getattr(args, "tag", None),
            limit=getattr(args, "limit", None),
        )
        filtered_memory = ProjectMemory(
            schema_version=memory.schema_version,
            generated_at=memory.generated_at,
            project_name=memory.project_name,
            lessons=lessons,
            sources_scanned=memory.sources_scanned,
            warnings=list(memory.warnings),
            errors=list(memory.errors),
        )
        if getattr(args, "json_output", False):
            print(json.dumps(filtered_memory.to_dict(), indent=2, ensure_ascii=False))
            return
        if command == "review":
            print(
                render_memory_review(
                    filtered_memory,
                    include_suppressed=bool(getattr(args, "include_suppressed", False)),
                    hygiene_map=hygiene_map,
                )
            )
            return
        print(render_memory_list(filtered_memory, lessons, hygiene_map=hygiene_map))
        return

    if command == "show":
        lesson = _require_lesson(memory, str(getattr(args, "lesson_id")))
        hygiene_item = hygiene_map.get(lesson.lesson_id)
        if getattr(args, "json_output", False):
            print(json.dumps({"lesson": lesson.to_dict(), "hygiene": hygiene_item}, indent=2, ensure_ascii=False))
            return
        print(render_memory_show(lesson, hygiene_item=hygiene_item))
        return

    if command in {"pin", "unpin", "suppress", "unsuppress", "note"}:
        lesson_id = str(getattr(args, "lesson_id"))
        _require_lesson(memory, lesson_id)
        overrides_path = default_memory_overrides_path(root)
        store = MemoryOverrideStore()
        if command == "pin":
            overrides = store.set_pin(overrides_path, lesson_id, True)
            payload = {"status": "updated", "lesson_id": lesson_id, "pinned": True, "suppressed": False}
        elif command == "unpin":
            overrides = store.set_pin(overrides_path, lesson_id, False)
            payload = {"status": "updated", "lesson_id": lesson_id, "pinned": False}
        elif command == "suppress":
            overrides = store.set_suppressed(overrides_path, lesson_id, True)
            payload = {"status": "updated", "lesson_id": lesson_id, "pinned": False, "suppressed": True}
        elif command == "unsuppress":
            overrides = store.set_suppressed(overrides_path, lesson_id, False)
            payload = {"status": "updated", "lesson_id": lesson_id, "suppressed": False}
        else:
            if getattr(args, "clear", False):
                note_value = None
            else:
                note_value = getattr(args, "note", None)
                if not note_value:
                    print("Error: --note 또는 --clear 가 필요합니다.", file=sys.stderr)
                    sys.exit(1)
            overrides = store.set_note(overrides_path, lesson_id, note_value)
            payload = {"status": "updated", "lesson_id": lesson_id, "note": note_value}
        payload["overrides_path"] = str(overrides_path)
        payload["override"] = overrides.overrides.get(lesson_id).to_dict() if lesson_id in overrides.overrides else {}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print(f"지원하지 않는 memory 명령입니다: {command}", file=sys.stderr)
    sys.exit(1)


def _handle_do(args: argparse.Namespace) -> None:
    """cambrian do 처리."""
    from engine.project_do import ProjectDoRunner, render_do_summary
    from engine.project_errors import hint_for_do_session

    session = ProjectDoRunner().run(
        user_request=getattr(args, "request"),
        project_root=Path.cwd(),
        options={
            "use_suggestion": getattr(args, "use_suggestion", None),
            "sources": list(getattr(args, "do_sources", []) or []),
            "tests": list(getattr(args, "do_tests", []) or []),
            "execute": bool(getattr(args, "execute", False)),
            "no_scan": bool(getattr(args, "no_scan", False)),
        },
    )
    payload = session.to_dict()
    recovery_hint = hint_for_do_session(payload)
    _save_recovery_hint(Path.cwd(), recovery_hint)

    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(render_do_summary(session))


def _handle_do_v2(args: argparse.Namespace) -> None:
    """확장된 cambrian do 처리."""
    from engine.project_continue import (
        ProjectDoContinuationRunner,
        render_do_continue_summary,
    )
    from engine.project_do import ProjectDoRunner, render_do_summary
    from engine.project_errors import hint_for_continue_session, hint_for_do_session

    common_options = {
        "session": getattr(args, "session", None),
        "agent": getattr(args, "agent", None),
        "use_suggestion": getattr(args, "use_suggestion", None),
        "sources": list(getattr(args, "do_sources", []) or []),
        "tests": list(getattr(args, "do_tests", []) or []),
        "old_choice": getattr(args, "old_choice", None),
        "old_text": getattr(args, "old_text", None),
        "old_text_file": getattr(args, "old_text_file", None),
        "new_text": getattr(args, "new_text", None),
        "new_text_file": getattr(args, "new_text_file", None),
        "propose": bool(getattr(args, "propose", False)),
        "validate": bool(getattr(args, "validate", False)),
        "apply": bool(getattr(args, "apply_patch", False)),
        "reason": getattr(args, "reason", None),
        "execute": bool(getattr(args, "execute", False)),
        "no_scan": bool(getattr(args, "no_scan", False)),
    }

    if getattr(args, "continue_session", False):
        session = ProjectDoContinuationRunner().run(
            project_root=Path.cwd(),
            options=common_options,
        )
        payload = session.to_dict()
        recovery_hint = hint_for_continue_session(payload)
        _save_recovery_hint(Path.cwd(), recovery_hint)
        try:
            from engine.project_pack_usage import safe_record_pack_usage_event

            safe_record_pack_usage_event(
                Path.cwd(),
                event_kind="used",
                surface_kind="continue",
                request=session.user_request,
                request_class=(
                    session.metrics_context.get("request_class")
                    if isinstance(session.metrics_context, dict)
                    else None
                )
                or ((session.intent or {}).get("intent_type") if isinstance(session.intent, dict) else None),
                linked_session_id=session.session_id,
                linked_session_ref=session.artifacts.get("session_path"),
                linked_request_ref=session.artifacts.get("request_path"),
                linked_bridge_reply_ref=session.bridge_context.get("reply_ref") if isinstance(session.bridge_context, dict) else None,
                summary="active pack used in continue",
            )
        except Exception as exc:
            logger.warning("pack usage continue event failed: %s", exc)
        if getattr(args, "json_output", False):
            print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
            return
        print(render_do_continue_summary(session))
        return

    if not getattr(args, "request", None):
        print("Error: do 요청 문자열이 필요합니다. 또는 --continue 를 사용하세요.", file=sys.stderr)
        sys.exit(1)

    session = ProjectDoRunner().run(
        user_request=getattr(args, "request"),
        project_root=Path.cwd(),
        options=common_options,
    )
    payload = session.to_dict()
    recovery_hint = hint_for_do_session(payload)
    _save_recovery_hint(Path.cwd(), recovery_hint)
    try:
        from engine.project_pack_usage import safe_record_pack_usage_event

        safe_record_pack_usage_event(
            Path.cwd(),
            event_kind="used",
            surface_kind="do",
            request=session.user_request,
            request_class=(
                session.metrics_context.get("request_class")
                if isinstance(session.metrics_context, dict)
                else None
            )
            or ((session.intent or {}).get("intent_type") if isinstance(session.intent, dict) else None),
            linked_session_id=session.session_id,
            linked_session_ref=session.artifacts.get("session_path"),
            linked_request_ref=session.artifacts.get("request_path"),
            summary="active pack used in do",
        )
    except Exception as exc:
        logger.warning("pack usage do event failed: %s", exc)

    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(render_do_summary(session))


def _handle_clarify(args: argparse.Namespace) -> None:
    """cambrian clarify 처리."""
    from engine.project_clarifier import RunClarifier, render_clarification_summary
    from engine.project_errors import hint_for_clarification

    root = Path.cwd()
    clarifier = RunClarifier()
    clarification_path = clarifier.resolve_artifact_path(
        getattr(args, "clarification_ref"),
        root,
    )

    has_answer = bool(getattr(args, "clarify_sources", [])) or bool(
        getattr(args, "clarify_tests", [])
    ) or getattr(args, "use_suggestion", None) is not None or getattr(args, "mode", None) is not None

    if has_answer:
        session = clarifier.answer(
            clarification_path,
            source=list(getattr(args, "clarify_sources", []) or []),
            tests=list(getattr(args, "clarify_tests", []) or []),
            use_suggestion=getattr(args, "use_suggestion", None),
            mode=getattr(args, "mode", None),
        )
    else:
        session = clarifier.load(clarification_path)

    if getattr(args, "execute", False):
        session = clarifier.execute_ready(clarification_path)
    payload = session.to_dict()
    recovery_hint = hint_for_clarification(payload)
    _save_recovery_hint(root, recovery_hint)

    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(render_clarification_summary(session))


def _handle_context(args: argparse.Namespace) -> None:
    """cambrian context 처리."""
    if getattr(args, "context_command", None) == "scan":
        _handle_context_scan(args)
        return
    print("context 하위 명령이 필요합니다. 예: cambrian context scan \"로그인 에러 수정해\"", file=sys.stderr)
    sys.exit(1)


def _handle_context_scan(args: argparse.Namespace) -> None:
    """cambrian context scan 처리."""
    from engine.project_context import ProjectContextScanner, render_context_scan_summary
    from engine.project_errors import hint_for_context_scan

    root = Path.cwd()
    scanner = ProjectContextScanner()
    project_payload = None
    rules_payload = None
    project_path = root / ".cambrian" / "project.yaml"
    rules_path = root / ".cambrian" / "rules.yaml"
    if project_path.exists():
        loaded = yaml.safe_load(project_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            project_payload = loaded
    if rules_path.exists():
        loaded = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            rules_payload = loaded

    result = scanner.scan(
        user_request=args.request,
        project_root=root,
        project_config=project_payload,
        rules=rules_payload,
        limit=int(getattr(args, "limit", 10)),
    )
    out_path = (
        Path(getattr(args, "out", "")).resolve()
        if getattr(args, "out", None)
        else root / ".cambrian" / "context" / f"context_{result.request_id}.yaml"
    )
    scanner.save(result, out_path)
    payload = result.to_dict()
    payload["artifact_path"] = str(out_path)
    recovery_hint = hint_for_context_scan(payload)
    _save_recovery_hint(root, recovery_hint)

    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(
        render_context_scan_summary(
            result,
            artifact_path=str(out_path.relative_to(root)).replace("\\", "/")
            if out_path.is_relative_to(root) else str(out_path),
        )
    )


def _handle_patch(args: argparse.Namespace) -> None:
    """cambrian patch 처리."""
    if getattr(args, "patch_command", None) == "intent":
        _handle_patch_intent(args)
        return
    if getattr(args, "patch_command", None) == "intent-fill":
        _handle_patch_intent_fill(args)
        return
    if getattr(args, "patch_command", None) == "propose":
        _handle_patch_propose(args)
        return
    if getattr(args, "patch_command", None) == "apply":
        _handle_patch_apply(args)
        return
    print("patch 하위 명령이 필요합니다. 예: cambrian patch propose --target src/a.py ...", file=sys.stderr)
    sys.exit(1)


def _patch_maybe_relative(workspace: Path, raw_path: str | None) -> str | None:
    """workspace 기준 상대 경로로 정규화한다."""
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        return str(path.resolve().relative_to(workspace)).replace("\\", "/")
    except ValueError:
        return raw_path


def _load_patch_rules_payload(workspace: Path) -> dict | None:
    """patch 계열 명령에서 rules.yaml을 로드한다."""
    rules_path = workspace / ".cambrian" / "rules.yaml"
    if not rules_path.exists():
        return None
    loaded = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        return loaded
    return None


def _proposal_payload_with_path(
    proposal: object,
    proposal_path: Path,
    workspace: Path,
) -> dict:
    """proposal payload에 relative proposal_path를 추가한다."""
    payload = proposal.to_dict() if hasattr(proposal, "to_dict") else dict(proposal)
    payload["proposal_path"] = (
        str(proposal_path.relative_to(workspace)).replace("\\", "/")
        if proposal_path.is_relative_to(workspace) else str(proposal_path)
    )
    return payload


def _blocked_patch_proposal_payload(
    reasons: list[str],
    next_actions: list[str] | None = None,
) -> dict:
    """proposal 생성 전 차단 결과를 공통 형식으로 만든다."""
    return {
        "proposal_status": "blocked",
        "safety_warnings": list(reasons),
        "next_actions": list(next_actions or []),
        "validation": {
            "attempted": False,
            "status": "not_requested",
        },
        "related_tests": [],
        "target_path": "",
    }


def _build_patch_proposal_from_values(
    *,
    workspace: Path,
    target: str,
    old_text: str | None,
    new_text: str | None,
    patch_file: str | None,
    related_tests: list[str],
    source_diagnosis_ref: str | None,
    source_context_ref: str | None,
    user_request: str | None,
    memory_guidance_ref: dict | None,
    out_dir: Path,
    execute: bool,
):
    """기본 입력값으로 patch proposal을 생성한다."""
    from engine.project_patch import PatchIntent, PatchProposalBuilder

    intent = PatchIntent(
        target_path=target,
        old_text=old_text,
        new_text=new_text,
        patch_file_path=patch_file,
        related_tests=list(related_tests),
        source_diagnosis_ref=source_diagnosis_ref,
        source_context_ref=source_context_ref,
        user_request=user_request,
        memory_guidance_ref=memory_guidance_ref,
    )
    proposal, proposal_path = PatchProposalBuilder().build(
        intent=intent,
        project_root=workspace,
        out_dir=out_dir,
        rules=_load_patch_rules_payload(workspace),
        execute=execute,
    )
    return proposal, proposal_path


def _handle_patch_intent(args: argparse.Namespace) -> None:
    """cambrian patch intent 처리."""
    from engine.project_patch_intent import (
        PatchIntentBuilder,
        PatchIntentStore,
        render_patch_intent_summary,
    )
    from engine.project_errors import hint_for_patch_intent

    workspace = Path.cwd().resolve()
    diagnosis_report = Path(getattr(args, "diagnosis_report")).resolve()
    form = PatchIntentBuilder().build_from_diagnosis(
        diagnosis_report_path=diagnosis_report,
        project_root=workspace,
        target_path=getattr(args, "target", None),
    )
    out_dir = (
        Path(getattr(args, "patch_intent_out_dir")).resolve()
        if getattr(args, "patch_intent_out_dir", None)
        else workspace / ".cambrian" / "patch_intents"
    )
    target_label = Path(form.target_path or "unknown").name or "unknown"
    intent_path = out_dir / f"patch_intent_{form.intent_id}_{target_label}.yaml"
    PatchIntentStore().save(form, intent_path)
    intent_path_rel = (
        str(intent_path.relative_to(workspace)).replace("\\", "/")
        if intent_path.is_relative_to(workspace) else str(intent_path)
    )
    payload = form.to_dict()
    payload["intent_path"] = intent_path_rel
    recovery_hint = hint_for_patch_intent(payload)
    _save_recovery_hint(workspace, recovery_hint)

    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(render_patch_intent_summary(form, intent_path=intent_path_rel))


def _handle_patch_intent_fill(args: argparse.Namespace) -> None:
    """cambrian patch intent-fill 처리."""
    from engine.project_patch import render_patch_proposal_summary
    from engine.project_errors import hint_for_patch_intent, hint_for_patch_proposal
    from engine.project_patch_intent import (
        PatchIntentStore,
        PatchIntentFiller,
        render_patch_intent_summary,
    )

    workspace = Path.cwd().resolve()
    intent_path = Path(getattr(args, "intent_path")).resolve()
    store = PatchIntentStore()
    form = PatchIntentFiller().fill(
        intent_path=intent_path,
        old_choice=getattr(args, "old_choice", None),
        old_text=getattr(args, "old_text", None),
        new_text=getattr(args, "new_text", None),
        new_text_file=Path(getattr(args, "new_text_file")).resolve()
        if getattr(args, "new_text_file", None) else None,
        old_text_file=Path(getattr(args, "old_text_file")).resolve()
        if getattr(args, "old_text_file", None) else None,
    )

    should_propose = bool(getattr(args, "propose", False) or getattr(args, "execute", False))
    if should_propose:
        if form.status != "ready_for_proposal" or not form.target_path:
            payload = _blocked_patch_proposal_payload(
                reasons=[
                    "intent is not ready_for_proposal",
                    *list(form.errors),
                ],
                next_actions=list(form.next_actions),
            )
            recovery_hint = hint_for_patch_proposal(payload)
            _save_recovery_hint(workspace, recovery_hint)
            if getattr(args, "json_output", False):
                print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
                return
            print(render_patch_proposal_summary(payload))
            return

        proposal, proposal_path = _build_patch_proposal_from_values(
            workspace=workspace,
            target=form.target_path,
            old_text=form.selected_old_text,
            new_text=form.new_text,
            patch_file=None,
            related_tests=list(form.related_tests),
            source_diagnosis_ref=_patch_maybe_relative(workspace, form.source_diagnosis_ref),
            source_context_ref=_patch_maybe_relative(workspace, form.source_context_ref),
            user_request=form.user_request,
            memory_guidance_ref=dict(form.memory_guidance),
            out_dir=workspace / ".cambrian" / "patches",
            execute=bool(getattr(args, "execute", False)),
        )
        proposal_payload = _proposal_payload_with_path(proposal, proposal_path, workspace)
        form.proposal_path = proposal_payload["proposal_path"]
        store.save(form, intent_path)
        proposal_payload["intent_path"] = (
            str(intent_path.relative_to(workspace)).replace("\\", "/")
            if intent_path.is_relative_to(workspace) else str(intent_path)
        )
        recovery_hint = hint_for_patch_proposal(proposal_payload)
        _save_recovery_hint(workspace, recovery_hint)
        if getattr(args, "json_output", False):
            print(json.dumps(_attach_recovery_payload(proposal_payload, recovery_hint), indent=2, ensure_ascii=False))
            return
        print(
            render_patch_proposal_summary(
                proposal,
                proposal_path=proposal_payload["proposal_path"],
            )
        )
        return

    payload = form.to_dict()
    payload["intent_path"] = (
        str(intent_path.relative_to(workspace)).replace("\\", "/")
        if intent_path.is_relative_to(workspace) else str(intent_path)
    )
    recovery_hint = hint_for_patch_intent(payload)
    _save_recovery_hint(workspace, recovery_hint)
    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return
    print(render_patch_intent_summary(form, intent_path=payload["intent_path"]))


def _handle_patch_propose(args: argparse.Namespace) -> None:
    """cambrian patch propose 처리."""
    from engine.project_patch import (
        render_patch_proposal_summary,
    )
    from engine.project_errors import hint_for_patch_proposal
    from engine.project_patch_intent import PatchIntentStore

    workspace = Path(getattr(args, "workspace", ".")).resolve()
    out_dir = (
        Path(getattr(args, "patch_out_dir")).resolve()
        if getattr(args, "patch_out_dir", None)
        else workspace / ".cambrian" / "patches"
    )

    if getattr(args, "from_intent", None):
        intent_path = Path(getattr(args, "from_intent")).resolve()
        form = PatchIntentStore().load(intent_path)
        if form.status != "ready_for_proposal" or not form.target_path or form.selected_old_text is None or form.new_text is None:
            payload = _blocked_patch_proposal_payload(
                reasons=[
                    "intent is not ready_for_proposal",
                    *list(form.errors),
                ],
                next_actions=list(form.next_actions),
            )
            recovery_hint = hint_for_patch_proposal(payload)
            _save_recovery_hint(workspace, recovery_hint)
            if getattr(args, "json_output", False):
                print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
                return
            print(render_patch_proposal_summary(payload))
            return

        proposal, proposal_path = _build_patch_proposal_from_values(
            workspace=workspace,
            target=form.target_path,
            old_text=form.selected_old_text,
            new_text=form.new_text,
            patch_file=None,
            related_tests=list(form.related_tests),
            source_diagnosis_ref=_patch_maybe_relative(workspace, form.source_diagnosis_ref),
            source_context_ref=_patch_maybe_relative(workspace, form.source_context_ref),
            user_request=form.user_request,
            memory_guidance_ref=dict(form.memory_guidance),
            out_dir=out_dir,
            execute=bool(getattr(args, "execute", False)),
        )
        proposal_payload = _proposal_payload_with_path(proposal, proposal_path, workspace)
        form.proposal_path = proposal_payload["proposal_path"]
        PatchIntentStore().save(form, intent_path)
    else:
        if not getattr(args, "target", None):
            print("Error: --target 이 필요합니다.", file=sys.stderr)
            sys.exit(1)
        proposal, proposal_path = _build_patch_proposal_from_values(
            workspace=workspace,
            target=str(getattr(args, "target")),
            old_text=getattr(args, "old_text", None),
            new_text=getattr(args, "new_text", None),
            patch_file=getattr(args, "patch_file", None),
            related_tests=list(getattr(args, "related_tests", []) or []),
            source_diagnosis_ref=_patch_maybe_relative(workspace, getattr(args, "from_diagnosis", None)),
            source_context_ref=_patch_maybe_relative(workspace, getattr(args, "from_context", None)),
            user_request=getattr(args, "request", None),
            memory_guidance_ref=None,
            out_dir=out_dir,
            execute=bool(getattr(args, "execute", False)),
        )
        proposal_payload = _proposal_payload_with_path(proposal, proposal_path, workspace)

    recovery_hint = hint_for_patch_proposal(proposal_payload)
    _save_recovery_hint(workspace, recovery_hint)
    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(proposal_payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(
        render_patch_proposal_summary(
            proposal,
            proposal_path=proposal_payload["proposal_path"],
        )
    )


def _handle_patch_apply(args: argparse.Namespace) -> None:
    """cambrian patch apply 처리."""
    from engine.project_patch_apply import (
        PatchApplier,
        render_patch_apply_summary,
    )
    from engine.project_errors import hint_for_patch_apply

    workspace = Path(getattr(args, "workspace", ".")).resolve()
    adoptions_dir = (
        Path(getattr(args, "adoptions_dir")).resolve()
        if getattr(args, "adoptions_dir", None)
        else workspace / ".cambrian" / "adoptions"
    )
    proposal_path = Path(getattr(args, "proposal_path")).resolve()

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=workspace,
        adoptions_dir=adoptions_dir,
        reason=str(getattr(args, "reason", "") or ""),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    payload = result.to_dict()
    recovery_hint = hint_for_patch_apply(payload)
    _save_recovery_hint(workspace, recovery_hint)

    if getattr(args, "json_output", False):
        print(json.dumps(_attach_recovery_payload(payload, recovery_hint), indent=2, ensure_ascii=False))
        return

    print(render_patch_apply_summary(result))


def _handle_acquire(args: argparse.Namespace) -> None:
    """cambrian acquire 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.models import AcquireRequest

    if not args.project and not args.goal:
        print("Error: --project 또는 --goal 중 하나는 필수", file=sys.stderr)
        sys.exit(1)

    engine = _create_engine(args)
    request = AcquireRequest(
        project_path=args.project,
        goal=args.goal,
        domain=getattr(args, "domain", None),
        tags=getattr(args, "tags", None),
        mode=getattr(args, "acq_mode", "advisory"),
        strategy=getattr(args, "strategy", "conservative"),
        allow_fuse=not getattr(args, "no_fuse", False),
        allow_generate=not getattr(args, "no_generate", False),
        max_actions=getattr(args, "max_actions", 3),
        dry_run=getattr(args, "dry_run", False),
    )
    result = engine.acquire(request)

    if getattr(args, "json_output", False):
        print(json.dumps(_acquire_result_to_dict(result), indent=2, ensure_ascii=False))
    else:
        _print_acquire_result(result)


def _acquire_result_to_dict(result: "AcquireResult") -> dict:
    """AcquireResult를 JSON 직렬화 가능한 dict로 변환한다.

    Args:
        result: acquire 결과

    Returns:
        dict
    """
    plan_dict = None
    if result.plan:
        plan_dict = {
            "actions": [
                {
                    "action_type": a.action_type,
                    "gap_category": a.gap_category,
                    "description": a.description,
                    "confidence": a.confidence,
                    "risk": a.risk,
                    "reuse_skill_id": a.reuse_skill_id,
                    "fuse_skill_a": a.fuse_skill_a,
                    "fuse_skill_b": a.fuse_skill_b,
                    "generate_goal": a.generate_goal,
                }
                for a in result.plan.actions
            ],
            "total_gaps": result.plan.total_gaps,
            "addressable_gaps": result.plan.addressable_gaps,
            "deferred_gaps": result.plan.deferred_gaps,
        }

    executed_dict = [
        {
            "action_type": e.action.action_type,
            "executed": e.executed,
            "success": e.success,
            "skill_id": e.skill_id,
            "error": e.error,
            "skipped_reason": e.skipped_reason,
        }
        for e in result.executed_actions
    ]

    return {
        "success": result.success,
        "mode": result.mode,
        "strategy": result.strategy,
        "plan": plan_dict,
        "executed_actions": executed_dict,
        "summary": result.summary,
        "warnings": result.warnings,
    }


def _print_acquire_result(result: "AcquireResult") -> None:
    """AcquireResult를 표 형태로 출력한다.

    Args:
        result: acquire 결과
    """
    print(f"Acquire ({result.mode} / {result.strategy})")
    print("═" * 55)

    if result.scan_report:
        fp = result.scan_report.fingerprint
        print(f"Scan: {fp.project_name} ({fp.total_files} files)")
        if fp.detected_capabilities:
            print(f"  Capabilities: {', '.join(fp.detected_capabilities)}")
        print(f"  Gaps: {result.scan_report.total_gaps} found")
        print()

    if result.plan:
        print("─" * 55)
        print(f"Plan ({len(result.plan.actions)} actions)")
        print("─" * 55)

        if result.plan.actions:
            print(f"{'#':<3} {'TYPE':<10} {'CONF':<6} {'RISK':<6} {'GAP':<18} ACTION")
            for idx, action in enumerate(result.plan.actions):
                print(
                    f"{idx + 1:<3} "
                    f"{action.action_type:<10} "
                    f"{action.confidence:<6.2f} "
                    f"{action.risk:<6} "
                    f"{action.gap_category:<18} "
                    f"{action.description[:40]}"
                )
        else:
            print("No actions generated.")

        print()
        print(
            f"Addressable: {result.plan.addressable_gaps}/{result.plan.total_gaps} gaps"
            f" | Deferred: {result.plan.deferred_gaps}"
        )

    if result.executed_actions:
        print()
        print("─" * 55)
        print("Executed Actions")
        print("─" * 55)
        print(f"{'#':<3} {'TYPE':<10} {'RESULT':<8} {'DETAIL'}")
        for idx, e in enumerate(result.executed_actions):
            if e.executed:
                status = "[OK]" if e.success else "[FAIL]"
                detail = e.skill_id or e.error or ""
            else:
                status = "[SKIP]"
                detail = e.skipped_reason
            print(
                f"{idx + 1:<3} "
                f"{e.action.action_type:<10} "
                f"{status:<8} "
                f"{detail[:40]}"
            )

    print()
    print("─" * 55)
    print(f"Summary: {result.summary}")

    if result.mode == "advisory" and result.plan and result.plan.addressable_gaps > 0:
        print("\nTo execute: cambrian acquire ... --mode execute --strategy balanced")

    if result.warnings:
        for w in result.warnings:
            print(f"  Warning: {w}")


def _handle_generate(args: argparse.Namespace) -> None:
    """cambrian generate 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.models import GenerateRequest

    engine = _create_engine(args)
    request = GenerateRequest(
        goal=args.goal,
        domain=args.domain,
        tags=args.tags,
        output_id=getattr(args, "output_id", None),
        dry_run=getattr(args, "dry_run", False),
        skip_search=getattr(args, "skip_search", False),
        reference_skills=getattr(args, "reference_skills", None),
    )
    result = engine.generate(request)

    if getattr(args, "json_output", False):
        output = {
            "success": result.success,
            "skill_id": result.skill_id,
            "skill_path": result.skill_path,
            "goal": result.goal,
            "domain": result.domain,
            "tags": result.tags,
            "output_mode": result.output_mode,
            "generation_rationale": result.generation_rationale,
            "reference_skill_ids": result.reference_skill_ids,
            "validation_passed": result.validation_passed,
            "validation_errors": result.validation_errors,
            "security_passed": result.security_passed,
            "security_violations": result.security_violations,
            "registered": result.registered,
            "dry_run": result.dry_run,
            "existing_alternatives": result.existing_alternatives,
            "warnings": result.warnings,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        _print_generate_result(result)

    if not result.success and not result.existing_alternatives:
        sys.exit(1)


def _print_generate_result(result: "GenerateResult") -> None:
    """GenerateResult를 표 형태로 출력한다.

    Args:
        result: 생성 결과
    """
    print(f"Generate: {result.domain}/{','.join(result.tags)}")
    print(f"Goal: {result.goal}")
    print("─" * 50)

    if result.existing_alternatives:
        print("[SKIP] Generate unnecessary — similar skills found:")
        for alt in result.existing_alternatives:
            print(
                f"  - {alt['skill_id']} (relevance: {alt['relevance_score']:.2f})"
            )
        return

    if result.success:
        prefix = "[DRY-RUN]" if result.dry_run else "[OK]"
        print(f"{prefix} Generated → '{result.skill_id}'")
        if result.generation_rationale:
            print(f"  Rationale: {result.generation_rationale}")
        print(f"  Mode: {result.output_mode}")
        if result.reference_skill_ids:
            print(f"  References: {', '.join(result.reference_skill_ids)}")
        print(f"  Path: {result.skill_path}")
        print(f"  Validation: {'PASS' if result.validation_passed else 'FAIL'}")
        print(f"  Security: {'PASS' if result.security_passed else 'FAIL'}")
        reg_status = "NO (dry-run)" if result.dry_run else ("YES" if result.registered else "NO")
        print(f"  Registered: {reg_status}")
    else:
        print("[FAIL] Generation failed")
        if result.validation_errors:
            print("  Validation errors:")
            for err in result.validation_errors:
                print(f"    - {err}")
        if result.security_violations:
            print("  Security violations:")
            for vio in result.security_violations:
                print(f"    - {vio}")
        if result.warnings:
            print("  Warnings:")
            for warn in result.warnings:
                print(f"    - {warn}")


def _handle_fuse(args: argparse.Namespace) -> None:
    """cambrian fuse 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.models import FuseRequest

    engine = _create_engine(args)
    request = FuseRequest(
        skill_id_a=args.skill_a,
        skill_id_b=args.skill_b,
        goal=args.goal,
        output_id=getattr(args, "output_id", None),
        dry_run=getattr(args, "dry_run", False),
    )

    try:
        result = engine.fuse(request)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        output = {
            "success": result.success,
            "skill_id": result.skill_id,
            "skill_path": result.skill_path,
            "source_ids": result.source_ids,
            "goal": result.goal,
            "fusion_rationale": result.fusion_rationale,
            "output_mode": result.output_mode,
            "validation_passed": result.validation_passed,
            "validation_errors": result.validation_errors,
            "security_passed": result.security_passed,
            "security_violations": result.security_violations,
            "registered": result.registered,
            "dry_run": result.dry_run,
            "warnings": result.warnings,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        _print_fuse_result(result)

    if not result.success:
        sys.exit(1)


def _print_fuse_result(result: "FuseResult") -> None:
    """FuseResult를 표 형태로 출력한다.

    Args:
        result: 융합 결과
    """
    print(f"Fuse: {' + '.join(result.source_ids)}")
    print(f"Goal: {result.goal}")
    print("─" * 50)

    if result.success:
        prefix = "[DRY-RUN]" if result.dry_run else "[OK]"
        print(f"{prefix} Fused → '{result.skill_id}'")
        if result.fusion_rationale:
            print(f"  Rationale: {result.fusion_rationale}")
        print(f"  Mode: {result.output_mode}")
        print(f"  Path: {result.skill_path}")
        print(f"  Validation: {'PASS' if result.validation_passed else 'FAIL'}")
        print(f"  Security: {'PASS' if result.security_passed else 'FAIL'}")
        reg_status = "NO (dry-run)" if result.dry_run else ("YES" if result.registered else "NO")
        print(f"  Registered: {reg_status}")
    else:
        print("[FAIL] Fusion failed")
        if result.validation_errors:
            print("  Validation errors:")
            for err in result.validation_errors:
                print(f"    - {err}")
        if result.security_violations:
            print("  Security violations:")
            for vio in result.security_violations:
                print(f"    - {vio}")
        if result.warnings:
            print("  Warnings:")
            for warn in result.warnings:
                print(f"    - {warn}")


def _handle_scan(args: argparse.Namespace) -> None:
    """cambrian scan 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    path = Path(args.path)
    if not path.exists():
        print(f"Error: '{args.path}' 경로가 존재하지 않음", file=sys.stderr)
        sys.exit(1)
    if not path.is_dir():
        print(f"Error: '{args.path}'는 디렉토리가 아님", file=sys.stderr)
        sys.exit(1)

    engine = _create_engine(args)
    report = engine.scan(
        project_path=str(path),
        max_depth=args.depth,
        max_queries=args.max_queries,
        top_k=args.top_k,
        run_search=not args.no_search,
    )

    if getattr(args, "json_output", False):
        print(json.dumps(_scan_report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        _print_scan_report(report)


def _handle_bootstrap_harness(args: argparse.Namespace) -> None:
    """cambrian bootstrap-harness 처리.

    프로젝트를 scan한 뒤 .cambrian/harness/ 아티팩트 세트를 생성한다.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.harness import HarnessBootstrapper

    path = Path(args.path)
    if not path.exists():
        print(f"Error: '{args.path}' 경로가 존재하지 않음", file=sys.stderr)
        sys.exit(1)
    if not path.is_dir():
        print(f"Error: '{args.path}'는 디렉토리가 아님", file=sys.stderr)
        sys.exit(1)

    # 1. scan
    engine = _create_engine(args)
    report = engine.scan(
        project_path=str(path),
        max_depth=args.depth,
        run_search=not args.no_search,
    )

    # 2. bootstrap
    bootstrapper = HarnessBootstrapper()
    result = bootstrapper.bootstrap(report, output_dir=path)

    # 3. 출력
    output_dir = str(path / ".cambrian")
    files_created = result.get("files_created", [])
    focus_areas = result.get("focus_areas", [])
    mapping = result.get("gap_candidate_mapping", {})
    next_actions = result.get("next_actions", [])

    if getattr(args, "json_output", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Bootstrap: {path}")
        print("=" * 60)
        print(f"Project: {result.get('project_name', '')}")
        print(f"Output:  {output_dir}")
        print()
        print(f"Artifacts ({len(files_created)}):")
        for art in files_created:
            print(f"  {art}")
        print()
        print(f"Focus Areas ({len(focus_areas)}):")
        for fa in focus_areas:
            print(f"  [{fa['priority'].upper()}] {fa['category']}")
        print()
        print("Candidate Mapping:")
        for cat, info in mapping.items():
            status = info["status"]
            candidates = info.get("candidates", [])
            if candidates:
                names = ", ".join(c["skill_id"] for c in candidates)
                print(f"  {cat}: {names} ({status})")
            else:
                print(f"  {cat}: ({status})")
        print()
        print("Next Actions:")
        for i, action in enumerate(next_actions, 1):
            print(f"  {i}. {action}")
        print()
        print(f"[OK] Harness bootstrap complete → {output_dir}")


def _scan_report_to_dict(report: "ProjectScanReport") -> dict:
    """ProjectScanReport를 JSON 직렬화 가능한 dict로 변환한다.

    Args:
        report: 스캔 보고서

    Returns:
        dict
    """
    fp = report.fingerprint
    return {
        "fingerprint": {
            "project_path": fp.project_path,
            "project_name": fp.project_name,
            "total_files": fp.total_files,
            "total_dirs": fp.total_dirs,
            "languages": fp.languages,
            "primary_language": fp.primary_language,
            "frameworks": fp.frameworks,
            "package_managers": fp.package_managers,
            "project_types": fp.project_types,
            "has_tests": fp.has_tests,
            "has_docs": fp.has_docs,
            "has_ci": fp.has_ci,
            "has_docker": fp.has_docker,
            "has_api": fp.has_api,
            "has_config": fp.has_config,
            "detected_capabilities": fp.detected_capabilities,
            "key_files": fp.key_files,
            "scan_depth": fp.scan_depth,
            "warnings": fp.warnings,
        },
        "gaps": [
            {
                "category": g.category,
                "description": g.description,
                "priority": g.priority,
                "evidence": g.evidence,
                "suggested_domain": g.suggested_domain,
                "suggested_tags": g.suggested_tags,
                "search_query": g.search_query,
            }
            for g in report.gaps
        ],
        "suggestions": [
            {
                "gap_category": s.gap_category,
                "skill_id": s.skill_id,
                "skill_name": s.skill_name,
                "skill_description": s.skill_description,
                "relevance_score": s.relevance_score,
                "source": s.source,
                "match_quality": s.match_quality,
            }
            for s in report.suggestions
        ],
        "total_gaps": report.total_gaps,
        "covered_gaps": report.covered_gaps,
        "uncovered_gaps": report.uncovered_gaps,
        "search_executed": report.search_executed,
        "timestamp": report.timestamp,
    }


def _print_scan_report(report: "ProjectScanReport") -> None:
    """ProjectScanReport를 표 형태로 출력한다.

    Args:
        report: 스캔 보고서
    """
    fp = report.fingerprint
    print(f"Scan: {fp.project_path}")
    print("═" * 60)
    print()
    print(f"Project: {fp.project_name}")
    print(f"Files: {fp.total_files} | Dirs: {fp.total_dirs}")

    if fp.languages:
        lang_parts = [f"{lang} ({count})" for lang, count in sorted(
            fp.languages.items(), key=lambda x: x[1], reverse=True,
        )]
        print(f"Language: {', '.join(lang_parts)}")
    else:
        print("Language: (none detected)")

    if fp.frameworks:
        print(f"Frameworks: {', '.join(fp.frameworks)}")
    print(f"Type: {', '.join(fp.project_types)}")

    if fp.detected_capabilities:
        print(f"Capabilities: {', '.join(fp.detected_capabilities)}")

    # gaps
    print()
    print("─" * 60)
    print(f"Capability Gaps ({report.total_gaps} found)")
    print("─" * 60)

    if not report.gaps:
        print("No gaps found.")
    else:
        print(f"{'#':<3} {'PRI':<6} {'CATEGORY':<20} DESCRIPTION")
        for idx, gap in enumerate(report.gaps):
            print(
                f"{idx + 1:<3} "
                f"{gap.priority.upper():<6} "
                f"{gap.category:<20} "
                f"{gap.description}"
            )

    # suggestions
    if report.search_executed:
        print()
        print("─" * 60)
        print(f"Recommended Skills ({len(report.suggestions)} found)")
        print("─" * 60)

        if report.suggestions:
            print(f"{'GAP':<20} {'SKILL_ID':<18} {'SCORE':<7} {'MATCH':<9} SOURCE")
            for s in report.suggestions:
                source_short = "registry" if s.source == "registry" else "external"
                print(
                    f"{s.gap_category:<20} "
                    f"{s.skill_id:<18} "
                    f"{s.relevance_score:<7.2f} "
                    f"{s.match_quality:<9} "
                    f"{source_short}"
                )

    # summary
    print()
    print("─" * 60)
    print(
        f"Summary: {report.total_gaps} gaps, "
        f"{report.covered_gaps} covered, "
        f"{report.uncovered_gaps} uncovered"
    )
    if report.uncovered_gaps > 0:
        print("Uncovered gaps → consider: cambrian generate")


def _handle_search(args: argparse.Namespace) -> None:
    """cambrian search 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.models import SearchQuery

    engine = _create_engine(args)
    query = SearchQuery(
        text=args.query,
        domain=getattr(args, "domain", None),
        tags=getattr(args, "tags", None),
        include_external=not getattr(args, "no_external", False),
        limit=getattr(args, "limit", 10),
    )
    report = engine.search(query)

    if getattr(args, "json_output", False):
        import dataclasses
        output = {
            "query": args.query,
            "results": [
                {
                    "rank": idx + 1,
                    "skill_id": r.skill_id,
                    "name": r.name,
                    "description": r.description,
                    "domain": r.domain,
                    "tags": r.tags,
                    "relevance_score": r.relevance_score,
                    "fitness_score": r.fitness_score,
                    "source": r.source,
                    "status": r.status,
                }
                for idx, r in enumerate(report.results)
            ],
            "total_scanned": report.total_scanned,
            "registry_hits": report.registry_hits,
            "external_hits": report.external_hits,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # 테이블 출력
    print(
        f'Search: "{args.query}" '
        f"(scanned: {report.registry_hits} registry"
        f" + {report.external_hits} external)"
    )
    print("─" * 70)

    if not report.results:
        print("No results found.")
        return

    print(
        f"{'RANK':<5} {'SCORE':<7} {'ID':<22} {'DOMAIN':<12} "
        f"{'SOURCE':<12} STATUS"
    )
    for idx, result in enumerate(report.results):
        source_short = (
            "registry" if result.source == "registry"
            else "external"
        )
        print(
            f"{idx + 1:<5} "
            f"{result.relevance_score:<7.2f} "
            f"{result.skill_id:<22} "
            f"{result.domain:<12} "
            f"{source_short:<12} "
            f"{result.status}"
        )

    print("─" * 70)
    print(f"{len(report.results)} results found")


def _handle_eval_input(args: argparse.Namespace) -> None:
    """eval-input 서브커맨드를 처리한다.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    registry = engine.get_registry()
    action = getattr(args, "eval_input_action", None)

    if action == "add":
        # JSON 유효성 검증
        try:
            json.loads(args.eval_input_data)
        except json.JSONDecodeError as exc:
            print(f"Error: 유효하지 않은 JSON 입력: {exc}", file=sys.stderr)
            sys.exit(1)

        eval_id = registry.add_evaluation_input(
            skill_id=args.skill_id,
            input_data=args.eval_input_data,
            description=args.desc,
        )
        print(f"Evaluation input added (id={eval_id}) for skill '{args.skill_id}'")

    elif action == "list":
        inputs = registry.get_evaluation_inputs(args.skill_id)
        if not inputs:
            print(f"No evaluation inputs for skill '{args.skill_id}'")
            return

        print(f"Evaluation inputs for '{args.skill_id}':")
        print("─" * 60)
        print(f"{'ID':<6} {'DESCRIPTION':<30} CREATED")
        for item in inputs:
            desc = item["description"][:28] or "(없음)"
            print(f"{item['id']:<6} {desc:<30} {item['created_at'][:19]}")
        print("─" * 60)
        print(f"{len(inputs)} input(s)")

    elif action == "remove":
        try:
            registry.remove_evaluation_input(args.eval_id)
            print(f"Evaluation input {args.eval_id} removed")
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    else:
        print("Usage: cambrian eval-input {add|list|remove}", file=sys.stderr)
        sys.exit(1)


def _handle_trace(args: argparse.Namespace) -> None:
    """cambrian trace 서브커맨드를 처리한다.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)

    # detail 모드
    if getattr(args, "detail", None) is not None:
        _handle_trace_detail(engine, args.detail)
        return

    # list 모드
    traces = engine.get_run_traces(
        trace_type=getattr(args, "type", None),
        skill_id=getattr(args, "skill", None),
        limit=args.limit,
    )

    if not traces:
        print("No traces found.")
        return

    print(
        f"{'ID':<5} {'TYPE':<22} {'WINNER':<18} "
        f"{'CAND':<6} {'REASON':<40} {'DATE'}"
    )
    print("─" * 105)

    for t in traces:
        trace_type = t["trace_type"]
        type_map = {
            "competitive_run": "competitive",
            "evolution_decision": "evolution",
            "auto_rollback": "rollback",
        }
        type_display = type_map.get(trace_type, trace_type)

        winner = t.get("winner_id") or "(none)"
        cand_str = f"{t.get('success_count', 0)}/{t.get('candidate_count', 0)}"

        reason_full = t.get("winner_reason", "")
        reason_short = (
            (reason_full[:37] + "...") if len(reason_full) > 40 else reason_full
        )

        date_str = t.get("created_at", "")[:16]

        print(
            f"{t['id']:<5} {type_display:<22} {winner:<18} "
            f"{cand_str:<6} {reason_short:<40} {date_str}"
        )


def _handle_trace_detail(engine: "CambrianEngine", trace_id: int) -> None:
    """특정 trace의 상세 정보를 출력한다.

    Args:
        engine: CambrianEngine 인스턴스
        trace_id: 조회할 trace ID
    """
    trace = engine.get_run_trace_by_id(trace_id)

    if trace is None:
        print(f"Trace #{trace_id} not found.", file=sys.stderr)
        sys.exit(1)

    # 헤더
    print(f"=== Trace #{trace['id']} ===")
    print(f"Type:       {trace['trace_type']}")
    print(f"Domain:     {trace.get('domain', '')}")

    tags_raw = trace.get("tags", [])
    if isinstance(tags_raw, str):
        try:
            tags_list = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            tags_list = []
    else:
        tags_list = tags_raw
    print(f"Tags:       {', '.join(tags_list) if tags_list else '(none)'}")

    print(f"Date:       {trace.get('created_at', '')}")
    print(f"Input:      {trace.get('input_summary', '')[:200]}")
    print(f"Total time: {trace.get('total_ms', 0)}ms")

    # 승자
    winner_id = trace.get("winner_id")
    if winner_id:
        print(f"\nWinner:     {winner_id}")
    else:
        print("\nWinner:     (none — all candidates failed)")
    print(f"Reason:     {trace.get('winner_reason', '')}")

    # 후보 파싱
    candidates_raw = trace.get("candidates_json", "[]")
    try:
        candidates = (
            json.loads(candidates_raw)
            if isinstance(candidates_raw, str)
            else candidates_raw
        )
    except (json.JSONDecodeError, TypeError):
        candidates = []
        print("\n(candidates data could not be parsed)")

    if not candidates:
        return

    # evolution verdict 형식 감지
    if "original_score" in candidates[0]:
        print(f"\nVerdicts ({len(candidates)} trials):")
        print(f"  {'TRIAL':<7} {'ORIGINAL':<10} {'VARIANT':<10} {'WINNER':<10} REASONING")
        print(f"  {'─' * 60}")
        for i, v in enumerate(candidates, 1):
            orig = f"{v.get('original_score', 0):.1f}"
            var = f"{v.get('variant_score', 0):.1f}"
            win = v.get("winner", "?")
            reason = v.get("reasoning", "")[:30]
            print(f"  {i:<7} {orig:<10} {var:<10} {win:<10} {reason}")
    else:
        # 일반 competitive 형식
        print(
            f"\nCandidates ({trace.get('candidate_count', 0)} total, "
            f"{trace.get('success_count', 0)} succeeded):"
        )
        print(
            f"  {'SKILL_ID':<20} {'MODE':<6} {'OK':<6} "
            f"{'TIME':<8} {'FITNESS':<8} ERROR"
        )
        print(f"  {'─' * 70}")
        for c in candidates:
            skill_id = c.get("skill_id", "?")
            mode = c.get("mode", "?")
            ok = "[OK]" if c.get("success") else "[FAIL]"
            time_ms = f"{c.get('execution_time_ms', 0)}ms"
            fitness = f"{c.get('fitness_before', 0):.4f}"
            error = c.get("error", "")
            error_short = (error[:30] + "...") if len(error) > 30 else error
            marker = " ★" if skill_id == winner_id else ""
            print(
                f"  {skill_id:<20} {mode:<6} {ok:<6} "
                f"{time_ms:<8} {fitness:<8} {error_short}{marker}"
            )


def _handle_eval(args: argparse.Namespace) -> None:
    """cambrian eval 서브커맨드를 처리한다.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    max_cases = getattr(args, "max_cases", None)
    if max_cases is not None:
        engine.MAX_EVAL_CASES = max(1, max_cases)

    if getattr(args, "detail", None) is not None:
        _handle_eval_detail(engine, args.detail)
        return

    if getattr(args, "report", False):
        _handle_eval_report(engine, args.skill_id, args.limit)
        return

    _handle_eval_run(engine, args.skill_id)


def _handle_eval_run(engine: "CambrianEngine", skill_id: str) -> None:
    """eval 실행 모드: replay set으로 평가 + 스냅샷 저장.

    Args:
        engine: CambrianEngine 인스턴스
        skill_id: 평가할 스킬 ID
    """
    try:
        result = engine.evaluate(skill_id)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Evaluation: {skill_id}")
    print("═" * 50)

    print(f"\nReplay Set: {result['input_count']} inputs")
    print(
        f"Results:    {result['pass_count']} pass / {result['fail_count']} fail "
        f"→ {result['pass_rate'] * 100:.1f}% pass rate"
    )
    print(f"Avg time:   {result['avg_time_ms']}ms (successful only)")
    print(f"Fitness:    {result['fitness_at_time']:.4f}")

    verdict = result["verdict"]
    delta = result["delta"]

    if verdict == "baseline":
        print(f"\nVerdict:    {verdict} (first evaluation — no comparison available)")
    else:
        arrow = {"improving": "↑", "regression": "↓"}.get(verdict, "→")
        print(f"\nVerdict:    {verdict} {arrow}")
        if delta:
            d_pass = delta["pass_rate"] * 100
            d_time = delta["avg_time_ms"]
            d_fit = delta["fitness"]
            prev_pass = delta["prev_pass_rate"] * 100
            prev_time = delta["prev_avg_time_ms"]
            prev_fit = delta["prev_fitness"]

            regression_mark = "  ← REGRESSION" if d_pass < 0 else ""
            print(
                f"  pass_rate:  {d_pass:+.1f}% "
                f"({prev_pass:.1f}% → {result['pass_rate'] * 100:.1f}%)"
                f"{regression_mark}"
            )
            print(
                f"  avg_time:   {d_time:+d}ms "
                f"({prev_time}ms → {result['avg_time_ms']}ms)"
            )
            print(
                f"  fitness:    {d_fit:+.4f} "
                f"({prev_fit:.4f} → {result['fitness_at_time']:.4f})"
            )

    print(f"\nSnapshot #{result['snapshot_id']} saved.")


def _handle_eval_report(
    engine: "CambrianEngine", skill_id: str, limit: int,
) -> None:
    """eval report 모드: 최근 스냅샷 추이를 출력한다.

    Args:
        engine: CambrianEngine 인스턴스
        skill_id: 대상 스킬 ID
        limit: 최대 스냅샷 수
    """
    report = engine.get_eval_report(skill_id, limit)

    if not report["snapshots"]:
        print(f"No evaluation history for '{skill_id}'.")
        print(f"Run first: cambrian eval {skill_id}")
        return

    snaps = report["snapshots"]
    print(
        f"Evaluation Report: {skill_id} ({report['total_snapshots']} snapshots)"
    )
    print("═" * 80)

    print(
        f"\n{'#':<3} {'DATE':<18} {'INPUTS':<8} {'PASS':<7} "
        f"{'RATE':<8} {'AVG_MS':<8} {'FITNESS':<9} DELTA"
    )
    for i, snap in enumerate(snaps, 1):
        date_str = snap.get("created_at", "")[:16]
        pass_str = f"{snap['pass_count']}/{snap['input_count']}"
        rate_str = f"{snap['pass_rate'] * 100:.1f}%"
        dv = snap.get("delta_verdict", "-")
        print(
            f"{i:<3} {date_str:<18} {snap['input_count']:<8} {pass_str:<7} "
            f"{rate_str:<8} {snap['avg_time_ms']:<8} "
            f"{snap['fitness_at_time']:<9.4f} {dv}"
        )

    trend = report["trend"]
    first_rate = snaps[0]["pass_rate"] * 100
    last_rate = snaps[-1]["pass_rate"] * 100
    arrow = {"improving": "↑", "declining": "↓"}.get(trend, "→")
    print(
        f"\nTrend: {trend} {arrow} "
        f"(pass_rate {first_rate:.1f}% → {last_rate:.1f}% "
        f"over {report['total_snapshots']} evaluations)"
    )


def _handle_eval_detail(engine: "CambrianEngine", snapshot_id: int) -> None:
    """eval detail 모드: 특정 스냅샷의 입력별 결과를 출력한다.

    Args:
        engine: CambrianEngine 인스턴스
        snapshot_id: 조회할 snapshot ID
    """
    snapshot = engine.get_registry().get_evaluation_snapshot_by_id(snapshot_id)

    if snapshot is None:
        print(f"Snapshot #{snapshot_id} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"=== Evaluation Snapshot #{snapshot['id']} ===")
    print(f"Skill:      {snapshot['skill_id']}")
    print(f"Date:       {snapshot.get('created_at', '')}")
    print(
        f"Pass rate:  {snapshot['pass_count']}/{snapshot['input_count']} "
        f"({snapshot['pass_rate'] * 100:.1f}%)"
    )
    print(f"Avg time:   {snapshot['avg_time_ms']}ms")
    print(f"Fitness:    {snapshot['fitness_at_time']:.4f}")

    results_raw = snapshot.get("results_json", "[]")
    try:
        results = json.loads(results_raw) if isinstance(results_raw, str) else results_raw
    except (json.JSONDecodeError, TypeError):
        results = []
        print("\n(results data could not be parsed)")

    if results:
        print(
            f"\nInput Results:"
            f"\n  {'#':<4} {'EVAL_ID':<9} {'DESCRIPTION':<22} "
            f"{'OK':<7} {'TIME':<8} ERROR"
        )
        for i, r in enumerate(results, 1):
            ok = "[OK]" if r.get("success") else "[FAIL]"
            desc = r.get("description", "")[:20]
            time_str = f"{r.get('execution_time_ms', 0)}ms"
            error = r.get("error", "")
            error_short = (error[:30] + "...") if len(error) > 30 else error
            print(
                f"  {i:<4} {r.get('eval_input_id', '?'):<9} {desc:<22} "
                f"{ok:<7} {time_str:<8} {error_short}"
            )


def _resolve_brain_runs_dir(args: argparse.Namespace) -> Path:
    """brain 서브커맨드용 runs_dir을 결정한다.

    Args:
        args: argparse 네임스페이스

    Returns:
        runs 디렉토리 Path
    """
    explicit = getattr(args, "runs_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "brain" / "runs"


def _handle_brain(args: argparse.Namespace) -> None:
    """cambrian brain 루트 핸들러. 서브커맨드로 분기한다."""
    sub = getattr(args, "brain_command", None)
    if sub == "run":
        _handle_brain_run(args)
    elif sub == "refine-hypothesis":
        _handle_brain_refine_hypothesis(args)
    elif sub == "resume":
        _handle_brain_resume(args)
    elif sub == "show":
        _handle_brain_show(args)
    elif sub == "handoff":
        _handle_brain_handoff(args)
    elif sub == "autopsy":
        _handle_brain_autopsy(args)
    else:
        print(
            "Error: brain 서브커맨드 필요 (run/refine-hypothesis/resume/show/handoff/autopsy)",
            file=sys.stderr,
        )
        sys.exit(1)


def _handle_brain_run(args: argparse.Namespace) -> None:
    """brain run 핸들러: TaskSpec YAML 로드 → RALF 실행."""
    from engine.brain.feedback_context import FeedbackContextLoader
    from engine.brain.hypothesis_refinement import HypothesisRefinementStore
    from engine.brain.models import TaskSpec
    from engine.brain.runner import RALFRunner
    from engine.brain.selection_pressure import SelectionPressureStore

    spec_path = Path(args.task_spec)
    if not spec_path.exists():
        print(f"Error: TaskSpec 파일 없음: {spec_path}", file=sys.stderr)
        sys.exit(1)

    try:
        task_spec = TaskSpec.from_yaml(spec_path)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: TaskSpec 로드 실패: {exc}", file=sys.stderr)
        sys.exit(1)

    seed_path_raw = getattr(args, "generation_seed_path", None)
    if seed_path_raw:
        if task_spec.generation_seed is None:
            seed_path = Path(seed_path_raw)
            if not seed_path.exists():
                print(f"Error: generation seed 파일 없음: {seed_path}", file=sys.stderr)
                sys.exit(1)
            try:
                seed_payload = FeedbackContextLoader().load_seed_file(seed_path)
            except (ValueError, OSError, yaml.YAMLError) as exc:
                print(f"Error: generation seed 로드 실패: {exc}", file=sys.stderr)
                sys.exit(1)
            seed_payload = dict(seed_payload)
            seed_payload.setdefault("source_seed_path", str(seed_path.resolve()))
            task_spec.generation_seed = seed_payload
            feedback_refs = list(task_spec.feedback_refs or [])
            source_feedback_ref = seed_payload.get("source_feedback_ref")
            if source_feedback_ref:
                feedback_refs.extend(
                    source_feedback_ref
                    if isinstance(source_feedback_ref, list)
                    else [str(source_feedback_ref)]
                )
            task_spec.feedback_refs = list(dict.fromkeys(str(item) for item in feedback_refs))
        else:
            print(
                "Warning: TaskSpec.generation_seed가 이미 있어 CLI --seed는 무시됩니다.",
                file=sys.stderr,
            )

    pressure_path_raw = getattr(args, "selection_pressure_path", None)
    if pressure_path_raw:
        if task_spec.selection_pressure is None:
            pressure_path = Path(pressure_path_raw)
            if not pressure_path.exists():
                print(
                    f"Error: selection pressure 파일 없음: {pressure_path}",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                pressure_payload = SelectionPressureStore().load(pressure_path).to_dict()
            except (ValueError, OSError, yaml.YAMLError) as exc:
                print(
                    f"Warning: selection pressure 로드 실패, error context만 주입합니다: {exc}",
                    file=sys.stderr,
                )
                pressure_payload = {
                    "source_pressure_path": str(pressure_path.resolve()),
                    "pressure_status": "error",
                    "blocked_variant_ids": [],
                    "warned_variant_ids": [],
                    "keep_patterns": [],
                    "avoid_patterns": [],
                    "risk_flags": [],
                    "warnings": [],
                    "errors": [str(exc)],
                }
            pressure_payload = dict(pressure_payload)
            pressure_payload.setdefault(
                "source_pressure_path",
                str(pressure_path.resolve()),
            )
            task_spec.selection_pressure = pressure_payload
            pressure_refs = list(task_spec.selection_pressure_refs or [])
            pressure_refs.append(str(pressure_path.resolve()))
            task_spec.selection_pressure_refs = list(dict.fromkeys(pressure_refs))
        else:
            print(
                "Warning: TaskSpec.selection_pressure가 이미 있어 CLI --pressure는 무시됩니다.",
                file=sys.stderr,
            )

    refinement_path_raw = getattr(args, "hypothesis_refinement_path", None)
    if refinement_path_raw:
        if task_spec.hypothesis_refinement is None:
            refinement_path = Path(refinement_path_raw)
            if not refinement_path.exists():
                print(
                    f"Error: refined hypothesis 파일 없음: {refinement_path}",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                refinement_payload = HypothesisRefinementStore().load(
                    refinement_path
                ).to_dict()
            except (ValueError, OSError, yaml.YAMLError) as exc:
                print(
                    f"Warning: refined hypothesis 로드 실패, error context만 주입합니다: {exc}",
                    file=sys.stderr,
                )
                refinement_payload = {
                    "source_refinement_path": str(refinement_path.resolve()),
                    "status": "error",
                    "refined_hypothesis": None,
                    "constraints": {},
                    "required_evidence": [],
                    "warnings": [],
                    "errors": [str(exc)],
                }
            refinement_payload = dict(refinement_payload)
            refinement_payload.setdefault(
                "source_refinement_path",
                str(refinement_path.resolve()),
            )
            task_spec.hypothesis_refinement = refinement_payload
            refinement_refs = list(task_spec.hypothesis_refinement_refs or [])
            refinement_refs.append(str(refinement_path.resolve()))
            task_spec.hypothesis_refinement_refs = list(
                dict.fromkeys(refinement_refs)
            )
        else:
            print(
                "Warning: TaskSpec.hypothesis_refinement이 이미 있어 CLI --refinement는 무시됩니다.",
                file=sys.stderr,
            )

    runs_dir = _resolve_brain_runs_dir(args)
    workspace = getattr(args, "workspace", None)
    runner = RALFRunner(runs_dir=runs_dir, workspace=workspace)
    state = runner.run(task_spec, max_iterations=args.max_iterations)

    report_path = runs_dir / state.run_id / "report.json"

    if getattr(args, "json_output", False):
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Brain Run: {state.run_id}")
    print("=" * 60)
    print(f"Task:        {task_spec.task_id} — {task_spec.goal}")
    print(f"Status:      {state.status}")
    print(f"Iterations:  {state.current_iteration} / {state.max_iterations}")
    print(f"Termination: {state.termination_reason}")
    print(f"Work items:  {len(state.work_items)}")
    done = sum(1 for w in state.work_items if w.status == "done")
    print(f"  done:      {done}")
    print(f"  failed:    "
          f"{sum(1 for w in state.work_items if w.status == 'failed')}")
    print(f"  pending:   "
          f"{sum(1 for w in state.work_items if w.status == 'pending')}")
    print(f"Report:      {report_path}")


def _handle_brain_refine_hypothesis(args: argparse.Namespace) -> None:
    """brain refine-hypothesis 핸들러."""
    from engine.brain.hypothesis_refinement import (
        HypothesisRefinementStore,
        HypothesisRefiner,
    )

    seed_path = (
        Path(args.generation_seed_path).resolve()
        if getattr(args, "generation_seed_path", None)
        else None
    )
    pressure_path = (
        Path(args.selection_pressure_path).resolve()
        if getattr(args, "selection_pressure_path", None)
        else None
    )
    task_spec_path = (
        Path(args.task_spec_path).resolve()
        if getattr(args, "task_spec_path", None)
        else None
    )

    if seed_path is None and task_spec_path is None:
        print(
            "Error: --seed 또는 --task 중 하나는 필요합니다.",
            file=sys.stderr,
        )
        sys.exit(1)

    refiner = HypothesisRefiner()
    refinement = refiner.refine(
        seed_path=seed_path,
        pressure_path=pressure_path,
        task_spec_path=task_spec_path,
        project_root=Path.cwd(),
    )
    store = HypothesisRefinementStore()
    out_path = (
        Path(args.refinement_out)
        if getattr(args, "refinement_out", None)
        else store.default_path(
            refinement,
            Path.cwd() / ".cambrian" / "hypotheses",
        )
    )
    store.save(refinement, out_path)

    if getattr(args, "json_output", False):
        print(json.dumps(refinement.to_dict(), indent=2, ensure_ascii=False))
        return

    print("[HYPOTHESIS] refined hypothesis created")
    print(f"  Status    : {refinement.status}")
    print(
        "  Base      : "
        f"{(refinement.base_hypothesis or {}).get('source', '-')}"
    )
    print(f"  Seed      : {refinement.source_seed_path or '-'}")
    print(f"  Pressure  : {refinement.source_pressure_path or '-'}")
    print(f"  Output    : {out_path}")
    print(f"  Required evidence : {len(refinement.required_evidence)}")
    print(
        "  Constraints       : "
        f"{len(refinement.constraints.get('blocked_variant_ids', []) or [])} blocked variants"
    )
    print("  Next      : use with cambrian brain run --refinement <file>")


def _handle_brain_resume(args: argparse.Namespace) -> None:
    """brain resume 핸들러: 중단된 run을 재개한다."""
    from engine.brain.runner import RALFRunner

    runs_dir = _resolve_brain_runs_dir(args)
    workspace = getattr(args, "workspace", None)
    runner = RALFRunner(runs_dir=runs_dir, workspace=workspace)

    try:
        state = runner.resume(args.run_id)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Brain Resume: {state.run_id}")
    print("=" * 60)
    print(f"Status:      {state.status}")
    print(f"Iterations:  {state.current_iteration} / {state.max_iterations}")
    print(f"Termination: {state.termination_reason}")


def _handle_brain_show(args: argparse.Namespace) -> None:
    """brain show 핸들러: run 상태를 출력한다."""
    from engine.brain.checkpoint import CheckpointManager

    runs_dir = _resolve_brain_runs_dir(args)
    cm = CheckpointManager(runs_dir)
    try:
        state = cm.load_state(args.run_id)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        print(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Brain Run: {state.run_id}")
    print("=" * 60)
    print(f"Task:        {state.task_spec.task_id} — {state.task_spec.goal}")
    print(f"Status:      {state.status}")
    print(f"Phase:       {state.current_phase}")
    print(f"Iterations:  {state.current_iteration} / {state.max_iterations}")
    print(f"Started:     {state.started_at}")
    print(f"Updated:     {state.updated_at}")
    print(f"Finished:    {state.finished_at or '(미완료)'}")
    print(f"Termination: {state.termination_reason or '-'}")
    print(f"\nWork Items ({len(state.work_items)}):")
    for w in state.work_items:
        print(f"  [{w.status:<10}] {w.item_id}: {w.description}")
    print(f"\nStep Results ({len(state.step_results)}):")
    for s in state.step_results[-10:]:
        print(f"  [{s.role:<8} {s.status:<8}] {s.summary}")

    report_path = runs_dir / state.run_id / "report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = None
        if isinstance(report, dict):
            hypothesis = report.get("hypothesis_evaluation")
            if isinstance(hypothesis, dict):
                checks = hypothesis.get("checks") or []
                passed = sum(
                    1 for check in checks
                    if isinstance(check, dict) and check.get("status") == "passed"
                )
                failed = sum(
                    1 for check in checks
                    if isinstance(check, dict) and check.get("status") == "failed"
                )
                inconclusive = sum(
                    1 for check in checks
                    if isinstance(check, dict)
                    and check.get("status") == "inconclusive"
                )
                print("\nHypothesis:")
                print(f"  id      : {hypothesis.get('hypothesis_id') or '-'}")
                print(f"  status  : {hypothesis.get('status') or '-'}")
                print(
                    f"  checks  : {passed} passed, {failed} failed, "
                    f"{inconclusive} inconclusive"
                )

            competitive = report.get("competitive_generation")
            if isinstance(competitive, dict):
                print("\nCompetitive Generation:")
                print(f"  status  : {competitive.get('status') or '-'}")
                print(
                    f"  winner  : "
                    f"{competitive.get('winner_variant_id') or '(none)'}"
                )
                for variant in competitive.get("variants", []) or []:
                    if not isinstance(variant, dict):
                        continue
                    test_results = variant.get("test_results") or {}
                    passed = int(test_results.get("passed", 0) or 0)
                    failed = int(test_results.get("failed", 0) or 0)
                    hypothesis_status = (
                        variant.get("hypothesis_status") or "skipped"
                    )
                    print(
                        "  - "
                        f"{variant.get('variant_id')}: "
                        f"{variant.get('status')}, "
                        f"tests {passed} passed / {failed} failed, "
                        f"hypothesis {hypothesis_status}"
                    )


def _resolve_generation_feedback_dir(args: argparse.Namespace) -> Path:
    """brain autopsy용 feedback 출력 경로를 결정한다."""
    explicit = getattr(args, "feedback_out_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "feedback"


def _resolve_next_generation_dir(args: argparse.Namespace) -> Path:
    """brain autopsy용 next generation seed 출력 경로를 결정한다."""
    explicit = getattr(args, "next_generation_out_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "next_generation"


def _handle_brain_autopsy(args: argparse.Namespace) -> None:
    """brain autopsy 핸들러."""
    from engine.brain.generation_feedback import (
        GenerationAutopsy,
        GenerationFeedbackStore,
        NextGenerationSeedBuilder,
    )

    source_path = Path(args.source_path).resolve()
    project_root = Path.cwd().resolve()
    feedback_dir = _resolve_generation_feedback_dir(args)
    next_generation_dir = _resolve_next_generation_dir(args)
    human_feedback = {
        "note": getattr(args, "note", ""),
        "rating": getattr(args, "rating", None),
        "keep": list(getattr(args, "keep", []) or []),
        "avoid": list(getattr(args, "avoid", []) or []),
    }

    autopsy = GenerationAutopsy()
    feedback = autopsy.analyze(
        source_path=source_path,
        project_root=project_root,
        human_feedback=human_feedback,
    )
    store = GenerationFeedbackStore()
    seed_builder = NextGenerationSeedBuilder()
    feedback_path = store.default_path(feedback, feedback_dir)
    next_seed_path = seed_builder.default_path(feedback, next_generation_dir)
    feedback.next_generation_seed_path = str(next_seed_path)

    store.save(feedback, feedback_path)
    try:
        seed_builder.build(
            feedback=feedback,
            feedback_path=feedback_path,
            out_path=next_seed_path,
        )
    except Exception:
        try:
            if feedback_path.exists():
                feedback_path.unlink()
        except OSError:
            pass
        raise

    if getattr(args, "json_output", False):
        print(json.dumps(feedback.to_dict(), indent=2, ensure_ascii=False))
        return

    print("[AUTOPSY] generation feedback created")
    print(f"  Source    : {source_path}")
    print(f"  Outcome   : {feedback.outcome}")
    print(f"  Brain Run : {feedback.brain_run_id or '-'}")
    print(f"  Winner    : {feedback.winner_variant_id or '-'}")
    print(f"  Feedback  : {feedback_path}")
    print(f"  Next Seed : {next_seed_path}")
    print(f"  Keep      : {len(feedback.keep_patterns)}")
    print(f"  Avoid     : {len(feedback.avoid_patterns)}")
    if feedback.outcome_reasons:
        print("  Reasons   :")
        for reason in feedback.outcome_reasons:
            print(f"    - {reason}")
    print("  Next      : use next generation seed as input for revised brain run")


def _resolve_evolution_ledger_path(args: argparse.Namespace) -> Path:
    """evolution ledger 경로를 결정한다."""
    explicit = getattr(args, "ledger_path", None) or getattr(args, "ledger_out", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "evolution" / "_ledger.json"


def _resolve_evolution_brain_runs_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "brain_runs_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "brain" / "runs"


def _resolve_evolution_adoptions_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "adoptions_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "adoptions"


def _resolve_evolution_feedback_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "feedback_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "feedback"


def _resolve_evolution_next_generation_dir(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "next_generation_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "next_generation"


def _load_evolution_ledger_or_exit(args: argparse.Namespace):
    """ledger 파일을 읽거나 종료한다."""
    from engine.brain.evolution_ledger import EvolutionLedgerStore

    ledger_path = _resolve_evolution_ledger_path(args)
    if not ledger_path.exists():
        print(
            f"Error: ledger 파일 없음: {ledger_path} "
            "(먼저 cambrian evolution rebuild-ledger 실행)",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        return EvolutionLedgerStore().load(ledger_path), ledger_path
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: ledger 로드 실패: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_evolution(args: argparse.Namespace) -> None:
    """cambrian evolution 루트 핸들러."""
    sub = getattr(args, "evolution_command", None)
    if sub == "rebuild-ledger":
        _handle_evolution_rebuild_ledger(args)
    elif sub == "build-pressure":
        _handle_evolution_build_pressure(args)
    elif sub == "list":
        _handle_evolution_list(args)
    elif sub == "show":
        _handle_evolution_show(args)
    elif sub == "lineage":
        _handle_evolution_lineage(args)
    else:
        print(
            "Error: evolution 서브커맨드 필요 "
            "(rebuild-ledger/build-pressure/list/show/lineage)",
            file=sys.stderr,
        )
        sys.exit(1)


def _handle_evolution_rebuild_ledger(args: argparse.Namespace) -> None:
    """source artifacts를 스캔해 evolution ledger를 재구성한다."""
    from engine.brain.evolution_ledger import (
        EvolutionLedgerBuilder,
        EvolutionLedgerStore,
    )

    brain_runs_dir = _resolve_evolution_brain_runs_dir(args)
    adoptions_dir = _resolve_evolution_adoptions_dir(args)
    feedback_dir = _resolve_evolution_feedback_dir(args)
    next_generation_dir = _resolve_evolution_next_generation_dir(args)
    ledger_out = _resolve_evolution_ledger_path(args)

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=brain_runs_dir,
        adoptions_dir=adoptions_dir,
        feedback_dir=feedback_dir,
        next_generation_dir=next_generation_dir,
        project_root=Path.cwd(),
    )
    EvolutionLedgerStore().save(ledger, ledger_out)

    if getattr(args, "json_output", False):
        print(json.dumps(ledger.to_dict(), indent=2, ensure_ascii=False))
        return

    print("[EVOLUTION] ledger rebuilt")
    print(f"  Brain Runs : {brain_runs_dir}")
    print(f"  Adoptions  : {adoptions_dir}")
    print(f"  Feedback   : {feedback_dir}")
    print(f"  Next Seeds : {next_generation_dir}")
    print(f"  Nodes      : {len(ledger.nodes)}")
    print(f"  Latest     : {ledger.latest_generation_id or '-'}")
    print(f"  Output     : {ledger_out}")
    if ledger.warnings:
        print(f"  Warnings   : {len(ledger.warnings)}")
    if ledger.errors:
        print(f"  Errors     : {len(ledger.errors)}")


def _handle_evolution_build_pressure(args: argparse.Namespace) -> None:
    """ledger에서 selection pressure artifact를 생성한다."""
    from engine.brain.selection_pressure import (
        SelectionPressureBuilder,
        SelectionPressureStore,
    )

    ledger, ledger_path = _load_evolution_ledger_or_exit(args)
    pressure = SelectionPressureBuilder().build(
        ledger,
        options={"source_ledger_path": str(ledger_path)},
    )
    out_path = Path(args.pressure_out)
    SelectionPressureStore().save(pressure, out_path)

    if getattr(args, "json_output", False):
        print(json.dumps(pressure.to_dict(), indent=2, ensure_ascii=False))
        return

    print("[PRESSURE] selection pressure built")
    print(f"  Ledger      : {ledger_path}")
    print(f"  Generations : {len(pressure.source_generation_ids)}")
    print(f"  Keep        : {len(pressure.keep_patterns)}")
    print(f"  Avoid       : {len(pressure.avoid_patterns)}")
    print(f"  Blocked IDs : {len(pressure.blocked_variant_ids)}")
    print(f"  Warnings    : {len(pressure.warnings)}")
    print(f"  Output      : {out_path}")


def _handle_evolution_list(args: argparse.Namespace) -> None:
    """ledger generation 목록을 출력한다."""
    ledger, _ = _load_evolution_ledger_or_exit(args)
    nodes = list(ledger.nodes)

    outcome_filter = getattr(args, "outcome", None)
    if outcome_filter:
        nodes = [node for node in nodes if node.outcome == outcome_filter]

    limit = getattr(args, "limit", None)
    if isinstance(limit, int) and limit > 0:
        nodes = nodes[-limit:]

    if getattr(args, "json_output", False):
        print(
            json.dumps(
                [node.to_dict() for node in nodes],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print("Generation Ledger")
    print("=" * 60)
    if not nodes:
        print("(empty)")
        return
    for node in nodes:
        winner = node.winner_variant_id or "-"
        hyp = node.hypothesis_status or "-"
        print(
            f"{node.generation_id:<24} {node.outcome:<12} "
            f"winner={winner:<10} hyp={hyp:<12} "
            f"children={len(node.child_generation_ids)}"
        )


def _handle_evolution_show(args: argparse.Namespace) -> None:
    """특정 generation 상세를 출력한다."""
    ledger, _ = _load_evolution_ledger_or_exit(args)
    generation_id = args.generation_id
    node = next(
        (item for item in ledger.nodes if item.generation_id == generation_id),
        None,
    )
    if node is None:
        print(f"Error: generation 없음: {generation_id}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        print(json.dumps(node.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"Generation: {node.generation_id}")
    print("=" * 60)
    print(f"Brain Run : {node.brain_run_id or '-'}")
    print(f"Task      : {node.task_id or '-'}")
    print(f"Goal      : {node.goal or '-'}")
    print(f"Outcome   : {node.outcome}")
    print(f"Status    : {node.status or '-'}")
    print(f"Hypothesis: {node.hypothesis_status or '-'} ({node.hypothesis_id or '-'})")
    print(f"Winner    : {node.winner_variant_id or '-'}")
    print(f"Selection : {node.selection_reason or '-'}")
    print(f"Adoption  : {node.adoption_status or '-'}")
    print(f"Parents   : {', '.join(node.parent_generation_ids) or '-'}")
    print(f"Children  : {', '.join(node.child_generation_ids) or '-'}")
    print(f"Feedback  : {', '.join(node.feedback_refs) or '-'}")
    print(f"Seeds     : {', '.join(node.next_seed_refs) or '-'}")
    if node.warnings:
        print("Warnings  :")
        for warning in node.warnings:
            print(f"  - {warning}")
    if node.errors:
        print("Errors    :")
        for error in node.errors:
            print(f"  - {error}")


def _handle_evolution_lineage(args: argparse.Namespace) -> None:
    """generation lineage를 출력한다."""
    ledger, _ = _load_evolution_ledger_or_exit(args)
    nodes = {node.generation_id: node for node in ledger.nodes}
    generation_id = args.generation_id
    if generation_id not in nodes:
        print(f"Error: generation 없음: {generation_id}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json_output", False):
        lineage_payload = {
            "generation_id": generation_id,
            "parents": nodes[generation_id].parent_generation_ids,
            "children": nodes[generation_id].child_generation_ids,
        }
        print(json.dumps(lineage_payload, indent=2, ensure_ascii=False))
        return

    def _print_ancestors(current_id: str, indent: int = 0) -> None:
        node = nodes[current_id]
        prefix = "  " * indent
        print(f"{prefix}{node.generation_id} [{node.outcome}]")
        if node.feedback_refs:
            for feedback_ref in node.feedback_refs:
                print(f"{prefix}  -> feedback: {feedback_ref}")
        if node.next_seed_refs:
            for seed_ref in node.next_seed_refs:
                print(f"{prefix}  -> seed: {seed_ref}")
        for child_id in node.child_generation_ids:
            _print_ancestors(child_id, indent + 1)

    _print_ancestors(generation_id)


def _resolve_candidates_dir(args: argparse.Namespace) -> Path:
    """adoption review 서브커맨드용 candidates_dir 결정."""
    explicit = getattr(args, "candidates_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "adoption_candidates"


def _resolve_generation_adoptions_dir(args: argparse.Namespace) -> Path:
    """generation adoption record 디렉토리를 결정한다."""
    explicit = getattr(args, "adoption_out_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "adoptions"


def _handle_adoption_accept_generation(args: argparse.Namespace) -> None:
    """adoption accept-generation 핸들러."""
    from engine.brain.generation_adoption import (
        GenerationAdoptionApplier,
        GenerationAdoptionValidator,
    )

    runs_dir = _resolve_brain_runs_dir(args)
    workspace = Path(getattr(args, "workspace", ".")).resolve()
    out_dir = _resolve_generation_adoptions_dir(args)

    validator = GenerationAdoptionValidator()
    validation = validator.validate(
        run_id_or_report=args.run_id,
        runs_dir=runs_dir,
        project_root=workspace,
        out_dir=out_dir,
    )
    result = GenerationAdoptionApplier().apply(
        validation=validation,
        reason=args.reason,
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    if getattr(args, "json_output", False):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if result.status == "adopted":
        print("[ADOPTION] brain generation accepted")
        print(f"  Run       : {result.brain_run_id}")
        print(f"  Winner    : {result.winner_variant_id}")
        print(f"  Status    : {result.status}")
        print(f"  Files     : {len(result.applied_files)} applied")
        print(
            "  Tests     : "
            f"{result.post_apply_tests.get('passed', 0)} passed, "
            f"{result.post_apply_tests.get('failed', 0)} failed"
        )
        print(f"  Record    : {result.adoption_record_path}")
        print("  Latest    : updated")
        print(f"  Reason    : {args.reason}")
        if result.warnings:
            print("  Warnings  :")
            for warning in result.warnings:
                print(f"    - {warning}")
        return

    if result.status == "dry_run":
        print("[ADOPTION] dry run")
        print(f"  Run       : {result.brain_run_id}")
        print(f"  Winner    : {result.winner_variant_id}")
        print("  Would apply:")
        for path in result.applied_files:
            print(f"    - {path}")
        print("  Would run tests:")
        tests_executed = result.post_apply_tests.get("tests_executed", [])
        if tests_executed:
            for path in tests_executed:
                print(f"    - {path}")
        else:
            print("    - (none)")
        print("  Latest    : not changed")
        return

    if result.status == "duplicate":
        print("[ADOPTION] brain generation duplicate")
        print(f"  Run       : {result.brain_run_id}")
        print(f"  Winner    : {result.winner_variant_id}")
        print(f"  Status    : {result.status}")
        print(f"  Record    : {result.adoption_record_path}")
        print("  Latest    : not changed")
        return

    if result.status == "blocked":
        print("[ADOPTION] brain generation blocked")
        print(f"  Run       : {result.brain_run_id}")
        print(f"  Status    : {result.status}")
        print("  Reasons   :")
        for reason in result.reasons:
            print(f"    - {reason}")
        if result.warnings:
            print("  Warnings  :")
            for warning in result.warnings:
                print(f"    - {warning}")
        print("  Latest    : not changed")
        return

    print("[ADOPTION] brain generation failed")
    print(f"  Run       : {result.brain_run_id}")
    print(f"  Winner    : {result.winner_variant_id or '(none)'}")
    print(f"  Status    : {result.status}")
    if result.applied_files:
        print("  Applied   :")
        for path in result.applied_files:
            print(f"    - {path}")
    if result.post_apply_tests:
        print(
            "  Tests     : "
            f"{result.post_apply_tests.get('passed', 0)} passed, "
            f"{result.post_apply_tests.get('failed', 0)} failed"
        )
    print("  Reasons   :")
    for reason in result.reasons:
        print(f"    - {reason}")
    print("  Latest    : not changed")


def _handle_adoption_review(args: argparse.Namespace) -> None:
    """adoption review 핸들러: handoff artifact → candidate 승격."""
    from engine.brain.candidate import CandidateGenerator

    handoff_path = Path(args.handoff_path)
    candidates_dir = _resolve_candidates_dir(args)
    generator = CandidateGenerator(candidates_dir=candidates_dir)
    record, result_type, reasons = generator.generate(handoff_path)

    if getattr(args, "json_output", False):
        payload: dict = {
            "result_type": result_type,
            "reasons": reasons,
            "record": record.to_dict() if record is not None else None,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    # artifact 경로 찾기 (created/duplicate 경로)
    def _find_artifact_rel(stable_ref: str) -> str | None:
        if not stable_ref:
            return None
        matches = sorted(
            candidates_dir.glob(f"candidate_*_{stable_ref}.json")
        )
        if not matches:
            return None
        try:
            return str(matches[-1].relative_to(Path.cwd()))
        except ValueError:
            return str(matches[-1])

    if result_type == "created" and record is not None:
        print(f"\n[REVIEW GATE] {record.handoff_ref or '(unknown)'}")
        print(f"  Task        : {record.task_id or '(unknown)'}")
        print(f"  Stable Ref  : {record.stable_ref}")
        print(f"  Gate Result : pass [OK]")
        print(f"  Candidate   : {record.candidate_status}")
        if record.reviewer_conclusion:
            print(f"  Reviewer    : {record.reviewer_conclusion}")
        print(f"  Tests       : exit {record.test_exit_code}")
        fc = len(record.files_created)
        fm = len(record.files_modified)
        print(f"  Files       : {fc} created, {fm} modified")
        risks = (
            ", ".join(record.remaining_risks)
            if record.remaining_risks else "none"
        )
        print(f"  Risks       : {risks}")
        rel = _find_artifact_rel(record.stable_ref)
        if rel:
            print(f"  Artifact    : {rel}")
        print(f"  Next        : candidate registered — "
              f"ready for adoption decision")

    elif result_type == "duplicate" and record is not None:
        print(f"\n[REVIEW GATE] {record.handoff_ref or '(unknown)'}")
        print(f"  Task        : {record.task_id or '(unknown)'}")
        print(f"  Stable Ref  : {record.stable_ref}")
        print(f"  Gate Result : pass [OK] (existing candidate)")
        rel = _find_artifact_rel(record.stable_ref)
        if rel:
            print(f"  Artifact    : {rel}")
        print(f"  Next        : existing candidate reused — "
              f"no new artifact created")

    elif result_type == "rejected":
        print(f"\n[REVIEW GATE] (rejected)")
        print(f"  Gate Result : rejected [FAIL]")
        print(f"  Reasons     :")
        for r in reasons:
            print(f"    - {r}")
        print(f"  Artifact    : not created")
        print(f"  Next        : resolve handoff issues, re-generate handoff, "
              f"then retry review")

    else:  # invalid
        print(f"\n[REVIEW GATE] (invalid)")
        print(f"  Gate Result : invalid [FAIL]")
        print(f"  Reasons     :")
        for r in reasons:
            print(f"    - {r}")
        print(f"  Artifact    : not created")


def _resolve_brain_handoffs_dir(args: argparse.Namespace) -> Path:
    """brain handoff 서브커맨드용 handoffs_dir 결정."""
    explicit = getattr(args, "handoffs_dir", None)
    if explicit:
        return Path(explicit)
    return Path.cwd() / ".cambrian" / "brain" / "handoffs"


def _handle_brain_handoff(args: argparse.Namespace) -> None:
    """brain handoff 핸들러: brain run 결과 → handoff artifact 생성."""
    from engine.brain.handoff import HandoffGenerator

    runs_dir = _resolve_brain_runs_dir(args)
    handoffs_dir = _resolve_brain_handoffs_dir(args)
    generator = HandoffGenerator(runs_dir=runs_dir, handoffs_dir=handoffs_dir)
    record = generator.generate(args.run_id)

    if getattr(args, "json_output", False):
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    print(f"\n[HANDOFF] {record.brain_run_id}")
    print(f"  Task      : {record.task_id or '(unknown)'}")

    # artifact 파일 경로 찾기 (저장된 경우)
    artifact_rel: str | None = None
    if record.handoff_status in ("ready", "blocked"):
        matches = sorted(
            handoffs_dir.glob(f"handoff_*_{record.brain_run_id}.json")
        )
        if matches:
            try:
                artifact_rel = str(matches[-1].relative_to(Path.cwd()))
            except ValueError:
                artifact_rel = str(matches[-1])

    if record.handoff_status == "ready":
        print(f"  Status    : ready [OK]")
        print(f"  Reviewer  : passed")
        print(f"  Tests     : exit {record.test_exit_code}")
        fc = len(record.files_created)
        fm = len(record.files_modified)
        print(f"  Files     : {fc} created, {fm} modified")
        if record.reviewer_conclusion:
            print(f"  Conclusion: {record.reviewer_conclusion}")
        risks = (
            ", ".join(record.remaining_risks)
            if record.remaining_risks else "none"
        )
        print(f"  Risks     : {risks}")
        if artifact_rel:
            print(f"  Artifact  : {artifact_rel}")
        print(f"  Next      : ready for adoption review")
    elif record.handoff_status == "blocked":
        print(f"  Status    : blocked [FAIL]")
        print(f"  Reasons   :")
        for r in record.block_reasons:
            print(f"    - {r}")
        if artifact_rel:
            print(f"  Artifact  : {artifact_rel}")
        print(f"  Next      : fix reviewer/test issues, re-run brain, "
              f"then retry handoff")
    else:  # invalid
        print(f"  Status    : invalid [FAIL]")
        print(f"  Reasons   :")
        for r in record.block_reasons:
            print(f"    - {r}")
        print(f"  Artifact  : not created")


def _emit_cli_payload(payload: dict, json_output: bool, text: str | None = None) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if text:
        print(text)
        return
    status = payload.get("status") or ("ok" if payload.get("ok") else "blocked")
    print(str(status))


def _payload_from_result(result) -> dict:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return dict(result)
    raise TypeError(f"Unsupported result payload: {type(result).__name__}")


def _exit_if_blocked(payload: dict) -> None:
    if not bool(payload.get("ok")):
        sys.exit(1)


def _handle_project(args: argparse.Namespace) -> None:
    if getattr(args, "project_command", None) != "scan":
        print("project subcommand is required", file=sys.stderr)
        sys.exit(2)
    from engine.project_harness_profile import ProjectHarnessProfileStore, ProjectHarnessScanner, default_project_profile_path

    root = Path.cwd()
    profile = ProjectHarnessScanner().scan(root)
    saved = ProjectHarnessProfileStore().save(profile, default_project_profile_path(root))
    payload = profile.to_dict()
    payload["ok"] = True
    payload["profile_ref"] = str(saved.relative_to(root)).replace("\\", "/")
    _emit_cli_payload(payload, bool(getattr(args, "json_output", False)), f"Project profile saved: {payload['profile_ref']}")


def _refresh_agent_history_artifacts(root: Path) -> tuple[dict[str, dict], dict]:
    """현재 프로젝트의 agent passport history와 dispatch log를 갱신한다."""
    from engine.project_agent_history import (
        AgentDispatchLogStore,
        AgentHistoryBuilder,
        AgentPassportHistoryStore,
        default_agent_passport_path,
        default_dispatch_log_path,
    )

    builder = AgentHistoryBuilder()
    passport_store = AgentPassportHistoryStore()
    dispatch_store = AgentDispatchLogStore()
    history_by_agent: dict[str, dict] = {}
    for history in builder.build_all_passports(root):
        passport_store.save(history, default_agent_passport_path(root, history.agent_id))
        history_by_agent[history.agent_id] = history.to_dict()
    dispatch_log = builder.build_dispatch_log(root)
    dispatch_store.save(dispatch_log, default_dispatch_log_path(root))
    return history_by_agent, dispatch_log.to_dict()

def _handle_lane(args: argparse.Namespace) -> None:
    """cambrian lane 처리."""
    from engine.project_win_lane import build_and_save_lane_profile, render_lane_profile

    root = Path.cwd()
    command = getattr(args, "lane_command", None) or "show"
    if command != "show":
        print("lane 하위 명령이 필요합니다. 예: cambrian lane show", file=sys.stderr)
        sys.exit(1)
    if not (root / ".cambrian" / "project.yaml").exists():
        print("Cambrian project mode is not initialized. Run `cambrian init --wizard` first.", file=sys.stderr)
        sys.exit(1)

    profile, profile_path = build_and_save_lane_profile(root)
    try:
        saved_path = str(profile_path.relative_to(root)).replace("\\", "/")
    except ValueError:
        saved_path = str(profile_path)
    payload = {
        "profile": profile.to_dict(),
        "saved_path": saved_path,
    }
    if getattr(args, "json_output", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(render_lane_profile(profile))
    print()
    print("Saved:")
    print(f"  {saved_path}")

def _handle_harness(args: argparse.Namespace) -> None:
    """cambrian harness 처리."""
    root = Path.cwd().resolve()
    command = getattr(args, "harness_command", None)
    if command == "engineer":
        from engine.project_harness_engineering import (
            design_harness_candidate,
            dry_run_harness_candidate,
            render_engineering_result,
            review_harness_candidate,
        )

        engineer_command = getattr(args, "harness_engineer_command", None)
        if engineer_command == "design":
            result = design_harness_candidate(root, seed_preset=getattr(args, "seed_preset", None))
        elif engineer_command == "review":
            result = review_harness_candidate(root)
        elif engineer_command == "dry-run":
            result = dry_run_harness_candidate(root, str(getattr(args, "request", "")))
        else:
            print("engineer 하위 명령이 필요합니다. 예: cambrian harness engineer design", file=sys.stderr)
            sys.exit(1)
        payload = result.to_dict()
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if not payload.get("ok"):
                sys.exit(1)
            return
        print(render_engineering_result(payload))
        if not payload.get("ok"):
            sys.exit(1)
        return
    if command == "interview":
        interview_command = getattr(args, "harness_interview_command", None)
        if interview_command == "start":
            from engine.project_harness_interview import (
                HarnessInterviewBuilder,
                render_harness_interview_session,
            )

            session = HarnessInterviewBuilder().start(root)
            if getattr(args, "json_output", False):
                print(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
                return
            print(render_harness_interview_session(session))
            return
        if interview_command == "answer":
            from engine.project_harness_interview import (
                HarnessInterviewAnswerHandler,
                render_harness_interview_answer_result,
            )

            try:
                result = HarnessInterviewAnswerHandler().answer(root, Path(str(getattr(args, "answers"))))
            except (FileNotFoundError, ValueError) as exc:
                print(f"Harness interview answer blocked: {exc}", file=sys.stderr)
                sys.exit(1)
            if getattr(args, "json_output", False):
                print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
                if result.status != "ready_for_plan":
                    sys.exit(1)
                return
            print(render_harness_interview_answer_result(result))
            if result.status != "ready_for_plan":
                sys.exit(1)
            return
        print("interview 하위 명령이 필요합니다. 예: cambrian harness interview start", file=sys.stderr)
        sys.exit(1)
    if command in {"plan", "design"}:
        from engine.project_harness_plan import build_and_save_harness_plan, render_harness_plan

        plan, saved = build_and_save_harness_plan(root, seed_preset=getattr(args, "seed_preset", None))
        payload = {
            "ok": plan.status in {"draft", "planned"},
            "plan_type": plan.plan_type,
            "harness_id": plan.harness_id,
            "status": plan.status,
            "seed_preset": plan.seed_preset,
            "agents": plan.agent_specs or plan.agents,
            "validation": plan.validation,
            "install_preview": plan.install_preview,
            "next_commands": plan.next_commands,
            "plan": plan.to_dict(),
            "saved_path": str(saved.relative_to(root)).replace("\\", "/") if saved.is_relative_to(root) else str(saved),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if plan.status not in {"draft", "planned"}:
                sys.exit(1)
            return
        print(render_harness_plan(plan, saved))
        if plan.status not in {"draft", "planned"}:
            sys.exit(1)
        return
    if command == "install":
        from engine.project_harness_plan import HarnessInstaller, render_harness_install_result

        result = HarnessInstaller().install(
            root,
            confirm=bool(getattr(args, "confirm", False)),
            seed_preset=getattr(args, "seed_preset", None),
        )
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.status != "installed":
                sys.exit(1)
            return
        print(render_harness_install_result(result))
        if result.status != "installed":
            sys.exit(1)
        return

    from engine.project_agents import (
        AgentRegistryBuilder,
        AgentRegistryStore,
        default_agent_registry_path,
    )
    from engine.project_harness import (
        HarnessProfileBuilder,
        HarnessProfileStore,
        default_harness_profile_path,
        render_harness_doctor,
        render_harness_profile,
    )
    from engine.project_harness_decisions import (
        HarnessDecisionStore,
        build_harness_decision,
        default_harness_decisions_path,
        load_latest_harness_suggestion,
        render_harness_decision_summary,
        render_harness_decisions,
        summarize_harness_decisions,
    )
    from engine.project_harness_policy import (
        build_and_save_policy_overlay,
        render_harness_policy_summary,
    )
    from engine.project_win_lane import build_and_save_lane_profile, render_lane_profile

    root = Path.cwd()
    command = getattr(args, "harness_command", None)
    if not command:
        print("harness 하위 명령이 필요합니다. 예: cambrian harness fit", file=sys.stderr)
        sys.exit(1)
    if not (root / ".cambrian" / "project.yaml").exists():
        print("Cambrian project mode is not initialized. Run `cambrian init --wizard` first.", file=sys.stderr)
        sys.exit(1)

    if command == "hire":
        command = "equip"
    elif command == "fire":
        command = "unequip"

    profile_path = default_harness_profile_path(root)
    registry_path = default_agent_registry_path(root)
    decisions_path = default_harness_decisions_path(root)
    profile_store = HarnessProfileStore()
    registry_store = AgentRegistryStore()
    decision_store = HarnessDecisionStore()

    if command == "fit":
        profile = HarnessProfileBuilder().build(root)
        profile_store.save(profile, profile_path)
        registry = AgentRegistryBuilder().build(root, harness=profile)
        registry_store.save(registry, registry_path)
        history_by_agent, dispatch_log = _refresh_agent_history_artifacts(root)
        payload = {
            "status": "fitted",
            "profile_path": str(profile_path.relative_to(root)).replace("\\", "/"),
            "registry_path": str(registry_path.relative_to(root)).replace("\\", "/"),
            "profile": profile.to_dict(),
            "registry": registry.to_dict(),
            "passport_histories": len(history_by_agent),
            "dispatch_log": dispatch_log,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_harness_profile(profile))
        print()
        print("Saved:")
        print(f"  {payload['profile_path']}")
        print(f"  {payload['registry_path']}")
        return

    if not profile_path.exists():
        print("Harness profile not found.\n\nRun:\n  cambrian harness fit", file=sys.stderr)
        sys.exit(1)

    profile = profile_store.load(profile_path)
    if command == "show":
        decisions_model = decision_store.load(decisions_path)
        policy_overlay, policy_path = build_and_save_policy_overlay(root)
        try:
            from engine.project_templates import load_current_template, render_current_template_summary

            current_template = load_current_template(root)
        except Exception:
            current_template = {}
        try:
            from engine.project_template_bootstrap import (
                load_template_bootstrap,
                render_template_bootstrap_summary,
            )

            template_bootstrap = load_template_bootstrap(root)
        except Exception:
            template_bootstrap = {}
        try:
            from engine.project_template_bootstrap_select import (
                load_template_bootstrap_choice,
                render_bootstrap_choice_result,
            )

            template_bootstrap_choice = load_template_bootstrap_choice(root)
        except Exception:
            template_bootstrap_choice = {}
        try:
            from engine.project_template_recommend import (
                load_template_recommendation_summary,
                render_template_recommendation_hint,
            )

            template_recommendation = load_template_recommendation_summary(root) if not current_template else {}
        except Exception:
            template_recommendation = {}
        try:
            from engine.project_template_decisions import (
                load_template_decision_summary,
                render_template_decision_summary,
            )

            template_decision_summary = load_template_decision_summary(root)
        except Exception:
            template_decision_summary = {}
        try:
            from engine.project_template_history import (
                load_template_history_summary,
                render_template_history_summary,
            )

            template_history_summary = (
                load_template_history_summary(root, str(current_template.get("name")))
                if current_template and current_template.get("name")
                else {}
            )
        except Exception:
            template_history_summary = {}
        try:
            from engine.project_template_library import (
                load_template_library_board_summary,
                render_template_library_summary,
            )

            template_library_summary = load_template_library_board_summary(root)
        except Exception:
            template_library_summary = {}
        try:
            from engine.project_template_library_decisions import (
                load_template_library_decision_summary,
                render_template_library_decision_summary,
            )

            template_library_decision_summary = load_template_library_decision_summary(root)
        except Exception:
            template_library_decision_summary = {}
        try:
            from engine.project_template_library_policy import (
                load_template_library_policy_summary,
                render_template_library_policy_summary,
            )

            template_library_policy_summary = load_template_library_policy_summary(root)
        except Exception:
            template_library_policy_summary = {}
        try:
            from engine.project_template_apply_guardrails import (
                load_template_apply_guardrail_summary,
                render_template_apply_guardrail_summary,
            )

            template_guardrail_summary = load_template_apply_guardrail_summary(root)
        except Exception:
            template_guardrail_summary = {}
        try:
            lane_profile, lane_path = build_and_save_lane_profile(root)
        except Exception as exc:
            logging.getLogger(__name__).warning("win lane profile build failed: %s", exc)
            lane_profile = None
            lane_path = None
        try:
            from engine.project_template_qualification_decisions import (
                load_lane_playbook_summary,
                load_qualification_decision_summary,
                render_lane_playbook_summary,
            )
            from engine.project_template_qualification_rollback import (
                load_qualification_adoption_summary,
                render_qualification_adoption_summary,
            )
            from engine.project_template_canary import (
                load_template_canary_summary,
                render_template_canary_summary,
            )
            from engine.project_template_canary_report import (
                load_latest_canary_report_summary,
                render_canary_report_summary,
            )
            from engine.project_template_canary_ledger import (
                load_canary_ledger_summary,
                render_canary_ledger_summary,
            )
            from engine.project_template_canary_outcomes import (
                load_canary_outcome_summary,
                render_canary_outcome_summary,
            )
            from engine.project_template_canary_review import (
                load_canary_review_summary,
                render_canary_review_summary,
            )
            from engine.project_template_challenge_matrix import (
                load_challenge_matrix_summary,
                render_challenge_matrix_summary,
            )

            lane_playbook_summary = load_lane_playbook_summary(root)
            qualification_decision_summary = load_qualification_decision_summary(root)
            qualification_adoption_summary = load_qualification_adoption_summary(root)
            template_canary_summary = load_template_canary_summary(root)
            canary_report_summary = load_latest_canary_report_summary(root)
            canary_ledger_summary = load_canary_ledger_summary(root)
            canary_outcome_summary = load_canary_outcome_summary(root)
            canary_review_summary = load_canary_review_summary(root)
            challenge_matrix_summary = load_challenge_matrix_summary(root)
        except Exception as exc:
            logging.getLogger(__name__).warning("qualification decision summary load failed: %s", exc)
            lane_playbook_summary = {}
            qualification_decision_summary = {}
            qualification_adoption_summary = {}
            template_canary_summary = {}
            canary_report_summary = {}
            canary_ledger_summary = {}
            canary_outcome_summary = {}
            canary_review_summary = {}
            challenge_matrix_summary = {}
        if getattr(args, "json_output", False):
            payload = profile.to_dict()
            payload["decisions"] = decisions_model.to_dict()
            payload["policy_overlay"] = policy_overlay.to_dict()
            payload["policy_overlay_path"] = str(policy_path.relative_to(root)).replace("\\", "/")
            payload["template_origin"] = current_template
            payload["template_bootstrap"] = template_bootstrap
            payload["template_bootstrap_choice"] = template_bootstrap_choice
            payload["template_recommendation"] = template_recommendation
            payload["template_decisions"] = template_decision_summary
            payload["template_history"] = template_history_summary
            payload["template_library"] = template_library_summary
            payload["template_library_decisions"] = template_library_decision_summary
            payload["template_library_policy"] = template_library_policy_summary
            payload["template_apply_guardrail"] = template_guardrail_summary
            payload["lane_playbook"] = lane_playbook_summary
            payload["template_qualification_decisions"] = qualification_decision_summary
            payload["template_qualification_adoptions"] = qualification_adoption_summary
            payload["template_canary_summary"] = template_canary_summary
            payload["canary_report_summary"] = canary_report_summary
            payload["canary_ledger_summary"] = canary_ledger_summary
            payload["canary_outcome_summary"] = canary_outcome_summary
            payload["canary_review_summary"] = canary_review_summary
            payload["challenge_matrix_summary"] = challenge_matrix_summary
            if lane_profile is not None:
                payload["win_lane"] = lane_profile.to_dict()
                if lane_path is not None:
                    payload["win_lane_path"] = str(lane_path.relative_to(root)).replace("\\", "/")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_harness_profile(profile))
        if lane_profile is not None:
            print()
            print(render_lane_profile(lane_profile))
        if lane_playbook_summary:
            print()
            print(render_lane_playbook_summary(lane_playbook_summary))
        if qualification_decision_summary and qualification_decision_summary.get("latest_status"):
            print()
            print("Template qualification decision:")
            print(f"  latest   : {qualification_decision_summary.get('latest_candidate')} {qualification_decision_summary.get('latest_status')}")
            if qualification_decision_summary.get("latest_reference"):
                print(f"  against  : {qualification_decision_summary.get('latest_reference')}")
        if qualification_adoption_summary:
            print()
            print(render_qualification_adoption_summary(qualification_adoption_summary))
        if template_canary_summary:
            print()
            print(render_template_canary_summary(template_canary_summary))
        if canary_report_summary:
            print()
            print(render_canary_report_summary(canary_report_summary))
        if canary_ledger_summary:
            print()
            print(render_canary_ledger_summary(canary_ledger_summary))
        if canary_outcome_summary:
            print()
            print(render_canary_outcome_summary(canary_outcome_summary))
        if canary_review_summary:
            print()
            print(render_canary_review_summary(canary_review_summary))
        if challenge_matrix_summary:
            print()
            print(render_challenge_matrix_summary(challenge_matrix_summary))
        if current_template:
            print()
            print(render_current_template_summary(current_template))
            if template_history_summary and template_history_summary.get("template_name"):
                print()
                print(render_template_history_summary(template_history_summary))
            if template_bootstrap:
                print()
                print(render_template_bootstrap_summary(template_bootstrap))
        elif template_bootstrap_choice and template_bootstrap_choice.get("selection_mode") == "skipped":
            print()
            print(render_bootstrap_choice_result(template_bootstrap_choice))
        elif template_recommendation and template_recommendation.get("best_template_name"):
            print()
            print(render_template_recommendation_hint(template_recommendation))
        if template_library_summary and (
            template_library_summary.get("preferred_templates")
            or template_library_summary.get("watch_templates")
            or template_library_summary.get("retire_candidates")
        ):
            print()
            print(render_template_library_summary(template_library_summary))
        if template_library_decision_summary and template_library_decision_summary.get("total"):
            print()
            print(render_template_library_decision_summary(template_library_decision_summary))
        if template_library_policy_summary and template_library_policy_summary.get("decision_count"):
            print()
            print(render_template_library_policy_summary(template_library_policy_summary))
        if template_decision_summary and (
            int(template_decision_summary.get("accepted", 0) or 0) > 0
            or int(template_decision_summary.get("dismissed", 0) or 0) > 0
        ):
            print()
            print(render_template_decision_summary(template_decision_summary))
        if template_guardrail_summary and template_guardrail_summary.get("template_name"):
            print()
            print(render_template_apply_guardrail_summary(template_guardrail_summary))
        if decisions_model.decisions:
            print()
            print(render_harness_decision_summary(decisions_model))
        if policy_overlay.accepted_decisions:
            print()
            print(render_harness_policy_summary(policy_overlay))
        try:
            from engine.project_team_decisions import (
                TeamDecisionStore,
                default_team_decisions_path,
                render_team_decisions,
            )

            team_decisions_model = TeamDecisionStore().load(default_team_decisions_path(root))
        except Exception:
            team_decisions_model = None
        if team_decisions_model is not None and team_decisions_model.decisions:
            print()
            print(render_team_decisions(team_decisions_model))
        try:
            from engine.project_team_policy import build_and_save_team_policy_overlay, render_team_policy_summary

            team_policy_overlay, _team_policy_path = build_and_save_team_policy_overlay(root)
        except Exception:
            team_policy_overlay = None
        if team_policy_overlay is not None and team_policy_overlay.accepted_decisions:
            print()
            print(render_team_policy_summary(team_policy_overlay))
        return

    if command == "doctor":
        from engine.project_agent_history import (
            default_agent_passports_dir,
            default_dispatch_log_path,
        )

        warnings: list[str] = []
        sources: list[str] = []
        for _, ref in profile.source_refs.items():
            candidate = root / ref
            if candidate.exists():
                sources.append(f"✓ {ref}")
            else:
                sources.append(f"! {ref}")
                warnings.append(f"missing source ref: {ref}")
        equipped_count = len(profile.active_agents)
        missing_agents = 0
        imported_count = 0
        blocked_compatibility_equipped = 0
        if registry_path.exists():
            registry = registry_store.load(registry_path)
            registry_ids = {agent.agent_id for agent in registry.agents}
            missing_agents = sum(1 for agent_id in profile.active_agents if agent_id not in registry_ids)
            imported_count = sum(1 for agent in registry.agents if agent.source_kind == "imported")
            blocked_compatibility_equipped = sum(
                1
                for agent in registry.agents
                if agent.source_kind == "imported"
                and agent.status == "equipped"
                and isinstance(agent.stats, dict)
                and str(agent.stats.get("compatibility_status", "")) == "blocked"
            )
            if missing_agents:
                warnings.append("some equipped agents are missing from registry")
        else:
            warnings.append("agent registry is missing")
            missing_agents = equipped_count
        passports_dir = default_agent_passports_dir(root)
        passport_histories_present = len(list(passports_dir.glob("*.yaml"))) if passports_dir.exists() else 0
        dispatch_log_present = default_dispatch_log_path(root).exists()
        if equipped_count and passport_histories_present == 0:
            warnings.append("agent passport histories are missing")
        status = "healthy" if not warnings else "warning"
        payload = {
            "status": status,
            "present": True,
            "sources": sources,
            "equipped_count": equipped_count,
            "missing_agents": missing_agents,
            "imported_count": imported_count,
            "blocked_compatibility_equipped": blocked_compatibility_equipped,
            "passport_histories_present": passport_histories_present,
            "dispatch_log_present": dispatch_log_present,
            "warnings": warnings,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_harness_doctor(payload))
        return

    if command == "accept":
        suggestion_id = str(getattr(args, "suggestion_id"))
        try:
            _report, suggestion, report_path = load_latest_harness_suggestion(root, suggestion_id)
        except KeyError:
            print(f"Suggestion not found: {suggestion_id}\n\nRun:\n  cambrian harness suggest", file=sys.stderr)
            sys.exit(1)
        try:
            decision = build_harness_decision(
                root,
                suggestion,
                status="accepted",
                resolution=getattr(args, "resolution", None),
                source_report_ref=str(report_path.relative_to(root)).replace("\\", "/"),
            )
        except (ValueError, FileNotFoundError) as exc:
            print(f"Harness accept blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        decision_store.add(decisions_path, decision)
        payload = {
            "status": "accepted",
            "decision": decision.to_dict(),
            "recorded_path": str(decisions_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print("Harness suggestion accepted.")
        print()
        print("Suggestion:")
        print(f"  {decision.summary}")
        if decision.resolution:
            print()
            print("Resolution:")
            print(f"  {decision.resolution}")
        if bool(decision.operational_effect.get("applied", False)):
            print()
            print("Operational effect:")
            print(f"  {decision.operational_effect.get('type')} applied")
        print()
        print("Recorded:")
        print(f"  {payload['recorded_path']}")
        return

    if command == "dismiss":
        suggestion_id = str(getattr(args, "suggestion_id"))
        try:
            _report, suggestion, report_path = load_latest_harness_suggestion(root, suggestion_id)
        except KeyError:
            print(f"Suggestion not found: {suggestion_id}\n\nRun:\n  cambrian harness suggest", file=sys.stderr)
            sys.exit(1)
        decision = build_harness_decision(
            root,
            suggestion,
            status="dismissed",
            resolution=getattr(args, "resolution", None),
            source_report_ref=str(report_path.relative_to(root)).replace("\\", "/"),
        )
        decision_store.add(decisions_path, decision)
        payload = {
            "status": "dismissed",
            "decision": decision.to_dict(),
            "recorded_path": str(decisions_path.relative_to(root)).replace("\\", "/"),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print("Harness suggestion dismissed.")
        if decision.resolution:
            print()
            print("Reason:")
            print(f"  {decision.resolution}")
        print()
        print("Recorded:")
        print(f"  {payload['recorded_path']}")
        return

    if command == "decisions":
        model = decision_store.load(decisions_path)
        filtered = [
            item.to_dict()
            for item in model.decisions
            if getattr(args, "status", None) is None or item.status == getattr(args, "status", None)
        ]
        if getattr(args, "json_output", False):
            print(
                json.dumps(
                    {
                        "schema_version": model.schema_version,
                        "updated_at": model.updated_at,
                        "decisions": filtered,
                        "summary": summarize_harness_decisions(model),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return
        print(render_harness_decisions(model, status=getattr(args, "status", None)))
        return

    if command == "suggest":
        from engine.project_harness_evolution import (
            HarnessEvolutionBuilder,
            HarnessEvolutionStore,
            default_harness_evolution_path,
            default_request_harness_evolution_path,
            render_harness_evolution,
        )

        report = HarnessEvolutionBuilder().build(root, request=getattr(args, "request", None))
        saved_path: Path | None = None
        if bool(getattr(args, "save", False)):
            target = (
                default_request_harness_evolution_path(root)
                if getattr(args, "request", None)
                else default_harness_evolution_path(root)
            )
            saved_path = HarnessEvolutionStore().save(report, target)
        payload = report.to_dict()
        decisions_model = decision_store.load(decisions_path)
        payload["decisions"] = decisions_model.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_harness_evolution(report))
        if decisions_model.decisions:
            print()
            print(render_harness_decision_summary(decisions_model))
        if saved_path is not None:
            print()
            print(f"Saved:\n  {saved_path}")
        return

    print("harness 하위 명령이 필요합니다. 예: cambrian harness show", file=sys.stderr)
    sys.exit(1)

def _handle_agent(args: argparse.Namespace) -> None:
    """cambrian agent 처리."""
    root = Path.cwd().resolve()
    command = getattr(args, "agent_command", None)
    if command == "dispatch":
        from engine.project_agent_dispatch import AgentDispatcher, render_agent_dispatch_result

        result = AgentDispatcher().dispatch(root, str(getattr(args, "request", "")))
        if getattr(args, "json_output", False):
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            if result.status != "created":
                sys.exit(1)
            return
        print(render_agent_dispatch_result(result))
        if result.status != "created":
            sys.exit(1)
        return
    if command == "run":
        from engine.project_custom_harness import create_custom_harness_job

        try:
            job_payload, pack_job_payload = create_custom_harness_job(
                root,
                str(getattr(args, "request", "")),
                selected_agent_id=str(getattr(args, "agent_id", "")),
                entry_mode="agent_run",
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Agent run blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = _job_start_payload(job_payload, pack_job_payload)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            if not payload.get("ok"):
                sys.exit(1)
            return
        print(_render_job_start_payload(payload))
        if not payload.get("ok"):
            sys.exit(1)
        return

    from engine.project_agents import (
        AgentRegistryBuilder,
        AgentRegistryStore,
        default_agent_registry_path,
        render_agent_list,
        render_agent_recommendation,
        render_agent_show,
    )
    from engine.project_agent_history import (
        AgentPassportHistoryStore,
        default_agent_passport_path,
        render_agent_history,
    )
    from engine.project_agent_reviews import (
        AgentReviewBuilder,
        AgentReviewStore,
        default_agent_reviews_dir,
        load_agent_review_summary,
        render_agent_review_add_summary,
        render_agent_reviews,
    )
    from engine.project_agent_transfer import (
        AgentPassportExporter,
        AgentPassportImporter,
        default_imported_agent_path,
        load_exported_agent_passport,
        render_agent_export_result,
        render_agent_import_result,
        update_imported_agent_local_status,
    )
    from engine.project_agent_trials import (
        AgentTrialRunner,
        AgentTrialStore,
        default_agent_trial_path,
        render_agent_trial,
        report_to_json,
        resolve_agent_trial_path,
    )
    from engine.project_dispatch_decisions import load_staffing_decision_summary
    from engine.project_harness import HarnessProfileStore, default_harness_profile_path

    root = Path.cwd()
    command = getattr(args, "agent_command", None)
    if not command:
        print("agent 하위 명령이 필요합니다. 예: cambrian agent list", file=sys.stderr)
        sys.exit(1)

    profile_path = default_harness_profile_path(root)
    registry_path = default_agent_registry_path(root)
    if not profile_path.exists() or not registry_path.exists():
        print("Harness or agent registry not found.\n\nRun:\n  cambrian harness fit", file=sys.stderr)
        sys.exit(1)

    profile_store = HarnessProfileStore()
    registry_store = AgentRegistryStore()
    profile = profile_store.load(profile_path)
    registry = AgentRegistryBuilder().build(root, harness=profile)
    registry_store.save(registry, registry_path)
    history_by_agent, dispatch_log = _refresh_agent_history_artifacts(root)
    history_store = AgentPassportHistoryStore()
    review_store = AgentReviewStore()

    def _find_agent(agent_id: str):
        for agent in registry.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def _review_summary(agent_id: str) -> dict:
        return load_agent_review_summary(root, agent_id).to_dict()

    if command == "list":
        payload = registry.to_dict()
        payload["history"] = history_by_agent
        payload["dispatch_log"] = dispatch_log
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_agent_list(registry, history_by_agent))
        return

    if command == "show":
        agent = _find_agent(str(getattr(args, "agent_id")))
        if agent is None:
            print(f"Agent not found: {getattr(args, 'agent_id')}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        history = history_by_agent.get(agent.agent_id, {})
        review_summary = _review_summary(agent.agent_id)
        staffing_summary = load_staffing_decision_summary(root, agent.agent_id)
        if getattr(args, "json_output", False):
            print(json.dumps({"agent": agent.to_dict(), "history": history, "reviews": review_summary, "staffing": staffing_summary}, indent=2, ensure_ascii=False))
            return
        print(render_agent_show(agent, history, review_summary, staffing_summary))
        return

    if command == "review":
        agent_id = str(getattr(args, "agent_id"))
        agent = _find_agent(agent_id)
        if agent is None:
            print(f"Agent not found: {agent_id}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        try:
            review = AgentReviewBuilder().build(
                root,
                agent_id,
                str(getattr(args, "text")),
                rating=str(getattr(args, "rating", "good")),
                review_kind=str(getattr(args, "review_kind", "performance")),
                tags=list(getattr(args, "review_tags", []) or []),
                session_ref=getattr(args, "session", None),
                artifact_refs=list(getattr(args, "review_artifacts", []) or []),
            )
        except ValueError as exc:
            print(f"Agent review blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = review_store.add(review, default_agent_reviews_dir(root))
        payload = {"status": "saved", "review": review.to_dict(), "saved_path": str(saved_path)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_agent_review_add_summary(review, str(saved_path.relative_to(root)).replace("\\", "/")))
        return

    if command == "reviews":
        agent_id = str(getattr(args, "agent_id"))
        agent = _find_agent(agent_id)
        if agent is None:
            print(f"Agent not found: {agent_id}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        reviews = review_store.list(
            default_agent_reviews_dir(root),
            agent_id=agent_id,
            rating=getattr(args, "rating", None),
            status=getattr(args, "status", None),
        )
        limit = max(0, int(getattr(args, "limit", 5) or 0))
        summary = _review_summary(agent_id)
        payload = {
            "agent_id": agent_id,
            "summary": summary,
            "reviews": [item.to_dict() for item in reviews[:limit] if limit > 0] if limit != 0 else [item.to_dict() for item in reviews],
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        visible = reviews[:limit] if limit > 0 else reviews
        print(render_agent_reviews(agent_id, visible))
        return

    if command == "trial":
        agent_id = str(getattr(args, "agent_id"))
        request_text = str(getattr(args, "request"))
        report = AgentTrialRunner().run(
            root,
            agent_id,
            request_text,
            current_lead_agent_id=getattr(args, "lead_agent_id", None),
        )
        saved_path = default_agent_trial_path(root, report)
        AgentTrialStore().save(report, saved_path)
        if getattr(args, "json_output", False):
            print(report_to_json(report))
            return
        print(render_agent_trial(report))
        return

    if command == "trial-show":
        try:
            trial_path = resolve_agent_trial_path(root, str(getattr(args, "trial_ref")))
            report = AgentTrialStore().load(trial_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Agent trial not found: {exc}", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(report_to_json(report))
            return
        print(render_agent_trial(report))
        return

    if command == "export":
        agent_id = str(getattr(args, "agent_id"))
        agent = _find_agent(agent_id)
        if agent is None:
            print(f"Agent not found: {agent_id}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        out_path = Path(str(getattr(args, "out"))) if getattr(args, "out", None) else None
        saved_path = AgentPassportExporter().export(root, agent_id, out_path=out_path)
        exported = load_exported_agent_passport(saved_path)
        payload = {
            "status": "exported",
            "saved_path": str(saved_path),
            "passport": exported.to_dict(),
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_agent_export_result(exported, saved_path))
        return

    if command == "import":
        passport_path = Path(str(getattr(args, "passport_path")))
        try:
            record = AgentPassportImporter().import_passport(root, passport_path, equip=False)
        except ValueError as exc:
            print(f"Agent import blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = default_imported_agent_path(root, record.agent_id)
        profile = profile_store.load(profile_path)
        registry = AgentRegistryBuilder().build(root, harness=profile)
        import_warning: str | None = None
        if bool(getattr(args, "equip", False)):
            if str(record.compatibility.get("status", "")) == "blocked":
                import_warning = "compatibility is blocked, so the imported agent was not equipped"
            else:
                registry, profile = AgentRegistryBuilder.equip(registry, profile, record.agent_id)
                update_imported_agent_local_status(root, record.agent_id, "equipped")
                record.local_status = "equipped"
        registry = AgentRegistryBuilder().build(root, harness=profile)
        registry_store.save(registry, registry_path)
        profile_store.save(profile, profile_path)
        history_by_agent, dispatch_log = _refresh_agent_history_artifacts(root)
        payload = {
            "status": "imported",
            "record": record.to_dict(),
            "saved_path": str(saved_path),
            "warning": import_warning,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_agent_import_result(record, saved_path))
        if import_warning:
            print()
            print(f"Warning:\n  {import_warning}")
        return

    if command == "recommend":
        recommendations = AgentRegistryBuilder.recommend(
            str(getattr(args, "request")),
            project_root=root,
            harness=profile,
            registry=registry,
        )
        payload = {
            "request": str(getattr(args, "request")),
            "recommendations": recommendations[:3],
            "harness_id": profile.harness_id,
        }
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_agent_recommendation(payload["request"], payload["recommendations"]))
        return

    if command == "history":
        agent_id = str(getattr(args, "agent_id"))
        agent = _find_agent(agent_id)
        if agent is None:
            print(f"Agent not found: {agent_id}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        history_path = default_agent_passport_path(root, agent_id)
        if not history_path.exists():
            history_by_agent, dispatch_log = _refresh_agent_history_artifacts(root)
        if not history_path.exists():
            print(f"Agent history not found: {agent_id}\n\nRun:\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        history = history_store.load(history_path)
        review_summary = _review_summary(agent_id)
        payload = history.to_dict()
        payload["reviews"] = review_summary
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_agent_history(history, limit=max(0, int(getattr(args, "limit", 5) or 0)), review_summary=review_summary))
        return

    if command == "equip":
        agent_id = str(getattr(args, "agent_id"))
        agent = _find_agent(agent_id)
        if agent is None:
            print(f"Agent not found: {agent_id}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        if agent.status == "equipped":
            payload = {"status": "unchanged", "agent_id": agent_id, "active_agents": list(profile.active_agents)}
        else:
            try:
                registry, profile = AgentRegistryBuilder.equip(registry, profile, agent_id)
            except ValueError as exc:
                print(f"Agent equip blocked: {exc}", file=sys.stderr)
                sys.exit(1)
            update_imported_agent_local_status(root, agent_id, "equipped")
            registry_store.save(registry, registry_path)
            profile_store.save(profile, profile_path)
            history_by_agent, dispatch_log = _refresh_agent_history_artifacts(root)
            payload = {"status": "equipped", "agent_id": agent_id, "active_agents": list(profile.active_agents)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(f"Equipped:\n  {agent_id}\n\nActive agents:")
        for item in profile.active_agents:
            print(f"  - {item}")
        return

    if command == "unequip":
        agent_id = str(getattr(args, "agent_id"))
        agent = _find_agent(agent_id)
        if agent is None:
            print(f"Agent not found: {agent_id}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        if agent.status != "equipped":
            payload = {"status": "unchanged", "agent_id": agent_id, "active_agents": list(profile.active_agents)}
        else:
            registry, profile = AgentRegistryBuilder.unequip(registry, profile, agent_id)
            update_imported_agent_local_status(root, agent_id, "imported")
            registry_store.save(registry, registry_path)
            profile_store.save(profile, profile_path)
            history_by_agent, dispatch_log = _refresh_agent_history_artifacts(root)
            payload = {"status": "unequipped", "agent_id": agent_id, "active_agents": list(profile.active_agents)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(f"Unequipped:\n  {agent_id}\n\nActive agents:")
        if profile.active_agents:
            for item in profile.active_agents:
                print(f"  - {item}")
        else:
            print("  - none")
        return

    print("agent 하위 명령이 필요합니다. 예: cambrian agent recommend \"fix the login bug\"", file=sys.stderr)
    sys.exit(1)

def _handle_dispatch(args: argparse.Namespace) -> None:
    """cambrian dispatch 처리."""
    from engine.project_dispatch import (
        DispatchBoardBuilder,
        DispatchBoardStore,
        default_dispatch_board_path,
        render_dispatch_board,
    )
    from engine.project_dispatch_decisions import (
        StaffingDecisionStore,
        build_staffing_decision,
        default_staffing_decisions_path,
        render_staffing_decision_result,
        render_staffing_decisions,
    )

    root = Path.cwd()
    command = getattr(args, "dispatch_command", None)
    if not command:
        print("dispatch 하위 명령이 필요합니다. 예: cambrian dispatch board", file=sys.stderr)
        sys.exit(1)

    builder = DispatchBoardBuilder()
    if command in {"accept", "dismiss"}:
        try:
            decision = build_staffing_decision(
                root,
                str(getattr(args, "agent_id")),
                status="accepted" if command == "accept" else "dismissed",
                decision_kind=str(getattr(args, "decision", "hire")),
                resolution=getattr(args, "resolution", None),
                source_ref=getattr(args, "source_ref", None),
            )
        except FileNotFoundError:
            print("Staffing decision requires a fitted harness.\n\nRun:\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        except KeyError as exc:
            print(f"Agent not found: {exc.args[0]}\n\nRun:\n  cambrian agent list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Staffing decision blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        saved_path = StaffingDecisionStore().add(default_staffing_decisions_path(root), decision)
        payload = {"status": decision.status, "decision": decision.to_dict(), "saved_path": str(saved_path)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_staffing_decision_result(decision, saved_path))
        return

    if command == "decisions":
        model = StaffingDecisionStore().load(default_staffing_decisions_path(root))
        status_filter = getattr(args, "status", None)
        payload = model.to_dict()
        if status_filter:
            payload["decisions"] = [
                item
                for item in payload.get("decisions", [])
                if isinstance(item, dict) and item.get("status") == status_filter
            ]
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_staffing_decisions(model, status=status_filter))
        return

    if command == "board":
        try:
            board = builder.build(root)
        except FileNotFoundError:
            print("Dispatch board를 만들려면 먼저 프로젝트를 초기화해야 합니다.\n\nRun:\n  cambrian init --wizard\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        saved_path: Path | None = None
        if bool(getattr(args, "save", False)):
            saved_path = DispatchBoardStore().save(board, default_dispatch_board_path(root))
        payload = board.to_dict()
        if saved_path is not None:
            payload["saved_path"] = str(saved_path)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_dispatch_board(board))
        if saved_path is not None:
            print()
            print(f"Saved:\n  {saved_path}")
        return

    if command == "recommend":
        try:
            board = builder.build(root, request=str(getattr(args, "request")))
        except FileNotFoundError:
            print("Dispatch recommendation을 만들려면 먼저 프로젝트를 초기화해야 합니다.\n\nRun:\n  cambrian init --wizard\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        payload = board.to_dict()
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_dispatch_board(board))
        return

    print("dispatch 하위 명령이 필요합니다. 예: cambrian dispatch recommend \"fix the login bug\"", file=sys.stderr)
    sys.exit(1)

def _handle_team(args: argparse.Namespace) -> None:
    """cambrian team 처리."""
    from engine.project_teams import (
        TeamPresetBuilder,
        TeamPresetStore,
        TeamRecommendationBuilder,
        apply_team_preset,
        default_team_presets_path,
        render_team_list,
        render_team_recommendation,
        render_team_show,
    )
    from engine.project_team_trials import (
        TeamTrialRunner,
        TeamTrialStore,
        default_team_trial_path,
        render_team_trial,
        resolve_team_trial_path,
        team_trial_to_json,
    )
    from engine.project_team_decisions import (
        TeamDecisionManager,
        TeamDecisionStore,
        default_team_decisions_path,
        load_team_decision_summary,
        render_team_decision_result,
        render_team_decisions,
    )

    root = Path.cwd()
    command = getattr(args, "team_command", None)
    if not command:
        print("team 하위 명령이 필요합니다. 예: cambrian team list", file=sys.stderr)
        sys.exit(1)
    teams_path = default_team_presets_path(root)
    store = TeamPresetStore()

    if command == "trial":
        try:
            report = TeamTrialRunner().run(
                root,
                str(getattr(args, "name")),
                str(getattr(args, "request")),
                current_team_name=getattr(args, "against", None),
            )
            saved_path = TeamTrialStore().save(report, default_team_trial_path(root, report))
            report.saved_path = str(saved_path)
        except KeyError as exc:
            print(f"Team trial blocked: team not found {exc.args[0]}\n\nRun:\n  cambrian team list", file=sys.stderr)
            sys.exit(1)
        payload = team_trial_to_json(report)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_team_trial(report))
        if report.status in {"blocked", "failed"}:
            sys.exit(1)
        return

    if command == "trial-show":
        try:
            report_path = resolve_team_trial_path(root, str(getattr(args, "trial_ref")))
            report = TeamTrialStore().load(report_path)
            report.saved_path = str(report_path)
        except FileNotFoundError as exc:
            print(f"Team trial not found: {exc.args[0]}\n\nRun:\n  cambrian team trial <team-name> \"request\"", file=sys.stderr)
            sys.exit(1)
        payload = team_trial_to_json(report)
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_team_trial(report))
        return

    if command == "accept":
        try:
            decision, decision_path = TeamDecisionManager().accept(
                root,
                str(getattr(args, "name")),
                str(getattr(args, "decision")),
                source_ref=getattr(args, "source_ref", None),
                resolution=getattr(args, "resolution", None),
            )
        except KeyError as exc:
            print(f"Team accept blocked: team not found {exc.args[0]}\n\nRun:\n  cambrian team list", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Team accept blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {"decision": decision.to_dict(), "path": str(decision_path)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_team_decision_result(decision, decision_path))
        return

    if command == "dismiss":
        try:
            decision, decision_path = TeamDecisionManager().dismiss(
                root,
                str(getattr(args, "name")),
                source_ref=getattr(args, "source_ref", None),
                resolution=getattr(args, "resolution", None),
            )
        except KeyError as exc:
            print(f"Team dismiss blocked: team not found {exc.args[0]}\n\nRun:\n  cambrian team list", file=sys.stderr)
            sys.exit(1)
        payload = {"decision": decision.to_dict(), "path": str(decision_path)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_team_decision_result(decision, decision_path))
        return

    if command == "decisions":
        model = TeamDecisionStore().load(default_team_decisions_path(root))
        status_filter = getattr(args, "status", None)
        if getattr(args, "json_output", False):
            payload = model.to_dict()
            if status_filter:
                payload["decisions"] = [
                    item for item in payload.get("decisions", []) if item.get("status") == status_filter
                ]
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print(render_team_decisions(model, status_filter=status_filter))
        return

    if command == "save":
        try:
            preset = TeamPresetBuilder().from_current_harness(
                root,
                str(getattr(args, "name")),
                description=getattr(args, "description", None),
                tags=list(getattr(args, "team_tags", []) or []),
            )
            saved_path = store.add(teams_path, preset)
        except FileNotFoundError:
            print("Team save requires a fitted harness.\n\nRun:\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Team save blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {"status": "saved", "team": preset.to_dict(), "saved_path": str(saved_path)}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print("Team saved.")
        print()
        print(render_team_show(preset))
        print()
        print(f"Saved:\n  {saved_path}")
        return

    if command == "list":
        model = store.load(teams_path)
        if getattr(args, "json_output", False):
            print(json.dumps(model.to_dict(), indent=2, ensure_ascii=False))
            return
        print(render_team_list(model))
        return

    if command == "show":
        model = store.load(teams_path)
        try:
            team = store.find(model, str(getattr(args, "name")))
        except KeyError as exc:
            print(f"Team not found: {exc.args[0]}\n\nRun:\n  cambrian team list", file=sys.stderr)
            sys.exit(1)
        if getattr(args, "json_output", False):
            print(json.dumps(team.to_dict(), indent=2, ensure_ascii=False))
            return
        try:
            from engine.project_team_policy import load_or_build_team_policy_overlay, team_policy_role

            policy_role = team_policy_role(team, load_or_build_team_policy_overlay(root))
        except Exception:
            policy_role = None
        print(render_team_show(team, load_team_decision_summary(root, team.team_id), policy_role=policy_role))
        return

    if command == "apply":
        try:
            team, model, warnings = apply_team_preset(root, str(getattr(args, "name")))
        except FileNotFoundError:
            print("Team apply requires a fitted harness and registry.\n\nRun:\n  cambrian harness fit", file=sys.stderr)
            sys.exit(1)
        except KeyError as exc:
            print(f"Team apply blocked: missing agent {exc.args[0]}", file=sys.stderr)
            sys.exit(1)
        except ValueError as exc:
            print(f"Team apply blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        payload = {"status": "applied", "team": team.to_dict(), "active_team_id": model.active_team_id, "warnings": warnings}
        if getattr(args, "json_output", False):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        print("Team applied.")
        print()
        print(render_team_show(team))
        if warnings:
            print()
            print("Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        return

    if command == "recommend":
        result = TeamRecommendationBuilder().recommend(root, request=str(getattr(args, "request")))
        if getattr(args, "json_output", False):
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        print(render_team_recommendation(result))
        return

    print("team 하위 명령이 필요합니다. 예: cambrian team recommend \"fix the login bug\"", file=sys.stderr)
    sys.exit(1)

def _handle_job(args: argparse.Namespace) -> None:
    command = getattr(args, "job_command", None)
    if command == "start":
        payload = _start_custom_job(str(getattr(args, "request", "")), selected_agent_id=None, entry_mode="job_start")
        _emit_cli_payload(payload, bool(getattr(args, "json_output", False)))
        _exit_if_blocked(payload)
        return
    if command == "ingest":
        from engine.project_custom_harness import ingest_custom_harness_job

        try:
            payload = ingest_custom_harness_job(Path.cwd(), str(getattr(args, "job_ref", "latest")), Path(str(getattr(args, "reply_path", ""))))
        except (FileNotFoundError, ValueError) as exc:
            payload = {"ok": False, "status": "blocked", "error": str(exc), "errors": [str(exc)]}
        _emit_cli_payload(payload, bool(getattr(args, "json_output", False)))
        _exit_if_blocked(payload)
        return
    if command == "validate":
        from engine.project_custom_harness import validate_custom_harness_job

        try:
            payload = validate_custom_harness_job(Path.cwd(), str(getattr(args, "job_ref", "latest")))
        except (FileNotFoundError, ValueError) as exc:
            payload = {"ok": False, "status": "blocked", "error": str(exc), "errors": [str(exc)]}
        _emit_cli_payload(payload, bool(getattr(args, "json_output", False)))
        _exit_if_blocked(payload)
        return
    if command == "complete":
        from engine.project_custom_harness import complete_custom_harness_job

        try:
            payload = complete_custom_harness_job(
                Path.cwd(),
                str(getattr(args, "job_ref", "latest")),
                str(getattr(args, "outcome", "")),
                str(getattr(args, "notes", "")),
            )
        except (FileNotFoundError, ValueError) as exc:
            payload = {"ok": False, "status": "blocked", "error": str(exc), "errors": [str(exc)]}
        _emit_cli_payload(payload, bool(getattr(args, "json_output", False)))
        _exit_if_blocked(payload)
        return
    print("job subcommand is required", file=sys.stderr)
    sys.exit(2)


def _start_custom_job(request: str, selected_agent_id: str | None, entry_mode: str) -> dict:
    from engine.project_custom_harness import create_custom_harness_job

    result, pack_job = create_custom_harness_job(Path.cwd(), request, selected_agent_id=selected_agent_id, entry_mode=entry_mode)
    job = dict(result.get("job", {})) if isinstance(result.get("job"), dict) else {}
    outcome = dict(job.get("outcome_snapshot", {})) if isinstance(job.get("outcome_snapshot"), dict) else {}
    packet_ref = str(pack_job.get("packet_ref") or job.get("linked_bridge_packet_ref") or "")
    return {
        "ok": True,
        "status": "created",
        "job_status": job.get("status"),
        "job_id": job.get("job_id"),
        "harness_id": outcome.get("harness_id") or job.get("pack_id"),
        "workforce_id": outcome.get("workforce_id"),
        "selected_agents": list(outcome.get("selected_agents", [])) if isinstance(outcome.get("selected_agents"), list) else [],
        "selected_skills": list(outcome.get("selected_skills", [])) if isinstance(outcome.get("selected_skills"), list) else [],
        "dispatch_reason": outcome.get("dispatch_reason"),
        "change_policy": outcome.get("change_policy"),
        "validation_commands": list(outcome.get("validation_commands", [])) if isinstance(outcome.get("validation_commands"), list) else [],
        "request_packet_ref": packet_ref,
        "request_packet": packet_ref,
        "job_ref": pack_job.get("job_ref"),
        "ai_provider_called": False,
        "source_code_modified": False,
        "next_commands": [
            "cambrian job ingest latest ai_reply_patch_candidate.yaml",
            "cambrian job validate latest",
        ],
        "pack_job": dict(pack_job),
    }


if __name__ == "__main__":
    main()
