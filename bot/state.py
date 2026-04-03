from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = "bot_state.json"


@dataclass
class BotState:
    # Data (ISO "YYYY-MM-DD") e preço no momento do último sinal de queda semanal.
    # None = nenhum sinal ativo / sem cooldown.
    last_drop_signal_date: str | None = None
    last_drop_signal_price: float | None = None


def load_state(path: str = STATE_FILE) -> BotState:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return BotState(
            last_drop_signal_date=data.get("last_drop_signal_date"),
            last_drop_signal_price=data.get("last_drop_signal_price"),
        )
    except FileNotFoundError:
        return BotState()
    except Exception as exc:
        logger.warning("Falha ao carregar state (%s) — usando estado limpo.", exc)
        return BotState()


def save_state(state: BotState, path: str = STATE_FILE) -> None:
    try:
        Path(path).write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Falha ao salvar state: %s", exc)
