"""Shared first-recipient operator note template helpers."""

from __future__ import annotations


def operator_dispatch_note_template(archive_sha256: str) -> str:
    """Return the canonical private operator note template for one manual send."""
    if not _looks_like_sha256(archive_sha256):
        raise ValueError("archive_sha256 must be a lowercase sha256 hex string.")
    return (
        "private send channel: <private-send-channel>\n"
        f"attachment sha256 checked: {archive_sha256}\n"
        "operator note: first external alpha one-recipient send only\n"
    )


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
