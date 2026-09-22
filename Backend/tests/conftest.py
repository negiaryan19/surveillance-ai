"""Shared pytest configuration.

Everything here must stay importable with only the light dependency set, and
must not import any project module at collection time: six owners' test files
share this conftest, and a broken import here would fail all of them.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = BACKEND_DIR / "config" / "settings.py"

# Importing config.settings loads Backend/.env into os.environ, which on a
# developer machine holds REAL credentials. No test may ever reach Telegram
# with them, so they are removed before every test (tests that need
# credentials set fake ones with monkeypatch.setenv, which runs after this).
_LIVE_CREDENTIALS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

_SETTINGS_ENV = (
    "CHANAKYA_DATA_DIR",
    "CHANAKYA_CAMERAS",
    "CHANAKYA_API_TOKEN",
    "CHANAKYA_CORS_ORIGINS",
    "CHANAKYA_HOST",
    "CHANAKYA_PORT",
    "CHANAKYA_DEBUG",
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: needs heavy optional dependencies or model files; run with -m slow",
    )


@pytest.fixture(autouse=True)
def _no_live_credentials(monkeypatch):
    for name in _LIVE_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)


class FakeClock:
    """A settable UTC clock for DatabaseManager(clock=...)."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def set(self, moment: datetime) -> None:
        self.now = moment


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 22, 14, 30, 0, tzinfo=UTC))


@pytest.fixture
def db(tmp_path, clock):
    from src.database_manager import DatabaseManager

    return DatabaseManager(tmp_path / "db" / "chanakya.db", clock=clock)


@pytest.fixture
def zones_file(tmp_path) -> Path:
    return tmp_path / "data" / "zones.json"


@pytest.fixture
def zone_manager(zones_file):
    from src.zones import ZoneManager

    return ZoneManager(zones_file)


@pytest.fixture
def load_settings(monkeypatch):
    """Execute a PRIVATE copy of config/settings.py under a controlled environment.

    The real ``config.settings`` in ``sys.modules`` is never reloaded (other
    modules hold references to it). ``load_dotenv`` is stubbed out and every
    ``CHANAKYA_*`` variable is cleared first, so the result depends only on the
    ``env`` passed in -- not on the developer's ``.env``.
    """
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    counter = iter(range(10**6))

    def _load(**env: str):
        for name in _SETTINGS_ENV:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        module_name = f"_chanakya_settings_copy_{next(counter)}"
        spec = importlib.util.spec_from_file_location(module_name, SETTINGS_FILE)
        module = importlib.util.module_from_spec(spec)
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(module_name, None)
        return module

    return _load
