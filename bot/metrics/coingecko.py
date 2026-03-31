from __future__ import annotations

import logging
import statistics

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coingecko.com/api/v3"
TIMEOUT = 15


class MetricFetchError(Exception):
    pass


def get_current_price() -> tuple[float, float]:
    """Retorna (preco_usd, preco_brl) do Bitcoin agora."""
    url = f"{BASE_URL}/simple/price"
    params = {"ids": "bitcoin", "vs_currencies": "usd,brl"}
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            raise MetricFetchError("CoinGecko: rate limit atingido (429). Tentará no próximo ciclo.")
        resp.raise_for_status()
        data = resp.json()
        usd = float(data["bitcoin"]["usd"])
        brl = float(data["bitcoin"]["brl"])
        return usd, brl
    except MetricFetchError:
        raise
    except Exception as exc:
        raise MetricFetchError(f"CoinGecko preço atual: {exc}") from exc


def get_historical_prices(days: int = 200) -> list[float]:
    """Retorna lista de preços diários de fechamento (USD), do mais antigo ao mais recente."""
    url = f"{BASE_URL}/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            raise MetricFetchError("CoinGecko: rate limit atingido (429). Tentará no próximo ciclo.")
        resp.raise_for_status()
        data = resp.json()
        # Cada item: [timestamp_ms, preco]
        prices = [float(p[1]) for p in data["prices"]]
        if len(prices) < 200:
            raise MetricFetchError(
                f"CoinGecko histórico: esperado >= 200 pontos, recebido {len(prices)}"
            )
        return prices
    except MetricFetchError:
        raise
    except Exception as exc:
        raise MetricFetchError(f"CoinGecko histórico: {exc}") from exc


def compute_moving_averages(prices: list[float]) -> tuple[float, float]:
    """Calcula (ma_50, ma_200) a partir da lista de preços diários."""
    if len(prices) < 200:
        raise ValueError(f"Necessário >= 200 preços para calcular MAs, recebido {len(prices)}")
    ma_50 = statistics.mean(prices[-50:])
    ma_200 = statistics.mean(prices[-200:])
    return ma_50, ma_200
