import json
import subprocess
import sys


def run(input_data: dict) -> dict:
    cmd = input_data.get("value", "echo hello")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return {"result": result.stdout}


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
