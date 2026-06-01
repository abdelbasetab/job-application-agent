"""Tracker agent — persists application state.

This agent is "real" already because all it does is wrap the SQLite store.
The schema and behavior stay the same across all sprints; later sprints add
status transitions (submitted → interview → …) but the surface stays this.
"""

from __future__ import annotations

from datetime import datetime

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, GeneratedApplication
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def run_tracker(
    application: GeneratedApplication,
    store: Store,
    status: str = "draft",
    notes: str = "",
) -> ApplicationStatus:
    """Persist the application and return its tracked status."""
    record = ApplicationStatus(
        job_id=application.job_id,
        status=status,  # type: ignore[arg-type]
        submitted_at=None,
        updated_at=datetime.now(),
        notes=notes,
    )
    store.upsert_status(record)
    store.save_application(application)
    log.info("[tracker] persisted %s → %s", application.job_id, record.status)
    return record
