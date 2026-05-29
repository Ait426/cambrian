from __future__ import annotations


def normalize_username(value: str) -> str:
    return value.strip().lower()


def can_login(username: str, allowed_users: set[str]) -> bool:
    return normalize_username(username) in allowed_users
