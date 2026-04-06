"""Cambrian CLI 진입점."""

import argparse
import json
import logging
import sys
from pathlib import Path

from engine.absorber import SkillAbsorber
from engine.exceptions import (
    SecurityViolationError,
    SkillNotFoundError,
    SkillValidationError,
)
from engine.loop import CambrianEngine


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
        description="Cambrian - Self-evolving skill engine",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="명령어")

    run_parser = subparsers.add_parser(
        "run",
        help="태스크 실행",
        parents=[common_parser],
    )
    run_parser.add_argument("--domain", "-d", required=True, help="스킬 도메인")
    run_parser.add_argument("--tags", "-t", nargs="+", required=True, help="스킬 태그")
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
        help="새 프로젝트 초기화 (시드 스킬 + 설정 파일 생성)",
        parents=[common_parser],
    )
    init_parser.add_argument(
        "--dir",
        type=str,
        default="./cambrian_project",
        help="초기화 디렉토리 (기본값: ./cambrian_project)",
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

    args = parser.parse_args()

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
        elif args.command == "search":
            _handle_search(args)
        elif args.command == "scan":
            _handle_scan(args)
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

    return CambrianEngine(
        schemas_dir=args.schemas,
        skills_dir=args.skills,
        skill_pool_dir=args.pool,
        db_path=args.db,
        external_skill_dirs=args.external if args.external else None,
        provider=provider,
    )


def _handle_run(args: argparse.Namespace) -> None:
    """cambrian run 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    try:
        if getattr(args, 'input_file', None):
            from pathlib import Path
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

    print(
        f"\nBudget Limits:"
        f"\n  Max candidates/run: {engine.MAX_CANDIDATES_PER_RUN} | "
        f"Max Mode A/run: {engine.MAX_MODE_A_PER_RUN} | "
        f"Max eval cases: {engine.MAX_EVAL_CASES}"
    )


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

    target = Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)

    # 시드 스킬 복사
    src_skills = Path(args.skills)
    dst_skills = target / "skills"
    if dst_skills.exists():
        print(f"skills/ already exists in {target}, skipping copy.")
    else:
        shutil.copytree(src_skills, dst_skills)
        print(f"Copied {len(list(dst_skills.iterdir()))} skills to {dst_skills}")

    # schemas 복사
    src_schemas = Path(args.schemas)
    dst_schemas = target / "schemas"
    if not dst_schemas.exists():
        shutil.copytree(src_schemas, dst_schemas)

    # skill_pool 생성
    (target / "skill_pool").mkdir(exist_ok=True)

    # 설정 파일 생성
    config_path = target / "cambrian.yaml"
    if not config_path.exists():
        import yaml

        config = {
            "provider": "anthropic",
            "model": None,
            "db_path": "skill_pool/registry.db",
            "skills_dir": "skills",
            "schemas_dir": "schemas",
            "skill_pool_dir": "skill_pool",
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)

    print(f"\n[OK] Initialized Cambrian project at {target}")
    print(f"Ready! Run: cd {target} && cambrian skills")


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


if __name__ == "__main__":
    main()
