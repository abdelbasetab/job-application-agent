"""CLI entrypoint for the Job Application Agent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from job_agent.agents.demo_scout import run_demo_scout
from job_agent.demo_profile import demo_profile
from job_agent.memory.store import Store
from job_agent.pipeline import run_pipeline
from job_agent.schemas import JobPosting, UserProfile
from job_agent.utils.config import settings
from job_agent.utils.logging import get_logger
from job_agent.web import run_web_server

app = typer.Typer(help="Job Application Agent")
console = Console()
log = get_logger(__name__)


def _resolve_profile(cv: str | None, profile_path: str | None) -> UserProfile:
    """Pick the candidate profile: CV (LLM) > YAML > baked-in demo profile."""
    if cv:
        from job_agent.agents.profiler import profile_from_cv_file

        log.info("[cli] reading CV and extracting profile: %s", cv)
        return profile_from_cv_file(cv)
    if profile_path:
        from job_agent.utils.cv import load_profile_yaml

        log.info("[cli] loading profile YAML: %s", profile_path)
        return load_profile_yaml(profile_path)
    return demo_profile()


def _direct_scout_runner(
    profile: UserProfile, query: str | None, limit: int
) -> list[JobPosting]:
    """Live Scout without CrewAI — calls the boards directly (no LLM tool-calling)."""
    from job_agent.tools.job_search import search_all

    hint = query or " ".join(profile.skills[:3])
    extra = [skill for skill in profile.skills[:3] if skill]
    postings = search_all(
        query=hint,
        location="Germany",
        limit=max(limit, 5),
        extra_queries=extra,
        adzuna_pages=2,
        enrich=True,
    )
    return postings[:limit]


@app.command("run-pipeline")
def run_pipeline_cmd(
    query: str = typer.Option(None, help="Optional free-text search hint passed to Scout."),
    threshold: float = typer.Option(0.5, help="Min match score to draft an application."),
    limit: int = typer.Option(5, help="Max jobs Scout should return."),
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Use stable offline demo jobs instead of live APIs/LLM.",
    ),
    db_path: str | None = typer.Option(
        None,
        "--db-path",
        help="Override SQLite path. Useful for a separate demo database.",
    ),
    reset_demo_db: bool = typer.Option(
        False,
        "--reset-demo-db",
        help="Delete the selected demo DB before running. Only allowed with --demo.",
    ),
    llm_agents: bool = typer.Option(
        False,
        "--llm-agents",
        help="Use Sprint-3 LLM matcher and writer with deterministic fallback.",
    ),
    chroma: bool = typer.Option(
        False,
        "--chroma",
        help="Index the profile in ChromaDB and pass retrieved context to agents.",
    ),
    cv: str | None = typer.Option(
        None,
        "--cv",
        help="Path to your CV (PDF/DOCX/TXT/MD). The LLM extracts your profile from it.",
    ),
    profile_path: str | None = typer.Option(
        None,
        "--profile",
        help="Path to a UserProfile YAML — an offline alternative to --cv.",
    ),
    direct: bool = typer.Option(
        False,
        "--direct",
        help="Live Scout without the CrewAI agent: query job boards directly "
        "(use when your gateway can't do tool-calling).",
    ),
) -> None:
    """Run the Scout -> Matcher -> Writer -> Tracker pipeline end-to-end."""
    profile = _resolve_profile(cv, profile_path)
    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    if reset_demo_db and not demo:
        raise typer.BadParameter("--reset-demo-db can only be used together with --demo")
    if reset_demo_db:
        demo_db = Path(selected_db_path)
        if demo_db.exists():
            demo_db.unlink()

    Path(selected_db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store(selected_db_path)

    scout_runner: Callable[[UserProfile, str | None, int], list[JobPosting]] = run_demo_scout
    if not demo:
        if direct:
            scout_runner = _direct_scout_runner
        else:
            from job_agent.agents.scout import run_scout

            scout_runner = run_scout

    result = run_pipeline(
        profile=profile,
        store=store,
        query=query,
        match_threshold=threshold,
        job_limit=limit,
        scout_runner=scout_runner,
        use_llm_agents=llm_agents,
        use_chroma=chroma,
    )

    table = Table(title="Pipeline summary", show_lines=True)
    table.add_column("Job")
    table.add_column("Company")
    table.add_column("Score", justify="right")
    table.add_column("Status")
    by_id = {j.id: j for j in result.jobs}
    statuses = {s.job_id: s for s in store.all_status()}

    for match in result.matches:
        job = by_id[match.job_id]
        status = statuses.get(match.job_id)
        table.add_row(
            job.title[:40],
            job.company,
            f"{match.score:.2f}",
            status.status if status else "-",
        )

    console.print(table)
    console.print(f"\n[bold green]OK[/bold green] State written to [cyan]{selected_db_path}[/cyan]")

    store.close()


@app.command("show-applications")
def show_applications_cmd(
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Read from the offline demo database.",
    ),
    db_path: str | None = typer.Option(
        None,
        "--db-path",
        help="Override SQLite path.",
    ),
) -> None:
    """Print every drafted application currently in the SQLite store."""
    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    store = Store(selected_db_path)
    for status in store.all_status():
        app_doc = store.get_application(status.job_id)
        console.rule(f"[bold]{status.job_id}[/bold] - {status.status}")
        if app_doc:
            console.print(app_doc.cover_letter_md)
    store.close()


@app.command("read-cv")
def read_cv_cmd(
    cv: str = typer.Option(..., "--cv", help="Path to the CV file (PDF/DOCX/TXT/MD)."),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Write the extracted profile as YAML to this path (e.g. data/profile/profile.yaml).",
    ),
) -> None:
    """Read a CV with the LLM and show the structured profile it extracted."""
    from job_agent.agents.profiler import profile_from_cv_file
    from job_agent.utils.cv import profile_to_yaml

    profile = profile_from_cv_file(cv)

    table = Table(title=f"Profile extracted from {Path(cv).name}", show_lines=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("name", profile.name)
    table.add_row("headline", profile.headline)
    table.add_row("location", profile.location)
    table.add_row("email", profile.email or "-")
    table.add_row("languages", ", ".join(f"{k}: {v}" for k, v in profile.languages.items()) or "-")
    table.add_row("skills", ", ".join(profile.skills) or "-")
    table.add_row("experience", f"{len(profile.experience)} entries")
    table.add_row("education", f"{len(profile.education)} entries")
    console.print(table)

    yaml_text = profile_to_yaml(profile)
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml_text, encoding="utf-8")
        console.print(f"[bold green]Saved profile YAML →[/bold green] [cyan]{out}[/cyan]")
        console.print("Reuse it offline with: [cyan]run-pipeline --profile " f"{out}[/cyan]")
    else:
        console.rule("profile.yaml")
        console.print(yaml_text)


@app.command("web")
def web_cmd(
    host: str = typer.Option(
        settings.web_host, "--host", help="Host for the web UI (env: WEB_HOST)."
    ),
    port: int = typer.Option(
        settings.web_port, "--port", help="Port for the web UI (env: WEB_PORT)."
    ),
    open_browser: bool = typer.Option(
        False,
        "--open",
        help="Open the web UI in the default browser.",
    ),
) -> None:
    """Start the multi-user browser UI."""
    run_web_server(host=host, port=port, open_browser=open_browser)


if __name__ == "__main__":
    app()
