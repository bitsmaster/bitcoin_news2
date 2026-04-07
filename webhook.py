"""
Telegram webhook endpoint for the Bitcoin bot.

Handles /btc and /status commands sent via Telegram Bot API.
Only processes messages from TELEGRAM_CHAT_ID (unauthorized chats are silently ignored).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="Bitcoin Bot Webhook")

_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
_ALLOWED_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")


# ---------------------------------------------------------------------------
# Telegram API helper
# ---------------------------------------------------------------------------

def send_message(chat_id: str, text: str) -> None:
    """Send a text message to a Telegram chat via Bot API."""
    url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Telegram reply sent to chat_id=%s", chat_id)
    except Exception as exc:
        logger.error("Failed to send Telegram message to chat_id=%s: %s", chat_id, exc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_btc(chat_id: str) -> None:
    """Collect metrics, score, and reply with the full report."""
    try:
        from bot.config import load as load_settings
        from bot.metrics.aggregator import collect, MetricFetchError
        from bot.notifier import format_message
        from bot.scoring import evaluate

        settings = load_settings()
        snapshot = collect(settings)
        result = evaluate(snapshot, settings)
        message = format_message(snapshot, result)
        send_message(chat_id, message)
    except Exception as exc:
        logger.exception("Error running BTC check: %s", exc)
        send_message(chat_id, f"⚠️ Erro ao coletar dados do Bitcoin: {exc}")


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    """
    Receive Telegram updates via webhook.
    Returns 200 immediately; slow work runs in a background thread.
    """
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        # Malformed payload — acknowledge and discard
        return JSONResponse({"ok": True})

    message: dict[str, Any] = (
        data.get("message")
        or data.get("edited_message")
        or {}
    )
    if not message:
        return JSONResponse({"ok": True})

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()

    # Security: ignore any chat that is not the configured owner
    if chat_id != _ALLOWED_CHAT_ID:
        logger.warning("Ignored update from unauthorized chat_id=%s", chat_id)
        return JSONResponse({"ok": True})

    logger.info("Received command '%s' from chat_id=%s", text, chat_id)

    if text.startswith("/btc"):
        # Run in a thread so the webhook responds immediately
        threading.Thread(target=_handle_btc, args=(chat_id,), daemon=True).start()

    elif text.startswith("/status"):
        send_message(chat_id, "🤖 Bot online and running")

    else:
        logger.debug("Unhandled text: %s", text)

    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
