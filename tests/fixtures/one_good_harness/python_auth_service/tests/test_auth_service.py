from src.auth_service import can_login, normalize_username


def test_normalize_username_strips_and_lowercases() -> None:
    assert normalize_username("  ALICE  ") == "alice"


def test_can_login_uses_normalized_username() -> None:
    assert can_login(" Alice ", {"alice", "bob"}) is True
    assert can_login("Mallory", {"alice", "bob"}) is False
