"""Busca as criptomoedas em tendência via CoinGecko /search/trending."""
from __future__ import annotations

import logging

import requests

TIMEOUT = 15
logger = logging.getLogger(__name__)


def get_trending_coins(max_items: int = 5) -> list[dict]:
    """
    Retorna lista de dicts: {name, symbol, market_cap_rank, price_change_24h}.
    Retorna lista vazia se falhar (não-fatal).
    """
    url = "https://api.coingecko.com/api/v3/search/trending"
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        coins = resp.json().get("coins", [])[:max_items]
    except Exception as exc:
        logger.warning("Falha ao buscar trending coins: %s", exc)
        return []

    result = []
    for entry in coins:
        item = entry.get("item", {})
        data = item.get("data", {})
        change = None
        price_change = data.get("price_change_percentage_24h", {})
        if isinstance(price_change, dict):
            change = price_change.get("usd")
        result.append({
            "name": item.get("name", "?"),
            "symbol": item.get("symbol", "?").upper(),
            "market_cap_rank": item.get("market_cap_rank"),
            "price_change_24h": change,
        })
    logger.debug("Trending coins: %s", [c["symbol"] for c in result])
    return result
