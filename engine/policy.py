"""Cambrian 운영 정책 로더.

JSON 파일에서 budget/governance/evolution 규칙을 읽고
기본값과 병합하여 엔진에 제공한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class CambrianPolicy:
    """운영 정책 로더. JSON 파일에서 정책을 읽고 기본값과 병합한다."""

    DEFAULTS: dict = {
        "budget": {
            "max_candidates_per_run": 5,
            "max_mode_a_per_run": 2,
            "max_eval_cases": 20,
            "max_eval_inputs_evolve": 10,
        },
        "governance": {
            "promote_min_executions": 10,
            "promote_min_fitness": 0.5,
            "demote_fitness_threshold": 0.3,
            "rollback_fitness_threshold": 0.2,
            "quarantine_block_count": 2,
        },
        "evolution": {
            "adoption_margin": 0.5,
            "trial_count": 3,
        },
    }

    # 각 필드의 기대 타입과 양수 여부
    _FIELD_SPEC: dict[str, dict[str, tuple[type, bool]]] = {
        "budget": {
            "max_candidates_per_run": (int, True),
            "max_mode_a_per_run": (int, True),
            "max_eval_cases": (int, True),
            "max_eval_inputs_evolve": (int, True),
        },
        "governance": {
            "promote_min_executions": (int, True),
            "promote_min_fitness": (float, False),
            "demote_fitness_threshold": (float, False),
            "rollback_fitness_threshold": (float, False),
            "quarantine_block_count": (int, True),
        },
        "evolution": {
            "adoption_margin": (float, False),
            "trial_count": (int, True),
        },
    }

    def __init__(self, policy_path: str | Path | None = None) -> None:
        """정책을 로드한다.

        Args:
            policy_path: 정책 JSON 파일 경로.
                None이면 현재 디렉토리의 cambrian_policy.json 자동 탐색,
                없으면 내장 기본값 사용.

        Raises:
            FileNotFoundError: 명시적 경로 지정 시 파일이 없을 때
            json.JSONDecodeError: JSON 파싱 실패 시
        """
        data: dict = {}
        self.policy_source: str = "default"

        if policy_path is not None:
            path = Path(policy_path)
            if not path.exists():
                raise FileNotFoundError(f"Policy file not found: {path}")
            data = self._load(path)
            self.policy_source = str(path)
        else:
            auto_path = Path("cambrian_policy.json")
            if auto_path.exists():
                data = self._load(auto_path)
                self.policy_source = str(auto_path)

        # 검증 + 기본값 병합
        warnings = self._validate(data)
        for w in warnings:
            logger.warning("Policy validation: %s", w)

        merged = self._merge_with_defaults(data)

        # budget
        self.max_candidates_per_run: int = merged["budget"]["max_candidates_per_run"]
        self.max_mode_a_per_run: int = merged["budget"]["max_mode_a_per_run"]
        self.max_eval_cases: int = merged["budget"]["max_eval_cases"]
        self.max_eval_inputs_evolve: int = merged["budget"]["max_eval_inputs_evolve"]

        # governance
        self.promote_min_executions: int = merged["governance"]["promote_min_executions"]
        self.promote_min_fitness: float = merged["governance"]["promote_min_fitness"]
        self.demote_fitness_threshold: float = merged["governance"]["demote_fitness_threshold"]
        self.rollback_fitness_threshold: float = merged["governance"]["rollback_fitness_threshold"]
        self.quarantine_block_count: int = merged["governance"]["quarantine_block_count"]

        # evolution
        self.adoption_margin: float = merged["evolution"]["adoption_margin"]
        self.trial_count: int = merged["evolution"]["trial_count"]

    def _load(self, path: Path) -> dict:
        """JSON 파일을 읽어 dict로 반환한다.

        Args:
            path: JSON 파일 경로

        Returns:
            파싱된 dict

        Raises:
            json.JSONDecodeError: JSON 파싱 실패 시
        """
        text = path.read_text(encoding="utf-8")
        return json.loads(text)

    def _validate(self, data: dict) -> list[str]:
        """정책 데이터의 타입과 값을 검증한다.

        유효하지 않은 값은 제거하여 기본값이 적용되도록 한다.

        Args:
            data: 검증할 정책 dict

        Returns:
            경고 메시지 리스트
        """
        warnings: list[str] = []
        known_sections = {"budget", "governance", "evolution"}

        for key in list(data.keys()):
            if key not in known_sections:
                warnings.append(f"알 수 없는 섹션 무시: '{key}'")

        for section, fields in self._FIELD_SPEC.items():
            section_data = data.get(section)
            if not isinstance(section_data, dict):
                continue

            for field, (expected_type, must_positive) in fields.items():
                if field not in section_data:
                    continue

                value = section_data[field]

                # int 필드에 float가 오면 int로 변환 (JSON에서 10.0 등)
                if expected_type is int and isinstance(value, float) and value == int(value):
                    section_data[field] = int(value)
                    value = section_data[field]

                if not isinstance(value, expected_type):
                    # float 필드에 int가 오면 float로 변환
                    if expected_type is float and isinstance(value, int):
                        section_data[field] = float(value)
                    else:
                        warnings.append(
                            f"{section}.{field}: 타입 오류 "
                            f"(기대 {expected_type.__name__}, 실제 {type(value).__name__}). "
                            f"기본값 사용."
                        )
                        del section_data[field]
                        continue

                if must_positive and section_data[field] <= 0:
                    warnings.append(
                        f"{section}.{field}: 양수여야 함 (값: {value}). 기본값 사용."
                    )
                    del section_data[field]

        return warnings

    def _merge_with_defaults(self, data: dict) -> dict:
        """사용자 정책과 기본값을 병합한다. 사용자 값이 우선.

        Args:
            data: 사용자 정책 dict (부분 허용)

        Returns:
            병합된 완전한 정책 dict
        """
        import copy
        merged = copy.deepcopy(self.DEFAULTS)

        for section in ("budget", "governance", "evolution"):
            user_section = data.get(section)
            if isinstance(user_section, dict):
                for key, value in user_section.items():
                    if key in merged[section]:
                        merged[section][key] = value

        return merged

    def to_dict(self) -> dict:
        """현재 정책을 dict로 반환한다.

        Returns:
            budget/governance/evolution 섹션이 포함된 dict
        """
        return {
            "budget": {
                "max_candidates_per_run": self.max_candidates_per_run,
                "max_mode_a_per_run": self.max_mode_a_per_run,
                "max_eval_cases": self.max_eval_cases,
                "max_eval_inputs_evolve": self.max_eval_inputs_evolve,
            },
            "governance": {
                "promote_min_executions": self.promote_min_executions,
                "promote_min_fitness": self.promote_min_fitness,
                "demote_fitness_threshold": self.demote_fitness_threshold,
                "rollback_fitness_threshold": self.rollback_fitness_threshold,
                "quarantine_block_count": self.quarantine_block_count,
            },
            "evolution": {
                "adoption_margin": self.adoption_margin,
                "trial_count": self.trial_count,
            },
            "source": self.policy_source,
        }
