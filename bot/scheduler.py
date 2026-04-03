from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import Settings
from .drop_alert import check_drop
from .metrics.aggregator import MetricFetchError, collect
from .notifier import notify, notify_drop_alert, notify_startup
from .scoring import evaluate
from .state import load_state, save_state

logger = logging.getLogger(__name__)


def run_check_cycle(settings: Settings) -> None:
    """Ciclo padrão: coleta métricas, pontua, verifica queda semanal e notifica."""
    logger.info("Iniciando ciclo de verificação...")
    try:
        snapshot = collect(settings)

        # --- Verificação de queda semanal (independente do scoring) ---
        state = load_state()
        drop_result, new_state = check_drop(
            current_price=snapshot.btc_price_usd,
            price_7d_ago=snapshot.price_7d_ago,
            state=state,
        )
        save_state(new_state)

        if drop_result.signal_triggered:
            notify_drop_alert(snapshot, drop_result, settings)

        # --- Scoring de métricas (MVRV + F&G + MAs) ---
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

    except MetricFetchError as exc:
        logger.error("Ciclo pulado — falha ao obter métricas obrigatórias: %s", exc)
    except Exception as exc:
        logger.exception("Erro inesperado no ciclo de verificação: %s", exc)


def run_weekly_status(settings: Settings) -> None:
    """Resumo semanal: sempre envia, independente da pontuação."""
    logger.info("Enviando resumo semanal...")
    try:
        snapshot = collect(settings)
        result = evaluate(snapshot, settings)
        notify(snapshot, result, settings, force=True)
    except MetricFetchError as exc:
        logger.error("Resumo semanal pulado — falha ao obter métricas: %s", exc)
    except Exception as exc:
        logger.exception("Erro inesperado no resumo semanal: %s", exc)


def start(settings: Settings) -> None:
    import datetime

    # Envia startup antes de calcular next_run_time para evitar "Run time missed"
    notify_startup(settings)

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")

    scheduler.add_job(
        run_check_cycle,
        trigger=IntervalTrigger(minutes=settings.check_interval_minutes),
        kwargs={"settings": settings},
        id="check_cycle",
        name="Verificação de métricas Bitcoin",
        next_run_time=datetime.datetime.now(),
    )

    if settings.weekly_status_enabled:
        scheduler.add_job(
            run_weekly_status,
            trigger=CronTrigger(day_of_week="sun", hour=9, minute=0, timezone="America/Sao_Paulo"),
            kwargs={"settings": settings},
            id="weekly_status",
            name="Resumo semanal Bitcoin",
        )
        logger.info("Resumo semanal agendado: todo domingo às 09h (Brasília).")

    def _shutdown(signum, frame):
        logger.info("Sinal %d recebido — encerrando...", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "Scheduler iniciado. Verificação a cada %d minuto(s). Ctrl+C para encerrar.",
        settings.check_interval_minutes,
    )
    scheduler.start()
