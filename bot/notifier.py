from __future__ import annotations

import logging
import re
import smtplib
from email.mime.text import MIMEText

import requests

from .config import Settings
from .metrics.aggregator import MetricSnapshot
from .scoring import ScoringResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formatação da mensagem
# ---------------------------------------------------------------------------

def _fmt_usd(value: float) -> str:
    return f"$ {value:,.0f}".replace(",", ".")


def _fmt_brl(value: float) -> str:
    return f"R$ {value:,.0f}".replace(",", ".")


def _ma_position_label(price: float, ma_50: float, ma_200: float) -> str:
    if price < ma_200:
        return "Abaixo da MA200"
    if price < ma_50:
        return "Abaixo da MA50"
    return "Acima de ambas as médias"


def _mvrv_label(mvrv: float | None) -> str:
    if mvrv is None:
        return "Indisponível"
    if mvrv < 1.0:
        return "fundo histórico — zona de acumulação forte"
    if mvrv < 2.0:
        return "zona de acumulação"
    if mvrv <= 3.5:
        return "mercado aquecido"
    return "topo de ciclo — sobrevalorizado"


def _fg_label(value: int | None, classification: str) -> str:
    if value is None:
        return "Indisponível"
    return f"{value} — {classification}"


def format_message(snapshot: MetricSnapshot, result: ScoringResult, weekly: bool = False) -> str:
    ts = snapshot.timestamp.strftime("%d/%m/%Y %H:%M")

    mvrv_pts = f"+{result.mvrv_score} pts" if result.mvrv_used else "0 pts (indisponível)"
    fg_pts = f"+{result.fear_greed_score} pts" if result.fear_greed_used else "0 pts (indisponível)"

    if result.ma_score > 0:
        ma_pts = f"+{result.ma_score} pts"
    else:
        ma_pts = "0 pts"

    ma_pos = _ma_position_label(snapshot.btc_price_usd, snapshot.ma_50, snapshot.ma_200)

    if weekly:
        titulo = "RESUMO SEMANAL — BITCOIN"
    else:
        titulo = f"ALERTA BITCOIN — {result.signal_label.upper()}"

    lines = [
        f"<b>{titulo}</b>",
        "",
        f"<b>Pontuação:</b> {result.total_score}/100 — {result.signal_label}",
        f"<b>Preço:</b> {_fmt_brl(snapshot.btc_price_brl)} ({_fmt_usd(snapshot.btc_price_usd)} USD)",
        f"<b>Data/Hora:</b> {ts}",
        "",
        "─── Métricas ───",
        f"<b>MVRV Ratio:</b> "
        + (f"{snapshot.mvrv_ratio:.2f} — {_mvrv_label(snapshot.mvrv_ratio)}" if snapshot.mvrv_ratio is not None else "Indisponível")
        + f"  ({mvrv_pts})",
        f"<b>Fear & Greed:</b> {_fg_label(snapshot.fear_greed_value, snapshot.fear_greed_classification)}  ({fg_pts})",
        f"<b>Média 50 dias:</b>  {_fmt_usd(snapshot.ma_50)}",
        f"<b>Média 200 dias:</b> {_fmt_usd(snapshot.ma_200)}",
        f"<b>Posição vs MAs:</b> {ma_pos}  ({ma_pts})",
    ]

    if snapshot.fetch_errors:
        lines += ["", "⚠️ Erros parciais: " + " | ".join(snapshot.fetch_errors)]

    if not weekly and result.signal_level != "NENHUM":
        lines += [
            "",
            "─── Interpretação ───",
            _build_interpretation(snapshot, result),
        ]

    lines += [
        "",
        "⚠️  Isso NÃO é conselho financeiro. Faça sua própria análise.",
    ]

    return "\n".join(lines)


def _build_interpretation(snapshot: MetricSnapshot, result: ScoringResult) -> str:
    parts = []
    if snapshot.mvrv_ratio is not None and snapshot.mvrv_ratio < 1.0:
        parts.append("Bitcoin está sendo negociado abaixo do seu valor realizado (MVRV < 1)")
    if snapshot.fear_greed_value is not None and snapshot.fear_greed_value < 25:
        parts.append("o sentimento de mercado indica pânico extremo")
    if snapshot.btc_price_usd < snapshot.ma_200:
        parts.append("o preço está abaixo da média histórica de longo prazo (MA200)")
    elif snapshot.btc_price_usd < snapshot.ma_50:
        parts.append("o preço está abaixo da média de curto prazo (MA50)")

    if not parts:
        return "Múltiplos indicadores apontam para uma oportunidade de acumulação gradual."

    sentence = ", ".join(parts[:2])
    if len(parts) > 2:
        sentence += " e " + parts[2]
    return sentence.capitalize() + ". Historicamente, estes são períodos favoráveis para acumulação gradual."


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


# ---------------------------------------------------------------------------
# Envio Telegram
# ---------------------------------------------------------------------------

def send_telegram(message: str, settings: Settings) -> bool:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("Telegram: mensagem enviada com sucesso.")
        return True
    except Exception as exc:
        logger.error("Telegram: falha ao enviar mensagem — %s", exc)
        return False


# ---------------------------------------------------------------------------
# Envio e-mail (Gmail SMTP)
# ---------------------------------------------------------------------------

def send_email(message: str, subject: str, settings: Settings) -> bool:
    plain_text = _strip_html(message)
    msg = MIMEText(plain_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.gmail_sender
    msg["To"] = ", ".join(settings.email_recipients)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(settings.gmail_sender, settings.gmail_app_password)
            smtp.sendmail(
                settings.gmail_sender,
                settings.email_recipients,
                msg.as_string(),
            )
        logger.info("E-mail: mensagem enviada para %s.", settings.email_recipients)
        return True
    except Exception as exc:
        logger.error("E-mail: falha ao enviar mensagem — %s", exc)
        return False


# ---------------------------------------------------------------------------
# Alerta de queda semanal
# ---------------------------------------------------------------------------

def notify_drop_alert(snapshot: MetricSnapshot, drop_result, settings: Settings) -> None:
    """Envia alerta quando detectada queda >= 10% no período de 7 dias."""
    from .drop_alert import DropCheckResult

    result: DropCheckResult = drop_result
    ts = snapshot.timestamp.strftime("%d/%m/%Y %H:%M")
    ref_date_str = result.reference_date.strftime("%d/%m/%Y") if result.reference_date else "?"
    next_check = (snapshot.timestamp.date() + __import__("datetime").timedelta(days=7)).strftime("%d/%m/%Y")

    drop_str = f"{result.drop_pct:.1f}%".replace(".", ",")
    ref_price_usd = _fmt_usd(result.reference_price) if result.reference_price else "?"

    message = (
        f"<b>⚠️ ALERTA BITCOIN — QUEDA DE {drop_str} EM 7 DIAS</b>\n"
        "\n"
        f"<b>Preço atual:</b>      {_fmt_brl(snapshot.btc_price_brl)} ({_fmt_usd(snapshot.btc_price_usd)} USD)\n"
        f"<b>Preço em {ref_date_str}:</b> {ref_price_usd} USD\n"
        f"<b>Variação 7 dias:</b>  -{drop_str}\n"
        f"<b>Data/Hora:</b>        {ts}\n"
        "\n"
        "Queda acumulada de 10%+ em 7 dias — <b>FORTE SINAL DE COMPRA</b> por queda recente.\n"
        "\n"
        f"<b>Próxima verificação de queda:</b> a partir de {next_check} (em 7 dias)\n"
        "\n"
        "⚠️  Isso NÃO é conselho financeiro. Faça sua própria análise."
    )
    subject = f"[Bitcoin Bot] ⚠️ Queda de {drop_str} em 7 dias — {snapshot.timestamp.strftime('%d/%m/%Y')}"

    if settings.telegram_enabled:
        send_telegram(message, settings)
    if settings.email_enabled:
        send_email(message, subject, settings)


# ---------------------------------------------------------------------------
# Notificação de inicialização
# ---------------------------------------------------------------------------

def notify_startup(settings: Settings) -> None:
    """Envia mensagem de confirmação assim que o bot é iniciado."""
    from datetime import datetime

    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    weekly_info = "Sim — todo domingo às 09h" if settings.weekly_status_enabled else "Não"

    message = (
        "<b>Bitcoin Bot iniciado com sucesso</b>\n"
        "\n"
        f"<b>Data/Hora:</b> {ts}\n"
        f"<b>Intervalo de verificação:</b> a cada {settings.check_interval_minutes} minuto(s)\n"
        f"<b>Resumo semanal:</b> {weekly_info}\n"
        f"<b>Limiares:</b> Forte ≥ {settings.score_strong_buy} pts | Moderado ≥ {settings.score_moderate_buy} pts\n"
        "\n"
        "O bot está monitorando Bitcoin e te avisará quando houver sinal de compra."
    )
    subject = "[Bitcoin Bot] Bot iniciado com sucesso"

    if settings.telegram_enabled:
        send_telegram(message, settings)
    if settings.email_enabled:
        send_email(message, subject, settings)


# ---------------------------------------------------------------------------
# Dispatcher principal
# ---------------------------------------------------------------------------

def notify(
    snapshot: MetricSnapshot,
    result: ScoringResult,
    settings: Settings,
    force: bool = False,
) -> None:
    """
    Envia notificação quando há sinal de compra (ou force=True para resumo semanal).
    force=True ignora o nível do sinal e envia mesmo sem alerta.
    """
    if result.signal_level == "NENHUM" and not force:
        return

    weekly = force and result.signal_level == "NENHUM"
    message = format_message(snapshot, result, weekly=weekly)

    if weekly:
        subject = f"[Bitcoin Bot] Resumo Semanal — {snapshot.timestamp.strftime('%d/%m/%Y')}"
    else:
        subject = f"[Bitcoin Bot] {result.signal_label} — BTC {_fmt_usd(snapshot.btc_price_usd)}"

    if settings.telegram_enabled:
        send_telegram(message, settings)

    if settings.email_enabled:
        send_email(message, subject, settings)
