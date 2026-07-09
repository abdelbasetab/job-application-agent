"""German application export package.

Renders real PDFs (fpdf2) in a formal German layout — sender block, recipient,
place + date, the cover letter, and an attachments line — plus a CV from the
structured profile and a job snapshot, bundled into one per-application zip.

fpdf2's core Helvetica covers German umlauts (latin-1). Text is sanitised so
smart quotes, dashes, the euro sign, etc. never crash the PDF writer.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from job_agent.schemas import GeneratedApplication, JobPosting, MatchResult, UserProfile
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# Characters outside latin-1 (or ambiguous) -> safe equivalents. Keys are built
# with chr(codepoint) so no ambiguous literals appear in the source file.
_LATIN1_MAP = {
    chr(0x2018): "'",
    chr(0x2019): "'",
    chr(0x201A): "'",
    chr(0x201B): "'",
    chr(0x201C): '"',
    chr(0x201D): '"',
    chr(0x201E): '"',
    chr(0x201F): '"',
    chr(0x2013): "-",
    chr(0x2014): "-",
    chr(0x2026): "...",
    chr(0x2022): "-",
    chr(0x00A0): " ",
    chr(0x20AC): "EUR",
    chr(0x2192): "->",
}


@dataclass(frozen=True)
class ExportResult:
    out_dir: Path
    files: list[str]
    zip_name: str


def _latin1(text: str) -> str:
    """Make text safe for fpdf2 core fonts (latin-1); keeps German umlauts."""
    for src, dst in _LATIN1_MAP.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("`", "")
    return text


def export_application(
    job: JobPosting,
    application: GeneratedApplication,
    profile: UserProfile,
    *,
    out_dir: str | Path,
    match: MatchResult | None = None,
    cv_source_path: str | Path | None = None,
) -> ExportResult:
    """Render anschreiben.pdf + lebenslauf.pdf + job_snapshot.json, then zip them."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    files: list[str] = []

    cover = target / "anschreiben.pdf"
    _render_cover_letter(cover, job, application, profile)
    files.append(cover.name)

    cv_source = Path(cv_source_path) if cv_source_path else None
    if cv_source is not None and cv_source.is_file():
        if cv_source.suffix.lower() == ".pdf":
            cv = target / "lebenslauf.pdf"
            shutil.copyfile(cv_source, cv)
            files.append(cv.name)
        else:
            cv = target / f"lebenslauf_original{cv_source.suffix.lower()}"
            shutil.copyfile(cv_source, cv)
            files.append(cv.name)
    else:
        cv = target / "lebenslauf.pdf"
        _render_cv(cv, profile, match=match)
        files.append(cv.name)

    snapshot = target / "job_snapshot.json"
    snapshot.write_text(
        json.dumps(_snapshot(job, match), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files.append(snapshot.name)

    zip_name = f"bewerbung_{_safe_slug(job.id)}.zip"
    with zipfile.ZipFile(target / zip_name, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(target / name, arcname=name)

    log.info("[export] wrote %d files + zip to %s", len(files), target)
    return ExportResult(out_dir=target, files=files, zip_name=zip_name)


def _new_pdf() -> Any:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(25, 20, 25)
    return pdf


def _line(pdf: Any, text: str, *, height: float = 5.0, align: str = "L") -> None:
    from fpdf.enums import XPos, YPos

    pdf.cell(0, height, _latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align)


def _para(pdf: Any, text: str, *, height: float = 6.0) -> None:
    pdf.multi_cell(0, height, _latin1(text))


def _render_cover_letter(
    path: Path,
    job: JobPosting,
    application: GeneratedApplication,
    profile: UserProfile,
) -> None:
    pdf = _new_pdf()

    pdf.set_font("Helvetica", size=10)
    for line in [profile.name, profile.location, profile.email or "", profile.phone or ""]:
        if line:
            _line(pdf, line)
    pdf.ln(6)

    pdf.set_font("Helvetica", size=11)
    _line(pdf, job.company)
    if job.location:
        _line(pdf, job.location)
    pdf.ln(4)

    place = profile.location or "Ort"
    _line(pdf, f"{place}, den {date.today().strftime('%d.%m.%Y')}", align="R")
    pdf.ln(4)

    body = _strip_markdown(application.cover_letter_md).strip()
    for paragraph in body.split("\n\n"):
        collapsed = " ".join(paragraph.split())
        if not collapsed:
            continue
        pdf.set_font("Helvetica", size=11)
        _para(pdf, collapsed)
        pdf.ln(2)

    pdf.ln(4)
    pdf.set_font("Helvetica", style="I", size=9)
    _para(pdf, "Anlagen: Lebenslauf")
    pdf.output(str(path))


def _tailored_skills(profile: UserProfile, match: MatchResult | None) -> list[str]:
    """Match-relevante Skills zuerst — das ATS/der Recruiter sieht sie sofort.

    Reordering only, never invention: the list stays exactly the profile's
    skills, matched ones move to the front (career-ops: „reformulieren, nie
    erfinden").
    """
    if match is None or not match.matched_skills:
        return list(profile.skills)
    matched = {skill.lower() for skill in match.matched_skills}
    front = [skill for skill in profile.skills if skill.lower() in matched]
    rest = [skill for skill in profile.skills if skill.lower() not in matched]
    return front + rest


def _render_cv(path: Path, profile: UserProfile, match: MatchResult | None = None) -> None:
    pdf = _new_pdf()

    pdf.set_font("Helvetica", style="B", size=18)
    _line(pdf, profile.name, height=9)
    pdf.set_font("Helvetica", size=12)
    if profile.headline:
        _line(pdf, profile.headline, height=6)
    contact = " - ".join(
        part for part in [profile.location, profile.email or "", profile.phone or ""] if part
    )
    if contact:
        pdf.set_font("Helvetica", size=10)
        _line(pdf, contact, height=6)
    pdf.ln(4)

    skills = _tailored_skills(profile, match)
    if skills:
        _section(pdf, "Kenntnisse")
        if match is not None and match.matched_skills:
            pdf.set_font("Helvetica", style="I", size=9)
            _line(
                pdf,
                "Fokus fuer diese Bewerbung: " + ", ".join(match.matched_skills[:6]),
                height=5,
            )
        pdf.set_font("Helvetica", size=11)
        _para(pdf, ", ".join(skills))
        pdf.ln(2)

    if profile.experience:
        _section(pdf, "Berufserfahrung")
        for exp in profile.experience:
            pdf.set_font("Helvetica", style="B", size=11)
            _line(pdf, f"{exp.role}, {exp.company}")
            pdf.set_font("Helvetica", style="I", size=9)
            _line(pdf, f"{exp.start} - {exp.end or 'heute'}", height=5)
            if exp.summary:
                pdf.set_font("Helvetica", size=10)
                _para(pdf, exp.summary, height=5)
            pdf.ln(2)

    if profile.education:
        _section(pdf, "Ausbildung")
        for edu in profile.education:
            pdf.set_font("Helvetica", style="B", size=11)
            _line(pdf, f"{edu.degree} {edu.field}".strip())
            pdf.set_font("Helvetica", style="I", size=9)
            _line(pdf, f"{edu.institution} ({edu.start} - {edu.end or 'heute'})", height=5)
            pdf.ln(2)

    if profile.languages:
        _section(pdf, "Sprachen")
        pdf.set_font("Helvetica", size=11)
        _para(pdf, ", ".join(f"{code}: {level}" for code, level in profile.languages.items()))

    pdf.output(str(path))


def _section(pdf: Any, title: str) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", style="B", size=12)
    _line(pdf, title.upper(), height=7)


def _snapshot(job: JobPosting, match: MatchResult | None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "captured_at": date.today().isoformat(),
        "job": job.model_dump(mode="json"),
    }
    if match is not None:
        data["match"] = match.model_dump(mode="json")
    return data


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "job"
