"""Cambrian 통합 스킬 검색 엔진."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from engine.loader import SkillLoader
from engine.models import SearchQuery, SearchReport, SearchResult
from engine.registry import SkillRegistry

logger = logging.getLogger(__name__)

# 검색 시 무시할 불용어 (2자 미만도 자동 제거)
_STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "to", "for", "of", "in", "on", "and", "or",
    "이", "가", "을", "를", "의", "에", "로", "와", "과", "은", "는",
}

# 쿼리 텍스트 최대 길이
_MAX_QUERY_LENGTH: int = 500


class SkillSearcher:
    """내부 레지스트리 + 외부 디렉토리를 통합 검색한다."""

    def __init__(self, registry: SkillRegistry, loader: SkillLoader) -> None:
        """초기화.

        Args:
            registry: SkillRegistry 인스턴스
            loader: SkillLoader 인스턴스
        """
        self._registry = registry
        self._loader = loader

    def search(
        self,
        query: SearchQuery,
        external_dirs: list[Path] | None = None,
    ) -> SearchReport:
        """통합 검색을 실행한다.

        Args:
            query: 검색 쿼리
            external_dirs: 외부 스킬 디렉토리 경로 리스트

        Returns:
            SearchReport 검색 결과 보고서
        """
        truncated_text = query.text[:_MAX_QUERY_LENGTH]
        keywords = self._extract_keywords(truncated_text)

        internal_results = self._search_registry(query, keywords)
        registry_hits = len(internal_results)

        external_results: list[SearchResult] = []
        if query.include_external and external_dirs:
            registered_ids = {r.skill_id for r in internal_results}
            external_results = self._search_external(
                query, keywords, external_dirs, registered_ids,
            )
        external_hits = len(external_results)

        merged = self._merge_and_rank(
            internal_results, external_results, query.limit,
        )
        total_scanned = registry_hits + external_hits

        return SearchReport(
            query=query,
            results=merged,
            total_scanned=total_scanned,
            registry_hits=registry_hits,
            external_hits=external_hits,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """쿼리 텍스트에서 검색 키워드를 추출한다.

        Args:
            text: 자연어 쿼리 텍스트

        Returns:
            소문자화된 키워드 리스트 (불용어, 2자 미만 제거)
        """
        tokens = text.lower().split()
        return [
            token for token in tokens
            if len(token) >= 2 and token not in _STOP_WORDS
        ]

    def _search_registry(
        self,
        query: SearchQuery,
        keywords: list[str],
    ) -> list[SearchResult]:
        """레지스트리에서 스킬을 검색한다.

        Args:
            query: 검색 쿼리
            keywords: 추출된 키워드 리스트

        Returns:
            레지스트리 검색 결과 리스트
        """
        all_skills = self._registry.list_all()
        results: list[SearchResult] = []

        for skill_data in all_skills:
            status = skill_data["status"]

            # fossil 항상 제외
            if status == "fossil":
                continue

            # dormant 제외 (include_dormant=False인 경우)
            if status == "dormant" and not query.include_dormant:
                continue

            # 도메인 필터
            if query.domain is not None and skill_data["domain"] != query.domain:
                continue

            # 모드 필터
            if query.mode is not None and skill_data["mode"] != query.mode:
                continue

            # 태그 필터: 쿼리 태그 중 하나라도 매칭되어야 함
            if query.tags is not None and len(query.tags) > 0:
                skill_tags = skill_data["tags"]
                if not any(tag in skill_tags for tag in query.tags):
                    continue

            relevance = self._calculate_relevance(keywords, skill_data)
            results.append(SearchResult(
                skill_id=skill_data["id"],
                name=skill_data["name"],
                description=skill_data["description"],
                domain=skill_data["domain"],
                tags=skill_data["tags"],
                mode=skill_data["mode"],
                relevance_score=relevance,
                fitness_score=skill_data["fitness_score"],
                source="registry",
                skill_path=skill_data["skill_path"],
                status=status,
            ))

        return results

    def _search_external(
        self,
        query: SearchQuery,
        keywords: list[str],
        external_dirs: list[Path],
        registered_ids: set[str],
    ) -> list[SearchResult]:
        """외부 디렉토리에서 스킬을 검색한다.

        Args:
            query: 검색 쿼리
            keywords: 추출된 키워드 리스트
            external_dirs: 외부 디렉토리 경로 리스트
            registered_ids: 이미 레지스트리에 있는 스킬 ID 세트 (중복 제거용)

        Returns:
            외부 검색 결과 리스트
        """
        results: list[SearchResult] = []

        for ext_dir in external_dirs:
            if not ext_dir.exists() or not ext_dir.is_dir():
                logger.warning("외부 디렉토리 미존재: %s", ext_dir)
                continue

            try:
                skills = self._loader.load_directory(ext_dir)
            except Exception as exc:
                logger.warning("외부 디렉토리 로드 실패 '%s': %s", ext_dir, exc)
                continue

            for skill in skills:
                # 이미 레지스트리에 등록된 스킬 제외
                if skill.id in registered_ids:
                    continue

                # 도메인 필터
                if query.domain is not None and skill.domain != query.domain:
                    continue

                # 모드 필터
                if query.mode is not None and skill.mode != query.mode:
                    continue

                # 태그 필터
                if query.tags is not None and len(query.tags) > 0:
                    if not any(tag in skill.tags for tag in query.tags):
                        continue

                skill_data = {
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description,
                    "domain": skill.domain,
                    "tags": skill.tags,
                    "mode": skill.mode,
                    "fitness_score": 0.0,
                }
                relevance = self._calculate_relevance(keywords, skill_data)
                results.append(SearchResult(
                    skill_id=skill.id,
                    name=skill.name,
                    description=skill.description,
                    domain=skill.domain,
                    tags=skill.tags,
                    mode=skill.mode,
                    relevance_score=relevance,
                    fitness_score=0.0,
                    source=f"external:{ext_dir}",
                    skill_path=str(skill.skill_path),
                    status="unregistered",
                ))

        return results

    def _merge_and_rank(
        self,
        internal: list[SearchResult],
        external: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        """내부 + 외부 결과를 합산 후 relevance 순 정렬한다.

        Args:
            internal: 레지스트리 검색 결과
            external: 외부 검색 결과
            limit: 최대 반환 수

        Returns:
            정렬 + 필터링된 결과 리스트
        """
        combined = internal + external

        # relevance_score < 0.1 제거
        filtered = [r for r in combined if r.relevance_score >= 0.1]

        # relevance_score 내림차순 정렬 (동점 시 fitness 내림차순)
        filtered.sort(
            key=lambda r: (r.relevance_score, r.fitness_score),
            reverse=True,
        )

        return filtered[:limit]

    @staticmethod
    def _calculate_relevance(keywords: list[str], skill_data: dict) -> float:
        """검색 키워드와 스킬 데이터 간 관련도를 계산한다.

        Args:
            keywords: 쿼리 키워드 리스트
            skill_data: 스킬 메타데이터 dict (id, name, description, domain, tags 필수)

        Returns:
            0.0 ~ 1.0 사이 관련도 점수
        """
        if not keywords:
            # 키워드 없으면 fitness 기반 정렬 (전체 결과)
            return 0.5 + skill_data.get("fitness_score", 0.0) * 0.5

        score = 0.0
        desc_lower = skill_data["description"].lower()
        name_lower = skill_data["name"].lower()
        tags_lower = [t.lower() for t in skill_data["tags"]]
        domain_lower = skill_data["domain"].lower()

        for kw in keywords:
            kw_lower = kw.lower()

            # description 또는 name 매칭
            if kw_lower in desc_lower or kw_lower in name_lower:
                score += 0.3

            # tags 매칭
            if kw_lower in tags_lower:
                score += 0.4

            # domain 매칭
            if kw_lower == domain_lower:
                score += 0.3

        keyword_count = max(len(keywords), 1)
        normalized = score / keyword_count
        text_relevance = min(1.0, normalized)

        # 최종 점수: 텍스트 관련도 70% + fitness 30%
        fitness = skill_data.get("fitness_score", 0.0)
        return round(text_relevance * 0.7 + fitness * 0.3, 4)
