from __future__ import annotations

import logging

import requests

from .coingecko import MetricFetchError

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"
MERCADO_BTC_URL = "https://www.mercadobitcoin.net/api/BTC/ticker/"
TIMEOUT = 15


def get_current_price_binance() -> tuple[float, float]:
    """Retorna (preco_usd, preco_brl) via Binance (USD) e Mercado Bitcoin (BRL)."""
    try:
        resp = requests.get(
            f"{BINANCE_BASE}/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        price_usd = float(resp.json()["price"])
    except Exception as exc:
        raise MetricFetchError(f"Binance preço USD: {exc}") from exc

    try:
        resp = requests.get(MERCADO_BTC_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        price_brl = float(resp.json()["ticker"]["last"])
    except Exception as exc:
        raise MetricFetchError(f"Mercado Bitcoin preço BRL: {exc}") from exc

    return price_usd, price_brl


def get_historical_prices_binance(days: int = 200) -> list[float]:
    """Retorna lista de preços de fechamento diários (USD) via Binance Klines."""
    try:
        resp = requests.get(
            f"{BINANCE_BASE}/klines",
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": days + 2},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        klines = resp.json()
        prices = [float(k[4]) for k in klines]  # índice 4 = preço de fechamento
        if len(prices) < 200:
            raise MetricFetchError(
                f"Binance histórico: esperado >= 200 pontos, recebido {len(prices)}"
            )
        return prices
    except MetricFetchError:
        raise
    except Exception as exc:
        raise MetricFetchError(f"Binance histórico: {exc}") from exc
