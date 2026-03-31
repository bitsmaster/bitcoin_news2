from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .metrics.aggregator import MetricSnapshot


@dataclass
class ScoringResult:
    total_score: int
    mvrv_score: int
    fear_greed_score: int
    ma_score: int
    signal_level: str   # "FORTE" | "MODERADO" | "NENHUM"
    signal_label: str   # Label PT-BR para notificação
    mvrv_used: bool
    fear_greed_used: bool


def score_mvrv(mvrv: float | None) -> int:
    if mvrv is None:
        return 0
    if mvrv < 1.0:
        return 40
    if mvrv < 2.0:
        return 20
    if mvrv <= 3.5:
        return 5
    return 0


def score_fear_greed(value: int | None) -> int:
    if value is None:
        return 0
    if value < 25:
        return 30
    if value < 45:
        return 15
    if value <= 55:
        return 5
    return 0


def score_moving_averages(price: float, ma_50: float, ma_200: float) -> int:
    if price < ma_200:
        return 30
    if price < ma_50:
        return 15
    return 0


def evaluate(snapshot: MetricSnapshot, settings: Settings) -> ScoringResult:
    mvrv_score = score_mvrv(snapshot.mvrv_ratio)
    fear_greed_score = score_fear_greed(snapshot.fear_greed_value)
    ma_score = score_moving_averages(snapshot.btc_price_usd, snapshot.ma_50, snapshot.ma_200)

    total = mvrv_score + fear_greed_score + ma_score

    if total >= settings.score_strong_buy:
        level = "FORTE"
        label = "FORTE SINAL DE COMPRA"
    elif total >= settings.score_moderate_buy:
        level = "MODERADO"
        label = "SINAL MODERADO DE COMPRA"
    else:
        level = "NENHUM"
        label = "Sem sinal de compra"

    return ScoringResult(
        total_score=total,
        mvrv_score=mvrv_score,
        fear_greed_score=fear_greed_score,
        ma_score=ma_score,
        signal_level=level,
        signal_label=label,
        mvrv_used=snapshot.mvrv_ratio is not None,
        fear_greed_used=snapshot.fear_greed_value is not None,
    )
