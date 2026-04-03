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
        help="최대 재시도 (기본값: 3)",
    )
    run_parser.add_argument(
        "--auto-evolve",
        action="store_true",
        help="fitness < 0.3인 스킬에 자동 진화 실행",
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

    subparsers.add_parser(
        "stats",
        help="엔진 통계",
        parents=[common_parser],
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
        skill = engine._absorber.absorb(args.path)
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
        engine._absorber.remove(args.skill_id)
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
    """cambrian stats 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    engine = _create_engine(args)
    skills = engine.list_skills()

    counts = {
        "active": 0,
        "newborn": 0,
        "dormant": 0,
        "fossil": 0,
    }

    for skill in skills:
        status = skill["status"]
        if status in counts:
            counts[status] += 1

    print("Cambrian Engine Stats")
    print("---------------------")
    print(f"Total skills: {len(skills)}")
    print(f"Active: {counts['active']}")
    print(f"Newborn: {counts['newborn']}")
    print(f"Dormant: {counts['dormant']}")
    print(f"Fossil: {counts['fossil']}")


def _handle_export(args: argparse.Namespace) -> None:
    """cambrian export 처리.

    Args:
        args: argparse가 파싱한 네임스페이스
    """
    from engine.portability import SkillPorter

    engine = _create_engine(args)
    porter = SkillPorter(engine._loader, engine.get_registry(), args.pool)

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
    porter = SkillPorter(engine._loader, engine.get_registry(), args.pool)

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


if __name__ == "__main__":
    main()
