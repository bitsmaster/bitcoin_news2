from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..config import Settings
from .coingecko import MetricFetchError, compute_moving_averages, get_current_price, get_historical_prices
from .fear_greed import get_fear_greed_index
from .mvrv import get_mvrv_ratio

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    timestamp: datetime
    btc_price_usd: float
    btc_price_brl: float
    ma_50: float
    ma_200: float
    mvrv_ratio: float | None          # None = falha não fatal
    fear_greed_value: int | None      # None = falha não fatal
    fear_greed_classification: str    # string vazia se falhou
    fetch_errors: list[str] = field(default_factory=list)


def collect(settings: Settings) -> MetricSnapshot:
    """
    Coleta todas as métricas. Falhas em MVRV e Fear & Greed são não fatais
    (campo fica None, ciclo continua). Falha em preço/histórico é fatal.
    """
    errors: list[str] = []

    # --- Obrigatórios (falha cancela o ciclo) ---
    price_usd, price_brl = get_current_price()
    logger.debug("Preço BTC: $%.2f USD / R$%.2f BRL", price_usd, price_brl)

    historical = get_historical_prices(days=200)
    ma_50, ma_200 = compute_moving_averages(historical)
    logger.debug("MA50: $%.2f | MA200: $%.2f", ma_50, ma_200)

    # --- Opcionais (falha registrada, ciclo continua) ---
    mvrv_ratio: float | None = None
    try:
        mvrv_ratio = get_mvrv_ratio()
        logger.debug("MVRV: %.4f", mvrv_ratio)
    except MetricFetchError as exc:
        msg = f"MVRV indisponível: {exc}"
        logger.warning(msg)
        errors.append(msg)

    fear_greed_value: int | None = None
    fear_greed_classification = ""
    try:
        fg = get_fear_greed_index()
        fear_greed_value = fg["value"]
        fear_greed_classification = fg["classification_pt"]
        logger.debug("Fear & Greed: %d (%s)", fear_greed_value, fear_greed_classification)
    except MetricFetchError as exc:
        msg = f"Fear & Greed indisponível: {exc}"
        logger.warning(msg)
        errors.append(msg)

    return MetricSnapshot(
        timestamp=datetime.now(),
        btc_price_usd=price_usd,
        btc_price_brl=price_brl,
        ma_50=ma_50,
        ma_200=ma_200,
        mvrv_ratio=mvrv_ratio,
        fear_greed_value=fear_greed_value,
        fear_greed_classification=fear_greed_classification,
        fetch_errors=errors,
    )
