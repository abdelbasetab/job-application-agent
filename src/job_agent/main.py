"""CLI entrypoint — `python -m job_agent.main run-pipeline` or `job-agent run-pipeline`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from job_agent.memory.store import Store
from job_agent.pipeline import run_pipeline
from job_agent.schemas import UserProfile
from job_agent.schemas.profile import Education, Experience, Preferences
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger

app = typer.Typer(help="Job Application Agent — Sprint 1 tracer bullet")
console = Console()
log = get_logger(__name__)


def _demo_profile() -> UserProfile:
    """A baked-in profile so the tracer bullet has something realistic to chew on.

    Sprint 2 replaces this with a loader for `data/profile/profile.yaml`.
    """
    return UserProfile(
        name="Abdelbaset Abidi",
        headline="AI Engineering Student @ Westfälische Hochschule",
        email="adessadess1990@gmail.com",
        location="Gelsenkirchen, DE",
        languages={"de": "C1", "en": "C1", "ar": "Native"},
        skills=[
            "python",
            "sql",
            "git",
            "llms",
            "rag",
            "machine learning",
            "chromadb",
        ],
        experience=[
            Experience(
                role="AI Engineering Coursework",
                company="Westfälische Hochschule",
                start="2025-10",
                summary="Building a multi-agent job-application system with CrewAI.",
                skills_used=["python", "llms", "rag"],
            ),
        ],
        education=[
            Education(
                degree="B.Sc.",
                institution="Westfälische Hochschule",
                field="Computer Science / AI",
                start="2023-10",
            ),
        ],
        preferences=Preferences(
            locations=["Gelsenkirchen", "Essen", "Dortmund", "Remote"],
            remote_ok=True,
            employment_types=["working-student", "internship"],
        ),
    )


@app.command("run-pipeline")
def run_pipeline_cmd(
    query: str = typer.Option(
        None, help="Optional free-text search hint passed to Scout."
    ),
    threshold: float = typer.Option(0.5, help="Min match score to draft an application."),
    limit: int = typer.Option(5, help="Max jobs Scout should return."),
) -> None:
    """Run the Scout → Matcher → Writer → Tracker pipeline end-to-end."""
    profile = _demo_profile()
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.sqlite_path)

    result = run_pipeline(
        profile=profile,
        store=store,
        query=query,
        match_threshold=threshold,
        job_limit=limit,
    )

    # ----- pretty summary -----
    table = Table(title="Pipeline summary", show_lines=True)
    table.add_column("Job")
    table.add_column("Company")
    table.add_column("Score", justify="right")
    table.add_column("Status")
    by_id = {j.id: j for j in result.jobs}
    statuses = {s.job_id: s for s in result.statuses}

    for m in result.matches:
        job = by_id[m.job_id]
        status = statuses.get(m.job_id)
        table.add_row(
            job.title[:40],
            job.company,
            f"{m.score:.2f}",
            status.status if status else "—",
        )

    console.print(table)
    console.print(
        f"\n[bold green]OK[/bold green] State written to [cyan]{settings.sqlite_path}[/cyan]"
    )

    store.close()


@app.command("show-applications")
def show_applications_cmd() -> None:
    """Print every drafted application currently in the SQLite store."""
    store = Store(settings.sqlite_path)
    for status in store.all_status():
        app_doc = store.get_application(status.job_id)
        console.rule(f"[bold]{status.job_id}[/bold] — {status.status}")
        if app_doc:
            console.print(app_doc.cover_letter_md)
    store.close()


if __name__ == "__main__":
    app()
