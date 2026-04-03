import json
import sys


def run(input_data: dict) -> dict:
    expr = input_data.get("value", "1+1")
    result = eval(expr)
    return {"result": str(result)}


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
