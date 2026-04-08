import json
import sys
import socket


def run(input_data: dict) -> dict:
    """sandbox 테스트: socket 연결 시도."""
    try:
        s = socket.create_connection(("8.8.8.8", 80), timeout=2)
        s.close()
        return {"connected": True}
    except OSError:
        return {"connected": False}


if __name__ == "__main__":
    try:
        s = socket.create_connection(("8.8.8.8", 80), timeout=2)
        s.close()
        print(json.dumps({"connected": True}))
    except OSError as e:
        sys.exit(f"Blocked: {e}")
