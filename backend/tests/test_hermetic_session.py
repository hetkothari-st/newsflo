"""The test session must never run with a live scheduler.

WHY THIS EXISTS (final review wave, item 3). app/main.py calls
`_maybe_start_scheduler()` at IMPORT time, and 20+ test modules import
app.main at module level -- so whether the suite spins up a real
BackgroundScheduler (polling real RSS feeds, running the real analysis
loop, writing to the real DB, mid-test) was decided by whatever
ENABLE_SCHEDULER happened to be in the developer's environment.
backend/.env sets it TRUE, because that is what the local runtime needs.

tests/conftest.py forces it false at conftest import time -- before pytest
imports any test module, hence before app.config's Settings() is ever
constructed, and a real environment variable outranks the dotenv file in
pydantic-settings. These tests prove that held, so "the suite is hermetic"
stops being a convention someone can quietly break.
"""
import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_enable_scheduler_resolves_false_even_though_dotenv_says_true():
    from app.config import settings

    env_file = BACKEND / ".env"
    if env_file.exists():
        dotenv = env_file.read_text(encoding="utf-8", errors="ignore")
        # Guard against the test going vacuous: if .env ever stops setting
        # the flag true, this test proves nothing and should be re-pointed.
        assert "ENABLE_SCHEDULER" in dotenv, (
            "backend/.env no longer mentions ENABLE_SCHEDULER -- this test "
            "no longer proves the env var beats the dotenv file")

    assert os.environ["ENABLE_SCHEDULER"] == "false"
    assert settings.enable_scheduler is False


def test_no_scheduler_is_running_in_this_process():
    """app.main's import-time gate must have taken the no-op branch. The
    started scheduler is parked on app.scheduler._scheduler; None means
    nothing was ever started (tests that construct one for assertions --
    tests/test_scheduler_universe.py -- reset it in a finally)."""
    import app.main  # noqa: F401 -- forces the import-time gate to have run
    import app.scheduler

    assert app.scheduler._scheduler is None
