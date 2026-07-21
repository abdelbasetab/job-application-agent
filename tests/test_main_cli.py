from __future__ import annotations

from pathlib import Path

import pytest
import typer

from job_agent import main
from job_agent.demo_profile import demo_profile
from job_agent.memory.store import Store


def test_cli_profile_resolution_requires_explicit_or_persisted_profile() -> None:
    with pytest.raises(typer.BadParameter, match="Kein Profil"):
        main._resolve_profile(None, None)

    assert main._resolve_profile(None, None, allow_demo=True) == demo_profile()


def test_cli_profile_resolution_reuses_persisted_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    expected = demo_profile().model_copy(update={"name": "Persisted Person"})
    store = Store(db_path)
    try:
        store.save_profile(expected, "cv")
    finally:
        store.close()

    resolved = main._resolve_profile(None, None, db_path=str(db_path))

    assert resolved == expected
