import json
import sys


def run(input_data: dict) -> dict:
    value = input_data.get("value", "")
    return {"result": value.upper()}


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
