import json
import sys
from pathlib import Path


def run(input_data: dict) -> dict:
    """sandbox 테스트: pathlib.Path.read_text로 외부 파일 읽기 시도."""
    try:
        data = Path("/etc/passwd").read_text()[:20]
        return {"read": data}
    except PermissionError:
        return {"read": ""}


if __name__ == "__main__":
    try:
        data = Path("/etc/passwd").read_text()[:20]
        print(json.dumps({"read": data}))
    except PermissionError as e:
        sys.exit(f"Blocked: {e}")
