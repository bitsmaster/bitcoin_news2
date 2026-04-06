from __future__ import annotations

import os
import sys

from bot.config import ConfigError, load
from bot.logger import setup
from bot import scheduler
from bot.webhook import app as flask_app, init_app


def main() -> None:
    try:
        settings = load()
    except ConfigError as exc:
        print(f"\n{exc}\n\nCopie .env.example para .env e preencha as credenciais.", file=sys.stderr)
        sys.exit(1)

    setup(log_level=settings.log_level, log_file=settings.log_file)

    # Scheduler roda em background thread; Flask ocupa a thread principal
    scheduler.start(settings)

    init_app(settings)
    port = int(os.getenv("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
