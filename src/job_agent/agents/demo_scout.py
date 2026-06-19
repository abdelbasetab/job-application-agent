"""Deterministic Scout data for offline demos.

The live Scout depends on external APIs and an LLM. This module keeps the
Sprint review demo stable while preserving the same JobPosting contract.
"""

from __future__ import annotations

from datetime import date

from job_agent.schemas import JobPosting, UserProfile
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


_DEMO_JOBS = [
    JobPosting(
        id="demo-adzuna-werkstudent-ki-gelsenkirchen",
        source="adzuna",
        source_id="demo-adzuna-001",
        url="https://www.adzuna.de/jobs/details/demo-adzuna-001",  # type: ignore[arg-type]
        title="Werkstudent KI & LLM Automation",
        company="Ruhr AI Solutions GmbH",
        location="Gelsenkirchen",
        posted_at=date(2026, 6, 3),
        description=(
            "Unterstuetzung beim Aufbau von LLM-Workflows, RAG-Prototypen "
            "und internen Automatisierungen mit Python."
        ),
        requirements_raw="Python, Git, LLMs, RAG",
        requirements=["python", "git", "llms", "rag"],
        nice_to_have=["chromadb", "sql"],
        employment_type="working-student",
        remote=True,
    ),
    JobPosting(
        id="demo-ba-data-analytics-essen",
        source="ba-jobsuche",
        source_id="demo-ba-001",
        url="https://www.arbeitsagentur.de/jobsuche/jobdetail/demo-ba-001",  # type: ignore[arg-type]
        title="Werkstudent Data Analytics",
        company="Emscher Data Services AG",
        location="Essen",
        posted_at=date(2026, 6, 2),
        description=(
            "Analyse von Reporting-Daten, Aufbau kleiner ETL-Skripte und "
            "Dokumentation von SQL-Auswertungen."
        ),
        requirements_raw="SQL, Python, Git",
        requirements=["sql", "python", "git"],
        nice_to_have=["machine learning"],
        employment_type="working-student",
        remote=False,
    ),
    JobPosting(
        id="demo-adzuna-ml-intern-dortmund",
        source="adzuna",
        source_id="demo-adzuna-002",
        url="https://www.adzuna.de/jobs/details/demo-adzuna-002",  # type: ignore[arg-type]
        title="Praktikum Machine Learning Engineering",
        company="Dortmund ML Lab GmbH",
        location="Dortmund",
        posted_at=date(2026, 6, 1),
        description=(
            "Mitarbeit an Klassifikationsmodellen, Datenaufbereitung und "
            "Evaluation kleiner Machine-Learning-Prototypen."
        ),
        requirements_raw="Python, Machine Learning, SQL",
        requirements=["python", "machine learning", "sql"],
        nice_to_have=["llms"],
        employment_type="internship",
        remote=True,
    ),
    JobPosting(
        id="demo-ba-backend-bochum",
        source="ba-jobsuche",
        source_id="demo-ba-002",
        url="https://www.arbeitsagentur.de/jobsuche/jobdetail/demo-ba-002",  # type: ignore[arg-type]
        title="Junior Backend Student Assistant",
        company="Bochum Cloud Factory GmbH",
        location="Bochum",
        posted_at=date(2026, 5, 31),
        description=(
            "Unterstuetzung im Backend-Team bei API-Entwicklung, Tests und "
            "Versionsverwaltung."
        ),
        requirements_raw="Python, Git, REST APIs",
        requirements=["python", "git", "rest apis"],
        nice_to_have=["sql"],
        employment_type="working-student",
        remote=False,
    ),
    JobPosting(
        id="demo-ba-support-gelsenkirchen",
        source="ba-jobsuche",
        source_id="demo-ba-003",
        url="https://www.arbeitsagentur.de/jobsuche/jobdetail/demo-ba-003",  # type: ignore[arg-type]
        title="IT Support Werkstudent",
        company="Campus IT Service GmbH",
        location="Gelsenkirchen",
        posted_at=date(2026, 5, 30),
        description=(
            "Support fuer interne IT-Prozesse, einfache Automatisierungen und "
            "Dokumentation."
        ),
        requirements_raw="Windows, Support, Dokumentation",
        requirements=["windows", "support", "documentation"],
        nice_to_have=["python"],
        employment_type="working-student",
        remote=False,
    ),
]


def run_demo_scout(
    profile: UserProfile, query: str | None = None, limit: int = 5
) -> list[JobPosting]:
    """Return stable demo postings without network, credentials, or LLM calls."""
    log.info(
        "[demo-scout] returning offline demo jobs profile=%s query=%r limit=%d",
        profile.name,
        query,
        limit,
    )
    return _DEMO_JOBS[:limit]
