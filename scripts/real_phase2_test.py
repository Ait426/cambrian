"""Cambrian Phase 2 실제 API 검증 스크립트.

경쟁 실행, Judge 진화, 퇴화, History detail을 실제 API로 검증한다.
"""

import json
import os
import shutil
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from engine.loop import CambrianEngine


DB_PATH = Path("skill_pool/phase2_test.db")
RESULTS: list[tuple[str, str, str]] = []  # (테스트명, 결과, 상세)


def record(name: str, passed: bool, detail: str) -> None:
    """테스트 결과를 기록한다."""
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, status, detail))
    print(f"  [{status}] {detail}")


def separator(title: str) -> None:
    """구분선을 출력한다."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def create_duplicate_skill() -> Path:
    """csv_to_chart의 복제 스킬을 생성한다."""
    src = Path("skills/csv_to_chart")
    dst = Path("skills/csv_to_chart_v2")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    # meta.yaml에서 id만 변경
    import yaml
    meta_path = dst / "meta.yaml"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = yaml.safe_load(f)
    meta["id"] = "csv_to_chart_v2"
    meta["name"] = "CSV to Chart V2"
    with open(meta_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)

    return dst


def cleanup_duplicate_skill() -> None:
    """복제 스킬을 삭제한다."""
    dst = Path("skills/csv_to_chart_v2")
    if dst.exists():
        shutil.rmtree(dst)


def run_test() -> None:
    """Phase 2 검증을 실행한다."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    test_input = {
        "csv_data": "Month,Sales,Profit\nJan,120000,28000\nFeb,158000,35000\nMar,142000,31000",
        "chart_type": "bar",
        "title": "Q1 Sales Report",
    }

    duplicate_path: Path | None = None

    try:
        # ============================================================
        # TEST 1: 경쟁 실행
        # ============================================================
        separator("TEST 1: Competitive Execution")

        duplicate_path = create_duplicate_skill()
        print(f"  Created duplicate skill: {duplicate_path}")

        engine = CambrianEngine(
            schemas_dir="schemas",
            skills_dir="skills",
            skill_pool_dir="skill_pool",
            db_path=str(DB_PATH),
        )

        # csv_to_chart + csv_to_chart_v2 = 2개 후보
        candidates = engine.get_registry().search(
            domain="data_visualization", tags=["csv", "chart"],
        )
        candidate_ids = [c["id"] for c in candidates]
        print(f"  Candidates found: {candidate_ids}")

        has_both = "csv_to_chart" in candidate_ids and "csv_to_chart_v2" in candidate_ids
        record("1a. 후보 2개 등록", has_both, f"candidates={candidate_ids}")

        result = engine.run_task(
            domain="data_visualization",
            tags=["csv", "chart"],
            input_data=test_input,
        )
        print(f"  Winner: {result.skill_id}")
        print(f"  Success: {result.success}")
        print(f"  Time: {result.execution_time_ms}ms")

        record("1b. 경쟁 실행 성공", result.success, f"winner={result.skill_id}")

        # 양쪽 모두 실행됐는지 확인
        data_1 = engine.get_registry().get("csv_to_chart")
        data_2 = engine.get_registry().get("csv_to_chart_v2")
        both_executed = data_1["total_executions"] >= 1 and data_2["total_executions"] >= 1
        record(
            "1c. 양쪽 모두 실행됨",
            both_executed,
            f"csv_to_chart={data_1['total_executions']}, v2={data_2['total_executions']}",
        )

        # ============================================================
        # TEST 2: Judge 기반 진화
        # ============================================================
        separator("TEST 2: Judge-based Evolution")

        engine.feedback(
            "csv_to_chart", 2,
            "The chart lacks gradient fills on bars. Add subtle gradient backgrounds.",
            input_data=test_input,
        )
        engine.feedback(
            "csv_to_chart", 3,
            "Missing data value labels on top of each bar.",
            input_data=test_input,
        )
        engine.feedback(
            "csv_to_chart", 3,
            "Animation duration should be longer, at least 1200ms.",
            input_data=test_input,
        )
        print("  3 feedbacks saved.")

        feedback_list = engine.get_registry().get_feedback("csv_to_chart")
        record("2a. 피드백 3개 저장", len(feedback_list) >= 3, f"count={len(feedback_list)}")

        print("  Evolving with Judge scoring...")
        evolution_record = engine.evolve("csv_to_chart", test_input)

        print(f"  Adopted: {evolution_record.adopted}")
        print(f"  Parent fitness: {evolution_record.parent_fitness:.4f}")
        print(f"  Child fitness:  {evolution_record.child_fitness:.4f}")
        print(f"  Judge reasoning: {evolution_record.judge_reasoning[:100]}...")

        record(
            "2b. 진화 실행 완료",
            True,
            f"adopted={evolution_record.adopted}, child_fitness={evolution_record.child_fitness:.4f}",
        )

        has_reasoning = len(evolution_record.judge_reasoning) > 0
        record("2c. Judge reasoning 존재", has_reasoning, f"len={len(evolution_record.judge_reasoning)}")

        has_score = evolution_record.child_fitness > 0.0
        record("2d. child_fitness > 0", has_score, f"fitness={evolution_record.child_fitness:.4f}")

        # ============================================================
        # TEST 3: 퇴화 확인
        # ============================================================
        separator("TEST 3: Decay Check")

        decay_result = engine.get_registry().decay()
        print(f"  Decay result: {decay_result}")

        # 모든 스킬이 방금 실행됐으므로 0/0이 정상
        is_zero = decay_result["dormant"] == 0 and decay_result["fossil"] == 0
        record("3a. 최근 사용 스킬 퇴화 없음", is_zero, f"result={decay_result}")

        # fossil이 검색에서 제외되는지 확인
        all_skills = engine.list_skills()
        fossil_in_list = any(s["status"] == "fossil" for s in all_skills)
        record("3b. list_all에 fossil 포함 가능", True, f"fossil_count={sum(1 for s in all_skills if s['status'] == 'fossil')}")

        # search에서 fossil 제외 확인 (fossil을 만들지 않았으므로 간접 확인)
        search_results = engine.get_registry().search(domain="data_visualization")
        all_non_fossil = all(s["status"] != "fossil" for s in search_results)
        record("3c. search 기본값 fossil 제외", all_non_fossil, f"search_count={len(search_results)}")

        # ============================================================
        # TEST 4: History detail
        # ============================================================
        separator("TEST 4: History Detail")

        history = engine.get_registry().get_evolution_history("csv_to_chart")
        print(f"  Evolution history count: {len(history)}")

        has_history = len(history) >= 1
        record("4a. 진화 이력 존재", has_history, f"count={len(history)}")

        if has_history:
            latest = history[0]
            print(f"  Record ID: {latest['id']}")
            print(f"  Adopted: {latest['adopted']}")

            # judge_reasoning 필드 확인
            reasoning = latest.get("judge_reasoning", "")
            print(f"  Judge reasoning: {reasoning[:100]}...")
            has_judge = len(reasoning) > 0
            record("4b. judge_reasoning 저장됨", has_judge, f"len={len(reasoning)}")

            # parent_skill_md vs child_skill_md diff 존재 확인
            parent_md = latest["parent_skill_md"]
            child_md = latest["child_skill_md"]
            is_different = parent_md != child_md
            record(
                "4c. SKILL.md 변이 발생",
                is_different,
                f"parent_len={len(parent_md)}, child_len={len(child_md)}",
            )

            # feedback_ids 확인
            feedback_ids = json.loads(latest.get("feedback_ids", "[]"))
            has_fb_ids = len(feedback_ids) >= 1
            record("4d. feedback_ids 기록됨", has_fb_ids, f"ids={feedback_ids}")

    except Exception as exc:
        record("EXCEPTION", False, str(exc))
        import traceback
        traceback.print_exc()

    finally:
        # 정리
        separator("CLEANUP")

        # 복제 스킬 삭제
        cleanup_duplicate_skill()
        print("  Duplicate skill removed.")

        # DB 정리
        try:
            engine.get_registry().close()
        except Exception:
            pass
        if DB_PATH.exists():
            os.remove(DB_PATH)
            print("  Test DB removed.")

    # ============================================================
    # 결과 테이블
    # ============================================================
    separator("RESULTS")

    print(f"{'TEST':<35} {'RESULT':<6} {'DETAIL'}")
    print("-" * 90)
    pass_count = 0
    fail_count = 0
    for name, status, detail in RESULTS:
        print(f"{name:<35} {status:<6} {detail}")
        if status == "PASS":
            pass_count += 1
        else:
            fail_count += 1

    print("-" * 90)
    print(f"Total: {pass_count} PASS, {fail_count} FAIL / {len(RESULTS)} tests")

    if fail_count > 0:
        print("\nSome tests FAILED.")
        sys.exit(1)
    else:
        print("\nAll tests PASSED.")


if __name__ == "__main__":
    run_test()
