"""
Telegram webhook endpoint for the Bitcoin bot.

Commands:
  /btc    — Bitcoin analysis (cached 60 s; duplicate calls blocked while in-flight)
  /news   — Latest crypto news (cached 10 min)
  /status — Liveness check

Only processes messages from TELEGRAM_CHAT_ID; all others are silently ignored.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
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

_BTC_CACHE_TTL: int = 60    # seconds — avoids CoinGecko 429s on repeated /btc
_NEWS_CACHE_TTL: int = 600  # 10 minutes — news doesn't change that fast


# ---------------------------------------------------------------------------
# Thread-safe in-memory cache
# ---------------------------------------------------------------------------

@dataclass
class _Cache:
    """
    Stores one cached string result with a monotonic timestamp.

    in_flight=True while a fetch thread is running so that concurrent
    callers don't trigger duplicate API calls.
    """
    value: str | None = None
    fetched_at: float = 0.0
    in_flight: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def is_fresh(self, ttl: int) -> bool:
        return self.value is not None and (time.monotonic() - self.fetched_at) < ttl


_btc_cache = _Cache()
_news_cache = _Cache()


# ---------------------------------------------------------------------------
# Telegram API helper
# ---------------------------------------------------------------------------

def send_message(chat_id: str, text: str) -> None:
    """Send an HTML-formatted message to a Telegram chat."""
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
# /btc handler
# ---------------------------------------------------------------------------

def _fetch_btc() -> str:
    """Blocking: collect metrics, evaluate, return formatted HTML string."""
    from bot.config import load as load_settings
    from bot.metrics.aggregator import collect
    from bot.notifier import format_message
    from bot.scoring import evaluate

    settings = load_settings()
    snapshot = collect(settings)
    result = evaluate(snapshot, settings)
    return format_message(snapshot, result)


def _handle_btc(chat_id: str) -> None:
    """
    Cache-aware /btc handler (runs in a daemon thread).

    State machine (all state transitions under lock; I/O outside):
      cache fresh  → reply with cached value immediately
      in_flight    → reply with "already running" message
      miss         → set in_flight, fetch, update cache
    """
    with _btc_cache.lock:
        if _btc_cache.is_fresh(_BTC_CACHE_TTL):
            age = time.monotonic() - _btc_cache.fetched_at
            logger.info("/btc: cache hit (age=%.1fs)", age)
            reply = _btc_cache.value
        elif _btc_cache.in_flight:
            logger.info("/btc: fetch already in progress — skipping duplicate")
            reply = "⏳ Consulta já em andamento. Aguarde alguns segundos e tente novamente."
        else:
            reply = None
            _btc_cache.in_flight = True

    # Send cached/in-flight reply without holding the lock
    if reply is not None:
        send_message(chat_id, reply)
        return

    # Cache miss — run the actual fetch outside the lock
    try:
        message = _fetch_btc()
        with _btc_cache.lock:
            _btc_cache.value = message
            _btc_cache.fetched_at = time.monotonic()
            _btc_cache.in_flight = False
        send_message(chat_id, message)
    except Exception as exc:
        logger.exception("Error running BTC check: %s", exc)
        with _btc_cache.lock:
            _btc_cache.in_flight = False
        send_message(chat_id, f"⚠️ Erro ao coletar dados do Bitcoin: {exc}")


# ---------------------------------------------------------------------------
# /news handler
# ---------------------------------------------------------------------------

def _fetch_news() -> str:
    """Blocking: fetch RSS news and return a formatted HTML string."""
    from bot.news import get_weekly_crypto_news

    items = get_weekly_crypto_news()
    if not items:
        return "📰 Nenhuma notícia disponível no momento."

    lines = ["<b>📰 Notícias Cripto — Últimos 7 dias</b>", ""]
    for item in items:
        lines.append(f'• <a href="{item["link"]}">{item["title"]}</a> — <i>{item["source"]}</i>')

    return "\n".join(lines)


def _handle_news(chat_id: str) -> None:
    """Cache-aware /news handler (runs in a daemon thread)."""
    with _news_cache.lock:
        if _news_cache.is_fresh(_NEWS_CACHE_TTL):
            age = time.monotonic() - _news_cache.fetched_at
            logger.info("/news: cache hit (age=%.1fs)", age)
            reply = _news_cache.value
        elif _news_cache.in_flight:
            reply = "⏳ Buscando notícias. Aguarde alguns segundos e tente novamente."
        else:
            reply = None
            _news_cache.in_flight = True

    if reply is not None:
        send_message(chat_id, reply)
        return

    try:
        message = _fetch_news()
        with _news_cache.lock:
            _news_cache.value = message
            _news_cache.fetched_at = time.monotonic()
            _news_cache.in_flight = False
        send_message(chat_id, message)
    except Exception as exc:
        logger.exception("Error fetching news: %s", exc)
        with _news_cache.lock:
            _news_cache.in_flight = False
        send_message(chat_id, f"⚠️ Erro ao buscar notícias: {exc}")


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/webhook")
async def telegram_webhook(request: Request) -> JSONResponse:
    """
    Receive Telegram updates.  Returns 200 immediately for all valid payloads;
    slow work (API calls) runs in a daemon thread.
    """
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
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

    if chat_id != _ALLOWED_CHAT_ID:
        logger.warning("Ignored update from unauthorized chat_id=%s", chat_id)
        return JSONResponse({"ok": True})

    logger.info("Command '%s' from chat_id=%s", text, chat_id)

    if text.startswith("/btc"):
        threading.Thread(target=_handle_btc, args=(chat_id,), daemon=True).start()
    elif text.startswith("/news"):
        threading.Thread(target=_handle_news, args=(chat_id,), daemon=True).start()
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
