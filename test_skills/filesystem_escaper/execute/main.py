import json
import sys


def run(input_data: dict) -> dict:
    """sandbox 테스트: 외부 파일 읽기 시도."""
    try:
        with open("/etc/passwd", "r") as f:
            data = f.read(20)
        return {"read": data}
    except PermissionError:
        return {"read": ""}


if __name__ == "__main__":
    try:
        with open("/etc/passwd", "r") as f:
            data = f.read(20)
        print(json.dumps({"read": data}))
    except PermissionError as e:
        sys.exit(f"Blocked: {e}")
