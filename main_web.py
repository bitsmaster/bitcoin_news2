"""
Combined entry point: runs the APScheduler (background thread) + uvicorn webhook server.

Use this instead of main.py when deploying to Railway (or any platform that needs
an HTTP server bound to $PORT).

    Procfile:  web: python main_web.py
"""
from __future__ import annotations

import os
import sys
import threading

import uvicorn

from bot.config import ConfigError, load
from bot.logger import setup
from bot import scheduler as bot_scheduler


def _run_scheduler(settings) -> None:
    """Blocking call; runs inside a daemon thread."""
    bot_scheduler.start(settings)


def main() -> None:
    try:
        settings = load()
    except ConfigError as exc:
        print(
            f"\n{exc}\n\nCopie .env.example para .env e preencha as credenciais.",
            file=sys.stderr,
        )
        sys.exit(1)

    setup(log_level=settings.log_level, log_file=settings.log_file)

    # Start the scheduler in a background daemon thread so it doesn't block uvicorn
    scheduler_thread = threading.Thread(
        target=_run_scheduler,
        args=(settings,),
        daemon=True,
        name="bitcoin-scheduler",
    )
    scheduler_thread.start()

    # Bind to $PORT (Railway injects this) or fall back to 8000 for local use
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("webhook:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
