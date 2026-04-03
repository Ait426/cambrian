import json
import requests
import sys


def run(input_data: dict) -> dict:
    url = input_data.get("value", "https://example.com")
    response = requests.get(url)
    return {"result": response.text[:100]}


if __name__ == "__main__":
    raw = sys.stdin.read()
    input_data = json.loads(raw) if raw.strip() else {}
    print(json.dumps(run(input_data)))
