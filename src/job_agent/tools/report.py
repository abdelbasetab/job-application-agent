"""Bewertungsreport als Markdown (career-ops: nummerierte Report-Dateien).

Ein Report bündelt alles, was das System über eine Stelle weiß — Job-Daten,
erklärbare Rubrik mit Evidenz, Ghost-Job-Check, Anschreiben-Entwurf samt
Quality-Checks, Status und Liveness — in einer menschenlesbaren Datei, die
sich archivieren, teilen oder dem Prüfer zeigen lässt. Deterministisch,
offline, ohne LLM.
"""

from __future__ import annotations

from datetime import datetime

from job_agent.schemas import (
    ApplicationStatus,
    GeneratedApplication,
    JobPosting,
    LivenessResult,
    MatchResult,
)

REPORT_FILENAME = "bewertungsreport.md"

_RECOMMENDATION_LABELS = {
    "strong": "Sehr guter Fit — bewerben",
    "good": "Guter Fit — bewerben",
    "maybe": "Prüfen",
    "skip": "Nicht priorisieren",
}
_RISK_LABELS = {"low": "niedrig", "medium": "mittel", "high": "hoch"}
_LIVENESS_LABELS = {"live": "offen", "expired": "abgelaufen", "unknown": "unsicher"}


def evaluation_report_md(
    job: JobPosting,
    match: MatchResult | None = None,
    application: GeneratedApplication | None = None,
    status: ApplicationStatus | None = None,
    liveness: LivenessResult | None = None,
) -> str:
    """Render one job evaluation as a self-contained German Markdown report."""
    lines: list[str] = []
    add = lines.append

    add(f"# Bewertungsreport: {job.title}")
    add("")
    add(f"**Unternehmen:** {job.company}  ")
    add(f"**Ort:** {job.location}{' · Remote möglich' if job.remote else ''}  ")
    add(f"**Quelle:** {job.source}  ")
    add(f"**URL:** {job.url}  ")
    if job.employment_type:
        add(f"**Art:** {job.employment_type}  ")
    if job.salary_range:
        low, high = job.salary_range
        add(f"**Gehaltsangabe:** {low:,} - {high:,} EUR  ".replace(",", "."))
    if job.posted_at:
        add(f"**Veröffentlicht:** {job.posted_at.isoformat()}  ")
    add(f"**Report erstellt:** {datetime.now().strftime('%d.%m.%Y %H:%M')}  ")
    if liveness is not None:
        label = _LIVENESS_LABELS.get(liveness.status, liveness.status)
        add(f"**Verfügbarkeit:** {label} ({liveness.confidence:.0%}) — {liveness.reason}  ")
    add("")

    if match is not None:
        add("## Bewertung")
        add("")
        recommendation = _RECOMMENDATION_LABELS.get(match.recommendation, match.recommendation)
        add(f"**Score:** {match.score:.2f} ({match.score:.0%})  ")
        add(f"**Empfehlung:** {recommendation}  ")
        add(f"**Risiko:** {_RISK_LABELS.get(match.risk_level, match.risk_level)}  ")
        if match.score_summary:
            add(f"**Kurzfazit:** {match.score_summary}  ")
        add("")
        if match.score_components:
            add("| Dimension | Score | Gewicht | Evidenz |")
            add("| --- | ---: | ---: | --- |")
            for component in match.score_components:
                evidence = component.evidence.replace("|", "/")
                add(f"| {component.label} | {component.score}/5 | {component.weight} % | {evidence} |")
            add("")
        add(f"**Passende Skills:** {', '.join(match.matched_skills) or '-'}  ")
        add(f"**Fehlende Skills:** {', '.join(match.missing_skills) or '-'}  ")
        add("")
        add("### Begründung")
        add("")
        add(match.rationale or "-")
        add("")
        add("### Ghost-Job- / Scam-Check")
        add("")
        if match.risk_flags:
            for flag in match.risk_flags:
                add(f"- {flag}")
        else:
            add("- Keine starken Ghost-Job- oder Scam-Signale erkannt.")
        add("")
    else:
        add("## Bewertung")
        add("")
        add("_Noch keine Bewertung vorhanden — Pipeline für diesen Job ausführen._")
        add("")

    if status is not None:
        add("## Status")
        add("")
        add(f"**Aktuell:** {status.status}  ")
        if status.submitted_at:
            add(f"**Eingereicht:** {status.submitted_at.strftime('%d.%m.%Y')}  ")
        add(f"**Aktualisiert:** {status.updated_at.strftime('%d.%m.%Y %H:%M')}  ")
        if status.notes:
            add("")
            add("**Notizen:**")
            add("")
            for line in status.notes.splitlines():
                if line.strip():
                    add(f"- {line.strip()}")
        add("")

    if application is not None:
        add("## Anschreiben-Entwurf")
        add("")
        checks = ", ".join(
            f"{'✓' if passed else '✗'} {name}" for name, passed in application.quality_checks.items()
        )
        if checks:
            add(f"**Quality-Checks:** {checks}")
            add("")
        add("```text")
        add(application.cover_letter_md.strip())
        add("```")
        add("")

    add("## Anzeige (Auszug)")
    add("")
    excerpt = " ".join(job.description.split())
    add(excerpt[:1200] + ("…" if len(excerpt) > 1200 else ""))
    add("")
    add("---")
    add("_Erstellt vom Job Application Agent — deterministischer Report, keine LLM-Inhalte._")
    add("")
    return "\n".join(lines)
