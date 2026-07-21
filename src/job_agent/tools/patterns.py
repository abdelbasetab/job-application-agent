"""Muster-Analyse über den Bewerbungs-Tracker (career-ops: „patterns").

Wertet die persistierten :class:`ApplicationStatus`-Einträge deterministisch
aus: Funnel, Antwort- und Interviewquote, Antwortzeiten, überfällige
Bewerbungen und Firmen-/Quellen-Verteilung. Alles offline, keine LLM-Calls —
das Ergebnis ist als JSON serialisierbar (CLI-Tabelle und Web-UI nutzen
dieselbe Struktur).

Persistierte Match-Ergebnisse werden in Score-Bändern den tatsächlichen
Tracker-Ausgängen gegenübergestellt. Kleine Stichproben werden kenntlich
gemacht; die Auswertung behauptet keine Kausalität.
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
_SCORE_BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 49, "0-49"),
    (50, 69, "50-69"),
    (70, 84, "70-84"),
    (85, 100, "85-100"),
)


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
    statuses_by_job = {status.job_id: status for status in statuses}
    score_outcomes = _score_outcomes(store, statuses_by_job)
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
        "score_outcomes": score_outcomes,
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


def _score_outcomes(
    store: Store, statuses_by_job: dict[str, Any]
) -> list[dict[str, Any]]:
    """Relate persisted scores to outcomes without overstating small samples."""
    rows: list[dict[str, Any]] = []
    matches = {match.job_id: match for match in store.all_matches()}
    for low, high, label in _SCORE_BANDS:
        band_statuses = []
        for job_id, match in matches.items():
            score = max(0, min(100, round(match.score * 100)))
            status = statuses_by_job.get(job_id)
            if low <= score <= high and status is not None:
                band_statuses.append(status)
        sent = [status for status in band_statuses if status.status in _SENT_STATES]
        responses = [status for status in sent if status.status in _RESPONSE_STATES]
        interviews = [status for status in sent if status.status in {"interview", "offer"}]
        rows.append(
            {
                "band": label,
                "tracked": len(band_statuses),
                "sent": len(sent),
                "responses": len(responses),
                "interviews": len(interviews),
                "offers": sum(status.status == "offer" for status in sent),
                "rejections": sum(status.status == "rejected" for status in sent),
                "response_rate": round(len(responses) / len(sent), 3) if sent else None,
                "interview_rate": round(len(interviews) / len(sent), 3) if sent else None,
                "sample_sufficient": len(sent) >= 5,
            }
        )
    return rows


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
    score_rows = [row for row in report.get("score_outcomes", []) if row["sent"] >= 5]
    if score_rows:
        best = max(score_rows, key=lambda row: row["interview_rate"] or 0.0)
        insights.append(
            f"Score-Band {best['band']} hat aktuell die höchste Interviewquote "
            f"({(best['interview_rate'] or 0.0):.0%}, n={best['sent']}); "
            "das ist eine Beobachtung, kein Kausalnachweis."
        )
    return insights
