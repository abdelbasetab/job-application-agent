"""Tracker agent — persists application state and drives follow-up cadence.

Submitted applications that have seen no activity for N days are surfaced
with a ready-to-send German follow-up draft. The cadence is derived from
``updated_at``; recording a follow-up resets that clock via a timestamped note.
"""

from __future__ import annotations

from datetime import datetime

from job_agent.memory.store import Store
from job_agent.schemas import ApplicationStatus, FollowUpItem, GeneratedApplication
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# After how many days without activity a submitted application is "due".
FOLLOW_UP_AFTER_DAYS = 7


def run_tracker(
    application: GeneratedApplication,
    store: Store,
    status: str = "draft",
    notes: str = "",
) -> ApplicationStatus:
    """Persist the application and return its tracked status."""
    store.save_application(application)
    existing = store.get_status(application.job_id)
    if existing is not None and status == "draft":
        log.info(
            "[tracker] refreshed draft for %s; preserving status %s",
            application.job_id,
            existing.status,
        )
        return existing
    record = ApplicationStatus(
        job_id=application.job_id,
        status=status,  # type: ignore[arg-type]
        submitted_at=None,
        updated_at=datetime.now(),
        notes=notes,
    )
    store.upsert_status(record, event_type="application_tracked")
    log.info("[tracker] persisted %s → %s", application.job_id, record.status)
    return record


def due_follow_ups(
    store: Store,
    days: int = FOLLOW_UP_AFTER_DAYS,
    candidate_name: str = "",
    now: datetime | None = None,
) -> list[FollowUpItem]:
    """Submitted applications without activity for ``days`` — most overdue first.

    Only ``submitted`` needs nudging: drafts are not sent yet, and interview/
    offer/rejected stages are handled by humans anyway.
    """
    reference = now or datetime.now()
    items: list[FollowUpItem] = []
    for status in store.all_status():
        if status.status != "submitted":
            continue
        last_activity = status.updated_at or status.submitted_at or reference
        days_since = max(0, (reference - last_activity).days)
        if days_since < days:
            continue
        job = store.get_job(status.job_id)
        title = job.title if job else status.job_id
        company = job.company if job else ""
        items.append(
            FollowUpItem(
                job_id=status.job_id,
                title=title,
                company=company,
                status=status.status,
                submitted_at=status.submitted_at,
                last_activity=last_activity,
                days_since_activity=days_since,
                days_overdue=days_since - days,
                suggested_email_md=follow_up_email_draft(
                    title, company, status.submitted_at, candidate_name
                ),
            )
        )
    items.sort(key=lambda item: item.days_overdue, reverse=True)
    log.info("[tracker] %d follow-up(s) due (window: %d days)", len(items), days)
    return items


def record_follow_up(
    store: Store,
    job_id: str,
    note: str = "",
    now: datetime | None = None,
) -> ApplicationStatus:
    """Log a follow-up on an application — resets the cadence clock.

    The event lands in ``notes`` and ``updated_at`` moves to now, so the same
    application only becomes due again after another full window.
    """
    existing = store.get_status(job_id)
    if existing is None:
        raise ValueError(f"No tracked application for job '{job_id}'.")
    reference = now or datetime.now()
    event = note or f"Follow-up am {reference.strftime('%d.%m.%Y')} vermerkt."
    merged = f"{existing.notes}\n{event}".strip() if existing.notes else event
    record = ApplicationStatus(
        job_id=job_id,
        status=existing.status,
        submitted_at=existing.submitted_at,
        updated_at=reference,
        notes=merged[-1000:],
    )
    store.upsert_status(record, event_type="follow_up_recorded")
    log.info("[tracker] follow-up recorded for %s", job_id)
    return record


def follow_up_email_draft(
    title: str,
    company: str,
    submitted_at: datetime | None,
    candidate_name: str,
) -> str:
    """Polite German follow-up draft — deterministic, ready to copy or send."""
    when = f"am {submitted_at.strftime('%d.%m.%Y')}" if submitted_at else "vor Kurzem"
    at_company = f" bei {company}" if company else ""
    name = candidate_name or "Ihr/e Bewerber/in"
    return (
        f"**Betreff: Nachfrage zu meiner Bewerbung als {title}**\n\n"
        "Sehr geehrte Damen und Herren,\n\n"
        f"{when} habe ich mich{at_company} auf die Position **{title}** beworben. "
        "Ich möchte mich freundlich nach dem aktuellen Stand des Auswahlverfahrens "
        "erkundigen.\n\n"
        "Mein Interesse an der Position ist unverändert groß — falls Sie weitere "
        "Unterlagen oder Informationen benötigen, sende ich diese gerne zu.\n\n"
        "Mit freundlichen Grüßen\n"
        f"{name}"
    )
