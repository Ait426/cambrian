"""Cambrian 패키지 번들 데이터 경로 해석.

pip install 후에도 시드 스킬, 스키마, 정책 파일을
정확하게 찾을 수 있도록 패키지 내부 경로를 제공한다.
"""

from pathlib import Path


def get_bundled_data_dir() -> Path:
    """패키지 번들 데이터 루트 디렉토리를 반환한다.

    Returns:
        engine/_data/ 의 절대 경로
    """
    return Path(__file__).parent / "_data"


def get_bundled_schemas_dir() -> Path:
    """번들 schemas 디렉토리 경로."""
    return get_bundled_data_dir() / "schemas"


def get_bundled_skills_dir() -> Path:
    """번들 시드 스킬 디렉토리 경로."""
    return get_bundled_data_dir() / "skills"


def get_bundled_policy_path() -> Path:
    """번들 정책 파일 경로."""
    return get_bundled_data_dir() / "cambrian_policy.json"
