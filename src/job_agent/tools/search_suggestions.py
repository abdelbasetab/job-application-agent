"""Job-search query suggestions derived from the user's own CV.

The Scout needs a search term, but a new user rarely knows which wording
actually returns German postings. These suggestions turn the structured
profile — preferred employment types, headline, field of study, top skills,
recent roles — into ready-to-run queries.

No LLM is involved: every suggestion is built from exactly one profile field
and carries the reason it was proposed, so the user can see why it is there.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.schemas import UserProfile

MAX_SUGGESTIONS = 6

# The Scout queries German job boards, so the preference enums become the
# words that actually appear in German postings.
_EMPLOYMENT_TERMS = {
    "working-student": "Werkstudent",
    "internship": "Praktikum",
    "thesis": "Abschlussarbeit",
    "part-time": "Teilzeit",
    "full-time": "Vollzeit",
}

# Skills are stored lowercase; these keep their uppercase form when shown.
_ACRONYMS = {
    "ai", "api", "aws", "bi", "cad", "ci", "crm", "css", "erp", "etl", "gcp",
    "html", "js", "json", "llm", "llms", "ml", "nlp", "php", "rag", "rest",
    "sap", "sql", "ts", "ui", "ux", "xml",
}

# Ubiquitous tools nobody searches a job by — they would only dilute results.
_GENERIC_SKILLS = {
    "excel", "git", "github", "microsoft office", "ms office", "office",
    "outlook", "powerpoint", "teamwork", "windows", "word",
}

# Stripped from a headline so "AI Engineering Student" yields "AI Engineering".
_STATUS_WORDS = {
    "absolvent", "absolventin", "bewerber", "bewerberin", "graduate",
    "student", "studentin", "studierende", "studierender",
}


@dataclass(frozen=True)
class SearchSuggestion:
    query: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"query": self.query, "reason": self.reason}


def search_suggestions(
    profile: UserProfile, limit: int = MAX_SUGGESTIONS
) -> list[SearchSuggestion]:
    """Ranked, deduplicated search queries built from ``profile``."""
    employment_terms = _employment_terms(profile)
    lead_term = employment_terms[0] if employment_terms else ""
    headline = _strip_status_words(profile.headline)
    field = _first_segment(profile.education[0].field) if profile.education else ""

    candidates: list[SearchSuggestion] = []

    # Preferred work type combined with what the person actually does.
    for term in employment_terms[:2]:
        if headline:
            candidates.append(
                SearchSuggestion(f"{term} {headline}", f"Arbeitsart + Profiltitel „{profile.headline}“")
            )
    if lead_term and field:
        candidates.append(SearchSuggestion(f"{lead_term} {field}", f"Arbeitsart + Studienfach „{field}“"))

    # Top skills — the strongest signal for what a posting must mention.
    for skill in _top_skills(profile, count=2):
        candidates.append(
            SearchSuggestion(
                f"{lead_term} {skill}".strip(), f"Arbeitsart + Skill „{skill}“" if lead_term else f"Skill „{skill}“"
            )
        )

    # The most recent role title, as job boards phrase it.
    for entry in profile.experience[:1]:
        role = _strip_status_words(entry.role)
        if role:
            candidates.append(SearchSuggestion(role, f"Letzte Position bei {entry.company}"))

    if headline:
        candidates.append(SearchSuggestion(headline, "Profiltitel ohne Filter"))
    if field:
        candidates.append(SearchSuggestion(field, f"Studienfach „{field}“"))

    return _dedupe(candidates)[:limit]


def _employment_terms(profile: UserProfile) -> list[str]:
    terms = [
        _EMPLOYMENT_TERMS[item.strip().lower()]
        for item in profile.preferences.employment_types
        if item.strip().lower() in _EMPLOYMENT_TERMS
    ]
    return list(dict.fromkeys(terms))


def _top_skills(profile: UserProfile, count: int) -> list[str]:
    picked: list[str] = []
    for skill in profile.skills:
        cleaned = " ".join(skill.split())
        if not cleaned or cleaned.lower() in _GENERIC_SKILLS:
            continue
        display = _display_case(cleaned)
        if display not in picked:
            picked.append(display)
        if len(picked) == count:
            break
    return picked


def _display_case(value: str) -> str:
    return " ".join(
        word.upper() if word.lower() in _ACRONYMS else word[:1].upper() + word[1:]
        for word in value.split()
    )


def _first_segment(value: str) -> str:
    """'Computer Science / AI' -> 'Computer Science'."""
    for separator in ("/", "|", ",", " - ", f" {chr(0x2013)} "):
        value = value.split(separator)[0]
    return " ".join(value.split())


def _strip_status_words(value: str) -> str:
    """Drop 'Student', 'Absolvent', … so the rest reads like a job title."""
    words = [word for word in _first_segment(value).split() if word.lower().strip(".,") not in _STATUS_WORDS]
    return " ".join(words)


def _dedupe(items: list[SearchSuggestion]) -> list[SearchSuggestion]:
    seen: set[str] = set()
    unique: list[SearchSuggestion] = []
    for item in items:
        query = " ".join(item.query.split())
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        unique.append(SearchSuggestion(query=query, reason=item.reason))
    return unique
