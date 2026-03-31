from __future__ import annotations

import logging

import requests

from .coingecko import MetricFetchError

logger = logging.getLogger(__name__)

# CoinMetrics Community API — gratuita, sem necessidade de cadastro
# Docs: https://docs.coinmetrics.io/api/v4
BASE_URL = "https://community-api.coinmetrics.io/v4"
TIMEOUT = 15


def get_mvrv_ratio() -> float:
    """
    Busca o MVRV Ratio do Bitcoin via CoinMetrics Community API (gratuita, sem API key).

    MVRV = Market Cap / Realized Cap
      < 1.0  → historicamente fundo de mercado (muito barato)
      1–2    → zona de acumulação
      2–3.5  → mercado aquecido
      > 3.5  → topo de ciclo (sobrevalorizado)

    Retorna o valor mais recente disponível (resolução diária, ~24h de lag).
    """
    url = f"{BASE_URL}/timeseries/asset-metrics"
    params = {
        "assets": "btc",
        "metrics": "CapMVRVCur",
        "frequency": "1d",
        "limit_per_asset": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code == 429:
            raise MetricFetchError("CoinMetrics MVRV: rate limit (429).")
        resp.raise_for_status()
        data = resp.json()
        entries = data.get("data", [])
        if not entries:
            raise MetricFetchError("CoinMetrics MVRV: resposta vazia.")
        value = entries[-1].get("CapMVRVCur")
        if value is None:
            raise MetricFetchError("CoinMetrics MVRV: campo CapMVRVCur ausente na resposta.")
        return float(value)
    except MetricFetchError:
        raise
    except Exception as exc:
        raise MetricFetchError(f"CoinMetrics MVRV: {exc}") from exc
