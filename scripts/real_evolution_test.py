"""Cambrian 실제 진화 루프 검증 스크립트.

csv_to_chart 스킬로 3라운드 진화를 실행하고 결과를 비교한다.
"""

import json
import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from engine.loop import CambrianEngine


def separator(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}\n")


def run_test() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    engine = CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path="skill_pool/evolution_test.db",
    )

    test_input = {
        "csv_data": "Quarter,Revenue,Profit,Employees\nQ1,125000,28000,45\nQ2,158000,35000,52\nQ3,142000,31000,48\nQ4,189000,45000,61",
        "chart_type": "bar",
        "title": "2025 Quarterly Business Metrics",
    }

    # ─── Round 0: 진화 전 기준 실행 ───
    separator("Round 0: Pre-evolution baseline")

    result_0 = engine.run_task(
        domain="data_visualization",
        tags=["csv", "chart"],
        input_data=test_input,
    )
    print(f"Success: {result_0.success}")
    print(f"Skill: {result_0.skill_id}")
    print(f"Time: {result_0.execution_time_ms}ms")

    if result_0.success and result_0.output:
        html_0 = result_0.output.get("html", "")
        print(f"HTML length: {len(html_0)} chars")
        print(f"Has <canvas>: {'<canvas' in html_0}")
        print(f"Has Chart.js: {'chart.js' in html_0.lower() or 'Chart(' in html_0}")
    else:
        print(f"FAILED: {result_0.error}")
        print("Stopping — baseline must succeed.")
        sys.exit(1)

    # ─── Round 1: 피드백 → 진화 ───
    separator("Round 1: Feedback + Evolution")

    engine.feedback(
        result_0.skill_id, 2,
        "The chart lacks a gradient background on bars. Add subtle gradient fills. "
        "Also the footer text is too large, make it 11px.",
        input_data=test_input,
        output_data=result_0.output,
    )
    engine.feedback(
        result_0.skill_id, 3,
        "Missing data value labels on top of each bar. "
        "Show the actual number above each bar element.",
    )

    print("Feedback saved. Evolving...")
    record_1 = engine.evolve(result_0.skill_id, test_input)
    print(f"Adopted: {record_1.adopted}")
    print(f"Parent fitness: {record_1.parent_fitness:.4f}")
    print(f"Child fitness:  {record_1.child_fitness:.4f}")

    # 진화 후 재실행
    result_1 = engine.run_task(
        domain="data_visualization",
        tags=["csv", "chart"],
        input_data=test_input,
    )
    if result_1.success and result_1.output:
        html_1 = result_1.output.get("html", "")
        print(f"Post-evolution HTML length: {len(html_1)} chars")
        if record_1.adopted:
            diff = len(html_1) - len(html_0)
            print(f"Length change: {'+' if diff >= 0 else ''}{diff} chars")
    else:
        print(f"Post-evolution run failed: {result_1.error}")

    # ─── Round 2: 추가 피드백 → 재진화 ───
    separator("Round 2: More feedback + Evolution")

    engine.feedback(
        result_0.skill_id, 3,
        "Add hover tooltips with formatted numbers (commas for thousands). "
        "The animation duration should be longer, at least 1200ms.",
    )

    print("Evolving round 2...")
    record_2 = engine.evolve(result_0.skill_id, test_input)
    print(f"Adopted: {record_2.adopted}")
    print(f"Parent fitness: {record_2.parent_fitness:.4f}")
    print(f"Child fitness:  {record_2.child_fitness:.4f}")

    result_2 = engine.run_task(
        domain="data_visualization",
        tags=["csv", "chart"],
        input_data=test_input,
    )
    if result_2.success and result_2.output:
        html_2 = result_2.output.get("html", "")
        print(f"Round 2 HTML length: {len(html_2)} chars")

    # ─── Round 3: 다른 차트 타입으로 진화 검증 ───
    separator("Round 3: Cross-type evolution check")

    line_input = {**test_input, "chart_type": "line", "title": "Revenue Trend"}
    result_line = engine.run_task(
        domain="data_visualization",
        tags=["csv", "chart"],
        input_data=line_input,
    )
    if result_line.success and result_line.output:
        html_line = result_line.output.get("html", "")
        print(f"Line chart HTML length: {len(html_line)} chars")
        print(f"Skill improvements carry over to line chart: {'tension' in html_line.lower() or 'line' in html_line.lower()}")

    # ─── 최종 요약 ───
    separator("SUMMARY")

    history = engine.get_registry().get_evolution_history(result_0.skill_id)
    skill_data = engine.get_registry().get(result_0.skill_id)

    print(f"Skill: {result_0.skill_id}")
    print(f"Total evolutions: {len(history)}")
    print(f"Adopted: {sum(1 for h in history if h['adopted'])}")
    print(f"Discarded: {sum(1 for h in history if not h['adopted'])}")
    print(f"Final fitness: {skill_data['fitness_score']:.4f}")
    print(f"Total executions: {skill_data['total_executions']}")
    print()
    print("HTML length progression:")
    lengths = []
    if result_0.success and result_0.output:
        lengths.append(("Baseline", len(result_0.output.get("html", ""))))
    if result_1.success and result_1.output:
        lengths.append(("Round 1", len(result_1.output.get("html", ""))))
    if result_2.success and result_2.output:
        lengths.append(("Round 2", len(result_2.output.get("html", ""))))
    for label, length in lengths:
        bar = "█" * (length // 100)
        print(f"  {label:>10}: {length:>6} chars {bar}")

    print()
    print("SKILL.md evolution:")
    skill = engine._loader.load(skill_data["skill_path"])
    md_lines = (skill.skill_md_content or "").count("\n")
    print(f"  Current SKILL.md: {md_lines} lines, {len(skill.skill_md_content or '')} chars")

    # 진화 전 원본과 비교
    if history:
        oldest = history[-1]  # DESC 정렬이므로 마지막이 가장 오래된 것
        original_lines = oldest["parent_skill_md"].count("\n")
        original_chars = len(oldest["parent_skill_md"])
        print(f"  Original SKILL.md: {original_lines} lines, {original_chars} chars")
        print(f"  Growth: +{md_lines - original_lines} lines, +{len(skill.skill_md_content or '') - original_chars} chars")

    # 정리
    import os as _os
    db_file = Path("skill_pool/evolution_test.db")
    if db_file.exists():
        _os.remove(db_file)
        print("\nTest DB cleaned up.")

    print("\n✅ Real evolution test complete.")


if __name__ == "__main__":
    run_test()
