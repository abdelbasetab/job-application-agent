"""Tiny env config helper — loads .env and exposes the few keys the app uses."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_REPO_ROOT / ".env", override=False)


class Settings:
    """A flat settings facade — no fancy validation, this is Sprint 1."""

    # LLM provider — one of: "ollama" (default), "openai", "kiconnect",
    # "anthropic", "groq". "openai" and "kiconnect" are OpenAI-compatible and
    # share OPENAI_API_KEY + LLM_BASE_URL (KI-Connect = a hosted OpenAI gateway).
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    llm_call_timeout: float = float(os.getenv("LLM_CALL_TIMEOUT", "45"))
    # Optional custom endpoint — used by Ollama (http://localhost:11434) or self-hosted gateways.
    llm_base_url: str | None = os.getenv("LLM_BASE_URL") or None
    enable_llm_agents: bool = os.getenv("ENABLE_LLM_AGENTS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    enable_chroma: bool = os.getenv("ENABLE_CHROMA", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

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

    # Optional real embeddings via the OpenAI-compatible gateway (e.g. KI-Connect).
    # A model the gateway exposes, e.g. "Qwen 3 Embedding 8B".
    # Empty -> ProfileVectorStore uses offline hash embeddings.
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")

    # Optional polite detail-page scraper (ADR-0005), off by default.
    enable_scraper: bool = os.getenv("ENABLE_SCRAPER", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    scraper_min_interval: float = float(os.getenv("SCRAPER_MIN_INTERVAL", "2.0"))

    # Optional SMTP submission for Tracker. Dry-run is the safe default.
    email_smtp_host: str | None = os.getenv("EMAIL_SMTP_HOST") or None
    email_smtp_port: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    email_smtp_user: str | None = os.getenv("EMAIL_SMTP_USER") or None
    email_smtp_password: str | None = os.getenv("EMAIL_SMTP_PASSWORD") or None
    email_from: str | None = os.getenv("EMAIL_FROM") or None
    email_demo_recipient: str | None = os.getenv("EMAIL_DEMO_RECIPIENT") or None
    email_use_tls: bool = os.getenv("EMAIL_USE_TLS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    email_dry_run: bool = os.getenv("EMAIL_DRY_RUN", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    @property
    def llm_api_key(self) -> str | None:
        """Return the API key for the configured provider (None for Ollama)."""
        provider = self.llm_provider.lower()
        if provider in {"openai", "kiconnect"}:
            return self.openai_api_key
        if provider == "anthropic":
            return self.anthropic_api_key
        if provider == "groq":
            return self.groq_api_key
        return None  # ollama needs no key


settings = Settings()
