from __future__ import annotations

import logging

from flask import Flask, jsonify, request

from .config import Settings
from .metrics.aggregator import MetricFetchError, collect
from .notifier import format_message, send_telegram
from .scoring import evaluate

logger = logging.getLogger(__name__)

app = Flask(__name__)
_settings: Settings | None = None


def init_app(settings: Settings) -> None:
    global _settings
    _settings = settings


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
def health():
    return jsonify(status="ok")


# ---------------------------------------------------------------------------
# Telegram Webhook
# ---------------------------------------------------------------------------

@app.post("/webhook")
def webhook():
    settings = _settings
    update = request.get_json(silent=True)
    if not update:
        return jsonify(ok=False), 400

    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify(ok=True)  # outros tipos de update (inline, callback, etc.)

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = (message.get("text") or "").strip()

    if chat_id != settings.telegram_chat_id:
        logger.warning("Mensagem ignorada — chat_id não autorizado: %s", chat_id)
        return jsonify(ok=True)

    if text == "/btc" or text.startswith("/btc@"):
        _cmd_btc(settings)
    elif text == "/status" or text.startswith("/status@"):
        send_telegram("🤖 Bot online and running", settings)

    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Handlers de comandos
# ---------------------------------------------------------------------------

def _cmd_btc(settings: Settings) -> None:
    """Coleta métricas, pontua e envia o resultado formatado no chat."""
    try:
        snapshot = collect(settings)
        result = evaluate(snapshot, settings)
        msg = format_message(snapshot, result)
        send_telegram(msg, settings)
    except MetricFetchError as exc:
        logger.error("Webhook /btc — falha ao coletar métricas: %s", exc)
        send_telegram(f"⚠️ Erro ao coletar métricas: {exc}", settings)
    except Exception as exc:
        logger.exception("Webhook /btc — erro inesperado: %s", exc)
        send_telegram(f"⚠️ Erro inesperado: {exc}", settings)
