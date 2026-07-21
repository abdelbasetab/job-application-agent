"""Matcher agent - scores each posting against the user's profile.

The deterministic matcher produces a visible 1-5 rubric plus ghost-job risk
signals. The scalar score remains 0.0..1.0 so the existing Writer and Tracker
contracts stay stable.

Skill matching is three-tiered (ADR-0006):

1. **Exact/alias** — ``_canonical_skill`` normalizes spellings and maps known
   synonyms (PostgreSQL → sql).
2. **Similarity** — near-duplicates the alias table cannot know ("python3" ≈
   "python"). Uses the OpenAI-compatible ``/embeddings`` endpoint when
   ``EMBEDDING_MODEL`` is configured, otherwise an offline fuzzy ratio.
3. **LLM** — the full semantic matcher (``--llm-agents``), with tiers 1-2 as
   the deterministic fallback.

The weighted rubric is the primary score. A hard gate keeps jobs with zero
covered must-have skills at 0.0, and risk penalties are applied last.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from difflib import SequenceMatcher
from functools import partial
from pathlib import Path
from typing import Any

from job_agent.schemas import (
    JobPosting,
    MatchResult,
    Recommendation,
    RiskLevel,
    ScoreComponent,
    UserProfile,
)
from job_agent.utils.config import settings
from job_agent.utils.llm import call_llm
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "matcher.md"

_SKILL_ALIASES = {
    "postgresql": "sql",
    "postgres": "sql",
    "mysql": "sql",
    "sqlite": "sql",
    "mariadb": "sql",
    "sql server": "sql",
    "llm": "llms",
    "large language model": "llms",
    "large language models": "llms",
    "retrieval augmented generation": "rag",
    "retrieval-augmented generation": "rag",
    "chroma db": "chromadb",
    "rest api": "rest apis",
    "restful api": "rest apis",
    "ml": "machine learning",
}

_SCAM_TERMS = {
    "whatsapp": "Bewerbung/Kontakt ueber WhatsApp",
    "telegram": "Bewerbung/Kontakt ueber Telegram",
    "vorkasse": "Vorkasse oder Zahlung vor Arbeitsbeginn",
    "crypto": "Crypto-/Zahlungsbezug im Inserat",
    "passives einkommen": "Unrealistisches Einkommensversprechen",
    "schnell geld": "Unrealistisches Einkommensversprechen",
    "keine erfahrung notwendig": "Sehr unspezifisches Einstiegsversprechen",
}


def _normalize(skills: list[str]) -> set[str]:
    return {_canonical_skill(s) for s in skills if s.strip()}


def run_matcher(
    jobs: list[JobPosting],
    profile: UserProfile,
    threshold: float = 0.6,
    use_llm: bool | None = None,
    profile_context: list[str] | None = None,
    use_embeddings: bool | None = None,
) -> list[MatchResult]:
    """Score every job against the profile.

    When `use_llm` is true, each job is sent to the configured LLM with the
    matcher prompt. Invalid or failed LLM calls fall back to the deterministic
    rubric scorer for that job. Set `use_embeddings=False` to force the
    deterministic scorer to remain offline even when a remote embedding model
    is configured; `None` preserves the configured runtime behavior.
    """
    llm_enabled = settings.enable_llm_agents if use_llm is None else use_llm
    embeddings_enabled = (
        bool(settings.embedding_model and settings.llm_base_url)
        if use_embeddings is None
        else use_embeddings
    )
    if llm_enabled:
        runner = partial(
            _run_llm_matcher,
            profile=profile,
            threshold=threshold,
            profile_context=profile_context,
            use_embeddings=embeddings_enabled,
        )
        if len(jobs) <= 1:
            return [runner(job) for job in jobs]
        # One LLM call per job — run them concurrently, keep the input order.
        workers = min(4, len(jobs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(runner, jobs))
    return [
        _run_deterministic_match(job, profile, use_embeddings=embeddings_enabled)
        for job in jobs
    ]


def _run_deterministic_match(
    job: JobPosting,
    profile: UserProfile,
    *,
    use_embeddings: bool,
) -> MatchResult:
    profile_skills = _normalize(profile.skills)
    required = _normalize(job.requirements)
    nice = _normalize(job.nice_to_have)

    matched = sorted(required & profile_skills)
    missing = sorted(required - profile_skills)

    # Tier 2: similarity matching for requirements tier 1 could not cover.
    similar_pairs = _similar_skill_matches(
        missing,
        profile_skills,
        use_embeddings=use_embeddings,
    )
    if similar_pairs:
        matched = sorted(set(matched) | set(similar_pairs))
        missing = [skill for skill in missing if skill not in similar_pairs]

    risk_flags, risk_level = _ghost_job_risk(job)
    components = _score_components(
        job=job,
        profile=profile,
        matched=matched,
        missing=missing,
        required=required,
        nice=nice,
        profile_skills=profile_skills,
        risk_flags=risk_flags,
        risk_level=risk_level,
        similar_pairs=similar_pairs,
    )
    preference_block = _preference_block(job, profile)

    # The weighted rubric is the score (ADR-0006). Hard gate: a posting whose
    # must-have skills are all uncovered stays at 0.0 regardless of the softer
    # dimensions; the risk penalty is applied on top.
    if preference_block:
        score = 0.0
    elif required and not matched:
        score = 0.0
    else:
        score = _weighted_score(components)
        if not required:
            score = min(score, _UNSTRUCTURED_REQUIREMENTS_CAP)
        # Level mismatch is a soft K.o.: a clearly senior role cannot become a
        # top recommendation for a student profile just because skills overlap.
        seniority = next(c for c in components if c.key == "seniority")
        if seniority.score <= 2:
            score = min(score, _SENIOR_MISMATCH_CAP)
    score = _apply_risk_penalty(score, risk_level)
    recommendation = _recommendation(score, risk_level)
    score_summary = _score_summary(job, matched, required, risk_level, recommendation)
    rationale = _rationale(job, matched, required, missing, components, risk_flags, score)
    if preference_block:
        score_summary = f"Nicht passend: {preference_block}"
        rationale = f"Praeferenz-Filter: {preference_block} {rationale}"

    result = MatchResult(
        job_id=job.id,
        score=round(score, 3),
        matched_skills=matched,
        missing_skills=missing,
        rationale=rationale,
        score_components=components,
        risk_level=risk_level,
        risk_flags=risk_flags,
        recommendation=recommendation,
        score_summary=score_summary,
    )
    log.info("[matcher] %s -> score=%.2f", job.id, result.score)
    return result


def _run_llm_matcher(
    job: JobPosting,
    profile: UserProfile,
    threshold: float,
    profile_context: list[str] | None,
    use_embeddings: bool,
) -> MatchResult:
    try:
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        user_payload = {
            "job": job.model_dump(mode="json"),
            "profile": profile.model_dump(mode="json"),
            "profile_context": profile_context or [],
            "threshold_hint": threshold,
        }
        raw = call_llm(
            [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        "Return only one JSON object matching MatchResult.\n"
                        f"{json.dumps(user_payload, ensure_ascii=False)}"
                    ),
                },
            ],
            schema=MatchResult,
            schema_name="MatchResult",
        )
        result = _parse_match(raw, expected_job_id=job.id)
        _validate_llm_match(result, job, profile)
        result.evaluation_method = "llm"
        result.evaluation_model = settings.llm_model
        log.info("[matcher:llm] %s -> score=%.2f", job.id, result.score)
        return result
    except Exception as exc:
        log.warning("[matcher:llm] falling back for %s: %s", job.id, exc)
        fallback = _run_deterministic_match(
            job,
            profile,
            use_embeddings=use_embeddings,
        )
        if not fallback.rationale.startswith("LLM fallback:"):
            fallback.rationale = f"LLM fallback: {fallback.rationale}"
        return fallback


def _parse_match(raw: Any, expected_job_id: str) -> MatchResult:
    if isinstance(raw, MatchResult):
        result = raw
    else:
        if not isinstance(raw, str):
            raise TypeError(f"expected string LLM output, got {type(raw)!r}")
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("LLM matcher output was not a JSON object")
        if not data.get("job_id"):
            raise ValueError("LLM matcher output omitted job_id")
        result = MatchResult.model_validate(data)
    if result.job_id != expected_job_id:
        raise ValueError(
            f"LLM matcher returned job_id {result.job_id!r}, expected {expected_job_id!r}"
        )
    return result


def _validate_llm_match(
    result: MatchResult,
    job: JobPosting,
    profile: UserProfile,
) -> None:
    """Reject structurally valid but semantically inconsistent LLM output."""
    required = _normalize(job.requirements)
    profile_skills = _normalize(profile.skills)
    matched = _normalize(result.matched_skills)
    missing = _normalize(result.missing_skills)
    if matched & missing:
        raise ValueError("LLM match lists the same skill as matched and missing")
    if matched - required or missing - required:
        raise ValueError("LLM match contains skills outside the job requirements")
    if required and matched | missing != required:
        raise ValueError("LLM match does not account for every required skill")
    if matched - profile_skills:
        raise ValueError("LLM claims a matched skill that is absent from the profile")
    if required and not matched and result.score != 0:
        raise ValueError("LLM score violates the zero-covered-must-have gate")
    if not required and result.score > _UNSTRUCTURED_REQUIREMENTS_CAP:
        raise ValueError("LLM score is too high without structured requirements")
    if _preference_block(job, profile) and (result.score != 0 or result.recommendation != "skip"):
        raise ValueError("LLM result violates a candidate preference gate")
    expected_recommendation = _recommendation(result.score, result.risk_level)
    if result.recommendation != expected_recommendation:
        raise ValueError("LLM recommendation contradicts score/risk")
    if result.score_components:
        keys = [component.key for component in result.score_components]
        if len(keys) != len(set(keys)) or sum(c.weight for c in result.score_components) != 100:
            raise ValueError("LLM score components are duplicated or do not total 100%")


def _canonical_skill(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return text
    for needle, canonical in sorted(_SKILL_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"(?<![a-z0-9+#]){re.escape(needle)}(?![a-z0-9+#])", text):
            return canonical
    return text


def _job_text(job: JobPosting) -> str:
    return " ".join(
        [
            job.title,
            job.company,
            job.location,
            job.description,
            job.requirements_raw,
            " ".join(job.requirements),
            " ".join(job.nice_to_have),
        ]
    ).lower()


def _score_components(
    *,
    job: JobPosting,
    profile: UserProfile,
    matched: list[str],
    missing: list[str],
    required: set[str],
    nice: set[str],
    profile_skills: set[str],
    risk_flags: list[str],
    risk_level: RiskLevel,
    similar_pairs: dict[str, str] | None = None,
) -> list[ScoreComponent]:
    hard_score = _ratio_to_1_5(len(matched) / len(required)) if required else 2
    hard_evidence = (
        f"{len(matched)}/{len(required)} Muss-Skills erkannt: {', '.join(matched) or 'keine'}."
        if required
        else "Keine strukturierten Muss-Skills im Inserat erkannt."
    )
    if similar_pairs:
        pairs = ", ".join(f"{req} ≈ {have}" for req, have in sorted(similar_pairs.items()))
        hard_evidence += f" Ähnlich erkannt: {pairs}."
    if missing:
        hard_evidence += f" Fehlend: {', '.join(missing)}."

    nice_matches = sorted(nice & profile_skills)
    if not nice:
        nice_score = 3
        nice_evidence = "Keine Nice-to-have-Skills im Inserat."
    elif nice_matches:
        nice_score = 5 if len(nice_matches) == len(nice) else 4
        nice_evidence = f"Nice-to-have-Treffer: {', '.join(nice_matches)}."
    else:
        nice_score = 2
        nice_evidence = "Keine Nice-to-have-Treffer."

    location_score, location_evidence = _location_component(job, profile)
    seniority_score, seniority_evidence = _seniority_component(job, profile)
    language_score, language_evidence = _language_component(job, profile)
    quality_score, quality_evidence = _quality_component(risk_flags, risk_level)

    return [
        ScoreComponent(
            key="hard_skills",
            label="Muss-Skills",
            score=hard_score,
            weight=45,
            evidence=hard_evidence,
        ),
        ScoreComponent(
            key="nice_to_have",
            label="Nice-to-have",
            score=nice_score,
            weight=5,
            evidence=nice_evidence,
        ),
        ScoreComponent(
            key="location",
            label="Standort/Remote",
            score=location_score,
            weight=15,
            evidence=location_evidence,
        ),
        ScoreComponent(
            key="seniority",
            label="Level/Jobtyp",
            score=seniority_score,
            weight=10,
            evidence=seniority_evidence,
        ),
        ScoreComponent(
            key="language",
            label="Sprache",
            score=language_score,
            weight=10,
            evidence=language_evidence,
        ),
        ScoreComponent(
            key="posting_quality",
            label="Inseratsqualitaet",
            score=quality_score,
            weight=15,
            evidence=quality_evidence,
        ),
    ]


def _ratio_to_1_5(ratio: float) -> int:
    if ratio >= 0.95:
        return 5
    if ratio >= 0.7:
        return 4
    if ratio >= 0.45:
        return 3
    if ratio > 0:
        return 2
    return 1


def _location_component(job: JobPosting, profile: UserProfile) -> tuple[int, str]:
    job_location = _clean_text(job.location)
    preferred = {_clean_text(item) for item in profile.preferences.locations}
    home = _clean_text(profile.location)
    remote_preferred = profile.preferences.remote_ok or "remote" in preferred

    if job.remote is True and remote_preferred:
        return 5, "Remote ist moeglich und im Profil akzeptiert."
    if _matches_location(job_location, preferred | {home}):
        return 5, f"Standort passt: {job.location}."
    if job.remote is True:
        return 4, "Remote ist moeglich."
    if not job_location or job_location in {"deutschland", "germany", "bundesweit"}:
        return 3, "Standort ist zu allgemein fuer eine harte Bewertung."
    return 2, f"Standort {job.location} liegt nicht in den Praeferenzen."


def _matches_location(job_location: str, preferred: set[str]) -> bool:
    if not job_location:
        return False
    return any(
        item
        and (
            _contains_phrase(job_location, item)
            or _contains_phrase(item, job_location)
        )
        for item in preferred
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _preference_block(job: JobPosting, profile: UserProfile) -> str:
    company = _company_key(job.company)
    for excluded in profile.preferences.excluded_companies:
        excluded_key = _company_key(excluded)
        if excluded_key and company and (
            _contains_phrase(company, excluded_key) or _contains_phrase(excluded_key, company)
        ):
            return f"Unternehmen {job.company} ist ausgeschlossen."
    minimum = profile.preferences.min_salary
    if minimum is not None and job.salary_range is not None and job.salary_range[1] < minimum:
        return (
            f"Gehaltsobergrenze {job.salary_range[1]:,} EUR liegt unter dem Minimum "
            f"von {minimum:,} EUR."
        )
    return ""


def _company_key(value: str) -> str:
    tokens = _clean_text(value).split()
    legal = {"ag", "gbr", "gmbh", "inc", "kg", "ltd", "ohg", "se"}
    return " ".join(token for token in tokens if token not in legal)


def _seniority_component(job: JobPosting, profile: UserProfile) -> tuple[int, str]:
    text = _job_text(job)
    prefs = {_clean_text(item) for item in profile.preferences.employment_types}
    profile_text = _clean_text(
        " ".join(
            [profile.headline, " ".join(exp.role for exp in profile.experience)]
        )
    )

    if job.employment_type and job.employment_type in prefs:
        return 5, f"Jobtyp passt zur Praeferenz: {job.employment_type}."
    if any(term in text for term in ("werkstudent", "working student", "praktikum", "internship")):
        if "student" in profile_text or prefs & {"working-student", "internship"}:
            return 5, "Studentischer Jobtyp passt zum Profil."
        return 4, "Studentischer Jobtyp wirkt passend."
    if any(term in text for term in ("senior", "lead", "principal", "head of")):
        return 2, "Inserat wirkt deutlich seniorer als das Profil."
    if any(term in text for term in ("junior", "entry", "trainee", "assistant")):
        return 4, "Junior-/Einstiegslevel passt grundsaetzlich."
    if job.employment_type:
        return 3, f"Jobtyp {job.employment_type} ist nicht direkt in den Praeferenzen."
    return 3, "Kein klares Level im Inserat erkannt."


def _language_component(job: JobPosting, profile: UserProfile) -> tuple[int, str]:
    text = _job_text(job).casefold()
    profile_levels = _profile_language_levels(profile.languages)
    requested: list[tuple[str, str, str | None]] = []
    for code, label, aliases in (
        ("de", "Deutsch", ("deutsch", "deutschkenntnisse", "german", "german language")),
        ("en", "Englisch", ("englisch", "englischkenntnisse", "english", "english language")),
    ):
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) for alias in aliases):
            requested.append((code, label, _required_cefr(text, aliases)))
    if not requested:
        return 4, "Keine harte Sprachanforderung erkannt."

    missing: list[str] = []
    too_low: list[str] = []
    for code, label, required_level in requested:
        available = profile_levels.get(code)
        if available is None:
            missing.append(label)
        elif required_level and _cefr_rank(available) < _cefr_rank(required_level):
            too_low.append(f"{label} {available} statt {required_level}")
    if missing:
        return 1, f"Sprachanforderung fehlt im Profil: {', '.join(missing)}."
    if too_low:
        return 2, f"Sprachniveau zu niedrig: {', '.join(too_low)}."
    details = ", ".join(
        f"{label} {required or profile_levels[code]}" for code, label, required in requested
    )
    if requested:
        return 5, f"Sprachanforderung erfuellt: {details}."
    return 4, "Keine harte Sprachanforderung erkannt."


_CEFR_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def _profile_language_levels(languages: dict[str, str]) -> dict[str, str]:
    aliases = {
        "de": "de",
        "deu": "de",
        "deutsch": "de",
        "german": "de",
        "en": "en",
        "eng": "en",
        "englisch": "en",
        "english": "en",
    }
    levels: dict[str, str] = {}
    for raw_key, raw_level in languages.items():
        code = aliases.get(_clean_text(raw_key))
        if code:
            levels[code] = _normalize_cefr(raw_level)
    return levels


def _normalize_cefr(value: str) -> str:
    normalized = value.strip().upper()
    match = re.search(r"\b([ABC][12])\b", normalized)
    if match:
        return match.group(1)
    lowered = value.casefold()
    if any(term in lowered for term in ("native", "mutter", "mother tongue")):
        return "C2"
    if any(term in lowered for term in ("fluent", "fliessend", "fließend")):
        return "C1"
    if any(term in lowered for term in ("advanced", "fortgeschritten")):
        return "B2"
    if any(term in lowered for term in ("basic", "grundkennt")):
        return "A2"
    return "A1"


def _required_cefr(text: str, language_aliases: tuple[str, ...]) -> str | None:
    language_spans = [
        match.span()
        for alias in language_aliases
        for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", text)
    ]
    candidates: list[tuple[int, str]] = []
    for match in re.finditer(r"(?<!\w)([abc][12])(?!\w)", text, flags=re.IGNORECASE):
        distance = min((_span_distance(match.span(), span) for span in language_spans), default=999)
        if distance <= 40:
            candidates.append((distance, match.group(1).upper()))
    qualitative = (
        (r"\b(?:muttersprachlich|native)\b", "C2"),
        (r"\b(?:verhandlungssicher|fliessend|fließend|fluent)\b", "C1"),
        (r"\b(?:sehr\s+gut|very\s+good|advanced)\b", "B2"),
        (r"\b(?:grundkenntnisse|basic)\b", "A2"),
    )
    for pattern, level in qualitative:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            distance = min((_span_distance(match.span(), span) for span in language_spans), default=999)
            if distance <= 40:
                candidates.append((distance, level))
    return min(candidates, default=(999, ""))[1] or None


def _span_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    if left[1] < right[0]:
        return right[0] - left[1]
    if right[1] < left[0]:
        return left[0] - right[1]
    return 0


def _cefr_rank(value: str) -> int:
    return _CEFR_ORDER.get(_normalize_cefr(value), 0)


def _quality_component(risk_flags: list[str], risk_level: RiskLevel) -> tuple[int, str]:
    if risk_level == "high":
        return 1, "Mehrere starke Ghost-Job-/Scam-Signale."
    if risk_level == "medium":
        return 3, "Einige Qualitaets- oder Risiko-Hinweise vorhanden."
    if risk_flags:
        return 4, "Leichte Qualitaetshinweise, aber kein hohes Risiko."
    return 5, "Inserat wirkt konkret und risikoarm."


# Tier-2 thresholds: fuzzy ratio is strict on purpose (near-duplicates only,
# "python3" ≈ "python"); embedding cosine may bridge real paraphrases.
_FUZZY_RATIO_MIN = 0.84
_EMBED_COSINE_MIN = 0.75
# A posting whose level clearly mismatches the profile (seniority score <= 2)
# is capped below the "good" band — it can stay a maybe, never a strong.
_SENIOR_MISMATCH_CAP = 0.55
_UNSTRUCTURED_REQUIREMENTS_CAP = 0.49


def _similar_skill_matches(
    missing: list[str],
    profile_skills: set[str],
    *,
    use_embeddings: bool,
) -> dict[str, str]:
    """Tier-2 skill matching — maps still-missing requirements to close profile skills.

    Uses the OpenAI-compatible ``/embeddings`` endpoint (semantic similarity)
    when ``EMBEDDING_MODEL`` is configured; otherwise a deterministic, offline
    fuzzy string ratio. Returns ``{required_skill: profile_skill}``.
    """
    if not missing or not profile_skills:
        return {}
    if use_embeddings and settings.embedding_model and settings.llm_base_url:
        try:
            return _embedding_matches(missing, sorted(profile_skills))
        except Exception as exc:
            log.warning("[matcher] embedding tier unavailable, using fuzzy ratio: %s", exc)
    return _fuzzy_matches(missing, profile_skills)


def _fuzzy_matches(missing: list[str], profile_skills: set[str]) -> dict[str, str]:
    candidates = sorted(
        (
            (SequenceMatcher(None, req, have).ratio(), req, have)
            for req in missing
            for have in profile_skills
        ),
        reverse=True,
    )
    return _one_to_one_matches(candidates, _FUZZY_RATIO_MIN)


def _embedding_matches(missing: list[str], have: list[str]) -> dict[str, str]:
    from job_agent.memory.profile_index import KIConnectEmbeddingFunction

    embed = KIConnectEmbeddingFunction(
        model=settings.embedding_model,
        base_url=settings.llm_base_url or "",
        api_key=settings.llm_api_key,
    )
    vectors = embed(missing + have)
    missing_vecs, have_vecs = vectors[: len(missing)], vectors[len(missing) :]

    candidates: list[tuple[float, str, str]] = []
    for req, req_vec in zip(missing, missing_vecs, strict=True):
        for skill, skill_vec in zip(have, have_vecs, strict=True):
            candidates.append((_cosine(req_vec, skill_vec), req, skill))
    return _one_to_one_matches(sorted(candidates, reverse=True), _EMBED_COSINE_MIN)


def _one_to_one_matches(
    candidates: list[tuple[float, str, str]], minimum: float
) -> dict[str, str]:
    result: dict[str, str] = {}
    used_profile_skills: set[str] = set()
    for similarity, required, available in candidates:
        if similarity < minimum:
            break
        if required in result or available in used_profile_skills:
            continue
        result[required] = available
        used_profile_skills.add(available)
    return result


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if not norm_a or not norm_b:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _weighted_score(components: list[ScoreComponent]) -> float:
    total_weight = sum(component.weight for component in components)
    if total_weight == 0:
        return 0.0
    weighted = sum(component.score * component.weight for component in components)
    return weighted / (5 * total_weight)


def _apply_risk_penalty(score: float, risk_level: RiskLevel) -> float:
    if risk_level == "high":
        score -= 0.35
    elif risk_level == "medium":
        score -= 0.10
    return max(0.0, min(1.0, score))


def _ghost_job_risk(job: JobPosting) -> tuple[list[str], RiskLevel]:
    text = _job_text(job)
    flags: list[str] = []
    points = 0

    if job.posted_at:
        age_days = (date.today() - job.posted_at).days
        if age_days > 120:
            flags.append(f"Anzeige ist sehr alt ({age_days} Tage).")
            points += 3
        elif age_days > 60:
            flags.append(f"Anzeige ist alt ({age_days} Tage).")
            points += 2
        elif age_days > 30:
            flags.append(f"Anzeige ist seit {age_days} Tagen online.")
            points += 1

    description_len = len(job.description.strip())
    if description_len < 120:
        flags.append("Beschreibung ist sehr kurz.")
        points += 1
    if not job.requirements and not job.requirements_raw.strip():
        flags.append("Keine konkreten Anforderungen erkannt.")
        points += 1

    company = _clean_text(job.company)
    if not company or company in {"unknown", "n/a", "firma", "company"} or "vertraulich" in company:
        flags.append("Unternehmen ist unklar oder anonym.")
        points += 2

    for term, label in _SCAM_TERMS.items():
        if term in text:
            flags.append(label)
            points += 3

    generic_title = any(term in _clean_text(job.title) for term in ("nebenjob", "heimarbeit", "job angebot"))
    if generic_title and description_len < 250:
        flags.append("Rolle ist sehr generisch beschrieben.")
        points += 2

    if job.salary_range and any(term in text for term in ("werkstudent", "praktikum", "internship")):
        _low, high = job.salary_range
        if high > 90000:
            flags.append("Gehalt wirkt fuer studentische Rolle unrealistisch hoch.")
            points += 2

    if points >= 5:
        level: RiskLevel = "high"
    elif points >= 3:
        level = "medium"
    else:
        level = "low"
    return flags, level


def _recommendation(score: float, risk_level: RiskLevel) -> Recommendation:
    if risk_level == "high" or score < 0.35:
        return "skip"
    if score >= 0.80:
        return "strong"
    if score >= 0.60:
        return "good"
    return "maybe"


def _score_summary(
    job: JobPosting,
    matched: list[str],
    required: set[str],
    risk_level: RiskLevel,
    recommendation: Recommendation,
) -> str:
    risk_label = {"low": "niedrig", "medium": "mittel", "high": "hoch"}[risk_level]
    rec_label = {
        "strong": "Sehr guter Fit",
        "good": "Guter Fit",
        "maybe": "Pruefen",
        "skip": "Eher nicht priorisieren",
    }[recommendation]
    skill_part = (
        f"{len(matched)}/{len(required)} Muss-Skills passen"
        if required
        else "Muss-Skills nicht strukturiert"
    )
    remote = ", Remote moeglich" if job.remote else ""
    return f"{rec_label}: {skill_part}{remote}. Risiko: {risk_label}."


def _rationale(
    job: JobPosting,
    matched: list[str],
    required: set[str],
    missing: list[str],
    components: list[ScoreComponent],
    risk_flags: list[str],
    score: float,
) -> str:
    location = next(item for item in components if item.key == "location")
    quality = next(item for item in components if item.key == "posting_quality")
    missing_text = f" Fehlend: {', '.join(missing)}." if missing else " Keine Muss-Skills fehlen."
    risk_text = (
        f" Risiko-Hinweise: {'; '.join(risk_flags[:3])}."
        if risk_flags
        else " Keine starken Ghost-Job-Signale."
    )
    return (
        f"{len(matched)}/{len(required)} Muss-Skills passen fuer {job.title} bei {job.company}."
        f"{missing_text} {location.evidence} {quality.evidence}{risk_text}"
        f" Gesamtbewertung: {score:.2f}."
    )


def _clean_text(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
