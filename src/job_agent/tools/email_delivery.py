"""Email delivery helper for Tracker submissions.

The default path is dry-run, so demos can show autonomous submission without
accidentally sending real applications. Set EMAIL_DRY_RUN=false plus SMTP
credentials to send for real.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from job_agent.schemas import GeneratedApplication, JobPosting
from job_agent.utils.config import settings


def send_application_email(
    job: JobPosting,
    application: GeneratedApplication,
    recipient: str | None = None,
) -> dict[str, Any]:
    """Send or dry-run a generated application email."""
    resolved_recipient = (recipient or settings.email_demo_recipient or "").strip()
    if not resolved_recipient:
        raise ValueError("No email recipient configured. Set EMAIL_DEMO_RECIPIENT or enter one in the UI.")

    sender = (settings.email_from or settings.email_smtp_user or "").strip()
    if not sender:
        sender = "job-agent@example.local"

    subject = f"Bewerbung: {job.title} - {job.company}"
    body = _email_body(job, application)
    message = _build_message(sender, resolved_recipient, subject, body)

    if settings.email_dry_run:
        return {
            "sent": False,
            "dry_run": True,
            "recipient": resolved_recipient,
            "subject": subject,
            "body_preview": body[:900],
        }

    if not settings.email_smtp_host:
        raise ValueError("EMAIL_SMTP_HOST is required when EMAIL_DRY_RUN=false.")

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=30) as smtp:
        if settings.email_use_tls:
            smtp.starttls()
        if settings.email_smtp_user:
            smtp.login(settings.email_smtp_user, settings.email_smtp_password or "")
        smtp.send_message(message)

    return {
        "sent": True,
        "dry_run": False,
        "recipient": resolved_recipient,
        "subject": subject,
    }


def _build_message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return message


def _email_body(job: JobPosting, application: GeneratedApplication) -> str:
    return (
        f"{application.cover_letter_md}\n\n"
        "---\n"
        "Quelle der Stelle:\n"
        f"{job.url}\n\n"
        "Diese E-Mail wurde vom Job Application Agent vorbereitet."
    )
