from __future__ import annotations

from job_agent.utils.doctor import Check, run_doctor, worst_status


def test_run_doctor_returns_valid_checks() -> None:
    checks = run_doctor()
    assert checks
    assert all(c.status in {"ok", "warn", "fail"} for c in checks)
    assert all(c.name and c.detail for c in checks)
    # Every non-OK check must offer a concrete fix.
    assert all(c.fix for c in checks if c.status != "ok")
    # In a normal checkout the web assets ship with the package.
    web = next(c for c in checks if "Web-UI" in c.name)
    assert web.status == "ok"


def test_worst_status_precedence() -> None:
    assert worst_status([Check("a", "ok", "x")]) == "ok"
    assert worst_status([Check("a", "ok", "x"), Check("b", "warn", "y")]) == "warn"
    assert worst_status([Check("a", "warn", "x"), Check("b", "fail", "z")]) == "fail"
    assert worst_status([]) == "ok"
