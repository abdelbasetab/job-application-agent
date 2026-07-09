"""Muster-Analyse über den Bewerbungs-Tracker (career-ops: „patterns").

Wertet die persistierten :class:`ApplicationStatus`-Einträge deterministisch
aus: Funnel, Antwort- und Interviewquote, Antwortzeiten, überfällige
Bewerbungen und Firmen-/Quellen-Verteilung. Alles offline, keine LLM-Calls —
das Ergebnis ist als JSON serialisierbar (CLI-Tabelle und Web-UI nutzen
dieselbe Struktur).

Grenze (bewusst): Score-Bänder je Ausgang fehlen noch, weil MatchResults
bislang nicht persistiert werden — siehe Ausblick in ARCHITECTURE.md.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from job_agent.memory.store import Store
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# Statuses that mean "the application actually went out".
_SENT_STATES = {"submitted", "interview", "offer", "rejected"}
# Statuses that count as a company response.
_RESPONSE_STATES = {"interview", "offer", "rejected"}
_STALE_AFTER_DAYS = 14


def analyze_patterns(store: Store, now: datetime | None = None) -> dict[str, Any]:
    """Aggregate tracker outcomes into an explainable pattern report."""
    reference = now or datetime.now()
    statuses = store.all_status()

    funnel: Counter[str] = Counter(status.status for status in statuses)
    sent = [status for status in statuses if status.status in _SENT_STATES]
    responded = [status for status in statuses if status.status in _RESPONSE_STATES]
    interviews = funnel.get("interview", 0) + funnel.get("offer", 0)

    response_days: list[float] = []
    for status in responded:
        if status.submitted_at and status.updated_at:
            delta = (status.updated_at - status.submitted_at).total_seconds() / 86400.0
            if delta >= 0:
                response_days.append(delta)

    stale: list[dict[str, Any]] = []
    companies: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for status in statuses:
        job = store.get_job(status.job_id)
        if job is not None:
            companies[job.company] += 1
            sources[job.source] += 1
        if status.status == "submitted":
            last = status.updated_at or status.submitted_at
            if last is not None:
                waiting = (reference - last).days
                if waiting >= _STALE_AFTER_DAYS:
                    stale.append(
                        {
                            "job_id": status.job_id,
                            "title": job.title if job else status.job_id,
                            "company": job.company if job else "",
                            "days_waiting": waiting,
                        }
                    )
    stale.sort(key=lambda item: item["days_waiting"], reverse=True)

    sent_total = len(sent)
    report: dict[str, Any] = {
        "ok": True,
        "total": len(statuses),
        "funnel": {
            stage: funnel.get(stage, 0)
            for stage in ("draft", "submitted", "interview", "offer", "rejected", "withdrawn")
        },
        "sent_total": sent_total,
        "response_rate": round(len(responded) / sent_total, 3) if sent_total else None,
        "interview_rate": round(interviews / sent_total, 3) if sent_total else None,
        "rejection_rate": round(funnel.get("rejected", 0) / sent_total, 3) if sent_total else None,
        "avg_days_to_response": (
            round(sum(response_days) / len(response_days), 1) if response_days else None
        ),
        "stale_submitted": stale[:10],
        "stale_after_days": _STALE_AFTER_DAYS,
        "top_companies": [
            {"company": name, "count": count} for name, count in companies.most_common(5)
        ],
        "sources": [
            {"source": name, "count": count} for name, count in sources.most_common()
        ],
        "insights": [],
    }
    report["insights"] = _insights(report)
    log.info(
        "[patterns] %d Einträge analysiert — %d gesendet, %d Antworten",
        report["total"],
        sent_total,
        len(responded),
    )
    return report


def _insights(report: dict[str, Any]) -> list[str]:
    """Turn the raw numbers into a few honest German takeaways."""
    insights: list[str] = []
    sent = report["sent_total"]
    if not report["total"]:
        return ["Noch keine Daten — starte die Pipeline und reiche Bewerbungen ein."]
    if not sent:
        insights.append(
            "Nur Entwürfe bisher: noch keine Bewerbung eingereicht — der Funnel beginnt erst mit 'Eingereicht'."
        )
        return insights
    response_rate = report["response_rate"] or 0.0
    if response_rate < 0.25:
        insights.append(
            f"Antwortquote {response_rate:.0%}: niedrig — Empfänger prüfen (echte Bewerbungsadresse?) "
            "und nach 7 Tagen konsequent nachfassen."
        )
    else:
        insights.append(f"Antwortquote {response_rate:.0%} über {sent} eingereichte Bewerbungen.")
    if report["interview_rate"] is not None and report["interview_rate"] >= 0.2:
        insights.append(
            f"Interviewquote {report['interview_rate']:.0%} — die Zielrichtung passt, dranbleiben."
        )
    if report["avg_days_to_response"] is not None:
        insights.append(
            f"Firmen antworten im Schnitt nach {report['avg_days_to_response']:.0f} Tagen — "
            "Follow-up-Fenster entsprechend wählen."
        )
    if report["stale_submitted"]:
        insights.append(
            f"{len(report['stale_submitted'])} Bewerbung(en) warten seit ≥ {report['stale_after_days']} Tagen "
            "ohne Antwort — Kandidaten für den Follow-up-Radar."
        )
    top = report["top_companies"]
    if top and top[0]["count"] >= 3:
        insights.append(
            f"Häufigste Firma: {top[0]['company']} ({top[0]['count']}x) — Duplikate oder echte Serie?"
        )
    return insights
