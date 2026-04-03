from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from .state import BotState

logger = logging.getLogger(__name__)

COOLDOWN_DAYS = 7
DROP_THRESHOLD_PCT = 10.0


@dataclass
class DropCheckResult:
    checked: bool               # False = pulado por cooldown ou dados insuficientes
    in_cooldown: bool
    days_remaining: int         # dias restantes no cooldown (0 se não estiver em cooldown)
    drop_pct: float | None      # positivo = queda, negativo = alta
    signal_triggered: bool
    reference_price: float | None
    reference_date: date | None


def check_drop(
    current_price: float,
    price_7d_ago: float,
    state: BotState,
) -> tuple[DropCheckResult, BotState]:
    """
    Verifica se houve queda >= 10% no período relevante e atualiza o estado.

    Regra de janela:
    - Sem sinal anterior: compara preço atual vs 7 dias atrás (janela deslizante normal).
    - Após sinal ativo: cooldown de 7 dias. Ao fim do cooldown, compara vs o preço
      no dia do sinal. Se nova queda >= 10%: novo sinal e nova janela de 7 dias.
      Se não houver queda suficiente: reseta para modo normal (próximo ciclo usa
      janela deslizante normal).

    Retorna (resultado, novo_estado).
    """
    today = date.today()
    new_state = BotState(
        last_drop_signal_date=state.last_drop_signal_date,
        last_drop_signal_price=state.last_drop_signal_price,
    )

    if state.last_drop_signal_date is not None:
        last_signal_date = date.fromisoformat(state.last_drop_signal_date)
        days_since = (today - last_signal_date).days

        if days_since < COOLDOWN_DAYS:
            # Ainda em cooldown — não verifica
            days_remaining = COOLDOWN_DAYS - days_since
            logger.info(
                "Verificação de queda: cooldown ativo — %d dia(s) restante(s) (desde %s).",
                days_remaining,
                state.last_drop_signal_date,
            )
            return DropCheckResult(
                checked=False,
                in_cooldown=True,
                days_remaining=days_remaining,
                drop_pct=None,
                signal_triggered=False,
                reference_price=state.last_drop_signal_price,
                reference_date=last_signal_date,
            ), new_state

        # Cooldown encerrado — compara vs preço do dia do sinal
        reference_price = state.last_drop_signal_price  # type: ignore[assignment]
        reference_date = last_signal_date
        drop_pct = (reference_price - current_price) / reference_price * 100

        logger.info(
            "Verificação de queda (pós-cooldown): atual=$%.0f | ref=$%.0f (%s) | variação=%.1f%%",
            current_price, reference_price, reference_date.isoformat(), -drop_pct,
        )

        if drop_pct >= DROP_THRESHOLD_PCT:
            new_state.last_drop_signal_date = today.isoformat()
            new_state.last_drop_signal_price = current_price
            logger.warning("SINAL DE QUEDA DISPARADO (pós-cooldown): %.1f%% de queda.", drop_pct)
        else:
            # Sem nova queda — reseta para modo normal
            new_state.last_drop_signal_date = None
            new_state.last_drop_signal_price = None
            logger.info("Sem nova queda após cooldown — retornando ao modo de janela normal.")

        return DropCheckResult(
            checked=True,
            in_cooldown=False,
            days_remaining=0,
            drop_pct=drop_pct,
            signal_triggered=drop_pct >= DROP_THRESHOLD_PCT,
            reference_price=reference_price,
            reference_date=reference_date,
        ), new_state

    # Modo normal: janela deslizante de 7 dias
    drop_pct = (price_7d_ago - current_price) / price_7d_ago * 100
    reference_date = today - timedelta(days=7)

    logger.info(
        "Verificação de queda (janela normal): atual=$%.0f | 7d atrás=$%.0f | variação=%.1f%%",
        current_price, price_7d_ago, -drop_pct,
    )

    if drop_pct >= DROP_THRESHOLD_PCT:
        new_state.last_drop_signal_date = today.isoformat()
        new_state.last_drop_signal_price = current_price
        logger.warning("SINAL DE QUEDA DISPARADO: %.1f%% de queda em 7 dias.", drop_pct)

    return DropCheckResult(
        checked=True,
        in_cooldown=False,
        days_remaining=0,
        drop_pct=drop_pct,
        signal_triggered=drop_pct >= DROP_THRESHOLD_PCT,
        reference_price=price_7d_ago,
        reference_date=reference_date,
    ), new_state
