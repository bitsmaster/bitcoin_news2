from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import Settings
from .drop_alert import check_drop
from .metrics.aggregator import MetricFetchError, collect, collect_alternative
from .notifier import notify, notify_collection_error, notify_drop_alert, notify_startup
from .scoring import evaluate
from .state import load_state, save_state

logger = logging.getLogger(__name__)

_scheduler: BlockingScheduler | None = None
_RETRY_JOB_ID = "check_cycle_retry"


def _execute_cycle(snapshot, settings: Settings) -> None:
    """Executa scoring, drop-alert e notificação a partir de um snapshot já coletado."""
    state = load_state()
    drop_result, new_state = check_drop(
        current_price=snapshot.btc_price_usd,
        price_7d_ago=snapshot.price_7d_ago,
        state=state,
        threshold_pct=settings.drop_alert_threshold_pct,
        cooldown_days=settings.drop_alert_cooldown_days,
    )
    save_state(new_state)

    if drop_result.signal_triggered:
        notify_drop_alert(snapshot, drop_result, settings)

    result = evaluate(snapshot, settings)
    logger.info(
        "BTC: $%s | MVRV: %s | F&G: %s | Pontuação: %d/100 — %s",
        f"{snapshot.btc_price_usd:,.0f}",
        f"{snapshot.mvrv_ratio:.2f}" if snapshot.mvrv_ratio is not None else "N/A",
        f"{snapshot.fear_greed_value}" if snapshot.fear_greed_value is not None else "N/A",
        result.total_score,
        result.signal_label,
    )
    notify(snapshot, result, settings)


def _schedule_retry(settings: Settings) -> None:
    """Agenda uma nova tentativa de coleta para daqui a 1 hora."""
    if _scheduler is None:
        return
    import datetime as _dt

    # Remove job de retry anterior caso já exista
    try:
        _scheduler.remove_job(_RETRY_JOB_ID)
    except Exception:
        pass

    retry_time = _dt.datetime.now() + _dt.timedelta(hours=1)
    _scheduler.add_job(
        _run_retry_cycle,
        trigger="date",
        run_date=retry_time,
        kwargs={"settings": settings},
        id=_RETRY_JOB_ID,
        name="Retry — coleta de métricas (1h após falha)",
    )
    logger.info(
        "Nova tentativa de coleta agendada para %s.",
        retry_time.strftime("%d/%m %H:%M"),
    )


def _run_retry_cycle(settings: Settings) -> None:
    """
    Retry após falha de coleta:
      1. Tenta CoinGecko novamente.
      2. Se ainda falhar, tenta Binance (fonte alternativa).
      3. Se ambos falharem, envia notificação de erro.
    """
    logger.info("Iniciando retry de coleta — tentando CoinGecko novamente...")
    try:
        snapshot = collect(settings)
        logger.info("Retry bem-sucedido via CoinGecko. Executando ciclo normal.")
        _execute_cycle(snapshot, settings)
        return
    except MetricFetchError as exc:
        logger.warning("CoinGecko falhou novamente no retry: %s. Tentando Binance...", exc)

    try:
        snapshot = collect_alternative(settings)
        logger.info("Retry bem-sucedido via Binance. Executando ciclo normal.")
        _execute_cycle(snapshot, settings)
    except MetricFetchError as exc:
        logger.error("Retry falhou em todas as fontes — CoinGecko e Binance indisponíveis: %s", exc)
        notify_collection_error(str(exc), settings)
    except Exception as exc:
        logger.exception("Erro inesperado no retry de coleta: %s", exc)


def run_check_cycle(settings: Settings) -> None:
    """Ciclo padrão: coleta métricas, pontua, verifica queda semanal e notifica."""
    logger.info("Iniciando ciclo de verificação...")
    try:
        snapshot = collect(settings)
        _execute_cycle(snapshot, settings)
    except MetricFetchError as exc:
        logger.error("Ciclo pulado — falha ao obter métricas obrigatórias: %s", exc)
        _schedule_retry(settings)
    except Exception as exc:
        logger.exception("Erro inesperado no ciclo de verificação: %s", exc)


def run_weekly_status(settings: Settings) -> None:
    """Resumo semanal: sempre envia, independente da pontuação."""
    logger.info("Enviando resumo semanal...")
    try:
        snapshot = collect(settings)
        result = evaluate(snapshot, settings)

        from .news import get_weekly_crypto_news
        from .metrics.trending import get_trending_coins

        news = []
        try:
            news = get_weekly_crypto_news()
            logger.info("Notícias da semana obtidas: %d itens.", len(news))
        except Exception as exc:
            logger.warning("Não foi possível obter notícias da semana: %s", exc)

        trending = []
        try:
            trending = get_trending_coins()
            logger.info("Trending coins obtidas: %d itens.", len(trending))
        except Exception as exc:
            logger.warning("Não foi possível obter trending coins: %s", exc)

        notify(snapshot, result, settings, force=True, news=news, trending=trending)
    except MetricFetchError as exc:
        logger.error("Resumo semanal pulado — falha ao obter métricas: %s", exc)
    except Exception as exc:
        logger.exception("Erro inesperado no resumo semanal: %s", exc)


def start(settings: Settings) -> None:
    global _scheduler
    import datetime

    # Envia startup antes de calcular next_run_time para evitar "Run time missed"
    notify_startup(settings)

    _scheduler = BlockingScheduler(timezone="America/Sao_Paulo")

    _scheduler.add_job(
        run_check_cycle,
        trigger=CronTrigger(hour=settings.check_hour, minute=settings.check_minute, timezone="America/Sao_Paulo"),
        kwargs={"settings": settings},
        id="check_cycle",
        name="Verificação de métricas Bitcoin",
        next_run_time=datetime.datetime.now(),
    )

    if settings.weekly_status_enabled:
        _scheduler.add_job(
            run_weekly_status,
            trigger=CronTrigger(day_of_week="sun", hour=9, minute=0, timezone="America/Sao_Paulo"),
            kwargs={"settings": settings},
            id="weekly_status",
            name="Resumo semanal Bitcoin",
        )
        logger.info("Resumo semanal agendado: todo domingo às 09h (Brasília).")

    def _shutdown(signum, frame):
        logger.info("Sinal %d recebido — encerrando...", signum)
        _scheduler.shutdown(wait=False)
        sys.exit(0)

    import threading
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "Scheduler iniciado. Verificação diária às %02d:%02d (Brasília). Ctrl+C para encerrar.",
        settings.check_hour,
        settings.check_minute,
    )
    _scheduler.start()
