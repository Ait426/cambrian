import json
import sys


def run(input_data: dict) -> dict:
    message = input_data.get("message", "intentional crash")
    raise ValueError(message)


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
