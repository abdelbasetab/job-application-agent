"""Best-effort recipient extraction for job postings.

The goal is conservative autofill: prefer likely recruiting/application
addresses, surface alternatives, and avoid filling obvious non-application
addresses such as no-reply or privacy mailboxes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_agent.schemas import JobPosting

_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_TRIM_CHARS = ".,;:!?)]}>\"'"

_POSITIVE_LOCAL = {
    "application": 26,
    "apply": 26,
    "bewerbung": 26,
    "bewerbungen": 26,
    "career": 24,
    "careers": 24,
    "hr": 22,
    "job": 20,
    "jobs": 20,
    "karriere": 24,
    "personal": 20,
    "recruiting": 28,
    "recruitment": 28,
    "talent": 22,
}
_POSITIVE_CONTEXT = {
    "bewerbung": 24,
    "bewerben": 24,
    "karriere": 18,
    "recruiting": 24,
    "recruiter": 20,
    "hr": 16,
    "personal": 16,
    "application": 22,
    "apply": 22,
    "contact": 10,
    "kontakt": 10,
    "ansprechpartner": 16,
}
_NEGATIVE_LOCAL = {
    "abuse": -45,
    "admin": -18,
    "datenschutz": -55,
    "info": -8,
    "newsletter": -50,
    "no-reply": -70,
    "noreply": -70,
    "postmaster": -60,
    "privacy": -55,
    "support": -35,
    "webmaster": -45,
}
_NEGATIVE_CONTEXT = {
    "datenschutz": -45,
    "impressum": -30,
    "newsletter": -45,
    "no-reply": -60,
    "noreply": -60,
    "privacy": -45,
    "support": -25,
    "kundenservice": -25,
}


@dataclass(frozen=True)
class RecipientSuggestion:
    email: str
    score: int
    confidence: float
    reason: str
    source: str

    def as_dict(self) -> dict[str, str | int | float]:
        return {
            "email": self.email,
            "score": self.score,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
        }


def recipient_suggestions(job: JobPosting) -> list[RecipientSuggestion]:
    """Return ranked recipient suggestions parsed from a posting."""
    candidates: dict[str, RecipientSuggestion] = {}
    for source, text in _job_texts(job):
        for match in _EMAIL_RE.finditer(text):
            email = match.group(1).strip(_TRIM_CHARS).lower()
            if not _valid_email(email):
                continue
            context = _context(text, match.start(), match.end())
            suggestion = _score_email(email, source, context)
            previous = candidates.get(email)
            if previous is None or suggestion.score > previous.score:
                candidates[email] = suggestion
    ranked = sorted(candidates.values(), key=lambda item: (-item.score, item.email))
    return [item for item in ranked if item.score > 0]


def best_recipient(job: JobPosting, minimum_score: int = 35) -> str:
    """Best autofill address, or an empty string when confidence is too low."""
    suggestions = recipient_suggestions(job)
    if not suggestions or suggestions[0].score < minimum_score:
        return ""
    return suggestions[0].email


def recipient_payload(job: JobPosting) -> dict[str, object]:
    suggestions = recipient_suggestions(job)
    best = suggestions[0].email if suggestions and suggestions[0].score >= 35 else ""
    return {
        "contact_email": best,
        "recipient_suggestions": [item.as_dict() for item in suggestions],
        "recipient_confidence": suggestions[0].confidence if best else 0.0,
    }


def _job_texts(job: JobPosting) -> list[tuple[str, str]]:
    fields = [
        ("description", job.description or ""),
        ("requirements", job.requirements_raw or ""),
        ("title", job.title or ""),
        ("company", job.company or ""),
    ]
    return [(source, text) for source, text in fields if text]


def _score_email(email: str, source: str, context: str) -> RecipientSuggestion:
    local, _, domain = email.partition("@")
    normalized_local = local.replace(".", "-").replace("_", "-").lower()
    context_l = context.lower()
    score = 42
    reasons: list[str] = []
    local_positive = False

    for token, value in _POSITIVE_LOCAL.items():
        if token in normalized_local:
            score += value
            reasons.append(f"Adresse enthaelt {token}")
            local_positive = True
            break
    for token, value in _POSITIVE_CONTEXT.items():
        if token in context_l:
            score += value
            reasons.append(f"Kontext nennt {token}")
            break
    for token, value in _NEGATIVE_LOCAL.items():
        if token in normalized_local:
            score += value
            reasons.append(f"Adresse wirkt nicht wie Bewerbung ({token})")
            break
    if not local_positive:
        for token, value in _NEGATIVE_CONTEXT.items():
            if token in context_l:
                score += value
                reasons.append(f"Kontext wirkt unpassend ({token})")
                break

    if source == "requirements":
        score += 4
    if domain.endswith(".de"):
        score += 2
    score = max(0, min(100, score))
    confidence = round(score / 100, 2)
    reason = "; ".join(reasons) if reasons else "E-Mail im Inserat gefunden"
    return RecipientSuggestion(
        email=email,
        score=score,
        confidence=confidence,
        reason=reason,
        source=source,
    )


def _context(text: str, start: int, end: int, radius: int = 80) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def _valid_email(email: str) -> bool:
    if len(email) > 254 or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if not local or not domain or ".." in domain:
        return False
    return "." in domain and not domain.startswith("-") and not domain.endswith("-")
