"""TODO CLI 유틸리티 함수."""

from datetime import datetime


def format_date(dt):
    """날짜를 문자열로 포맷한다."""
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate(text, max_len=50):
    """텍스트를 주어진 길이로 잘라낸다."""
    return text[:max_len - 3] + "..." if len(text) > max_len else text


def priority_label(level):
    """우선순위 숫자를 레이블로 변환한다."""
    labels = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}
    return labels.get(level, "UNKNOWN")
