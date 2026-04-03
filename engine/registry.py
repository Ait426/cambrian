"""Cambrian 스킬 레지스트리."""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.exceptions import SkillNotFoundError
from engine.models import EvolutionRecord, ExecutionResult, Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """스킬 메타데이터 SQLite DB 관리 + 검색."""

    def __init__(self, db_path: str | Path = ":memory:"):
        """레지스트리를 초기화한다.

        Args:
            db_path: SQLite DB 파일 경로. 기본값 ":memory:".
        """
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self) -> None:
        """skills 테이블이 없으면 생성한다."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                id                    TEXT PRIMARY KEY,
                version               TEXT NOT NULL,
                name                  TEXT NOT NULL,
                description           TEXT NOT NULL,
                domain                TEXT NOT NULL,
                tags                  TEXT NOT NULL,
                mode                  TEXT NOT NULL,
                language              TEXT NOT NULL,
                needs_network         INTEGER NOT NULL DEFAULT 0,
                needs_filesystem      INTEGER NOT NULL DEFAULT 0,
                timeout_seconds       INTEGER NOT NULL DEFAULT 30,
                skill_path            TEXT NOT NULL,
                status                TEXT NOT NULL DEFAULT 'newborn',
                fitness_score         REAL NOT NULL DEFAULT 0.0,
                total_executions      INTEGER NOT NULL DEFAULT 0,
                successful_executions INTEGER NOT NULL DEFAULT 0,
                last_used             TEXT,
                crystallized_at       TEXT,
                avg_judge_score       REAL DEFAULT NULL,
                registered_at         TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id    TEXT NOT NULL,
                rating      INTEGER NOT NULL,
                comment     TEXT NOT NULL DEFAULT '',
                input_data  TEXT NOT NULL DEFAULT '{}',
                output_data TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evolution_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id         TEXT NOT NULL,
                parent_skill_md  TEXT NOT NULL,
                child_skill_md   TEXT NOT NULL,
                parent_fitness   REAL NOT NULL DEFAULT 0.0,
                child_fitness    REAL NOT NULL DEFAULT 0.0,
                adopted          INTEGER NOT NULL DEFAULT 0,
                mutation_summary TEXT NOT NULL DEFAULT '',
                feedback_ids     TEXT NOT NULL DEFAULT '[]',
                judge_reasoning  TEXT NOT NULL DEFAULT '',
                created_at       TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def register(self, skill: Skill) -> None:
        """스킬을 DB에 등록한다. 이미 같은 id가 있으면 UPDATE한다.

        Args:
            skill: 등록할 Skill 객체
        """
        registered_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO skills (
                id,
                version,
                name,
                description,
                domain,
                tags,
                mode,
                language,
                needs_network,
                needs_filesystem,
                timeout_seconds,
                skill_path,
                status,
                fitness_score,
                total_executions,
                successful_executions,
                last_used,
                crystallized_at,
                registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill.id,
                skill.version,
                skill.name,
                skill.description,
                skill.domain,
                json.dumps(skill.tags),
                skill.mode,
                skill.runtime.language,
                int(skill.runtime.needs_network),
                int(skill.runtime.needs_filesystem),
                skill.runtime.timeout_seconds,
                str(skill.skill_path),
                skill.lifecycle.status,
                skill.lifecycle.fitness_score,
                skill.lifecycle.total_executions,
                skill.lifecycle.successful_executions,
                skill.lifecycle.last_used,
                skill.lifecycle.crystallized_at,
                registered_at,
            ),
        )
        self._conn.commit()

    def unregister(self, skill_id: str) -> None:
        """스킬을 DB에서 삭제한다.

        Args:
            skill_id: 삭제할 스킬 ID

        Raises:
            SkillNotFoundError: 해당 ID가 DB에 없을 때
        """
        cursor = self._conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        self._conn.commit()
        if cursor.rowcount == 0:
            raise SkillNotFoundError(skill_id)

    def get(self, skill_id: str) -> dict:
        """스킬 ID로 단건 조회한다.

        Args:
            skill_id: 조회할 스킬 ID

        Returns:
            스킬 메타데이터 dict

        Raises:
            SkillNotFoundError: 해당 ID가 DB에 없을 때
        """
        cursor = self._conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
        row = cursor.fetchone()
        if row is None:
            raise SkillNotFoundError(skill_id)
        return self._row_to_dict(row)

    def search(
        self,
        domain: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        mode: str | None = None,
        min_fitness: float | None = None,
    ) -> list[dict]:
        """조건에 맞는 스킬 목록을 검색한다.

        Args:
            domain: 도메인 필터
            tags: 태그 필터
            status: 상태 필터
            mode: 모드 필터
            min_fitness: 최소 적응도

        Returns:
            매칭되는 스킬 메타데이터 dict 리스트
        """
        query = "SELECT * FROM skills WHERE 1=1"
        params: list[object] = []

        if domain is not None:
            query += " AND domain = ?"
            params.append(domain)

        if status is not None:
            query += " AND status = ?"
            params.append(status)
        else:
            query += " AND status != 'fossil'"

        if mode is not None:
            query += " AND mode = ?"
            params.append(mode)

        if min_fitness is not None:
            query += " AND fitness_score >= ?"
            params.append(min_fitness)

        if tags is not None and len(tags) > 0:
            tag_conditions: list[str] = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
            query += " AND (" + " OR ".join(tag_conditions) + ")"

        query += " ORDER BY fitness_score DESC"

        cursor = self._conn.execute(query, tuple(params))
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_after_execution(
        self,
        skill_id: str,
        result: ExecutionResult,
        judge_score: float | None = None,
    ) -> None:
        """실행 결과에 따라 lifecycle 필드를 갱신한다.

        Args:
            skill_id: 갱신할 스킬 ID
            result: 실행 결과
            judge_score: LLM Judge 점수 (0.0~10.0). None이면 기존 로직.

        Raises:
            SkillNotFoundError: 해당 ID가 DB에 없을 때
        """
        current = self.get(skill_id)
        total_executions = current["total_executions"] + 1
        successful_executions = current["successful_executions"] + int(result.success)
        last_used = datetime.now(timezone.utc).isoformat()

        existing_judge = current.get("avg_judge_score")
        if judge_score is not None:
            if existing_judge is None:
                new_avg_judge = judge_score
            else:
                new_avg_judge = existing_judge * 0.7 + judge_score * 0.3
        else:
            new_avg_judge = existing_judge

        fitness_score = self._calculate_fitness(
            successful_executions,
            total_executions,
            new_avg_judge,
        )

        cursor = self._conn.execute(
            """
            UPDATE skills
            SET total_executions = ?,
                successful_executions = ?,
                fitness_score = ?,
                last_used = ?,
                avg_judge_score = ?
            WHERE id = ?
            """,
            (
                total_executions,
                successful_executions,
                fitness_score,
                last_used,
                new_avg_judge,
                skill_id,
            ),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise SkillNotFoundError(skill_id)

    def update_status(self, skill_id: str, new_status: str) -> None:
        """스킬의 lifecycle 상태를 변경한다.

        Args:
            skill_id: 스킬 ID
            new_status: 새 상태

        Raises:
            SkillNotFoundError: 해당 ID가 DB에 없을 때
            ValueError: new_status가 유효하지 않은 값일 때
        """
        valid_statuses = {"active", "newborn", "dormant", "fossil"}
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}")

        cursor = self._conn.execute(
            "UPDATE skills SET status = ? WHERE id = ?",
            (new_status, skill_id),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise SkillNotFoundError(skill_id)

    def list_all(self) -> list[dict]:
        """모든 스킬을 반환한다. fitness_score 내림차순.

        Returns:
            전체 스킬 메타데이터 dict 리스트.
        """
        cursor = self._conn.execute(
            "SELECT * FROM skills ORDER BY fitness_score DESC"
        )
        rows = cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    def count(self) -> int:
        """등록된 스킬 총 개수를 반환한다."""
        cursor = self._conn.execute("SELECT COUNT(*) AS count FROM skills")
        row = cursor.fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def add_feedback(
        self,
        skill_id: str,
        rating: int,
        comment: str,
        input_data: str,
        output_data: str,
    ) -> int:
        """피드백을 저장하고 생성된 ID를 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            rating: 1~5 평점
            comment: 사용자 코멘트
            input_data: 입력 JSON 문자열
            output_data: 출력 JSON 문자열

        Returns:
            생성된 피드백 ID

        Raises:
            ValueError: rating 범위가 잘못된 경우
        """
        if rating < 1 or rating > 5:
            raise ValueError("rating must be between 1 and 5")

        violations = self._validate_feedback(comment)
        if violations:
            raise ValueError(f"Feedback rejected: {'; '.join(violations)}")

        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO feedback (skill_id, rating, comment, input_data, output_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (skill_id, rating, comment, input_data, output_data, created_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_feedback(self, skill_id: str, limit: int = 10) -> list[dict]:
        """해당 스킬의 최근 피드백을 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            limit: 최대 반환 개수

        Returns:
            최신순 피드백 목록
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM feedback
            WHERE skill_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (skill_id, limit),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def add_evolution_record(self, record: EvolutionRecord) -> int:
        """진화 기록을 저장하고 생성된 ID를 반환한다.

        Args:
            record: 저장할 진화 기록

        Returns:
            생성된 진화 기록 ID
        """
        cursor = self._conn.execute(
            """
            INSERT INTO evolution_history (
                skill_id,
                parent_skill_md,
                child_skill_md,
                parent_fitness,
                child_fitness,
                adopted,
                mutation_summary,
                feedback_ids,
                judge_reasoning,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.skill_id,
                record.parent_skill_md,
                record.child_skill_md,
                record.parent_fitness,
                record.child_fitness,
                int(record.adopted),
                record.mutation_summary,
                record.feedback_ids,
                record.judge_reasoning,
                record.created_at,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_evolution_history(self, skill_id: str, limit: int = 10) -> list[dict]:
        """해당 스킬의 진화 이력을 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            limit: 최대 반환 개수

        Returns:
            최신순 진화 기록 목록
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM evolution_history
            WHERE skill_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (skill_id, limit),
        )
        rows = cursor.fetchall()
        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["adopted"] = bool(item["adopted"])
            results.append(item)
        return results

    def get_feedback_by_ids(self, feedback_ids: list[int]) -> list[dict]:
        """ID 목록으로 피드백을 조회한다.

        Args:
            feedback_ids: 조회할 피드백 ID 목록

        Returns:
            매칭되는 피드백 목록
        """
        if not feedback_ids:
            return []

        placeholders = ", ".join("?" for _ in feedback_ids)
        cursor = self._conn.execute(
            f"SELECT * FROM feedback WHERE id IN ({placeholders}) ORDER BY created_at DESC, id DESC",
            tuple(feedback_ids),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def decay(self) -> dict[str, int]:
        """장기 미사용 스킬을 자동 퇴화시킨다.

        - active/newborn + last_used < 30일 전 → dormant
        - active/newborn + last_used IS NULL + registered_at < 30일 전 → dormant
        - dormant + last_used < 90일 전 → fossil

        Returns:
            {"dormant": dormant_count, "fossil": fossil_count} 변경된 수
        """
        now = datetime.now(timezone.utc)
        cutoff_30 = (now - timedelta(days=30)).isoformat()
        cutoff_90 = (now - timedelta(days=90)).isoformat()

        # active/newborn → dormant (last_used 있음, 30일 초과)
        cursor = self._conn.execute(
            """
            UPDATE skills
            SET status = 'dormant'
            WHERE status IN ('active', 'newborn')
              AND last_used IS NOT NULL
              AND last_used < ?
            """,
            (cutoff_30,),
        )
        dormant_count = cursor.rowcount

        # active/newborn → dormant (last_used NULL, registered_at 30일 초과)
        cursor2 = self._conn.execute(
            """
            UPDATE skills
            SET status = 'dormant'
            WHERE status IN ('active', 'newborn')
              AND last_used IS NULL
              AND registered_at < ?
            """,
            (cutoff_30,),
        )
        dormant_count += cursor2.rowcount

        # dormant → fossil (90일 초과)
        cursor3 = self._conn.execute(
            """
            UPDATE skills
            SET status = 'fossil'
            WHERE status = 'dormant'
              AND (
                (last_used IS NOT NULL AND last_used < ?)
                OR (last_used IS NULL AND registered_at < ?)
              )
            """,
            (cutoff_90, cutoff_90),
        )
        fossil_count = cursor3.rowcount

        self._conn.commit()
        logger.info(
            "decay(): %d → dormant, %d → fossil", dormant_count, fossil_count
        )
        return {"dormant": dormant_count, "fossil": fossil_count}

    def close(self) -> None:
        """DB 연결을 닫는다."""
        self._conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """sqlite3.Row를 dict로 변환하고 tags를 역직렬화한다.

        Args:
            row: 변환할 DB 행

        Returns:
            변환된 dict
        """
        result = dict(row)
        result["tags"] = json.loads(result["tags"])
        result["needs_network"] = bool(result["needs_network"])
        result["needs_filesystem"] = bool(result["needs_filesystem"])
        return result

    @staticmethod
    def _validate_feedback(comment: str) -> list[str]:
        """피드백 코멘트의 안전성을 검증한다.

        Args:
            comment: 검증할 코멘트 문자열

        Returns:
            위반 사항 목록. 빈 리스트면 안전.
        """
        # 시스템 생성 피드백은 injection 검증만 건너뛰되 길이 제한은 적용
        if comment.startswith("[AUTO]") or comment.startswith("[CRITIC]"):
            if len(comment) > 500:
                return [f"System feedback exceeds 500 character limit: {len(comment)} chars"]
            return []

        violations: list[str] = []
        lower = comment.lower()

        # 프롬프트 인젝션 시도
        injection_patterns = ["ignore previous", "ignore above", "disregard"]
        for pattern in injection_patterns:
            if pattern in lower:
                violations.append(f"Injection attempt detected: '{pattern}'")

        # 역할 탈취 시도
        hijack_patterns = ["system prompt", "you are now", "act as"]
        for pattern in hijack_patterns:
            if pattern in lower:
                violations.append(f"Role hijacking attempt: '{pattern}'")

        # 과도한 길이
        if len(comment) > 200:
            violations.append(f"Comment too long: {len(comment)} chars (max 200)")

        return violations

    def _calculate_fitness(
        self,
        successful: int,
        total: int,
        avg_judge_score: float | None = None,
    ) -> float:
        """적응도를 계산한다.

        Args:
            successful: 성공 횟수
            total: 전체 실행 횟수
            avg_judge_score: 평균 Judge 점수 (0.0~10.0). None이면 기존 공식.

        Returns:
            계산된 적응도 (0.0~1.0)
        """
        if total == 0:
            return 0.0
        raw = successful / total
        confidence = min(total / 10, 1.0)
        execution_fitness = raw * confidence

        if avg_judge_score is None:
            return round(execution_fitness, 4)

        judge_fitness = avg_judge_score / 10.0
        combined = execution_fitness * 0.5 + judge_fitness * 0.5
        return round(combined, 4)
