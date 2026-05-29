from pathlib import Path

import pytest


if Path.cwd().resolve() != Path(__file__).resolve().parents[1]:
    pytest.skip("데모 디렉토리에서 실행할 때만 이 테스트를 실행합니다.", allow_module_level=True)

from src.auth import normalize_username

def test_normalize_username_lowercases_email() -> None:
    assert normalize_username("USER@EXAMPLE.COM") == "user@example.com"
