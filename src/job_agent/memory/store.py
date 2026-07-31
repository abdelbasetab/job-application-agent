"""SQLite-backed, per-user persistence for the application workflow.

Pydantic models remain the public contract. SQLite stores the current objects
plus immutable snapshots, a status timeline, inbox de-duplication, and an
idempotent email outbox. Web callers give every authenticated user a separate
database path, so none of these tables are shared between accounts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    LivenessResult,
    MatchResult,
    UserProfile,
)
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


# Ordered and append-only. Never edit a released migration; append a new one.
_MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS applications (
        job_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS status (
        job_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS liveness (
        job_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS email_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        job_id TEXT,
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_email_audit_job ON email_audit(job_id);
    CREATE INDEX IF NOT EXISTS idx_email_audit_created ON email_audit(created_at);
    """,
    # Restart-safe profiles, match results, and immutable content snapshots.
    """
    CREATE TABLE IF NOT EXISTS profiles (
        fingerprint TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        source TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS active_profile (
        slot INTEGER PRIMARY KEY CHECK (slot = 1),
        fingerprint TEXT NOT NULL REFERENCES profiles(fingerprint)
    );
    CREATE TABLE IF NOT EXISTS matches (
        job_id TEXT PRIMARY KEY,
        profile_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS match_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        profile_fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE(job_id, profile_fingerprint, payload_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_match_history_job ON match_history(job_id);
    CREATE TABLE IF NOT EXISTS job_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        captured_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE(job_id, payload_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_job_history_job ON job_history(job_id);
    CREATE TABLE IF NOT EXISTS application_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE(job_id, payload_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_application_history_job
        ON application_history(job_id);
    """,
    # Status timeline plus durable inbox/outbox state.
    """
    CREATE TABLE IF NOT EXISTS status_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        previous_status TEXT,
        new_status TEXT NOT NULL,
        event_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_status_events_job ON status_events(job_id);
    CREATE INDEX IF NOT EXISTS idx_status_events_created ON status_events(created_at);
    CREATE TABLE IF NOT EXISTS processed_email (
        message_key TEXT PRIMARY KEY,
        uid TEXT,
        message_id TEXT,
        received_at TEXT,
        processed_at TEXT NOT NULL,
        job_id TEXT,
        stage TEXT,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_processed_email_job ON processed_email(job_id);
    CREATE TABLE IF NOT EXISTS email_outbox (
        idempotency_key TEXT PRIMARY KEY,
        job_id TEXT,
        event_type TEXT NOT NULL,
        recipient TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('pending', 'sent', 'dry_run', 'failed')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        message_id TEXT,
        error TEXT,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_email_outbox_job ON email_outbox(job_id);
    """,
]


def _json_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to the latest schema version and return that version."""
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
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        version = apply_migrations(self._conn)
        log.info("[store] opened sqlite at %s (schema v%d)", self.db_path, version)

    # ----- jobs -----
    def save_job(self, job: JobPosting) -> None:
        payload = job.model_dump_json()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs(job_id, payload) VALUES (?, ?)",
                (job.id, payload),
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO job_history(job_id, captured_at, payload_hash, payload)
                VALUES (?, ?, ?, ?)
                """,
                (job.id, datetime.now().isoformat(), _json_hash(payload), payload),
            )

    def get_job(self, job_id: str) -> JobPosting | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return JobPosting.model_validate_json(row[0]) if row else None

    def all_jobs(self) -> list[JobPosting]:
        rows = self._conn.execute("SELECT payload FROM jobs").fetchall()
        return [JobPosting.model_validate_json(row[0]) for row in rows]

    def clear_pipeline_results(self) -> None:
        """Atomically clear search/match/draft state without deleting the DB file.

        Profiles and mail audit/idempotency records are intentionally retained:
        resetting a search must neither forget the active identity nor make an
        already processed delivery appear new again.
        """
        with self._conn:
            self._conn.execute("DELETE FROM status_events")
            self._conn.execute("DELETE FROM status")
            self._conn.execute("DELETE FROM application_history")
            self._conn.execute("DELETE FROM applications")
            self._conn.execute("DELETE FROM match_history")
            self._conn.execute("DELETE FROM matches")
            self._conn.execute("DELETE FROM liveness")
            self._conn.execute("DELETE FROM job_history")
            self._conn.execute("DELETE FROM jobs")

    # ----- applications -----
    def save_application(self, app: GeneratedApplication) -> None:
        payload = app.model_dump_json()
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO applications(job_id, payload) VALUES (?, ?)",
                (app.job_id, payload),
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO application_history(
                    job_id, created_at, payload_hash, payload
                ) VALUES (?, ?, ?, ?)
                """,
                (app.job_id, datetime.now().isoformat(), _json_hash(payload), payload),
            )

    def get_application(self, job_id: str) -> GeneratedApplication | None:
        row = self._conn.execute(
            "SELECT payload FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return GeneratedApplication.model_validate_json(row[0]) if row else None

    def job_exists(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM applications WHERE job_id = ? LIMIT 1", (job_id,)
        ).fetchone()
        return row is not None

    # ----- status -----
    def upsert_status(
        self,
        status: ApplicationStatus,
        *,
        event_type: str = "status_update",
        event_payload: dict[str, Any] | None = None,
    ) -> None:
        """Persist current status and append the same change to its timeline."""
        existing = self.get_status(status.job_id)
        previous = existing.status if existing is not None else None
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO status(job_id, payload) VALUES (?, ?)",
                (status.job_id, status.model_dump_json()),
            )
            self._conn.execute(
                """
                INSERT INTO status_events(
                    job_id, previous_status, new_status, event_type, created_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    status.job_id,
                    previous,
                    status.status,
                    event_type,
                    status.updated_at.isoformat(),
                    json.dumps(event_payload or {}, ensure_ascii=False),
                ),
            )

    def get_status(self, job_id: str) -> ApplicationStatus | None:
        row = self._conn.execute(
            "SELECT payload FROM status WHERE job_id = ?", (job_id,)
        ).fetchone()
        return ApplicationStatus.model_validate_json(row[0]) if row else None

    def all_status(self) -> list[ApplicationStatus]:
        rows = self._conn.execute("SELECT payload FROM status").fetchall()
        return [ApplicationStatus.model_validate_json(row[0]) for row in rows]

    def status_events(
        self, job_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return newest-first events for analytics and audit views."""
        cap = max(1, min(1000, int(limit)))
        if job_id is None:
            rows = self._conn.execute(
                """
                SELECT id, job_id, previous_status, new_status, event_type, created_at, payload
                FROM status_events ORDER BY id DESC LIMIT ?
                """,
                (cap,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id, job_id, previous_status, new_status, event_type, created_at, payload
                FROM status_events WHERE job_id = ? ORDER BY id DESC LIMIT ?
                """,
                (job_id, cap),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "job_id": str(row[1]),
                "previous_status": row[2],
                "new_status": str(row[3]),
                "event_type": str(row[4]),
                "created_at": str(row[5]),
                "payload": json.loads(str(row[6])),
            }
            for row in rows
        ]

    # ----- profiles and matches -----
    def save_profile(self, profile: UserProfile, source: str) -> str:
        payload = profile.model_dump_json()
        fingerprint = _json_hash(payload)
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO profiles(fingerprint, created_at, source, payload)
                VALUES (?, ?, ?, ?)
                """,
                (fingerprint, datetime.now().isoformat(), source, payload),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO active_profile(slot, fingerprint) VALUES (1, ?)",
                (fingerprint,),
            )
        return fingerprint

    def get_active_profile(self) -> tuple[UserProfile, str, str] | None:
        row = self._conn.execute(
            """
            SELECT p.payload, p.source, p.fingerprint
            FROM active_profile AS active
            JOIN profiles AS p ON p.fingerprint = active.fingerprint
            WHERE active.slot = 1
            """
        ).fetchone()
        if row is None:
            return None
        return UserProfile.model_validate_json(row[0]), str(row[1]), str(row[2])

    def save_match(self, match: MatchResult, profile_fingerprint: str) -> None:
        payload = match.model_dump_json()
        now = datetime.now().isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO matches(job_id, profile_fingerprint, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (match.job_id, profile_fingerprint, now, payload),
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO match_history(
                    job_id, profile_fingerprint, created_at, payload_hash, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (match.job_id, profile_fingerprint, now, _json_hash(payload), payload),
            )

    def get_match(self, job_id: str) -> MatchResult | None:
        row = self._conn.execute(
            "SELECT payload FROM matches WHERE job_id = ?", (job_id,)
        ).fetchone()
        return MatchResult.model_validate_json(row[0]) if row else None

    def all_matches(self) -> list[MatchResult]:
        rows = self._conn.execute(
            "SELECT payload FROM matches ORDER BY created_at DESC"
        ).fetchall()
        return [MatchResult.model_validate_json(row[0]) for row in rows]

    # ----- liveness -----
    def save_liveness(self, job_id: str, result: LivenessResult) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO liveness(job_id, payload) VALUES (?, ?)",
                (job_id, result.model_dump_json()),
            )

    def get_liveness(self, job_id: str) -> LivenessResult | None:
        row = self._conn.execute(
            "SELECT payload FROM liveness WHERE job_id = ?", (job_id,)
        ).fetchone()
        return LivenessResult.model_validate_json(row[0]) if row else None

    def all_liveness(self) -> dict[str, LivenessResult]:
        rows = self._conn.execute("SELECT job_id, payload FROM liveness").fetchall()
        return {row[0]: LivenessResult.model_validate_json(row[1]) for row in rows}

    # ----- email audit, inbox, and idempotent outbox -----
    def record_email_audit(
        self,
        event_type: str,
        payload: dict[str, Any],
        job_id: str | None = None,
    ) -> int:
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO email_audit(created_at, job_id, event_type, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    job_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return int(cursor.lastrowid or 0)

    def email_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, created_at, job_id, event_type, payload
            FROM email_audit ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(200, int(limit))),),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row[4]))
            events.append(
                {
                    "id": int(row[0]),
                    "created_at": str(row[1]),
                    "job_id": row[2],
                    "event_type": str(row[3]),
                    "payload": payload if isinstance(payload, dict) else {},
                }
            )
        return events

    def email_processed(self, message_key: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_email WHERE message_key = ?", (message_key,)
        ).fetchone()
        return row is not None

    def record_processed_email(
        self,
        message_key: str,
        *,
        uid: str | None,
        message_id: str | None,
        received_at: datetime | None,
        job_id: str | None,
        stage: str | None,
        payload: dict[str, Any],
    ) -> bool:
        """Record an inbox message once; return False if it was already seen."""
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO processed_email(
                    message_key, uid, message_id, received_at, processed_at,
                    job_id, stage, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_key,
                    uid,
                    message_id,
                    received_at.isoformat() if received_at else None,
                    datetime.now().isoformat(),
                    job_id,
                    stage,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return cursor.rowcount == 1

    def apply_inbox_status(
        self,
        message_key: str,
        status: ApplicationStatus,
        *,
        uid: str | None,
        message_id: str | None,
        received_at: datetime | None,
        stage: str,
        payload: dict[str, Any],
    ) -> bool:
        """Atomically de-duplicate a message and apply its tracker update."""
        existing = self.get_status(status.job_id)
        previous = existing.status if existing is not None else None
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO processed_email(
                    message_key, uid, message_id, received_at, processed_at,
                    job_id, stage, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_key,
                    uid,
                    message_id,
                    received_at.isoformat() if received_at else None,
                    datetime.now().isoformat(),
                    status.job_id,
                    stage,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._conn.execute(
                "INSERT OR REPLACE INTO status(job_id, payload) VALUES (?, ?)",
                (status.job_id, status.model_dump_json()),
            )
            self._conn.execute(
                """
                INSERT INTO status_events(
                    job_id, previous_status, new_status, event_type, created_at, payload
                ) VALUES (?, ?, ?, 'inbox_sync', ?, ?)
                """,
                (
                    status.job_id,
                    previous,
                    status.status,
                    status.updated_at.isoformat(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return True

    def reserve_email(
        self,
        idempotency_key: str,
        *,
        job_id: str | None,
        event_type: str,
        recipient: str,
        payload: dict[str, Any],
        allow_retry_from_dry_run: bool = False,
    ) -> bool:
        """Atomically reserve a delivery key before talking to SMTP."""
        now = datetime.now().isoformat()
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO email_outbox(
                    idempotency_key, job_id, event_type, recipient, state,
                    created_at, updated_at, payload
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    idempotency_key,
                    job_id,
                    event_type,
                    recipient,
                    now,
                    now,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            if cursor.rowcount == 1:
                return True
            if not allow_retry_from_dry_run:
                return False
            row = self._conn.execute(
                "SELECT state FROM email_outbox WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None or str(row[0]) != "dry_run":
                return False
            cursor = self._conn.execute(
                """
                UPDATE email_outbox
                SET job_id = ?, event_type = ?, recipient = ?, state = 'pending',
                    updated_at = ?, message_id = NULL, error = ?, payload = ?
                WHERE idempotency_key = ? AND state = 'dry_run'
                """,
                (
                    job_id,
                    event_type,
                    recipient,
                    now,
                    None,
                    json.dumps(payload, ensure_ascii=False),
                    idempotency_key,
                ),
            )
        return cursor.rowcount == 1

    def finish_email(
        self,
        idempotency_key: str,
        *,
        state: str,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        if state not in {"sent", "dry_run", "failed"}:
            raise ValueError(f"Invalid final email state: {state}")
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE email_outbox
                SET state = ?, updated_at = ?, message_id = ?, error = ?
                WHERE idempotency_key = ? AND state = 'pending'
                """,
                (state, datetime.now().isoformat(), message_id, error, idempotency_key),
            )
        if cursor.rowcount != 1:
            raise ValueError("Email reservation is missing or already finalized.")

    def email_outbox_entry(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT job_id, event_type, recipient, state, created_at, updated_at,
                   message_id, error, payload
            FROM email_outbox WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "job_id": row[0],
            "event_type": str(row[1]),
            "recipient": str(row[2]),
            "state": str(row[3]),
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
            "message_id": row[6],
            "error": row[7],
            "payload": json.loads(str(row[8])),
        }

    def close(self) -> None:
        self._conn.close()
