"""CLI entrypoint for the Job Application Agent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from job_agent.evaluation import EvalReport

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


def _resolve_profile(
    cv: str | None,
    profile_path: str | None,
    *,
    allow_demo: bool = False,
    db_path: str | None = None,
) -> UserProfile:
    """Pick an explicit, persisted, or consciously selected demo profile."""
    if cv:
        from job_agent.agents.profiler import profile_from_cv_file

        log.info("[cli] reading CV and extracting profile: %s", cv)
        return profile_from_cv_file(cv)
    if profile_path:
        from job_agent.utils.cv import load_profile_yaml

        log.info("[cli] loading profile YAML: %s", profile_path)
        return load_profile_yaml(profile_path)
    if db_path and Path(db_path).is_file():
        store = Store(db_path)
        try:
            active = store.get_active_profile()
        finally:
            store.close()
        if active is not None:
            log.info("[cli] reusing persisted active profile from %s", db_path)
            return active[0]
    if allow_demo:
        return demo_profile()
    raise typer.BadParameter(
        "Kein Profil vorhanden. --cv oder --profile angeben, oder --demo bewusst verwenden."
    )


def _direct_scout_runner(
    profile: UserProfile, query: str | None, limit: int
) -> list[JobPosting]:
    """Live Scout that calls the boards directly without generative source data."""
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
        help="Use the LLM matcher and writer with deterministic fallback.",
    ),
    chroma: bool = typer.Option(
        False,
        "--profile-memory",
        "--chroma",
        help="Index the profile locally and pass retrieved context to agents.",
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
        help="Compatibility flag: the live Scout always queries job boards directly.",
    ),
) -> None:
    """Run the Scout -> Matcher -> Writer -> Tracker pipeline end-to-end."""
    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    if reset_demo_db and not demo:
        raise typer.BadParameter("--reset-demo-db can only be used together with --demo")
    profile = _resolve_profile(
        cv,
        profile_path,
        allow_demo=demo,
        db_path=selected_db_path,
    )

    Path(selected_db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store(selected_db_path)
    try:
        if reset_demo_db:
            store.clear_pipeline_results()

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
        statuses = {s.job_id: s for s in store.all_status()}
    finally:
        store.close()

    table = Table(title="Pipeline summary", show_lines=True)
    table.add_column("Job")
    table.add_column("Company")
    table.add_column("Score", justify="right")
    table.add_column("Status")
    by_id = {j.id: j for j in result.jobs}

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


@app.command("doctor")
def doctor_cmd() -> None:
    """Diagnose local readiness: data dirs, LLM/email config, optional tools."""
    from job_agent.utils.doctor import run_doctor, worst_status

    icons = {"ok": "[green]OK[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]"}
    checks = run_doctor()

    table = Table(title="job-agent doctor", show_lines=False)
    table.add_column("", justify="center")
    table.add_column("Check", style="bold")
    table.add_column("Detail")
    for check in checks:
        detail = check.detail
        if check.fix and check.status != "ok":
            detail += f"\n[dim]→ {check.fix}[/dim]"
        table.add_row(icons[check.status], check.name, detail)
    console.print(table)

    overall = worst_status(checks)
    fails = sum(1 for c in checks if c.status == "fail")
    warns = sum(1 for c in checks if c.status == "warn")
    if overall == "fail":
        console.print(f"\n[bold red]{fails} FAIL[/bold red], {warns} WARN — bitte die FAIL-Punkte beheben.")
        raise typer.Exit(code=1)
    if overall == "warn":
        console.print(f"\n[bold yellow]{warns} WARN[/bold yellow] — Kernbetrieb ok, optionale Features eingeschränkt.")
        return
    console.print("\n[bold green]Alles OK[/bold green] — lokal einsatzbereit.")


@app.command("eval")
def eval_cmd(
    threshold: float = typer.Option(0.6, help="Apply-Schwelle für Precision/Recall."),
    llm: bool = typer.Option(
        False, "--llm", help="Zusätzlich den LLM-Matcher messen (braucht Provider/Key)."
    ),
    chroma: bool = typer.Option(
        False,
        "--profile-memory",
        "--chroma",
        help="RAG-Ablation: LLM-Matcher zusätzlich MIT Profil-Kontext messen (nur mit --llm).",
    ),
    json_out: str | None = typer.Option(
        None, "--json-out", help="Report zusätzlich als JSON speichern (z.B. data/eval_report.json)."
    ),
) -> None:
    """Matcher & Writer gegen das Golden-Set messen (offline, deterministisch)."""
    import json as _json

    from job_agent.evaluation import evaluate

    profile = demo_profile()
    reports: dict[str, EvalReport] = {}

    reports["deterministic"] = evaluate(profile, threshold=threshold, use_llm=False)
    _print_eval_report("Deterministischer Matcher (Tier 1+2)", reports["deterministic"])

    if llm:
        reports["llm"] = evaluate(profile, threshold=threshold, use_llm=True)
        _print_eval_report("LLM-Matcher (Tier 3)", reports["llm"])
        if chroma:
            from job_agent.memory.profile_index import ProfileVectorStore

            index = ProfileVectorStore()
            index.upsert_profile(profile)
            context = index.query(" ".join(profile.skills[:5]), top_k=3)
            reports["llm_rag"] = evaluate(
                profile, threshold=threshold, use_llm=True, profile_context=context
            )
            _print_eval_report(
                f"LLM-Matcher + RAG-Kontext ({len(context)} Snippets)", reports["llm_rag"]
            )

    if json_out:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: report.to_dict() for name, report in reports.items()}
        out_path.write_text(
            _json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        console.print(f"\n[bold green]Report gespeichert →[/bold green] [cyan]{json_out}[/cyan]")


def _print_eval_report(title: str, report: EvalReport) -> None:
    """Render one EvalReport as rich tables (metrics + misses)."""
    table = Table(title=f"Eval: {title} — {len(report.results)} Golden-Cases", show_lines=False)
    table.add_column("Metrik", style="bold")
    table.add_column("Wert", justify="right")
    table.add_row("Accuracy (Empfehlung exakt)", f"{report.accuracy:.1%}")
    table.add_row("Within-1 (max. 1 Stufe daneben)", f"{report.within_one:.1%}")
    table.add_row("Cohen's Kappa", f"{report.kappa:.2f}")
    table.add_row("Spearman (Score vs. Label)", f"{report.spearman:.2f}")
    table.add_row(f"Apply-Precision @ {report.threshold:.2f}", f"{report.apply_precision:.1%}")
    table.add_row(f"Apply-Recall @ {report.threshold:.2f}", f"{report.apply_recall:.1%}")
    table.add_row("Writer-Quality-Pass-Rate", f"{report.writer_pass_rate:.1%}")
    if report.llm_comparison:
        for key, value in report.llm_comparison.items():
            table.add_row(f"LLM vs. deterministisch: {key}", f"{value}")
    if report.telemetry_summary and report.telemetry_summary.get("calls"):
        t = report.telemetry_summary
        table.add_row(
            "LLM-Telemetrie",
            f"{t['calls']:.0f} Calls, {t.get('retries', 0):.0f} Retries, "
            f"Ø {t.get('avg_latency_s', 0):.2f}s",
        )
    console.print(table)

    if report.misses:
        misses = Table(title="Abweichungen (erwartet ≠ vorhergesagt)", show_lines=False)
        misses.add_column("Job")
        misses.add_column("Erwartet")
        misses.add_column("Vorhergesagt")
        misses.add_column("Score", justify="right")
        misses.add_column("Notiz")
        for miss in report.misses:
            misses.add_row(
                f"{miss.case.job.title[:34]}",
                miss.case.expected,
                miss.match.recommendation,
                f"{miss.match.score:.2f}",
                miss.case.note[:60],
            )
        console.print(misses)


@app.command("review-cv")
def review_cv_cmd(
    cv: str = typer.Option(..., "--cv", help="Pfad zum Lebenslauf (PDF/DOCX/TXT/MD)."),
    llm: bool = typer.Option(
        False, "--llm", help="Zusätzlich einen LLM-Feedback-Absatz einholen (braucht Provider)."
    ),
) -> None:
    """Lebenslauf bewerten: erklärbare 1-5-Rubrik + konkrete Tipps (offline)."""
    from job_agent.agents.cv_reviewer import run_cv_reviewer
    from job_agent.utils.cv import extract_cv_text

    text = extract_cv_text(cv)
    assessment = run_cv_reviewer(text, use_llm=llm)

    table = Table(
        title=f"CV-Check: {Path(cv).name} — Gesamt {assessment.overall_score:.1f}/5",
        show_lines=False,
    )
    table.add_column("Dimension", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Gewicht", justify="right")
    table.add_column("Evidenz")
    for component in assessment.components:
        table.add_row(
            component.label,
            f"{component.score}/5",
            f"{component.weight}%",
            component.evidence,
        )
    console.print(table)
    console.print(f"\n[bold]{assessment.summary}[/bold]")
    if assessment.tips:
        console.print("\n[bold]Konkrete Tipps:[/bold]")
        for index, tip in enumerate(assessment.tips, start=1):
            console.print(f"  {index}. {tip}")
    if assessment.llm_feedback:
        console.rule("LLM-Feedback")
        console.print(assessment.llm_feedback)


@app.command("follow-ups")
def follow_ups_cmd(
    days: int = typer.Option(7, help="Tage ohne Aktivität, bis eine Bewerbung fällig ist."),
    demo: bool = typer.Option(False, "--demo", help="Offline-Demo-Datenbank verwenden."),
    db_path: str | None = typer.Option(None, "--db-path", help="SQLite-Pfad überschreiben."),
    mark: str | None = typer.Option(
        None, "--mark", help="Follow-up für diese Job-ID als erledigt vermerken."
    ),
) -> None:
    """Fällige Follow-ups zeigen: 'submitted' ohne Aktivität seit N Tagen."""
    from job_agent.agents.tracker import due_follow_ups, record_follow_up

    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    store = Store(selected_db_path)
    try:
        if mark:
            record = record_follow_up(store, mark)
            console.print(
                f"[bold green]Follow-up vermerkt[/bold green] für [cyan]{mark}[/cyan] "
                f"(Status bleibt '{record.status}')."
            )
        items = due_follow_ups(store, days=days, candidate_name=demo_profile().name)
    finally:
        store.close()

    if not items:
        console.print(
            f"[bold green]Keine fälligen Follow-ups[/bold green] — nichts ist älter als "
            f"{days} Tage ohne Aktivität."
        )
        return

    table = Table(title=f"Fällige Follow-ups (> {days} Tage ohne Aktivität)", show_lines=False)
    table.add_column("Job", style="bold")
    table.add_column("Unternehmen")
    table.add_column("Beworben am")
    table.add_column("Inaktiv seit", justify="right")
    table.add_column("Überfällig", justify="right")
    for item in items:
        table.add_row(
            item.title[:40],
            item.company[:28],
            item.submitted_at.strftime("%d.%m.%Y") if item.submitted_at else "-",
            f"{item.days_since_activity} Tagen",
            f"{item.days_overdue} Tage",
        )
    console.print(table)
    console.rule("Vorschlag für das älteste Follow-up")
    console.print(items[0].suggested_email_md)
    console.print(
        "\n[dim]Vermerken mit: job-agent follow-ups --mark <job_id>"
        + (" --demo" if demo else "")
        + "[/dim]"
    )


@app.command("inbox")
def inbox_cmd(
    add: str | None = typer.Option(None, "--add", help="URL in die Inbox legen."),
    note: str = typer.Option("", "--note", help="Optionale Notiz zum Eintrag."),
    remove: str | None = typer.Option(None, "--remove", help="Eintrag (ID) entfernen."),
    data_dir: str = typer.Option("./data", "--data-dir", help="Datenverzeichnis der Inbox."),
) -> None:
    """URL-Inbox: Stellen-Links merken und später gesammelt bewerten."""
    from job_agent.tools.inbox import add_item, inbox_path, load_inbox, remove_item

    path = inbox_path(data_dir)
    if add:
        item = add_item(path, add, note=note)
        console.print(f"[bold green]Gemerkt[/bold green] [{item['id']}] {item['url']}")
    if remove:
        if remove_item(path, remove):
            console.print(f"[bold green]Entfernt[/bold green] {remove}")
        else:
            console.print(f"[yellow]Eintrag {remove} nicht gefunden.[/yellow]")

    items = load_inbox(path)
    if not items:
        console.print("[dim]Inbox ist leer — mit --add <URL> befüllen.[/dim]")
        return
    table = Table(title=f"URL-Inbox ({len(items)} Einträge)", show_lines=False)
    table.add_column("ID", style="bold")
    table.add_column("Status")
    table.add_column("URL")
    table.add_column("Notiz")
    for item in items:
        table.add_row(item["id"], item["status"], item["url"][:60], (item.get("note") or "")[:40])
    console.print(table)


@app.command("evaluate-jd")
def evaluate_jd_cmd(
    file: str = typer.Option(..., "--file", help="Textdatei mit der kompletten Stellenanzeige."),
    title: str = typer.Option(..., "--title", help="Jobtitel der Anzeige."),
    company: str = typer.Option("", "--company", help="Unternehmen."),
    location: str = typer.Option("", "--location", help="Standort."),
    url: str = typer.Option("", "--url", help="Original-URL der Anzeige."),
    threshold: float = typer.Option(0.5, help="Ab diesem Score wird ein Anschreiben entworfen."),
    llm: bool = typer.Option(False, "--llm", help="LLM-Matcher/-Writer verwenden."),
    demo: bool = typer.Option(False, "--demo", help="In die Demo-Datenbank schreiben."),
    db_path: str | None = typer.Option(None, "--db-path", help="SQLite-Pfad überschreiben."),
    cv: str | None = typer.Option(None, "--cv", help="CV für das Profil."),
    profile_path: str | None = typer.Option(None, "--profile", help="Profil-YAML (offline)."),
) -> None:
    """Eine eingefügte Stellenanzeige sofort bewerten (Ein-Job-Auto-Pipeline)."""
    from job_agent.tools.inbox import evaluate_pasted_job, posting_from_text

    text = Path(file).read_text(encoding="utf-8", errors="replace")
    posting = posting_from_text(
        title=title, company=company, location=location, description=text, url=url
    )
    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    profile = _resolve_profile(
        cv,
        profile_path,
        allow_demo=demo,
        db_path=selected_db_path,
    )
    Path(selected_db_path).parent.mkdir(parents=True, exist_ok=True)
    store = Store(selected_db_path)
    try:
        match, application = evaluate_pasted_job(
            store, profile, posting, threshold=threshold, use_llm=llm
        )
    finally:
        store.close()

    table = Table(title=f"Bewertung: {posting.title} — {posting.company}", show_lines=False)
    table.add_column("Dimension", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Evidenz")
    for component in match.score_components:
        table.add_row(component.label, f"{component.score}/5", component.evidence)
    console.print(table)
    console.print(
        f"\n[bold]Score {match.score:.2f}[/bold] · Empfehlung: {match.recommendation} · "
        f"Risiko: {match.risk_level}"
    )
    console.print(match.score_summary or match.rationale)
    if application is not None:
        console.rule("Anschreiben-Entwurf")
        console.print(application.cover_letter_md)
    else:
        console.print(
            f"\n[dim]Score unter {threshold:.2f} oder bereits beworben — kein Entwurf erstellt.[/dim]"
        )


@app.command("patterns")
def patterns_cmd(
    demo: bool = typer.Option(False, "--demo", help="Offline-Demo-Datenbank auswerten."),
    db_path: str | None = typer.Option(None, "--db-path", help="SQLite-Pfad überschreiben."),
) -> None:
    """Muster im Bewerbungs-Tracker: Funnel, Quoten, Wartezeiten, Auffälligkeiten."""
    from job_agent.tools.patterns import analyze_patterns

    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    store = Store(selected_db_path)
    try:
        report = analyze_patterns(store)
    finally:
        store.close()

    funnel = Table(title=f"Bewerbungs-Funnel ({report['total']} Einträge)", show_lines=False)
    funnel.add_column("Phase", style="bold")
    funnel.add_column("Anzahl", justify="right")
    labels = {
        "draft": "Entwurf",
        "submitted": "Eingereicht",
        "interview": "Interview",
        "offer": "Angebot",
        "rejected": "Absage",
        "withdrawn": "Zurückgezogen",
    }
    for stage, count in report["funnel"].items():
        funnel.add_row(labels.get(stage, stage), str(count))
    console.print(funnel)

    stats = Table(title="Quoten & Zeiten", show_lines=False)
    stats.add_column("Metrik", style="bold")
    stats.add_column("Wert", justify="right")
    stats.add_row("Eingereicht gesamt", str(report["sent_total"]))
    stats.add_row(
        "Antwortquote",
        f"{report['response_rate']:.0%}" if report["response_rate"] is not None else "-",
    )
    stats.add_row(
        "Interviewquote",
        f"{report['interview_rate']:.0%}" if report["interview_rate"] is not None else "-",
    )
    stats.add_row(
        "Ø Tage bis Antwort",
        f"{report['avg_days_to_response']:.0f}"
        if report["avg_days_to_response"] is not None
        else "-",
    )
    console.print(stats)

    if report["stale_submitted"]:
        console.print(
            f"\n[bold yellow]{len(report['stale_submitted'])} Bewerbung(en) ohne Antwort seit "
            f"≥ {report['stale_after_days']} Tagen[/bold yellow]"
        )
        for item in report["stale_submitted"][:5]:
            console.print(f"  · {item['title']} ({item['company']}) — {item['days_waiting']} Tage")

    console.print("\n[bold]Erkenntnisse:[/bold]")
    for insight in report["insights"]:
        console.print(f"  • {insight}")


@app.command("interview-prep")
def interview_prep_cmd(
    job_id: str = typer.Option(..., "--job-id", help="Job-ID aus Pipeline/Tracker."),
    llm: bool = typer.Option(False, "--llm", help="Zusätzlich anzeigenspezifische LLM-Fragen."),
    demo: bool = typer.Option(False, "--demo", help="Offline-Demo-Datenbank verwenden."),
    db_path: str | None = typer.Option(None, "--db-path", help="SQLite-Pfad überschreiben."),
    cv: str | None = typer.Option(None, "--cv", help="CV für das Profil."),
    profile_path: str | None = typer.Option(None, "--profile", help="Profil-YAML (offline)."),
    out: str | None = typer.Option(None, "--out", help="Leitfaden als Markdown-Datei speichern."),
) -> None:
    """Interview-Leitfaden für einen bewerteten Job (offline, optional + LLM)."""
    from job_agent.agents.interview_prep import build_interview_prep, interview_prep_md

    selected_db_path = db_path or ("./data/demo_job_agent.db" if demo else settings.sqlite_path)
    store = Store(selected_db_path)
    try:
        job = store.get_job(job_id)
    finally:
        store.close()
    if job is None:
        raise typer.BadParameter(f"Job '{job_id}' nicht in {selected_db_path} gefunden.")

    profile = _resolve_profile(
        cv,
        profile_path,
        allow_demo=demo,
        db_path=selected_db_path,
    )
    guide = build_interview_prep(job, profile, use_llm=llm)
    markdown = interview_prep_md(guide)
    if out:
        out_file = Path(out)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(markdown, encoding="utf-8")
        console.print(f"[bold green]Gespeichert →[/bold green] [cyan]{out}[/cyan]")
    console.print(markdown)


if __name__ == "__main__":
    app()
