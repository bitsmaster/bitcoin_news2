from __future__ import annotations

import logging

import requests

from .coingecko import MetricFetchError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.alternative.me/fng/"
TIMEOUT = 15

CLASSIFICATION_PT: dict[str, str] = {
    "Extreme Fear": "Medo Extremo",
    "Fear": "Medo",
    "Neutral": "Neutro",
    "Greed": "Ganância",
    "Extreme Greed": "Ganância Extrema",
}


def get_fear_greed_index() -> dict:
    """
    Retorna dict com:
      - value: int (0–100)
      - classification_en: str  (original em inglês)
      - classification_pt: str  (traduzido para português)
    """
    try:
        resp = requests.get(BASE_URL, params={"limit": 1}, timeout=TIMEOUT)
        if resp.status_code == 429:
            raise MetricFetchError("Fear & Greed: rate limit (429).")
        resp.raise_for_status()
        data = resp.json()
        entry = data["data"][0]
        classification_en = entry.get("value_classification", "")
        return {
            "value": int(entry["value"]),
            "classification_en": classification_en,
            "classification_pt": CLASSIFICATION_PT.get(classification_en, classification_en),
        }
    except MetricFetchError:
        raise
    except Exception as exc:
        raise MetricFetchError(f"Fear & Greed Index: {exc}") from exc
