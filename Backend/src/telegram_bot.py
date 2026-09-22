"""Telegram notifications, fire-and-forget from a daemon thread.

Credentials are read from the environment at call time (``config.settings``
has already loaded ``.env``), never cached at import, so tests and rotations
do not need a process restart. The bot token is part of every Telegram URL, and
``requests`` puts the URL into its exception text, so exceptions are logged by
class name only — never ``str(exc)``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading

log = logging.getLogger("chanakya.telegram")

_API = "https://api.telegram.org"
_warned_unconfigured = False


def _credentials() -> tuple[str | None, str | None]:
    from config import settings  # noqa: F401 - imported for its .env side effect

    return os.getenv("TELEGRAM_BOT_TOKEN") or None, os.getenv("TELEGRAM_CHAT_ID") or None


def telegram_configured() -> bool:
    token, chat_id = _credentials()
    return bool(token and chat_id)


def send_telegram_alert(
    object_type: str, threat_score: int, image_path: str | None = None, extra: str | None = None
) -> bool:
    """Queue one alert message (photo with caption when a snapshot exists)."""
    global _warned_unconfigured
    token, chat_id = _credentials()
    if not token or not chat_id:
        if not _warned_unconfigured:
            log.warning("Telegram alerts disabled: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
            _warned_unconfigured = True
        return False

    caption = f"PROJECT CHANAKYA ALERT\nThreat detected: {object_type}\nThreat score: {int(threat_score)}%"
    if extra:
        caption += f"\nReasons: {extra}"
    threading.Thread(
        target=_send, args=(token, chat_id, caption, image_path), daemon=True, name="telegram-alert"
    ).start()
    return True


def _send(token: str, chat_id: str, caption: str, image_path: str | None) -> None:
    import requests

    try:
        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as photo:
                response = requests.post(
                    f"{_API}/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": photo},
                    timeout=15,
                )
        else:
            response = requests.post(
                f"{_API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": caption},
                timeout=10,
            )
        if response.status_code == 200:
            log.info("Telegram alert sent")
            return
        description = ""
        with contextlib.suppress(Exception):  # non-JSON error bodies are fine to ignore
            description = str(response.json().get("description", ""))
        log.warning("Telegram rejected the alert: HTTP %s %s", response.status_code, description[:200])
    except Exception as exc:  # noqa: BLE001 - exception text contains the bot token
        log.warning("Telegram send failed: %s", type(exc).__name__)
