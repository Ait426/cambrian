"""Hello World skill - 최소 예제 스킬."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def run(input_data: dict) -> dict:
    """스킬 실행 함수.

    Args:
        input_data: {"text": "대상 텍스트"}

    Returns:
        {"greeting": "Hello, {text}!", "timestamp": "ISO 8601"}

    Raises:
        ValueError: text가 string이 아닐 때
    """
    text = input_data.get("text", "")

    if not isinstance(text, str):
        raise ValueError(f"text must be string, got {type(text).__name__}")

    if text == "":
        text = "World"
    elif len(text) > 500:
        text = text[:500]

    return {
        "greeting": f"Hello, {text}!",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    result = run(input_data)
    print(json.dumps(result, ensure_ascii=False))
