"""
Paridade do Poder de Compra (PPP) — USD/BRL.

Calcula o valor justo (fair value) do dólar em reais usando dados do Banco Mundial
e compara com a taxa de câmbio atual via AwesomeAPI.
"""
from __future__ import annotations

import logging

import requests

from .coingecko import MetricFetchError

logger = logging.getLogger(__name__)

WORLD_BANK_URL = (
    "https://api.worldbank.org/v2/country/BR;US/indicator/PA.NUS.PPP"
    "?format=json&mrv=5&per_page=20"
)
AWESOME_URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
TIMEOUT = 15


def get_ppp_data() -> dict:
    """
    Retorna dict com:
      ppp_rate       — valor justo PPP do dólar em BRL
      market_rate    — taxa de câmbio atual (BRL/USD)
      deviation_pct  — desvio % do mercado em relação ao PPP
                       positivo = dólar caro / negativo = dólar barato
      ppp_year       — ano de referência dos dados PPP
    """
    ppp_rate, ppp_year = _fetch_ppp_rate()
    market_rate = _fetch_market_rate()
    deviation_pct = (market_rate - ppp_rate) / ppp_rate * 100
    return {
        "ppp_rate": ppp_rate,
        "market_rate": market_rate,
        "deviation_pct": deviation_pct,
        "ppp_year": ppp_year,
    }


def _fetch_ppp_rate() -> tuple[float, int]:
    """Busca o PPP de BRL e USD no Banco Mundial e retorna (taxa_ppp, ano)."""
    try:
        resp = requests.get(WORLD_BANK_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        _, entries = resp.json()
    except Exception as exc:
        raise MetricFetchError(f"Banco Mundial PPP: {exc}") from exc

    # Agrupa os valores mais recentes por país
    latest: dict[str, tuple[float, int]] = {}
    for entry in entries:
        country = entry.get("countryiso3code", "")
        value = entry.get("value")
        year = entry.get("date")
        if value is None or not year:
            continue
        code = "BR" if country == "BRA" else "US" if country == "USA" else None
        if code and code not in latest:
            latest[code] = (float(value), int(year))

    if "BR" not in latest or "US" not in latest:
        raise MetricFetchError("Banco Mundial PPP: dados insuficientes para BR ou US.")

    br_val, br_year = latest["BR"]
    us_val, _ = latest["US"]
    ppp_rate = br_val / us_val
    return ppp_rate, br_year


def _fetch_market_rate() -> float:
    """Busca a taxa de câmbio USD/BRL atual via AwesomeAPI."""
    try:
        resp = requests.get(AWESOME_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        return float(resp.json()["USDBRL"]["bid"])
    except Exception as exc:
        raise MetricFetchError(f"AwesomeAPI USD/BRL: {exc}") from exc
