import json
import sys
import time


def run(input_data: dict) -> dict:
    seconds = input_data.get("seconds", 5)
    time.sleep(seconds)
    return {"waited": seconds}


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
