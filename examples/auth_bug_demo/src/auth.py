def normalize_username(username: str) -> str:
    return username


def can_login(username: str, known_users: set[str]) -> bool:
    normalized = normalize_username(username)
    return normalized in known_users
