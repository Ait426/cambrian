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
    skill_parser.add_argument("skill_id", help="스킬 ID")

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
        help="스킬 1회 진화",
        parents=[common_parser],
    )
    evolve_parser.add_argument("skill_id", help="진화시킬 스킬 ID")
    evolve_parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="벤치마크용 테스트 입력 (JSON 문자열)",
    )

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
        help="프로젝트 하네스를 초기화",
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
        elif args.command == "status":
            _handle_status(args)
        elif args.command == "summary":
            _handle_summary(args)
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
    """cambrian evolve 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
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
    print(f"[OK] Evolution complete — variant {status}")
    print(f"  Skill: {record.skill_id}")
    print(f"  Parent fitness: {record.parent_fitness:.4f}")
    print(f"  Child fitness:  {record.child_fitness:.4f}")
    print(f"  Record ID: {record.id}")


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
    from engine.project_wizard import (
        ProjectWizard,
        ProjectWizardResult,
        load_answers_file,
        render_wizard_summary,
    )

    target = Path(args.dir).resolve()
    result: object
    is_wizard = bool(getattr(args, "wizard", False))

    if is_wizard:
        answers_payload: dict | None = None
        answers_file = getattr(args, "answers_file", None)
        if answers_file:
            try:
                answers_payload = load_answers_file(Path(answers_file).resolve())
            except (OSError, ValueError, yaml.YAMLError) as exc:
                result = ProjectWizardResult(
                    status="blocked",
                    answers=None,
                    created_files=[],
                    skipped_files=[],
                    warnings=[],
                    errors=[f"answers-file 로드 실패: {exc}"],
                    next_actions=["answers-file 경로와 YAML 형식을 확인하세요."],
                )
            else:
                detected = ProjectInitializer._detect(target)
                result = ProjectWizard().run(
                    project_root=target,
                    detected=detected,
                    answers=answers_payload,
                    force=bool(getattr(args, "force", False)),
                    interactive=False,
                )
        elif getattr(args, "non_interactive", False):
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
                "project_name": getattr(args, "name", None),
                "project_type": getattr(args, "project_type", None),
                "stack": getattr(args, "stack", None),
                "test_command": getattr(args, "test_cmd", None),
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
            project_type=getattr(args, "project_type", None),
            stack=getattr(args, "stack", None),
            test_cmd=getattr(args, "test_cmd", None),
            force=bool(getattr(args, "force", False)),
        )

    # 기존 init 테스트 호환: 별도 대상 디렉토리를 줄 때는 예전 스캐폴드도 유지한다.
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
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if is_wizard:
        print(render_wizard_summary(result))
        return

    print(render_init_summary(result))


def _handle_status(args: argparse.Namespace) -> None:
    """cambrian status 처리."""
    from engine.project_mode import ProjectStatusReader, render_status_summary
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


if __name__ == "__main__":
    main()
