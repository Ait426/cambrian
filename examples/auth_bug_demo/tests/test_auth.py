from pathlib import Path

import pytest


if Path.cwd().resolve() != Path(__file__).resolve().parents[1]:
    pytest.skip("데모 fixture 디렉토리에서 실행할 때만 이 테스트를 실행합니다.", allow_module_level=True)

from src.auth import can_login, normalize_username


def test_normalize_username_strips_and_lowercases() -> None:
    assert normalize_username(" Alice ") == "alice"


def test_can_login_accepts_normalized_username() -> None:
    assert can_login(" ALICE ", {"alice"}) is True
