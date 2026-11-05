from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from services.schemas import EvaluationResult, StructuredJD


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    jd_text TEXT NOT NULL,
                    jd_hash TEXT NOT NULL,
                    jd_requirements_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS resumes (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    parsed_text_preview TEXT NOT NULL DEFAULT '',
                    ocr_used INTEGER NOT NULL DEFAULT 0,
                    total_score INTEGER,
                    grade TEXT,
                    recommendation TEXT,
                    hard_gate TEXT,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_resumes_task_id
                ON resumes(task_id);
                """
            )

    def create_task(
        self,
        *,
        task_id: str,
        jd_text: str,
        jd_hash: str,
        structured_jd: StructuredJD,
        created_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks
                (id, jd_text, jd_hash, jd_requirements_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    jd_text,
                    jd_hash,
                    structured_jd.model_dump_json(),
                    "running",
                    created_at,
                ),
            )

    def complete_task(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,)
            )

    def add_resume(
        self,
        *,
        resume_id: str,
        task_id: str,
        filename: str,
        preview: str,
        ocr_used: bool,
        status: str,
        result: EvaluationResult | None,
        error_message: str,
        created_at: str,
        duration_ms: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO resumes
                (id, task_id, filename, parsed_text_preview, ocr_used,
                 total_score, grade, recommendation, hard_gate, status,
                 result_json, error_message, created_at, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resume_id,
                    task_id,
                    filename,
                    preview,
                    int(ocr_used),
                    result.total_score if result else None,
                    result.grade.value if result else None,
                    result.recommendation if result else None,
                    result.hard_gate.value if result else None,
                    status,
                    result.model_dump_json() if result else "",
                    error_message,
                    created_at,
                    duration_ms,
                ),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_task_requirements(self, task_id: str) -> StructuredJD:
        task = self.get_task(task_id)
        if not task:
            raise KeyError("任务不存在")
        return StructuredJD.model_validate_json(task["jd_requirements_json"])

    def list_resumes(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resumes
                WHERE task_id = ?
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    t.*,
                    COUNT(r.id) AS resume_count,
                    SUM(CASE WHEN r.status = 'success' THEN 1 ELSE 0 END)
                        AS success_count,
                    MIN(r.created_at) AS evaluated_at
                FROM tasks t
                LEFT JOIN resumes r ON r.task_id = t.id
                GROUP BY t.id
                ORDER BY t.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_task(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def clear_all(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks")

    @staticmethod
    def load_result(row: dict[str, Any]) -> EvaluationResult | None:
        payload = row.get("result_json") or ""
        if not payload:
            return None
        return EvaluationResult.model_validate_json(payload)

