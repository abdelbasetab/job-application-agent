"""Tiny env config helper — loads .env and exposes the few keys the app uses."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=False)


class Settings:
    """A flat settings facade — no fancy validation, this is Sprint 1."""

    # LLM provider — one of: "ollama" (default), "anthropic", "groq"
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    # Optional custom endpoint — used by Ollama (http://localhost:11434) or self-hosted gateways.
    llm_base_url: str | None = os.getenv("LLM_BASE_URL") or None

    # Provider keys
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    groq_api_key: str | None = os.getenv("GROQ_API_KEY")

    # Job APIs
    adzuna_app_id: str | None = os.getenv("ADZUNA_APP_ID")
    adzuna_app_key: str | None = os.getenv("ADZUNA_APP_KEY")
    adzuna_country: str = os.getenv("ADZUNA_COUNTRY", "de")
    ba_jobsuche_base_url: str = os.getenv(
        "BA_JOBSUCHE_BASE_URL",
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4",
    )
    # Public, fixed API key the BA-Jobsuche API requires on every request.
    # Same value for everyone; without it the server returns 403.
    ba_jobsuche_api_key: str = os.getenv("BA_JOBSUCHE_API_KEY", "jobboerse-jobsuche")

    # Storage
    sqlite_path: str = os.getenv("SQLITE_PATH", "./data/job_agent.db")
    chroma_path: str = os.getenv("CHROMA_PATH", "./data/chroma_db")


settings = Settings()
