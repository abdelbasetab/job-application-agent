"""SQLite-backed persistence for jobs, applications, and status.

Three tables — all keyed by `job_id`:

  jobs(job_id PRIMARY KEY, payload JSON)
  applications(job_id PRIMARY KEY, payload JSON)
  status(job_id PRIMARY KEY, payload JSON)

We store full Pydantic dumps as JSON. This is intentionally low-tech for
Sprint 1 — a real relational schema arrives in Sprint 4 alongside ChromaDB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
)
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


# Ordered, append-only schema migrations. Each entry upgrades the DB by one
# version; `PRAGMA user_version` records how many have been applied, so existing
# databases upgrade in place and new ones are built from scratch — never edit a
# past migration, add a new one.
_MIGRATIONS: list[str] = [
    # v1 — base tables (one JSON payload per job_id).
    """
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
    """,
]


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring `conn` up to the latest schema version. Returns that version."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for index in range(version, len(_MIGRATIONS)):
        conn.executescript(_MIGRATIONS[index])
        conn.execute(f"PRAGMA user_version = {index + 1}")
    conn.commit()
    return len(_MIGRATIONS)


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        # WAL keeps concurrent readers from blocking the writer — important now
        # that each authenticated user has their own DB hit per request.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        version = apply_migrations(self._conn)
        log.info("[store] opened sqlite at %s (schema v%d)", self.db_path, version)

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

    def job_exists(self, job_id: str) -> bool:
        """True iff this job_id already has a persisted application.

        Used by the pipeline to avoid drafting a second cover letter for a
        job we've already applied to. Checks the `applications` table — the
        `jobs` table is irrelevant here, since Scout always re-saves jobs.
        """
        row = self._conn.execute(
            "SELECT 1 FROM applications WHERE job_id = ? LIMIT 1", (job_id,)
        ).fetchone()
        return row is not None

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
