"""Read a candidate's CV (Lebenslauf) into plain text, and load/save profiles.

Text extraction supports the formats students actually hand in:
    .pdf            -> pdfplumber (page text, joined)
    .docx           -> python-docx (optional dependency)
    .txt/.md/other  -> read as UTF-8 text

The extracted text is handed to ``agents.profiler.run_profiler`` which asks the
LLM to turn it into a structured :class:`UserProfile`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from job_agent.schemas import UserProfile
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# Top-level keys UserProfile accepts. We filter to these before validation
# because the schema uses ``extra = "forbid"``.
_PROFILE_KEYS = {
    "name",
    "headline",
    "email",
    "phone",
    "location",
    "languages",
    "skills",
    "experience",
    "education",
    "preferences",
}


def extract_cv_text(path: str | Path) -> str:
    """Return the plain text of a CV file. Raises on missing/empty files."""
    cv_path = Path(path)
    if not cv_path.exists():
        raise FileNotFoundError(f"CV file not found: {cv_path}")

    suffix = cv_path.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf(cv_path)
    elif suffix == ".docx":
        text = _extract_docx(cv_path)
    else:
        # .txt, .md, or anything else we treat as UTF-8 text.
        text = cv_path.read_text(encoding="utf-8", errors="replace")

    text = text.strip()
    if not text:
        raise ValueError(f"CV file is empty or unreadable: {cv_path}")
    log.info("[cv] extracted %d chars from %s", len(text), cv_path.name)
    return text


def _extract_pdf(path: Path) -> str:
    """Extract a PDF's text layer; fall back to OCR for scanned/image PDFs."""
    text = _pdf_text_layer(path)
    if len(text.strip()) >= 30:
        return text
    # No usable text layer (scanned or image-only CV) → OCR the rendered pages.
    log.info("[cv] no text layer in %s — running OCR", path.name)
    ocr_text = _ocr_pdf(path)
    return ocr_text if ocr_text.strip() else text


def _pdf_text_layer(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Reading PDF CVs needs 'pdfplumber'. Install it (uv pip install pdfplumber) "
            "or convert your CV to .txt/.md."
        ) from exc

    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\n".join(pages)


def _ocr_pdf(path: Path) -> str:
    """OCR a scanned/image PDF: render pages with PyMuPDF, read with Tesseract."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "This looks like a scanned/image PDF. OCR needs PyMuPDF "
            "(uv pip install pymupdf)."
        ) from exc

    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise RuntimeError(
            "Scanned/image PDF detected, but the 'tesseract' OCR binary is not on "
            "PATH. Install Tesseract, or provide a text-based PDF / paste the text."
        )

    env = os.environ.copy()
    if not env.get("TESSDATA_PREFIX"):
        tessdata = _find_tessdata(tesseract)
        if tessdata:
            env["TESSDATA_PREFIX"] = tessdata
    langs = _tesseract_langs(env.get("TESSDATA_PREFIX"))

    texts: list[str] = []
    doc = fitz.open(str(path))
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            texts.append(_run_tesseract(tesseract, pix.tobytes("png"), langs, env))
    finally:
        doc.close()
    return "\n\n".join(texts).strip()


def _run_tesseract(tesseract: str, png_bytes: bytes, langs: str, env: dict[str, str]) -> str:
    fd, img_path = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(png_bytes)
        proc = subprocess.run(
            [tesseract, img_path, "stdout", "-l", langs],
            capture_output=True,
            env=env,
            timeout=180,
        )
        return proc.stdout.decode("utf-8", "replace")
    finally:
        try:
            os.remove(img_path)
        except OSError:
            pass


def _find_tessdata(tesseract_path: str) -> str | None:
    """Locate a tessdata directory near the tesseract binary (handles conda)."""
    base = Path(tesseract_path).resolve()
    candidates = [
        base.parent / "tessdata",
        base.parent.parent / "tessdata",
        base.parent.parent / "share" / "tessdata",
        base.parent.parent.parent / "share" / "tessdata",
    ]
    for candidate in candidates:
        if (candidate / "eng.traineddata").exists() or (candidate / "deu.traineddata").exists():
            return str(candidate)
    return None


def _tesseract_langs(tessdata: str | None) -> str:
    if not tessdata:
        return "eng"
    have = {p.stem for p in Path(tessdata).glob("*.traineddata")}
    wanted = [lang for lang in ("deu", "eng") if lang in have]
    return "+".join(wanted) or "eng"


def _extract_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Reading .docx CVs needs 'python-docx'. Install it (uv pip install python-docx) "
            "or convert your CV to .pdf/.txt/.md."
        ) from exc

    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def load_profile_yaml(path: str | Path) -> UserProfile:
    """Load a :class:`UserProfile` from a YAML file (see profile.yaml.example)."""
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile YAML not found: {profile_path}")
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Profile YAML must be a mapping, got {type(data).__name__}")
    return UserProfile.model_validate({k: v for k, v in data.items() if k in _PROFILE_KEYS})


def profile_to_yaml(profile: UserProfile) -> str:
    """Serialize a profile to YAML (used by the ``read-cv`` command's --out)."""
    return str(
        yaml.safe_dump(
            profile.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )
    )
