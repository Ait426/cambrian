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


@dataclass
class ProjectFingerprint:
    """프로젝트 구조 분석 결과. 규칙 기반 파싱으로 생성."""

    project_path: str                           # 분석 대상 절대 경로
    project_name: str                           # 디렉토리 이름
    total_files: int                            # 전체 파일 수
    total_dirs: int                             # 전체 디렉토리 수

    # 언어/스택 추정
    languages: dict[str, int]                   # {"python": 45, ...} 확장자별 파일 수
    primary_language: str                       # 가장 많은 확장자의 언어
    frameworks: list[str]                       # 감지된 프레임워크
    package_managers: list[str]                 # 감지된 패키지 매니저

    # 프로젝트 유형 분류
    project_types: list[str]                    # ["cli", "web_api", "library", ...]

    # 구조 신호
    has_tests: bool
    has_docs: bool
    has_ci: bool
    has_docker: bool
    has_api: bool
    has_config: bool

    # 감지된 현재 capability
    detected_capabilities: list[str] = field(default_factory=list)

    # 핵심 파일 목록 (경로만)
    key_files: list[str] = field(default_factory=list)

    # 메타
    scan_depth: int = 4
    warnings: list[str] = field(default_factory=list)


@dataclass
class CapabilityGap:
    """프로젝트에서 식별된 부족한 capability."""

    category: str                               # gap 범주
    description: str                            # 사람이 읽을 수 있는 gap 설명
    priority: str                               # "high" | "medium" | "low"
    evidence: list[str]                         # gap 판단 근거
    suggested_domain: str                       # search에 전달할 도메인
    suggested_tags: list[str]                   # search에 전달할 태그
    search_query: str                           # search에 전달할 자연어 쿼리


@dataclass
class SkillSuggestion:
    """gap에 대해 search가 찾은 추천 스킬."""

    gap_category: str                           # 연결된 CapabilityGap.category
    skill_id: str
    skill_name: str
    skill_description: str
    relevance_score: float                      # search의 relevance_score
    source: str                                 # "registry" | "external:<path>"
    match_quality: str                          # "strong" | "partial" | "weak"


@dataclass
class ProjectScanReport:
    """프로젝트 스캔 최종 보고서."""

    fingerprint: ProjectFingerprint
    gaps: list[CapabilityGap]                   # 우선순위 내림차순 정렬
    suggestions: list[SkillSuggestion]          # relevance_score 내림차순 정렬
    total_gaps: int
    covered_gaps: int                           # 추천 스킬이 1개 이상 있는 gap 수
    uncovered_gaps: int                         # 추천 스킬 없는 gap 수
    search_executed: bool                       # --no-search 시 False
    timestamp: str


@dataclass
class FuseRequest:
    """스킬 융합 요청."""

    skill_id_a: str                             # 첫 번째 소스 스킬 ID
    skill_id_b: str                             # 두 번째 소스 스킬 ID
    goal: str                                   # 융합 목적 설명 (자연어)
    output_id: str | None = None                # 결과 스킬 ID (None이면 자동 생성)
    output_mode: str = "a"                      # 결과 모드 ("a" 고정, v2에서 "b" 확장)
    dry_run: bool = False                       # True면 등록 안 함


@dataclass
class FuseResult:
    """스킬 융합 결과."""

    success: bool
    skill_id: str
    skill_path: str
    source_ids: list[str]                       # [skill_id_a, skill_id_b]
    goal: str
    fusion_rationale: str                       # LLM이 설명한 융합 근거
    output_mode: str
    validation_passed: bool
    validation_errors: list[str] = field(default_factory=list)
    security_passed: bool = True
    security_violations: list[str] = field(default_factory=list)
    registered: bool = False
    dry_run: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class GenerateRequest:
    """스킬 생성 요청."""

    goal: str                                   # 생성할 스킬 목적 (자연어, 최소 10자)
    domain: str                                 # 스킬 도메인
    tags: list[str]                             # 스킬 태그 (최소 1개)
    output_id: str | None = None                # 결과 스킬 ID (None이면 자동)
    output_mode: str = "a"                      # "a" 고정 (v1)
    project_path: str | None = None             # scan 컨텍스트용 프로젝트 경로
    reference_skills: list[str] | None = None   # few-shot 참고 스킬 ID
    dry_run: bool = False
    skip_search: bool = False                   # 유사 스킬 사전 검색 스킵


@dataclass
class GenerateResult:
    """스킬 생성 결과."""

    success: bool
    skill_id: str
    skill_path: str
    goal: str
    domain: str
    tags: list[str]
    output_mode: str
    generation_rationale: str
    reference_skill_ids: list[str] = field(default_factory=list)
    validation_passed: bool = False
    validation_errors: list[str] = field(default_factory=list)
    security_passed: bool = True
    security_violations: list[str] = field(default_factory=list)
    registered: bool = False
    dry_run: bool = False
    existing_alternatives: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AcquireRequest:
    """capability 확보 요청."""

    project_path: str | None = None         # 프로젝트 경로 (scan용)
    goal: str | None = None                 # 원하는 capability (자연어)
    domain: str | None = None               # 도메인 힌트
    tags: list[str] | None = None           # 태그 힌트
    mode: str = "advisory"                  # "advisory" | "execute"
    strategy: str = "conservative"          # "conservative" | "balanced" | "aggressive"
    allow_fuse: bool = True
    allow_generate: bool = True
    max_actions: int = 3
    dry_run: bool = False


@dataclass
class AcquireAction:
    """단일 추천/실행 액션."""

    action_type: str                        # "reuse" | "fuse" | "generate" | "defer"
    gap_category: str                       # 대상 gap category
    description: str                        # 액션 설명
    confidence: float                       # 0.0 ~ 1.0
    risk: str                               # "low" | "medium" | "high"

    # reuse 전용
    reuse_skill_id: str | None = None
    reuse_relevance: float = 0.0

    # fuse 전용
    fuse_skill_a: str | None = None
    fuse_skill_b: str | None = None
    fuse_goal: str | None = None

    # generate 전용
    generate_goal: str | None = None
    generate_domain: str | None = None
    generate_tags: list[str] | None = None


@dataclass
class AcquirePlan:
    """수립된 실행 계획."""

    actions: list[AcquireAction]            # 우선순위 내림차순
    total_gaps: int
    addressable_gaps: int                   # 액션이 생성된 gap 수
    deferred_gaps: int                      # 보류된 gap 수
    strategy_applied: str


@dataclass
class AcquireActionResult:
    """실행된 액션의 결과."""

    action: AcquireAction                   # 실행된 액션 원본
    executed: bool                          # 실제 실행 여부
    success: bool
    skill_id: str | None = None
    skill_path: str | None = None
    error: str = ""
    skipped_reason: str = ""


@dataclass
class AcquireResult:
    """acquire 전체 결과."""

    success: bool
    mode: str
    strategy: str
    scan_report: ProjectScanReport | None = None
    plan: AcquirePlan | None = None
    executed_actions: list[AcquireActionResult] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
