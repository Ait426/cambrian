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
                release_state         TEXT NOT NULL DEFAULT 'experimental',
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
                created_at       TEXT NOT NULL,
                auto_rolled_back INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        # 기존 DB 마이그레이션: auto_rolled_back 컬럼이 없으면 추가
        try:
            self._conn.execute(
                "ALTER TABLE evolution_history "
                "ADD COLUMN auto_rolled_back INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()
        except Exception:
            pass  # 이미 존재하면 무시
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_inputs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id    TEXT NOT NULL,
                input_data  TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_traces (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_type      TEXT NOT NULL,
                domain          TEXT NOT NULL DEFAULT '',
                tags            TEXT NOT NULL DEFAULT '[]',
                input_summary   TEXT NOT NULL DEFAULT '',
                candidate_count INTEGER NOT NULL DEFAULT 0,
                success_count   INTEGER NOT NULL DEFAULT 0,
                winner_id       TEXT,
                winner_reason   TEXT NOT NULL DEFAULT '',
                candidates_json TEXT NOT NULL DEFAULT '[]',
                total_ms        INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS governance_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id     TEXT NOT NULL,
                from_state   TEXT NOT NULL,
                to_state     TEXT NOT NULL,
                reason       TEXT NOT NULL DEFAULT '',
                triggered_by TEXT NOT NULL DEFAULT 'auto',
                created_at   TEXT NOT NULL
            );
            """
        )
        # 기존 DB 마이그레이션: release_state 컬럼이 없으면 추가
        try:
            self._conn.execute(
                "ALTER TABLE skills "
                "ADD COLUMN release_state TEXT NOT NULL DEFAULT 'experimental'"
            )
            self._conn.commit()
        except Exception:
            pass  # 이미 존재하면 무시
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evaluation_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id        TEXT NOT NULL,
                input_count     INTEGER NOT NULL DEFAULT 0,
                pass_count      INTEGER NOT NULL DEFAULT 0,
                fail_count      INTEGER NOT NULL DEFAULT 0,
                pass_rate       REAL NOT NULL DEFAULT 0.0,
                avg_time_ms     INTEGER NOT NULL DEFAULT 0,
                fitness_at_time REAL NOT NULL DEFAULT 0.0,
                results_json    TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outcomes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_trace_id    INTEGER,
                skill_id        TEXT NOT NULL,
                domain          TEXT NOT NULL DEFAULT '',
                verdict         TEXT NOT NULL,
                human_note      TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS adoption_lineage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                child_skill_name  TEXT NOT NULL,
                child_run_id      TEXT NOT NULL,
                parent_skill_name TEXT,
                parent_run_id     TEXT,
                scenario_id       TEXT,
                policy_hash       TEXT,
                adopted_at        TEXT NOT NULL,
                notes             TEXT
            );
            """
        )
        self._conn.commit()

    def register(self, skill: Skill) -> None:
        """스킬을 DB에 등록한다. 이미 같은 id가 있으면 정적 필드만 UPDATE한다.

        신규 스킬이면 INSERT, 기존 스킬이면 runtime 필드
        (fitness_score, total_executions, successful_executions,
        last_used, avg_judge_score, status, crystallized_at, registered_at)를
        보존하고 정적 메타데이터만 갱신한다.

        Args:
            skill: 등록할 Skill 객체
        """
        existing = self._conn.execute(
            "SELECT id FROM skills WHERE id = ?", (skill.id,)
        ).fetchone()

        if existing is None:
            # 신규 스킬: 전체 필드 INSERT
            registered_at = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                """
                INSERT INTO skills (
                    id, version, name, description, domain, tags, mode,
                    language, needs_network, needs_filesystem, timeout_seconds,
                    skill_path, status, release_state, fitness_score,
                    total_executions, successful_executions, last_used,
                    crystallized_at, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    "experimental",
                    skill.lifecycle.fitness_score,
                    skill.lifecycle.total_executions,
                    skill.lifecycle.successful_executions,
                    skill.lifecycle.last_used,
                    skill.lifecycle.crystallized_at,
                    registered_at,
                ),
            )
        else:
            # 기존 스킬: 정적 메타데이터만 UPDATE, runtime 필드 보존
            self._conn.execute(
                """
                UPDATE skills SET
                    version = ?,
                    name = ?,
                    description = ?,
                    domain = ?,
                    tags = ?,
                    mode = ?,
                    language = ?,
                    needs_network = ?,
                    needs_filesystem = ?,
                    timeout_seconds = ?,
                    skill_path = ?
                WHERE id = ?
                """,
                (
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
                    skill.id,
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
        release_state: str | None = None,
    ) -> list[dict]:
        """조건에 맞는 스킬 목록을 검색한다.

        Args:
            domain: 도메인 필터
            tags: 태그 필터
            status: 상태 필터
            mode: 모드 필터
            min_fitness: 최소 적응도
            release_state: release 상태 필터. 미지정 시 quarantined 제외.

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

        if release_state is not None:
            query += " AND release_state = ?"
            params.append(release_state)
        else:
            query += " AND release_state != 'quarantined'"

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

        # LIKE는 부분 매칭이므로 Python 레벨에서 정확 매칭 후처리
        if tags is not None and len(tags) > 0:
            filtered_rows = []
            for row in rows:
                row_tags = json.loads(row["tags"])
                if set(tags) & set(row_tags):
                    filtered_rows.append(row)
            rows = filtered_rows

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
            item["auto_rolled_back"] = bool(item.get("auto_rolled_back", 0))
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

    def add_evaluation_input(
        self,
        skill_id: str,
        input_data: str,
        description: str = "",
    ) -> int:
        """진화 평가용 입력을 추가하고 생성된 ID를 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            input_data: JSON 문자열
            description: 입력 설명

        Returns:
            생성된 evaluation_input ID
        """
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO evaluation_inputs (skill_id, input_data, description, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (skill_id, input_data, description, created_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_evaluation_inputs(self, skill_id: str) -> list[dict]:
        """해당 스킬의 평가 입력 목록을 반환한다.

        Args:
            skill_id: 대상 스킬 ID

        Returns:
            등록순 평가 입력 목록
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM evaluation_inputs
            WHERE skill_id = ?
            ORDER BY id ASC
            """,
            (skill_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def remove_evaluation_input(self, eval_id: int) -> None:
        """평가 입력을 삭제한다.

        Args:
            eval_id: 삭제할 evaluation_input ID

        Raises:
            ValueError: 해당 ID가 존재하지 않을 때
        """
        cursor = self._conn.execute(
            "DELETE FROM evaluation_inputs WHERE id = ?", (eval_id,)
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Evaluation input not found: {eval_id}")

    def add_run_trace(
        self,
        trace_type: str,
        domain: str,
        tags: list[str],
        input_summary: str,
        candidate_count: int,
        success_count: int,
        winner_id: str | None,
        winner_reason: str,
        candidates_json: str,
        total_ms: int,
    ) -> int:
        """실행 trace를 저장하고 생성된 ID를 반환한다.

        Args:
            trace_type: trace 유형 (competitive_run, evolution_decision 등)
            domain: 도메인
            tags: 태그 리스트
            input_summary: 입력 요약 (JSON 문자열 앞부분)
            candidate_count: 후보 수
            success_count: 성공 수
            winner_id: 승자 스킬 ID (None이면 전부 실패)
            winner_reason: 승자 선택 이유
            candidates_json: 각 후보 결과 JSON
            total_ms: 전체 실행 시간

        Returns:
            생성된 trace ID
        """
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO run_traces (
                trace_type, domain, tags, input_summary,
                candidate_count, success_count, winner_id,
                winner_reason, candidates_json, total_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_type,
                domain,
                json.dumps(tags),
                input_summary,
                candidate_count,
                success_count,
                winner_id,
                winner_reason,
                candidates_json,
                total_ms,
                created_at,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_run_traces(
        self,
        trace_type: str | None = None,
        skill_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """실행 trace를 조회한다.

        Args:
            trace_type: trace 유형 필터 (None이면 전체)
            skill_id: 스킬 ID 필터 (winner_id 또는 candidates_json에 포함)
            limit: 최대 반환 개수

        Returns:
            최신순 trace 목록
        """
        query = "SELECT * FROM run_traces WHERE 1=1"
        params: list[object] = []

        if trace_type is not None:
            query += " AND trace_type = ?"
            params.append(trace_type)

        if skill_id is not None:
            query += " AND (winner_id = ? OR candidates_json LIKE ?)"
            params.append(skill_id)
            params.append(f'%"skill_id": "{skill_id}"%')

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, tuple(params))
        rows = cursor.fetchall()
        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags"])
            results.append(item)
        return results

    def get_run_trace_by_id(self, trace_id: int) -> dict | None:
        """특정 run trace를 ID로 조회한다.

        Args:
            trace_id: 조회할 trace ID

        Returns:
            trace dict 또는 None (미존재 시)
        """
        cursor = self._conn.execute(
            "SELECT * FROM run_traces WHERE id = ?", (trace_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        item = dict(row)
        item["tags"] = json.loads(item["tags"])
        return item

    def get_skill_trace_stats(
        self, skill_id: str, limit: int = 20,
    ) -> dict:
        """해당 스킬이 참여한 최근 경쟁 실행 통계를 집계한다.

        Args:
            skill_id: 대상 스킬 ID
            limit: 최근 N개 trace 대상

        Returns:
            participated, won, win_rate, avg_execution_ms 등 집계 dict
        """
        empty = {
            "participated": 0, "won": 0, "win_rate": 0.0,
            "avg_execution_ms": 0, "success_in_runs": 0, "fail_in_runs": 0,
        }
        try:
            traces = self.get_run_traces(
                trace_type="competitive_run", skill_id=skill_id, limit=limit,
            )
        except Exception:
            return empty

        participated = 0
        won = 0
        total_time = 0
        time_count = 0
        success_in_runs = 0
        fail_in_runs = 0

        for t in traces:
            # candidates_json에서 해당 skill 항목 추출
            try:
                candidates = json.loads(t["candidates_json"])
            except (json.JSONDecodeError, TypeError):
                continue

            skill_found = False
            for c in candidates:
                if c.get("skill_id") == skill_id:
                    skill_found = True
                    if c.get("success"):
                        success_in_runs += 1
                    else:
                        fail_in_runs += 1
                    ms = c.get("execution_time_ms", 0)
                    if ms > 0:
                        total_time += ms
                        time_count += 1
                    break

            if skill_found:
                participated += 1
                if t.get("winner_id") == skill_id:
                    won += 1

        return {
            "participated": participated,
            "won": won,
            "win_rate": round(won / participated, 3) if participated > 0 else 0.0,
            "avg_execution_ms": (
                round(total_time / time_count) if time_count > 0 else 0
            ),
            "success_in_runs": success_in_runs,
            "fail_in_runs": fail_in_runs,
        }

    def get_skill_evolution_stats(self, skill_id: str) -> dict:
        """해당 스킬의 진화 통계를 집계한다.

        Args:
            skill_id: 대상 스킬 ID

        Returns:
            total_evolutions, adopted_count, adoption_rate 등 집계 dict
        """
        empty = {
            "total_evolutions": 0, "adopted_count": 0, "discarded_count": 0,
            "adoption_rate": 0.0, "last_evolution_adopted": None,
            "last_parent_fitness": None, "last_child_fitness": None,
        }

        cursor = self._conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN adopted = 1 THEN 1 ELSE 0 END) as adopted,
                SUM(CASE WHEN adopted = 0 THEN 1 ELSE 0 END) as discarded
            FROM evolution_history WHERE skill_id = ?
            """,
            (skill_id,),
        )
        row = cursor.fetchone()
        if row is None or row["total"] == 0:
            return empty

        total = row["total"]
        adopted = row["adopted"]
        discarded = row["discarded"]

        # 최근 진화 조회
        cursor2 = self._conn.execute(
            """
            SELECT parent_fitness, child_fitness, adopted
            FROM evolution_history WHERE skill_id = ?
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (skill_id,),
        )
        last = cursor2.fetchone()

        return {
            "total_evolutions": total,
            "adopted_count": adopted,
            "discarded_count": discarded,
            "adoption_rate": round(adopted / total, 3) if total > 0 else 0.0,
            "last_evolution_adopted": bool(last["adopted"]) if last else None,
            "last_parent_fitness": (
                float(last["parent_fitness"]) if last else None
            ),
            "last_child_fitness": (
                float(last["child_fitness"]) if last else None
            ),
        }

    def get_skill_rollback_count(self, skill_id: str) -> int:
        """해당 스킬의 자동 롤백 횟수를 반환한다.

        Args:
            skill_id: 대상 스킬 ID

        Returns:
            auto_rollback trace 수
        """
        try:
            cursor = self._conn.execute(
                """
                SELECT COUNT(*) as cnt FROM run_traces
                WHERE trace_type = 'auto_rollback'
                AND winner_reason LIKE ?
                """,
                (f"%{skill_id}%",),
            )
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0

    def add_evaluation_snapshot(
        self,
        skill_id: str,
        input_count: int,
        pass_count: int,
        fail_count: int,
        pass_rate: float,
        avg_time_ms: int,
        fitness_at_time: float,
        results_json: str,
    ) -> int:
        """평가 스냅샷을 저장하고 생성된 ID를 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            input_count: 전체 입력 수
            pass_count: 성공 수
            fail_count: 실패 수
            pass_rate: 성공률 (0.0~1.0)
            avg_time_ms: 성공 입력 평균 실행 시간
            fitness_at_time: 평가 시점 fitness
            results_json: 입력별 결과 JSON

        Returns:
            생성된 snapshot ID
        """
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO evaluation_snapshots (
                skill_id, input_count, pass_count, fail_count,
                pass_rate, avg_time_ms, fitness_at_time,
                results_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill_id, input_count, pass_count, fail_count,
                pass_rate, avg_time_ms, fitness_at_time,
                results_json, created_at,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_evaluation_snapshots(
        self, skill_id: str, limit: int = 10,
    ) -> list[dict]:
        """해당 스킬의 평가 스냅샷 목록을 반환한다.

        Args:
            skill_id: 대상 스킬 ID
            limit: 최대 반환 개수

        Returns:
            최신순 스냅샷 목록
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM evaluation_snapshots
            WHERE skill_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (skill_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_evaluation_snapshot_by_id(self, snapshot_id: int) -> dict | None:
        """특정 평가 스냅샷을 ID로 조회한다.

        Args:
            snapshot_id: 조회할 snapshot ID

        Returns:
            snapshot dict 또는 None
        """
        cursor = self._conn.execute(
            "SELECT * FROM evaluation_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def update_release_state(
        self,
        skill_id: str,
        new_state: str,
        reason: str,
        triggered_by: str = "auto",
    ) -> None:
        """스킬의 release_state를 변경하고 governance_log에 기록한다.

        Args:
            skill_id: 대상 스킬 ID
            new_state: 새 release 상태
            reason: 변경 사유
            triggered_by: 'auto' 또는 'manual'

        Raises:
            ValueError: new_state가 유효하지 않은 값일 때
            SkillNotFoundError: 해당 ID가 DB에 없을 때
        """
        valid_states = {"experimental", "candidate", "production", "quarantined"}
        if new_state not in valid_states:
            raise ValueError(f"Invalid release_state: {new_state}")

        current = self.get(skill_id)
        from_state = current.get("release_state", "experimental")

        self._conn.execute(
            "UPDATE skills SET release_state = ? WHERE id = ?",
            (new_state, skill_id),
        )

        created_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO governance_log
                (skill_id, from_state, to_state, reason, triggered_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (skill_id, from_state, new_state, reason, triggered_by, created_at),
        )
        self._conn.commit()

    def get_governance_log(
        self,
        skill_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """governance 이력을 조회한다.

        Args:
            skill_id: 특정 스킬만 필터 (None이면 전체)
            limit: 최대 반환 개수

        Returns:
            최신순 governance log 목록
        """
        query = "SELECT * FROM governance_log WHERE 1=1"
        params: list[object] = []

        if skill_id is not None:
            query += " AND skill_id = ?"
            params.append(skill_id)

        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]

    def get_quarantine_count(self, skill_id: str) -> int:
        """해당 스킬이 quarantine된 총 횟수를 반환한다.

        Args:
            skill_id: 대상 스킬 ID

        Returns:
            quarantine 전이 횟수
        """
        cursor = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM governance_log "
            "WHERE skill_id = ? AND to_state = 'quarantined'",
            (skill_id,),
        )
        row = cursor.fetchone()
        return int(row["cnt"]) if row else 0

    # === Adoption Lineage ===

    def add_lineage(
        self,
        child_skill_name: str,
        child_run_id: str,
        parent_skill_name: str | None = None,
        parent_run_id: str | None = None,
        scenario_id: str | None = None,
        policy_hash: str | None = None,
        notes: str | None = None,
    ) -> int:
        """채택 계보 레코드를 추가한다.

        Args:
            child_skill_name: 자식 스킬 이름
            child_run_id: 자식 실행 ID
            parent_skill_name: 부모 스킬 이름 (None이면 최초 생성)
            parent_run_id: 부모 실행 ID
            scenario_id: 시나리오 식별자
            policy_hash: 정책 해시
            notes: 메모

        Returns:
            생성된 lineage ID
        """
        adopted_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO adoption_lineage
                (child_skill_name, child_run_id, parent_skill_name,
                 parent_run_id, scenario_id, policy_hash, adopted_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_skill_name, child_run_id,
                parent_skill_name, parent_run_id,
                scenario_id, policy_hash, adopted_at, notes,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_ancestors(
        self,
        skill_name: str,
        run_id: str,
    ) -> list[dict]:
        """run_id 기준 직계 조상 체인을 반환한다 (최신→최초 순).

        Args:
            skill_name: 스킬 이름
            run_id: 시작 run ID

        Returns:
            조상 체인 리스트
        """
        ancestors: list[dict] = []
        current_run_id: str | None = run_id
        visited: set[str] = set()

        while current_run_id:
            if current_run_id in visited:
                break
            visited.add(current_run_id)

            row = self._conn.execute(
                """
                SELECT child_skill_name, child_run_id, parent_skill_name,
                       parent_run_id, adopted_at, scenario_id, policy_hash
                FROM adoption_lineage
                WHERE child_run_id = ?
                """,
                (current_run_id,),
            ).fetchone()

            if not row:
                break

            ancestors.append({
                "skill_name": row["child_skill_name"],
                "run_id": row["child_run_id"],
                "parent_skill_name": row["parent_skill_name"],
                "parent_run_id": row["parent_run_id"],
                "adopted_at": row["adopted_at"],
                "scenario_id": row["scenario_id"],
                "policy_hash": row["policy_hash"],
            })
            current_run_id = row["parent_run_id"]

        return ancestors

    def get_descendants(
        self,
        run_id: str,
        depth: int = 0,
        max_depth: int = 10,
    ) -> list[dict]:
        """run_id 기준 직계 자손 목록을 반환한다 (재귀).

        Args:
            run_id: 시작 run ID
            depth: 현재 깊이
            max_depth: 최대 깊이

        Returns:
            자손 트리 리스트
        """
        if depth >= max_depth:
            return []

        rows = self._conn.execute(
            """
            SELECT child_skill_name, child_run_id, parent_run_id,
                   adopted_at, scenario_id, policy_hash
            FROM adoption_lineage
            WHERE parent_run_id = ?
            ORDER BY adopted_at ASC
            """,
            (run_id,),
        ).fetchall()

        result: list[dict] = []
        for row in rows:
            node = {
                "skill_name": row["child_skill_name"],
                "run_id": row["child_run_id"],
                "parent_run_id": row["parent_run_id"],
                "adopted_at": row["adopted_at"],
                "scenario_id": row["scenario_id"],
                "policy_hash": row["policy_hash"],
                "children": self.get_descendants(
                    row["child_run_id"], depth + 1, max_depth,
                ),
            }
            result.append(node)
        return result

    def get_adoption_history(
        self,
        skill_name: str | None = None,
        since: str | None = None,
        until: str | None = None,
        scenario_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """필터형 채택 이력을 조회한다.

        Args:
            skill_name: 스킬 이름 필터
            since: 시작일 필터 (ISO 문자열)
            until: 종료일 필터 (ISO 문자열)
            scenario_id: 시나리오 ID 필터
            limit: 최대 반환 건수

        Returns:
            최신순 채택 이력 리스트
        """
        clauses: list[str] = []
        params: list[object] = []

        if skill_name:
            clauses.append("child_skill_name = ?")
            params.append(skill_name)
        if since:
            clauses.append("adopted_at >= ?")
            params.append(since)
        if until:
            clauses.append("adopted_at <= ?")
            params.append(until)
        if scenario_id:
            clauses.append("scenario_id = ?")
            params.append(scenario_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = self._conn.execute(
            f"""
            SELECT child_skill_name, child_run_id, parent_skill_name,
                   parent_run_id, adopted_at, scenario_id, policy_hash, notes
            FROM adoption_lineage
            {where}
            ORDER BY adopted_at DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()

        return [dict(row) for row in rows]

    # === Outcome / Pilot KPI ===

    def add_outcome(
        self,
        skill_id: str,
        verdict: str,
        run_trace_id: int | None = None,
        domain: str = "",
        human_note: str = "",
    ) -> int:
        """실행 결과에 대한 사람의 사용 판정을 기록한다.

        Args:
            skill_id: 대상 스킬 ID
            verdict: 사용 결과 (approved/edited/rejected/redo)
            run_trace_id: 연결할 run_trace ID (선택)
            domain: 스킬 도메인
            human_note: 사람 메모

        Returns:
            생성된 outcome ID

        Raises:
            ValueError: verdict가 유효하지 않은 값일 때
        """
        valid_verdicts = {"approved", "edited", "rejected", "redo"}
        if verdict not in valid_verdicts:
            raise ValueError(f"Invalid verdict: {verdict}")

        created_at = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO outcomes
                (run_trace_id, skill_id, domain, verdict, human_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_trace_id, skill_id, domain, verdict, human_note, created_at),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def get_outcomes(
        self,
        skill_id: str | None = None,
        verdict: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """outcome 목록을 조회한다.

        Args:
            skill_id: 스킬 ID 필터
            verdict: verdict 필터
            limit: 최대 반환 개수

        Returns:
            최신순 outcome 목록
        """
        query = "SELECT * FROM outcomes WHERE 1=1"
        params: list[object] = []

        if skill_id is not None:
            query += " AND skill_id = ?"
            params.append(skill_id)

        if verdict is not None:
            query += " AND verdict = ?"
            params.append(verdict)

        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, tuple(params))
        return [dict(row) for row in cursor.fetchall()]

    def get_pilot_kpi(
        self,
        skill_id: str | None = None,
        days: int | None = None,
    ) -> dict:
        """파일럿 KPI를 집계한다.

        Args:
            skill_id: 특정 스킬 필터 (None이면 전체)
            days: 최근 N일 필터 (None이면 전체)

        Returns:
            total, approved, edited, rejected, redo + 5개 rate
        """
        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN verdict = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN verdict = 'edited' THEN 1 ELSE 0 END) as edited,
                SUM(CASE WHEN verdict = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN verdict = 'redo' THEN 1 ELSE 0 END) as redo
            FROM outcomes WHERE 1=1
        """
        params: list[object] = []

        if skill_id is not None:
            query += " AND skill_id = ?"
            params.append(skill_id)

        if days is not None:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).isoformat()
            query += " AND created_at >= ?"
            params.append(cutoff)

        cursor = self._conn.execute(query, tuple(params))
        row = cursor.fetchone()

        total = int(row["total"]) if row and row["total"] else 0
        approved = int(row["approved"]) if row and row["approved"] else 0
        edited = int(row["edited"]) if row and row["edited"] else 0
        rejected = int(row["rejected"]) if row and row["rejected"] else 0
        redo = int(row["redo"]) if row and row["redo"] else 0

        return {
            "total": total,
            "approved": approved,
            "edited": edited,
            "rejected": rejected,
            "redo": redo,
            "acceptance_rate": round(approved / total, 3) if total > 0 else 0.0,
            "edit_rate": round(edited / total, 3) if total > 0 else 0.0,
            "reject_rate": round(rejected / total, 3) if total > 0 else 0.0,
            "redo_rate": round(redo / total, 3) if total > 0 else 0.0,
            "net_useful_rate": (
                round((approved + edited) / total, 3) if total > 0 else 0.0
            ),
        }

    def get_pilot_kpi_by_skill(
        self,
        days: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """스킬별 파일럿 KPI를 집계한다.

        Args:
            days: 최근 N일 필터 (None이면 전체)
            limit: 최대 스킬 수

        Returns:
            스킬별 KPI 목록 (total 내림차순)
        """
        query = """
            SELECT
                skill_id,
                COUNT(*) as total,
                SUM(CASE WHEN verdict = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN verdict = 'edited' THEN 1 ELSE 0 END) as edited,
                SUM(CASE WHEN verdict = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN verdict = 'redo' THEN 1 ELSE 0 END) as redo
            FROM outcomes WHERE 1=1
        """
        params: list[object] = []

        if days is not None:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).isoformat()
            query += " AND created_at >= ?"
            params.append(cutoff)

        query += " GROUP BY skill_id ORDER BY total DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, tuple(params))
        results: list[dict] = []
        for row in cursor.fetchall():
            total = int(row["total"])
            approved = int(row["approved"]) if row["approved"] else 0
            edited = int(row["edited"]) if row["edited"] else 0
            rejected = int(row["rejected"]) if row["rejected"] else 0
            redo = int(row["redo"]) if row["redo"] else 0
            results.append({
                "skill_id": row["skill_id"],
                "total": total,
                "approved": approved,
                "edited": edited,
                "rejected": rejected,
                "redo": redo,
                "net_useful_rate": (
                    round((approved + edited) / total, 3) if total > 0 else 0.0
                ),
            })
        return results

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
