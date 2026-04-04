from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

RSS_SOURCES = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
]
TIMEOUT = 15
MAX_ITEMS = 5
DAYS_BACK = 7


def get_weekly_crypto_news() -> list[dict]:
    """
    Busca as principais notícias cripto da semana via RSS (CoinDesk e Cointelegraph).
    Tenta as fontes em ordem e retorna os primeiros MAX_ITEMS itens dos últimos 7 dias.
    Retorna lista vazia se todas as fontes falharem (não fatal).
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=DAYS_BACK)
    all_items: list[dict] = []

    for source_name, url in RSS_SOURCES:
        try:
            items = _fetch_rss(url, source_name, cutoff)
            logger.debug("Notícias obtidas de %s: %d itens", source_name, len(items))
            all_items.extend(items)
        except Exception as exc:
            logger.warning("Falha ao buscar notícias de %s: %s", source_name, exc)

    # Ordena por data decrescente e limita
    all_items.sort(key=lambda x: x["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return all_items[:MAX_ITEMS]


def _fetch_rss(url: str, source_name: str, cutoff: datetime) -> list[dict]:
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_str = item.findtext("pubDate") or ""

        if not title or not link:
            continue

        try:
            pub_date = parsedate_to_datetime(pub_date_str)
        except Exception:
            pub_date = None

        if pub_date and pub_date < cutoff:
            continue

        # Trunca títulos muito longos
        if len(title) > 120:
            title = title[:117] + "..."

        items.append({"title": title, "link": link, "source": source_name, "date": pub_date})

    return items
