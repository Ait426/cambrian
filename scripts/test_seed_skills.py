"""Cambrian 신규 시드 스킬 7개 실제 API 검증 스크립트."""

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from engine.loop import CambrianEngine

RESULTS: list[tuple[str, bool, str]] = []

SKILL_TESTS = {
    "email_draft": {
        "input": {
            "situation": "Client missed the deadline for Q1 report submission. Need to send a polite reminder.",
            "recipient": "Kim Jaehyun, Project Manager",
            "tone": "formal",
        },
        "expected_keys": ["html", "subject"],
    },
    "meeting_summary": {
        "input": {
            "transcript": "Meeting started at 2pm. John: We need to finalize the Q2 budget. Sarah: I'll prepare the draft by Friday. Mike: The client wants a demo next week. John: Sarah, also check the vendor contracts. Meeting ended at 2:30pm.",
            "attendees": ["John", "Sarah", "Mike"],
        },
        "expected_keys": ["html"],
    },
    "code_review": {
        "input": {
            "code": "def calculate(x, y):\n    result = x / y\n    return result\n\nprint(calculate(10, 0))",
            "language": "python",
        },
        "expected_keys": ["issues", "summary"],
    },
    "data_cleaner": {
        "input": {
            "csv_data": "Name,Age,Email\nJohn Doe,25,john@example.com\njane,,JANE@EXAMPLE.COM\n  Bob  ,thirty,bob@\n,40,valid@test.com",
            "rules": ["Remove rows with empty name", "Normalize email to lowercase", "Convert age to integer"],
        },
        "expected_keys": ["cleaned_csv", "changes_made"],
    },
    "seo_meta": {
        "input": {
            "url": "https://example.com/products/ai-assistant",
            "description": "An AI-powered assistant that helps with daily tasks, scheduling, and email management.",
            "keywords": ["AI assistant", "productivity", "automation"],
        },
        "expected_keys": ["title", "meta_description"],
    },
    "api_doc": {
        "input": {
            "endpoint": "/api/v1/users/{id}",
            "method": "GET",
            "params": {"id": {"type": "integer", "description": "User ID"}},
            "response_example": {"id": 1, "name": "John", "email": "john@example.com"},
        },
        "expected_keys": ["html"],
    },
    "expense_report": {
        "input": {
            "expenses": [
                {"date": "2026-03-01", "category": "Transportation", "amount": 45000, "description": "Taxi to client meeting"},
                {"date": "2026-03-05", "category": "Meals", "amount": 32000, "description": "Team lunch"},
                {"date": "2026-03-10", "category": "Office Supplies", "amount": 15000, "description": "Printer paper"},
                {"date": "2026-03-15", "category": "Transportation", "amount": 28000, "description": "KTX to Busan"},
                {"date": "2026-03-20", "category": "Meals", "amount": 18000, "description": "Client dinner"},
            ],
            "period": "2026-03",
        },
        "expected_keys": ["html", "total"],
    },
}


def run_test() -> None:
    """7개 스킬을 실제 API로 테스트한다."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    engine = CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )

    for skill_id, test_config in SKILL_TESTS.items():
        print(f"\n{'=' * 50}")
        print(f"  Testing: {skill_id}")
        print(f"{'=' * 50}")

        skill_data = engine.get_registry().get(skill_id)
        domain = skill_data["domain"]
        tags = json.loads(skill_data["tags"]) if isinstance(skill_data["tags"], str) else skill_data["tags"]

        try:
            result = engine.run_task(
                domain=domain,
                tags=tags[:2],
                input_data=test_config["input"],
            )

            if not result.success:
                RESULTS.append((skill_id, False, f"FAILED: {result.error}"))
                print(f"  FAILED: {result.error}")
                continue

            output = result.output or {}
            print(f"  Success: True")
            print(f"  Time: {result.execution_time_ms}ms")
            print(f"  Output keys: {list(output.keys())}")

            # expected_keys 확인
            missing = [k for k in test_config["expected_keys"] if k not in output]
            if missing:
                # raw_output에 들어갔을 수 있음
                if "raw_output" in output:
                    RESULTS.append((skill_id, False, f"JSON extraction failed — got raw_output ({len(output['raw_output'])} chars)"))
                    print(f"  WARNING: raw_output, missing keys: {missing}")
                else:
                    RESULTS.append((skill_id, False, f"Missing keys: {missing}"))
                    print(f"  MISSING KEYS: {missing}")
                continue

            # 값 길이 확인
            for key in test_config["expected_keys"]:
                val = output.get(key)
                if isinstance(val, str):
                    print(f"  {key}: {len(val)} chars")
                elif isinstance(val, (list, dict)):
                    print(f"  {key}: {type(val).__name__}, {len(val)} items")
                else:
                    print(f"  {key}: {val}")

            RESULTS.append((skill_id, True, f"{result.execution_time_ms}ms, keys={list(output.keys())}"))

        except Exception as exc:
            RESULTS.append((skill_id, False, f"EXCEPTION: {exc}"))
            print(f"  EXCEPTION: {exc}")

    # 결과 테이블
    print(f"\n{'=' * 60}")
    print("  RESULTS")
    print(f"{'=' * 60}\n")

    print(f"{'SKILL':<25} {'RESULT':<6} {'DETAIL'}")
    print("-" * 70)
    pass_count = 0
    for skill_id, passed, detail in RESULTS:
        status = "PASS" if passed else "FAIL"
        if passed:
            pass_count += 1
        print(f"{skill_id:<25} {status:<6} {detail}")

    print("-" * 70)
    print(f"Total: {pass_count}/{len(RESULTS)} PASS")

    if pass_count < len(RESULTS):
        sys.exit(1)


if __name__ == "__main__":
    run_test()
