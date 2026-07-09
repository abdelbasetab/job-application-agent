"""Offline tests for the URL inbox and the paste-a-JD auto-pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.memory.store import Store
from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Preferences
from job_agent.tools.inbox import (
    add_item,
    evaluate_pasted_job,
    inbox_path,
    load_inbox,
    posting_from_text,
    remove_item,
    update_status,
)

_JD_TEXT = """RuhrTech GmbH sucht Verstärkung im KI-Team in Gelsenkirchen.

Deine Aufgaben:
- Du baust LLM-Prototypen und Auswertungen.

Dein Profil:
- Python
- SQL
- Git

Wir bieten flexible Arbeitszeiten neben dem Studium und ein nettes Team.
Sehr gute Deutschkenntnisse sind erwünscht. Gehalt: 20.000 - 24.000 EUR.
"""


def _profile() -> UserProfile:
    return UserProfile(
        name="Test Candidate",
        headline="AI Engineering Student",
        email="test@example.com",
        location="Gelsenkirchen",
        languages={"de": "C1", "en": "B2"},
        skills=["python", "sql", "rag"],
        preferences=Preferences(locations=["Gelsenkirchen", "Essen"]),
    )


def test_inbox_add_list_update_remove(tmp_path: Path) -> None:
    path = inbox_path(tmp_path)

    item = add_item(path, "https://example.de/jobs/1", note="sieht gut aus")
    assert item["status"] == "neu"
    assert load_inbox(path)[0]["url"] == "https://example.de/jobs/1"

    # Re-adding the same URL is idempotent (refreshes the note, no duplicate).
    add_item(path, "https://example.de/jobs/1", note="zweiter blick")
    items = load_inbox(path)
    assert len(items) == 1
    assert items[0]["note"] == "zweiter blick"

    updated = update_status(path, item["id"], "verworfen")
    assert updated["status"] == "verworfen"

    assert remove_item(path, item["id"]) is True
    assert load_inbox(path) == []
    assert remove_item(path, item["id"]) is False


def test_inbox_rejects_non_urls_and_bad_status(tmp_path: Path) -> None:
    path = inbox_path(tmp_path)
    with pytest.raises(ValueError, match="URL"):
        add_item(path, "kein-link")
    item = add_item(path, "https://example.de/jobs/2")
    with pytest.raises(ValueError, match="Status"):
        update_status(path, item["id"], "erledigt")
    with pytest.raises(ValueError, match="nicht gefunden"):
        update_status(path, "unbekannt", "neu")


def test_posting_from_text_extracts_requirements_and_salary() -> None:
    posting = posting_from_text(
        title="Werkstudent KI",
        company="RuhrTech GmbH",
        location="Gelsenkirchen",
        description=_JD_TEXT,
        url="https://example.de/jobs/42",
    )

    assert posting.source == "manual"
    assert posting.requirements == ["python", "sql", "git"]
    assert posting.salary_range == (20000, 24000)
    assert str(posting.url) == "https://example.de/jobs/42"


def test_posting_from_text_keyword_fallback_and_short_text() -> None:
    posting = posting_from_text(
        title="Data Job",
        description=(
            "Wir suchen Unterstützung für unser Team. Erfahrung mit Python und SQL "
            "sowie Docker ist hilfreich. Es erwartet dich ein modernes Umfeld."
        ),
    )
    assert "python" in posting.requirements
    assert "sql" in posting.requirements

    with pytest.raises(ValueError, match="zu kurz"):
        posting_from_text(title="X", description="zu wenig")


def test_evaluate_pasted_job_runs_single_job_pipeline(tmp_path: Path) -> None:
    store = Store(tmp_path / "inbox.db")
    posting = posting_from_text(
        title="Werkstudent KI",
        company="RuhrTech GmbH",
        location="Gelsenkirchen",
        description=_JD_TEXT,
    )

    match, application = evaluate_pasted_job(
        store, _profile(), posting, threshold=0.5, use_llm=False
    )

    assert match.job_id == posting.id
    assert match.score >= 0.8, "voller Skill-Match + Standort muss hoch scoren"
    assert application is not None
    assert store.get_application(posting.id) is not None
    assert store.get_status(posting.id) is not None

    # Second evaluation must not create a duplicate draft (dedup guard).
    match2, application2 = evaluate_pasted_job(
        store, _profile(), posting, threshold=0.5, use_llm=False
    )
    assert match2.score == match.score
    assert application2 is None
    store.close()
