from src.auth import normalize_username


def test_normalize_username_lowercases_email() -> None:
    assert normalize_username("USER@EXAMPLE.COM") == "user@example.com"
