from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    # Glassnode (opcional)
    glassnode_api_key: str

    # Telegram
    telegram_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str

    # Email
    email_enabled: bool
    gmail_sender: str
    gmail_app_password: str
    email_recipients: list[str]

    # Agendamento
    check_interval_minutes: int
    weekly_status_enabled: bool

    # Limiares de pontuação
    score_strong_buy: int
    score_moderate_buy: int

    # Agendamento — horário da verificação diária
    check_hour: int
    check_minute: int

    # Alerta de queda
    drop_alert_threshold_pct: float
    drop_alert_cooldown_days: int

    # Logging
    log_level: str
    log_file: str


def load() -> Settings:
    load_dotenv()

    errors: list[str] = []

    def _get(key: str, default: str = "") -> str:
        return os.getenv(key, default).strip()

    def _get_bool(key: str, default: bool = False) -> bool:
        val = _get(key, str(default).lower())
        return val.lower() in ("true", "1", "yes")

    def _get_int(key: str, default: int = 0) -> int:
        val = _get(key, str(default))
        try:
            return int(val)
        except ValueError:
            errors.append(f"{key} deve ser um número inteiro (valor atual: '{val}')")
            return default

    glassnode_api_key = _get("GLASSNODE_API_KEY")

    telegram_enabled = _get_bool("TELEGRAM_ENABLED", False)
    telegram_bot_token = _get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = _get("TELEGRAM_CHAT_ID")

    email_enabled = _get_bool("EMAIL_ENABLED", False)
    gmail_sender = _get("GMAIL_SENDER")
    gmail_app_password = _get("GMAIL_APP_PASSWORD")
    recipients_raw = _get("EMAIL_RECIPIENTS")
    email_recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    check_interval_minutes = _get_int("CHECK_INTERVAL_MINUTES", 1440)
    weekly_status_enabled = _get_bool("WEEKLY_STATUS_ENABLED", True)

    check_hour = _get_int("CHECK_HOUR", 5)
    check_minute = _get_int("CHECK_MINUTE", 0)

    drop_alert_threshold_pct_raw = _get("DROP_ALERT_THRESHOLD_PCT", "10.0")
    try:
        drop_alert_threshold_pct = float(drop_alert_threshold_pct_raw)
    except ValueError:
        errors.append(f"DROP_ALERT_THRESHOLD_PCT deve ser um número (valor atual: '{drop_alert_threshold_pct_raw}')")
        drop_alert_threshold_pct = 10.0
    drop_alert_cooldown_days = _get_int("DROP_ALERT_COOLDOWN_DAYS", 7)

    score_strong_buy = _get_int("SCORE_STRONG_BUY", 45)
    score_moderate_buy = _get_int("SCORE_MODERATE_BUY", 30)

    log_level = _get("LOG_LEVEL", "INFO").upper()
    log_file = _get("LOG_FILE", "bitcoin_bot.log")

    # Validações
    if not telegram_enabled and not email_enabled:
        errors.append(
            "Pelo menos um notificador deve estar ativo. "
            "Configure TELEGRAM_ENABLED=true ou EMAIL_ENABLED=true"
        )

    if telegram_enabled:
        if not telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN é obrigatório quando TELEGRAM_ENABLED=true")
        if not telegram_chat_id:
            errors.append("TELEGRAM_CHAT_ID é obrigatório quando TELEGRAM_ENABLED=true")

    if email_enabled:
        if not gmail_sender:
            errors.append("GMAIL_SENDER é obrigatório quando EMAIL_ENABLED=true")
        if not gmail_app_password:
            errors.append("GMAIL_APP_PASSWORD é obrigatório quando EMAIL_ENABLED=true")
        if not email_recipients:
            errors.append("EMAIL_RECIPIENTS é obrigatório quando EMAIL_ENABLED=true")

    if check_interval_minutes < 1:
        errors.append("CHECK_INTERVAL_MINUTES deve ser >= 1")

    if not (0 <= check_hour <= 23):
        errors.append(f"CHECK_HOUR deve ser entre 0 e 23 (valor atual: {check_hour})")
    if not (0 <= check_minute <= 59):
        errors.append(f"CHECK_MINUTE deve ser entre 0 e 59 (valor atual: {check_minute})")
    if drop_alert_threshold_pct <= 0:
        errors.append(f"DROP_ALERT_THRESHOLD_PCT deve ser > 0 (valor atual: {drop_alert_threshold_pct})")
    if drop_alert_cooldown_days < 1:
        errors.append(f"DROP_ALERT_COOLDOWN_DAYS deve ser >= 1 (valor atual: {drop_alert_cooldown_days})")

    if score_moderate_buy >= score_strong_buy:
        errors.append(
            f"SCORE_STRONG_BUY ({score_strong_buy}) deve ser maior que "
            f"SCORE_MODERATE_BUY ({score_moderate_buy})"
        )

    if errors:
        msg = "Erros de configuração encontrados:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigError(msg)

    return Settings(
        glassnode_api_key=glassnode_api_key,
        telegram_enabled=telegram_enabled,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        email_enabled=email_enabled,
        gmail_sender=gmail_sender,
        gmail_app_password=gmail_app_password,
        email_recipients=email_recipients,
        check_interval_minutes=check_interval_minutes,
        weekly_status_enabled=weekly_status_enabled,
        check_hour=check_hour,
        check_minute=check_minute,
        drop_alert_threshold_pct=drop_alert_threshold_pct,
        drop_alert_cooldown_days=drop_alert_cooldown_days,
        score_strong_buy=score_strong_buy,
        score_moderate_buy=score_moderate_buy,
        log_level=log_level,
        log_file=log_file,
    )
