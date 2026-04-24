"""
Telegram webhook endpoint for the Bitcoin bot.

Commands:
  /btc    — Bitcoin analysis (cached 60 s; duplicate calls blocked while in-flight)
  /news   — Latest crypto news (cached 10 min)
  /dollar — USD/BRL fair value vs market rate (PPP, cached 60 min)
  /status — Liveness check

Only processes messages from TELEGRAM_CHAT_ID; all others are silently ignored.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
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

_BTC_CACHE_TTL: int = 60      # seconds — avoids CoinGecko 429s on repeated /btc
_NEWS_CACHE_TTL: int = 600    # 10 minutes — news doesn't change that fast
_DOLLAR_CACHE_TTL: int = 3600 # 1 hour — PPP data is slow-moving


# ---------------------------------------------------------------------------
# Settings (lazy-loaded once; environment never changes at runtime)
# ---------------------------------------------------------------------------

_settings_lock = threading.Lock()
_settings = None


def _get_settings():
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                from bot.config import load as _load
                _settings = _load()
    return _settings


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
_dollar_cache = _Cache()


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
# Generic cache-aware dispatcher
# ---------------------------------------------------------------------------

def _cached_fetch(
    name: str,
    cache: _Cache,
    ttl: int,
    fetch_fn: Callable[[], str],
    chat_id: str,
    in_flight_msg: str,
    error_prefix: str,
) -> None:
    """
    Runs fetch_fn() at most once per TTL window, per cache object.

    State machine (all state transitions under lock; I/O outside):
      cache fresh → reply with cached value immediately
      in_flight   → reply with in_flight_msg
      miss        → set in_flight, call fetch_fn(), update cache
    """
    with cache.lock:
        if cache.is_fresh(ttl):
            logger.info("%s: cache hit (age=%.1fs)", name, time.monotonic() - cache.fetched_at)
            reply = cache.value
        elif cache.in_flight:
            logger.info("%s: fetch already in progress — skipping duplicate", name)
            reply = in_flight_msg
        else:
            reply = None
            cache.in_flight = True

    # Send cached/in-flight reply without holding the lock
    if reply is not None:
        send_message(chat_id, reply)
        return

    # Cache miss — run the actual fetch outside the lock
    try:
        message = fetch_fn()
        with cache.lock:
            cache.value = message
            cache.fetched_at = time.monotonic()
            cache.in_flight = False
        send_message(chat_id, message)
    except Exception as exc:
        logger.exception("%s error: %s", name, exc)
        with cache.lock:
            cache.in_flight = False
        send_message(chat_id, f"⚠️ {error_prefix}: {exc}")


# ---------------------------------------------------------------------------
# /btc
# ---------------------------------------------------------------------------

def _fetch_btc() -> str:
    from bot.metrics.aggregator import collect
    from bot.notifier import format_message
    from bot.scoring import evaluate

    settings = _get_settings()
    snapshot = collect(settings)
    result = evaluate(snapshot, settings)
    return format_message(snapshot, result)


def _handle_btc(chat_id: str) -> None:
    _cached_fetch(
        "/btc", _btc_cache, _BTC_CACHE_TTL, _fetch_btc, chat_id,
        "⏳ Consulta já em andamento. Aguarde alguns segundos e tente novamente.",
        "Erro ao coletar dados do Bitcoin",
    )


# ---------------------------------------------------------------------------
# /news
# ---------------------------------------------------------------------------

def _fetch_news() -> str:
    from bot.news import get_weekly_crypto_news

    items = get_weekly_crypto_news()
    if not items:
        return "📰 Nenhuma notícia disponível no momento."

    lines = ["<b>📰 Notícias Cripto — Últimos 7 dias</b>", ""]
    for item in items:
        lines.append(f'• <a href="{item["link"]}">{item["title"]}</a> — <i>{item["source"]}</i>')
    return "\n".join(lines)


def _handle_news(chat_id: str) -> None:
    _cached_fetch(
        "/news", _news_cache, _NEWS_CACHE_TTL, _fetch_news, chat_id,
        "⏳ Buscando notícias. Aguarde alguns segundos e tente novamente.",
        "Erro ao buscar notícias",
    )


# ---------------------------------------------------------------------------
# /dollar
# ---------------------------------------------------------------------------

def _fmt_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fetch_dollar() -> str:
    from bot.metrics.ppp import get_ppp_data

    d = get_ppp_data()
    market = d["market_rate"]
    ppp = d["ppp_rate"]
    dev = d["deviation_pct"]
    year = d["ppp_year"]

    if dev < -10:
        signal = "🟢 <b>Dólar barato</b> — bom momento para comprar USD"
    elif dev <= 10:
        signal = "🟡 <b>Dólar próximo do valor justo</b>"
    else:
        signal = "🔴 <b>Dólar caro</b>"

    dev_str = f"{dev:+.1f}%".replace(".", ",")
    lines = [
        "<b>💵 Câmbio USD/BRL — Paridade do Poder de Compra</b>",
        "",
        f"<b>Taxa de mercado:</b>  {_fmt_brl(market)}",
        f"<b>Valor justo (PPP):</b> {_fmt_brl(ppp)}  <i>(ref. {year})</i>",
        f"<b>Desvio:</b>           {dev_str} em relação ao valor justo",
        "",
        signal,
        "",
        "⚠️  Isso NÃO é conselho financeiro. Faça sua própria análise.",
    ]
    return "\n".join(lines)


def _handle_dollar(chat_id: str) -> None:
    _cached_fetch(
        "/dollar", _dollar_cache, _DOLLAR_CACHE_TTL, _fetch_dollar, chat_id,
        "⏳ Consultando dados. Aguarde alguns segundos e tente novamente.",
        "Erro ao buscar dados do câmbio",
    )


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
    elif text.startswith("/dollar"):
        threading.Thread(target=_handle_dollar, args=(chat_id,), daemon=True).start()
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
