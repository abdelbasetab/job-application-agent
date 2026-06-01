"""SQLite-backed persistence for jobs, applications, and status.

Three tables — all keyed by `job_id`:

  jobs(job_id PRIMARY KEY, payload JSON)
  applications(job_id PRIMARY KEY, payload JSON)
  status(job_id PRIMARY KEY, payload JSON)

We store full Pydantic dumps as JSON. This is intentionally low-tech for
Sprint 1 — a real relational schema arrives in Sprint 4 alongside ChromaDB.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
)
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    job_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status (
    job_id  TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        log.info("[store] opened sqlite at %s", self.db_path)

    # ----- jobs -----
    def save_job(self, job: JobPosting) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO jobs(job_id, payload) VALUES (?, ?)",
            (job.id, job.model_dump_json()),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> JobPosting | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return JobPosting.model_validate_json(row[0]) if row else None

    def all_jobs(self) -> list[JobPosting]:
        rows = self._conn.execute("SELECT payload FROM jobs").fetchall()
        return [JobPosting.model_validate_json(r[0]) for r in rows]

    # ----- applications -----
    def save_application(self, app: GeneratedApplication) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO applications(job_id, payload) VALUES (?, ?)",
            (app.job_id, app.model_dump_json()),
        )
        self._conn.commit()

    def get_application(self, job_id: str) -> GeneratedApplication | None:
        row = self._conn.execute(
            "SELECT payload FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return GeneratedApplication.model_validate_json(row[0]) if row else None

    # ----- status -----
    def upsert_status(self, status: ApplicationStatus) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO status(job_id, payload) VALUES (?, ?)",
            (status.job_id, status.model_dump_json()),
        )
        self._conn.commit()

    def get_status(self, job_id: str) -> ApplicationStatus | None:
        row = self._conn.execute(
            "SELECT payload FROM status WHERE job_id = ?", (job_id,)
        ).fetchone()
        return ApplicationStatus.model_validate_json(row[0]) if row else None

    def all_status(self) -> list[ApplicationStatus]:
        rows = self._conn.execute("SELECT payload FROM status").fetchall()
        return [ApplicationStatus.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        self._conn.close()
