from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler


def setup(log_level: str = "INFO", log_file: str = "bitcoin_bot.log") -> None:
    level = getattr(logging, log_level, logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    # Evita duplicar handlers ao chamar setup() mais de uma vez
    if root.handlers:
        return

    # stdout
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    # Arquivo rotativo (máx 5 MB, 3 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
