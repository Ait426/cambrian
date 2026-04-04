"""Cambrian 스킬 도메인 모델."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


@dataclass
class SkillRuntime:
    """스킬 실행 환경 설정."""

    language: str                          # "python" | "javascript" | "shell"
    needs_network: bool = False
    needs_filesystem: bool = False
    timeout_seconds: int = 30


@dataclass
class SkillLifecycle:
    """스킬 생명주기 상태."""

    status: str = "newborn"                # "active" | "newborn" | "dormant" | "fossil"
    fitness_score: float = 0.0             # 0.0 ~ 1.0
    total_executions: int = 0
    successful_executions: int = 0
    last_used: str | None = None           # ISO 8601 datetime string
    crystallized_at: str | None = None     # ISO 8601 datetime string


@dataclass
class Skill:
    """스킬 도메인 객체. 스킬 디렉토리의 완전한 인메모리 표현."""

    # === 필수 식별 정보 (meta.yaml) ===
    id: str
    version: str
    name: str
    description: str
    domain: str
    tags: list[str]
    mode: str                              # "a" | "b"

    # === 실행 환경 ===
    runtime: SkillRuntime

    # === 생명주기 ===
    lifecycle: SkillLifecycle

    # === 경로 ===
    skill_path: Path                       # 스킬 디렉토리 절대 경로

    # === 인터페이스 (interface.yaml) ===
    interface_input: dict = field(default_factory=dict)
    interface_output: dict = field(default_factory=dict)

    # === 콘텐츠 ===
    skill_md_content: str | None = None    # SKILL.md 내용 (Mode A용)

    # === 선택 필드 (meta.yaml) ===
    author: str | None = None
    license: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ExecutionResult:
    """스킬 실행 결과."""

    skill_id: str
    success: bool
    output: dict | None = None
    error: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time_ms: int = 0
    mode: str = "b"


class FailureType(Enum):
    """실패 유형 분류."""

    SKILL_MISSING = "skill_missing"
    EXECUTION_ERROR = "execution_error"
    TIMEOUT = "timeout"
    INPUT_MISMATCH = "input_mismatch"
    OUTPUT_INVALID = "output_invalid"
    UNKNOWN = "unknown"


@dataclass
class SkillNeed:
    """Autopsy가 추천하는 필요 스킬 정보."""

    domain: str
    tags: list[str]
    description: str
    priority: str = "medium"


@dataclass
class AutopsyReport:
    """실패 분석 보고서."""

    skill_id: str
    failure_type: FailureType
    root_cause: str
    stderr_summary: str
    recommendation: str
    needed_skill: SkillNeed | None = None
    retry_suggested: bool = False
    fitness_penalty: float = 0.0


@dataclass
class Feedback:
    """스킬 실행에 대한 사용자 피드백."""

    id: int
    skill_id: str
    rating: int
    comment: str
    input_data_json: str
    output_data_json: str
    created_at: str


@dataclass
class JudgeVerdict:
    """LLM Judge의 비교 채점 결과."""

    original_score: float              # 0.0 ~ 10.0
    variant_score: float               # 0.0 ~ 10.0
    reasoning: str                     # Judge의 채점 근거
    winner: str                        # "original" | "variant" | "tie"


@dataclass
class EvolutionRecord:
    """진화 시도 기록."""

    id: int
    skill_id: str
    parent_skill_md: str
    child_skill_md: str
    parent_fitness: float
    child_fitness: float
    adopted: bool
    mutation_summary: str
    feedback_ids: str
    created_at: str
    judge_reasoning: str = ""          # Judge 채점 근거 요약


@dataclass
class BenchmarkEntry:
    """단일 스킬 후보의 벤치마크 결과 행."""

    skill_id: str
    success: bool
    output: dict | None
    error: str
    execution_time_ms: int
    fitness_score: float
    mode: str
    rank: int = 0


@dataclass
class BenchmarkReport:
    """전체 후보 대상 벤치마크 집계 보고서."""

    entries: list[BenchmarkEntry]
    best_skill_id: str | None
    total_candidates: int
    successful_count: int
    domain: str
    tags: list[str]
    timestamp: str


@dataclass
class SearchQuery:
    """통합 검색 쿼리."""

    text: str                                   # 자연어 쿼리 텍스트
    domain: str | None = None                   # 도메인 필터 (선택)
    tags: list[str] | None = None               # 태그 필터 (선택)
    mode: str | None = None                     # "a" | "b" 필터 (선택)
    include_external: bool = True               # 외부 디렉토리 포함 여부
    include_dormant: bool = False               # dormant 상태 포함 여부
    limit: int = 10                             # 최대 결과 수


@dataclass
class SearchResult:
    """단일 검색 결과."""

    skill_id: str
    name: str
    description: str
    domain: str
    tags: list[str]
    mode: str
    relevance_score: float                      # 0.0 ~ 1.0
    fitness_score: float
    source: str                                 # "registry" | "external:<path>"
    skill_path: str
    status: str                                 # "active" | "newborn" | "dormant" | "unregistered"


@dataclass
class SearchReport:
    """통합 검색 결과 보고서."""

    query: SearchQuery
    results: list[SearchResult]
    total_scanned: int                          # 전체 스캔된 스킬 수
    registry_hits: int                          # 레지스트리 매칭 수
    external_hits: int                          # 외부 매칭 수
    timestamp: str
