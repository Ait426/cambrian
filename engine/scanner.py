"""Cambrian 프로젝트 스캐너. 규칙 기반 프로젝트 분석 + gap 도출 + search 연동."""

from __future__ import annotations

import fnmatch
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from engine.models import (
    CapabilityGap,
    ProjectFingerprint,
    ProjectScanReport,
    SearchQuery,
    SkillSuggestion,
)

if TYPE_CHECKING:
    from engine.models import SearchResult
    from engine.search import SkillSearcher

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 상수: 무시 목록
# ═══════════════════════════════════════════════════════════════════

IGNORE_DIRS: set[str] = {
    "node_modules", ".git", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".tox", ".eggs", "dist", "build",
    ".next", ".nuxt", ".svelte-kit", "venv", ".venv",
    "env", ".env", "vendor", "target",
    ".idea", ".vscode", ".DS_Store",
    "cambrian.egg-info",
}

IGNORE_FILES: set[str] = {
    ".DS_Store", "Thumbs.db", ".gitkeep",
}

IGNORE_EXTENSIONS: set[str] = {
    ".pyc", ".pyo", ".class", ".o", ".so", ".dylib",
    ".whl", ".egg", ".tar.gz", ".zip",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".wav", ".avi",
    ".db", ".sqlite", ".sqlite3",
}

# ═══════════════════════════════════════════════════════════════════
# 상수: 언어 감지
# ═══════════════════════════════════════════════════════════════════

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".r": "r",
    ".R": "r",
    ".scala": "scala",
    ".lua": "lua",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
}

# ═══════════════════════════════════════════════════════════════════
# 상수: 프레임워크 감지 신호
# ═══════════════════════════════════════════════════════════════════

FRAMEWORK_SIGNALS: list[dict[str, object]] = [
    # Python 웹
    {"framework": "fastapi", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["fastapi"]},
    {"framework": "django", "files": ["manage.py", "requirements.txt", "pyproject.toml"], "keywords": ["django"]},
    {"framework": "flask", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["flask"]},
    {"framework": "streamlit", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["streamlit"]},
    # Python 데이터
    {"framework": "pandas", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["pandas"]},
    {"framework": "numpy", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["numpy"]},
    {"framework": "pytorch", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["torch"]},
    {"framework": "tensorflow", "files": ["requirements.txt", "pyproject.toml"], "keywords": ["tensorflow"]},
    # Python 테스트
    {"framework": "pytest", "files": ["requirements.txt", "pyproject.toml", "setup.cfg"], "keywords": ["pytest"]},
    # JavaScript/TypeScript
    {"framework": "react", "files": ["package.json"], "keywords": ["react"]},
    {"framework": "vue", "files": ["package.json"], "keywords": ["vue"]},
    {"framework": "nextjs", "files": ["package.json", "next.config.js", "next.config.mjs"], "keywords": ["next"]},
    {"framework": "express", "files": ["package.json"], "keywords": ["express"]},
    {"framework": "nestjs", "files": ["package.json"], "keywords": ["@nestjs"]},
    # 기타
    {"framework": "docker", "files": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"], "keywords": []},
    {"framework": "terraform", "files": ["main.tf", "terraform.tfvars"], "keywords": []},
]

# ═══════════════════════════════════════════════════════════════════
# 상수: 패키지 매니저 감지
# ═══════════════════════════════════════════════════════════════════

PACKAGE_MANAGER_SIGNALS: dict[str, list[str]] = {
    "pip": ["requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"],
    "npm": ["package.json"],
    "yarn": ["yarn.lock"],
    "pnpm": ["pnpm-lock.yaml"],
    "cargo": ["Cargo.toml"],
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "go_mod": ["go.mod"],
    "bundler": ["Gemfile"],
    "composer": ["composer.json"],
}

# 파일 수 상한
_MAX_FILES: int = 1000


class ProjectScanner:
    """프로젝트 디렉토리를 분석하여 capability gap과 추천 스킬을 도출한다."""

    def __init__(self, searcher: "SkillSearcher | None" = None) -> None:
        """초기화.

        Args:
            searcher: SkillSearcher 인스턴스. None이면 search 연동 안 함.
        """
        self._searcher = searcher

    # ═══════════════════════════════════════════════════════════════
    # 메인 진입점
    # ═══════════════════════════════════════════════════════════════

    def scan(
        self,
        project_path: str | Path,
        max_depth: int = 4,
        max_queries: int = 10,
        top_k: int = 3,
        run_search: bool = True,
        external_dirs: list[Path] | None = None,
    ) -> ProjectScanReport:
        """프로젝트를 분석하여 capability gap과 추천 스킬을 반환한다.

        Args:
            project_path: 분석할 프로젝트 디렉토리 경로
            max_depth: 파일트리 스캔 최대 깊이
            max_queries: 최대 search 호출 횟수
            top_k: gap당 최대 추천 스킬 수
            run_search: False면 search 미실행 (gap 분석까지만)
            external_dirs: 외부 스킬 디렉토리 경로 리스트

        Returns:
            ProjectScanReport

        Raises:
            FileNotFoundError: 경로가 존재하지 않을 때
            ValueError: 경로가 디렉토리가 아닐 때
        """
        root = Path(project_path)
        if not root.exists():
            raise FileNotFoundError(f"경로가 존재하지 않음: {root}")
        if not root.is_dir():
            raise ValueError(f"디렉토리가 아님: {root}")

        # 1. 파일 수집
        files, dirs = self._collect_file_tree(root, max_depth)

        # 2. fingerprint 생성
        fingerprint = self._build_fingerprint(root, files, dirs, max_depth)

        # 3. gap 분석
        gaps = self._analyze_gaps(fingerprint)

        # 4. search 연동
        suggestions: list[SkillSuggestion] = []
        search_executed = False
        if run_search and self._searcher is not None:
            suggestions = self._search_for_gaps(
                gaps, max_queries, top_k, external_dirs,
            )
            search_executed = True

        # 5. 보고서 조립
        covered_categories = {s.gap_category for s in suggestions}
        covered_gaps = sum(1 for g in gaps if g.category in covered_categories)

        return ProjectScanReport(
            fingerprint=fingerprint,
            gaps=gaps,
            suggestions=suggestions,
            total_gaps=len(gaps),
            covered_gaps=covered_gaps,
            uncovered_gaps=len(gaps) - covered_gaps,
            search_executed=search_executed,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ═══════════════════════════════════════════════════════════════
    # Step 1: 파일 수집
    # ═══════════════════════════════════════════════════════════════

    def _collect_file_tree(
        self, root: Path, max_depth: int,
    ) -> tuple[list[Path], list[str]]:
        """프로젝트 디렉토리의 파일/디렉토리를 수집한다.

        Args:
            root: 프로젝트 루트 경로
            max_depth: 최대 탐색 깊이

        Returns:
            (파일 Path 리스트, 상대 디렉토리 이름 리스트)
        """
        files: list[Path] = []
        dirs: list[str] = []
        warnings: list[str] = []

        root_str = str(root.resolve())

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)

            # 깊이 제한
            try:
                rel = current.relative_to(root)
                depth = len(rel.parts)
            except ValueError:
                continue
            if depth > max_depth:
                dirnames.clear()
                continue

            # 무시 디렉토리 필터링 (in-place로 os.walk 재귀 제어)
            dirnames[:] = [
                d for d in dirnames
                if d not in IGNORE_DIRS and not d.startswith(".")
                or d in (".github",)  # .github는 허용
            ]

            for d in dirnames:
                dir_rel = str((current / d).relative_to(root))
                dirs.append(dir_rel)

            for fname in filenames:
                if fname in IGNORE_FILES:
                    continue

                fpath = current / fname
                ext = fpath.suffix.lower()
                if ext in IGNORE_EXTENSIONS:
                    continue

                # 심볼릭 링크 스킵
                if fpath.is_symlink():
                    continue

                files.append(fpath)

                if len(files) >= _MAX_FILES:
                    logger.warning("파일 수 %d개 초과, 수집 중단", _MAX_FILES)
                    return files, dirs

        return files, dirs

    # ═══════════════════════════════════════════════════════════════
    # Step 2: fingerprint 생성
    # ═══════════════════════════════════════════════════════════════

    def _build_fingerprint(
        self,
        root: Path,
        files: list[Path],
        dirs: list[str],
        depth: int,
    ) -> ProjectFingerprint:
        """프로젝트 fingerprint를 생성한다.

        Args:
            root: 프로젝트 루트
            files: 수집된 파일 리스트
            dirs: 수집된 디렉토리 리스트
            depth: 스캔 깊이

        Returns:
            ProjectFingerprint
        """
        languages = self._detect_languages(files)
        primary_language = (
            max(languages, key=languages.get) if languages else "unknown"
        )
        frameworks = self._detect_frameworks(root, files)
        package_managers = self._detect_package_managers(root, files)
        key_files = self._find_key_files(root, files)

        has_tests = self._has_signal_dir(dirs, {"tests", "test"}) or any(
            fnmatch.fnmatch(f.name, "test_*.py") for f in files
        )
        has_docs = self._has_signal_dir(dirs, {"docs", "doc"}) or self._has_large_readme(root)
        has_ci = (
            self._has_signal_dir(dirs, {".github/workflows"})
            or any(f.name in {".gitlab-ci.yml", ".travis.yml", "Jenkinsfile"} for f in files)
        )
        has_docker = any(
            f.name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
            for f in files
        )
        has_api = (
            self._has_signal_dir(dirs, {"api"})
            or any(f.name in {"openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"} for f in files)
        )
        has_config = self._has_signal_dir(dirs, {"config"}) or any(
            f.name in {".env.example", "config.yaml", "config.json"} for f in files
        )

        fp_data = {
            "frameworks": frameworks,
            "primary_language": primary_language,
            "has_docker": has_docker,
            "has_api": has_api,
            "has_tests": has_tests,
            "key_files": key_files,
        }
        project_types = self._classify_project_types(fp_data)

        capabilities = self._detect_capabilities(
            root, files, dirs, frameworks,
        )

        warnings: list[str] = []
        if len(files) >= _MAX_FILES:
            warnings.append(f"파일 수 {_MAX_FILES}개 상한에 도달하여 일부 파일이 스캔되지 않았음")

        return ProjectFingerprint(
            project_path=str(root.resolve()),
            project_name=root.resolve().name,
            total_files=len(files),
            total_dirs=len(dirs),
            languages=languages,
            primary_language=primary_language,
            frameworks=frameworks,
            package_managers=package_managers,
            project_types=project_types,
            has_tests=has_tests,
            has_docs=has_docs,
            has_ci=has_ci,
            has_docker=has_docker,
            has_api=has_api,
            has_config=has_config,
            detected_capabilities=capabilities,
            key_files=key_files,
            scan_depth=depth,
            warnings=warnings,
        )

    def _detect_languages(self, files: list[Path]) -> dict[str, int]:
        """확장자별 언어를 감지한다.

        Args:
            files: 파일 리스트

        Returns:
            언어별 파일 수 딕셔너리
        """
        counts: dict[str, int] = {}
        for f in files:
            ext = f.suffix.lower()
            lang = EXTENSION_TO_LANGUAGE.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
        return counts

    def _detect_frameworks(self, root: Path, files: list[Path]) -> list[str]:
        """프레임워크를 감지한다.

        Args:
            root: 프로젝트 루트
            files: 파일 리스트

        Returns:
            감지된 프레임워크 이름 리스트
        """
        file_names = {f.name for f in files}
        detected: list[str] = []

        for signal in FRAMEWORK_SIGNALS:
            framework = str(signal["framework"])
            signal_files = signal["files"]
            keywords = signal["keywords"]

            # signal_files 중 프로젝트에 존재하는 파일 찾기
            matched_file: Path | None = None
            for sf in signal_files:  # type: ignore[union-attr]
                if sf in file_names:
                    # 루트 레벨 우선 탐색
                    candidate = root / sf
                    if candidate.exists():
                        matched_file = candidate
                        break
                    # 하위 파일에서 탐색
                    for f in files:
                        if f.name == sf:
                            matched_file = f
                            break
                    if matched_file:
                        break

            if matched_file is None:
                continue

            # keywords가 비어있으면 파일 존재만으로 매칭
            if not keywords:
                detected.append(framework)
                continue

            # 파일 내용 첫 100줄에서 keyword 검색
            try:
                content = self._read_head(matched_file, max_lines=100).lower()
                if any(kw.lower() in content for kw in keywords):  # type: ignore[union-attr]
                    detected.append(framework)
            except OSError:
                continue

        return detected

    def _detect_package_managers(self, root: Path, files: list[Path]) -> list[str]:
        """패키지 매니저를 감지한다.

        Args:
            root: 프로젝트 루트
            files: 파일 리스트

        Returns:
            감지된 패키지 매니저 이름 리스트
        """
        file_names = {f.name for f in files}
        detected: list[str] = []

        for manager, signal_files in PACKAGE_MANAGER_SIGNALS.items():
            if any(sf in file_names for sf in signal_files):
                detected.append(manager)

        return detected

    def _classify_project_types(self, fp_data: dict) -> list[str]:
        """구조 신호 조합으로 프로젝트 유형을 분류한다.

        Args:
            fp_data: fingerprint 부분 데이터 dict

        Returns:
            프로젝트 유형 리스트
        """
        types: list[str] = []
        frameworks = set(fp_data["frameworks"])

        web_api_frameworks = {"fastapi", "django", "flask", "express", "nestjs"}
        if web_api_frameworks & frameworks:
            types.append("web_api")

        web_front_frameworks = {"react", "vue", "nextjs"}
        if web_front_frameworks & frameworks:
            types.append("web_frontend")

        data_frameworks = {"pandas", "numpy", "pytorch", "tensorflow"}
        if data_frameworks & frameworks:
            types.append("data_pipeline")

        if fp_data["has_docker"]:
            types.append("containerized_app")

        if not types:
            if fp_data["primary_language"] != "unknown":
                types.append("generic_project")
            else:
                types.append("unknown")

        return types

    def _detect_capabilities(
        self,
        root: Path,
        files: list[Path],
        dirs: list[str],
        frameworks: list[str],
    ) -> list[str]:
        """프로젝트가 이미 갖추고 있는 capability를 감지한다.

        Args:
            root: 프로젝트 루트
            files: 파일 리스트
            dirs: 디렉토리 리스트
            frameworks: 감지된 프레임워크

        Returns:
            감지된 capability 이름 리스트
        """
        caps: list[str] = []
        file_names = {f.name for f in files}
        dir_set = set(dirs)

        # testing
        if (
            self._has_signal_dir(dirs, {"tests", "test"})
            or any(fnmatch.fnmatch(f.name, "test_*.py") for f in files)
            or any(fnmatch.fnmatch(f.name, "*.test.js") for f in files)
            or any(fnmatch.fnmatch(f.name, "*.test.ts") for f in files)
            or any(fnmatch.fnmatch(f.name, "*.spec.js") for f in files)
            or any(fnmatch.fnmatch(f.name, "*.spec.ts") for f in files)
            or "pytest" in frameworks
        ):
            caps.append("testing")

        # documentation
        if (
            self._has_signal_dir(dirs, {"docs", "doc"})
            or "CONTRIBUTING.md" in file_names
            or "CHANGELOG.md" in file_names
            or self._has_large_readme(root)
        ):
            caps.append("documentation")

        # ci_cd
        if (
            self._has_signal_dir(dirs, {".github/workflows"})
            or ".gitlab-ci.yml" in file_names
            or ".travis.yml" in file_names
            or "Jenkinsfile" in file_names
        ):
            caps.append("ci_cd")

        # containerization
        if any(n in file_names for n in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}):
            caps.append("containerization")

        # api_documentation
        if any(n in file_names for n in {"openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"}):
            caps.append("api_documentation")

        # linting
        if any(n in file_names for n in {
            ".eslintrc.json", ".eslintrc.js", ".flake8", "ruff.toml", ".pylintrc",
        }) or self._file_contains_keyword(root / "pyproject.toml", "ruff"):
            caps.append("linting")

        # type_checking
        if any(n in file_names for n in {
            "tsconfig.json", "mypy.ini", "py.typed",
        }) or self._file_contains_keyword(root / "pyproject.toml", "mypy"):
            caps.append("type_checking")

        # monitoring
        if (
            "prometheus.yml" in file_names
            or self._has_signal_dir(dirs, {"monitoring"})
        ):
            caps.append("monitoring")

        # data_processing
        if (
            any(f in frameworks for f in ["pandas", "numpy"])
            or self._has_signal_dir(dirs, {"data", "datasets"})
        ):
            caps.append("data_processing")

        # security_scanning
        if any(n in file_names for n in {".bandit", ".snyk", "security.md"}):
            caps.append("security_scanning")

        return caps

    def _find_key_files(self, root: Path, files: list[Path]) -> list[str]:
        """분석에 사용된 핵심 파일 목록을 반환한다.

        Args:
            root: 프로젝트 루트
            files: 파일 리스트

        Returns:
            핵심 파일 이름 리스트
        """
        key_names = {
            "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
            "package.json", "Cargo.toml", "go.mod", "pom.xml",
            "Gemfile", "composer.json",
            "README.md", "README.rst", "README",
            "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
            "Makefile", ".env.example",
        }
        found: list[str] = []
        for f in files:
            if f.name in key_names:
                try:
                    found.append(str(f.relative_to(root)))
                except ValueError:
                    found.append(f.name)
        # 중복 제거하면서 순서 유지
        seen: set[str] = set()
        result: list[str] = []
        for name in found:
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ═══════════════════════════════════════════════════════════════
    # Step 3: gap 분석
    # ═══════════════════════════════════════════════════════════════

    def _analyze_gaps(self, fingerprint: ProjectFingerprint) -> list[CapabilityGap]:
        """fingerprint를 기반으로 capability gap 목록을 도출한다.

        Args:
            fingerprint: 프로젝트 fingerprint

        Returns:
            priority 순 정렬된 CapabilityGap 리스트
        """
        gaps: list[CapabilityGap] = []
        caps = set(fingerprint.detected_capabilities)

        # testing gap
        if "testing" not in caps:
            priority = "high" if fingerprint.total_files > 10 else "medium"
            gaps.append(CapabilityGap(
                category="testing",
                description="테스트 코드가 없음. 단위/통합 테스트 자동화 필요",
                priority=priority,
                evidence=["tests/ 디렉토리 없음", "test 관련 파일 없음"],
                suggested_domain="testing",
                suggested_tags=["unit_test", "pytest"],
                search_query="automated testing unit test",
            ))

        # documentation gap
        if "documentation" not in caps:
            gaps.append(CapabilityGap(
                category="documentation",
                description="문서화가 부족함. README/가이드 자동 생성 필요",
                priority="medium",
                evidence=["docs/ 디렉토리 없음", "README.md 없거나 부실"],
                suggested_domain="documentation",
                suggested_tags=["readme", "docs", "writing"],
                search_query="documentation readme generation writing",
            ))

        # ci_cd gap
        if "ci_cd" not in caps and fingerprint.total_files > 5:
            priority = "medium" if fingerprint.has_tests else "low"
            gaps.append(CapabilityGap(
                category="ci_cd",
                description="CI/CD 파이프라인이 없음. 자동 빌드/테스트/배포 필요",
                priority=priority,
                evidence=[".github/workflows/ 없음", "CI 설정 파일 없음"],
                suggested_domain="deployment",
                suggested_tags=["ci", "cd", "github_actions"],
                search_query="CI CD pipeline automation deployment",
            ))

        # containerization gap (웹 프로젝트인 경우만)
        if "containerization" not in caps and any(
            t in fingerprint.project_types
            for t in ["web_api", "web_frontend"]
        ):
            gaps.append(CapabilityGap(
                category="containerization",
                description="Docker 설정이 없음. 컨테이너화 필요",
                priority="medium",
                evidence=["Dockerfile 없음", "docker-compose 없음"],
                suggested_domain="deployment",
                suggested_tags=["docker", "container"],
                search_query="Docker container deployment",
            ))

        # api_documentation gap (API 프로젝트인 경우만)
        if "api_documentation" not in caps and "web_api" in fingerprint.project_types:
            gaps.append(CapabilityGap(
                category="api_documentation",
                description="API 문서가 없음. OpenAPI/Swagger 자동 생성 필요",
                priority="high",
                evidence=["openapi.yaml 없음", "swagger 없음"],
                suggested_domain="documentation",
                suggested_tags=["api", "openapi", "swagger"],
                search_query="API documentation openapi swagger auto generate",
            ))

        # data_reporting gap (데이터 프로젝트인 경우만)
        if "data_pipeline" in fingerprint.project_types and "data_processing" in caps:
            gaps.append(CapabilityGap(
                category="data_reporting",
                description="데이터 파이프라인은 있지만 보고서/차트 생성 기능 없음",
                priority="medium",
                evidence=["report/ 디렉토리 없음", "차트/시각화 코드 없음"],
                suggested_domain="data",
                suggested_tags=["report", "chart", "visualization"],
                search_query="data report chart visualization",
            ))

        # security gap
        if "security_scanning" not in caps and fingerprint.total_files > 20:
            gaps.append(CapabilityGap(
                category="security",
                description="보안 스캐닝 설정이 없음",
                priority="low",
                evidence=["보안 스캐너 설정 파일 없음"],
                suggested_domain="security",
                suggested_tags=["security", "scan", "audit"],
                search_query="security scanning code audit",
            ))

        # code_review gap
        if fingerprint.total_files > 30 and "linting" not in caps:
            gaps.append(CapabilityGap(
                category="code_review",
                description="린팅/코드리뷰 도구가 설정되지 않음",
                priority="low",
                evidence=["lint 설정 파일 없음", "코드 스타일 검사 미설정"],
                suggested_domain="development",
                suggested_tags=["code_review", "lint", "quality"],
                search_query="code review linting quality",
            ))

        # EP-1: LLM 확장 포인트 — 규칙이 놓친 gap 추가 도출

        # priority 정렬: high > medium > low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        gaps.sort(key=lambda g: priority_order.get(g.priority, 99))

        return gaps

    # ═══════════════════════════════════════════════════════════════
    # Step 4: search 연동
    # ═══════════════════════════════════════════════════════════════

    def _search_for_gaps(
        self,
        gaps: list[CapabilityGap],
        max_queries: int,
        top_k: int,
        external_dirs: list[Path] | None,
    ) -> list[SkillSuggestion]:
        """각 gap에 대해 search를 실행하고 추천 스킬을 수집한다.

        Args:
            gaps: gap 리스트
            max_queries: 최대 search 호출 횟수
            top_k: gap당 최대 추천 수
            external_dirs: 외부 디렉토리

        Returns:
            SkillSuggestion 리스트
        """
        if self._searcher is None:
            return []

        suggestions: list[SkillSuggestion] = []
        queried = 0

        for gap in gaps:
            if queried >= max_queries:
                break

            query = self._gap_to_search_query(gap)
            query.include_external = external_dirs is not None

            report = self._searcher.search(query, external_dirs=external_dirs)
            queried += 1

            for result in report.results[:top_k]:
                if result.relevance_score >= 0.1:
                    suggestions.append(
                        self._search_result_to_suggestion(gap, result)
                    )

        suggestions.sort(key=lambda s: s.relevance_score, reverse=True)
        return suggestions

    @staticmethod
    def _gap_to_search_query(gap: CapabilityGap) -> SearchQuery:
        """CapabilityGap을 SearchQuery로 변환한다.

        Args:
            gap: gap 객체

        Returns:
            SearchQuery
        """
        # EP-2: LLM 확장 포인트 — 더 정교한 search query 생성
        return SearchQuery(
            text=gap.search_query,
            domain=gap.suggested_domain,
            tags=gap.suggested_tags,
            include_external=True,
            include_dormant=False,
            limit=5,
        )

    @staticmethod
    def _search_result_to_suggestion(
        gap: CapabilityGap, result: "SearchResult",
    ) -> SkillSuggestion:
        """SearchResult를 SkillSuggestion으로 변환한다.

        Args:
            gap: 연결된 gap
            result: 검색 결과

        Returns:
            SkillSuggestion
        """
        if result.relevance_score >= 0.6:
            match_quality = "strong"
        elif result.relevance_score >= 0.3:
            match_quality = "partial"
        else:
            match_quality = "weak"

        return SkillSuggestion(
            gap_category=gap.category,
            skill_id=result.skill_id,
            skill_name=result.name,
            skill_description=result.description,
            relevance_score=result.relevance_score,
            source=result.source,
            match_quality=match_quality,
        )

    # ═══════════════════════════════════════════════════════════════
    # 유틸리티
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _has_signal_dir(dirs: list[str], targets: set[str]) -> bool:
        """디렉토리 리스트에 대상 이름이 있는지 확인한다.

        Args:
            dirs: 상대 디렉토리 경로 리스트
            targets: 찾을 디렉토리 이름 세트

        Returns:
            하나라도 있으면 True
        """
        for d in dirs:
            # 정확한 이름 또는 경로 끝 부분 매칭
            parts = d.replace("\\", "/").split("/")
            if parts[-1] in targets or d in targets:
                return True
        return False

    @staticmethod
    def _has_large_readme(root: Path) -> bool:
        """README.md가 50줄 이상인지 확인한다.

        Args:
            root: 프로젝트 루트

        Returns:
            True면 충실한 README 존재
        """
        readme = root / "README.md"
        if not readme.exists():
            return False
        try:
            lines = readme.read_text(encoding="utf-8", errors="replace").splitlines()
            return len(lines) >= 50
        except OSError:
            return False

    @staticmethod
    def _read_head(path: Path, max_lines: int = 100) -> str:
        """파일의 처음 N줄을 읽어 반환한다.

        Args:
            path: 파일 경로
            max_lines: 최대 줄 수

        Returns:
            파일 내용 문자열
        """
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines: list[str] = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(line)
                return "".join(lines)
        except OSError:
            return ""

    @staticmethod
    def _file_contains_keyword(path: Path, keyword: str) -> bool:
        """파일의 첫 100줄에 키워드가 포함되어 있는지 확인한다.

        Args:
            path: 파일 경로
            keyword: 검색할 키워드

        Returns:
            포함되어 있으면 True
        """
        if not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= 100:
                        break
                    if keyword.lower() in line.lower():
                        return True
        except OSError:
            pass
        return False
