"""LivenessResult — is a job posting still open?"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LivenessStatus = Literal["live", "expired", "unknown"]
CheckedVia = Literal["http", "api", "playwright"]


class LivenessResult(BaseModel):
    """Structured verdict on whether a posting is still reachable/open.

    ``status`` is tri-state on purpose — a posting can be clearly open,
    clearly gone, or genuinely uncertain (blocked, timed out, anti-bot). The
    UI maps these to offen / abgelaufen / unsicher and never crashes the
    pipeline on a failed probe.
    """

    url: str
    status: LivenessStatus = "unknown"
    confidence: float = Field(ge=0.0, le=1.0, description="0..1 certainty in the status.")
    reason: str = Field(description="Human-readable explanation of the verdict.")
    checked_via: CheckedVia = "http"
    checked_at: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "forbid"}
