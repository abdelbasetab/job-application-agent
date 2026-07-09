from __future__ import annotations

from job_agent.schemas import JobPosting
from job_agent.tools.recipient_extraction import (
    best_recipient,
    recipient_payload,
    recipient_suggestions,
)


def _job(description: str, requirements_raw: str = "") -> JobPosting:
    return JobPosting(
        id="recipient-1",
        source="manual",
        source_id="recipient-1",
        url="https://example.com/jobs/1",
        title="Werkstudent Software",
        company="Example GmbH",
        location="Berlin",
        description=description,
        requirements_raw=requirements_raw,
        requirements=["python"],
    )


def test_recipient_extraction_prefers_recruiting_address_over_noreply() -> None:
    job = _job(
        "Automatische Benachrichtigung: no-reply@example.de. "
        "Bitte senden Sie Ihre Bewerbung an recruiting@example.de."
    )

    assert best_recipient(job) == "recruiting@example.de"
    suggestions = recipient_suggestions(job)
    assert suggestions[0].email == "recruiting@example.de"
    assert suggestions[0].score > 60


def test_recipient_payload_exposes_best_and_suggestions() -> None:
    payload = recipient_payload(
        _job(
            "Kontakt: jobs@example.de",
            requirements_raw="Ihre Bewerbung richten Sie an karriere@example.de.",
        )
    )

    assert payload["contact_email"] == "karriere@example.de"
    assert payload["recipient_confidence"]
    assert len(payload["recipient_suggestions"]) == 2


def test_recipient_extraction_does_not_autofill_low_confidence_only() -> None:
    job = _job("Impressum und Datenschutz: privacy@example.de")

    assert best_recipient(job) == ""
    assert recipient_payload(job)["contact_email"] == ""
