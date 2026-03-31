from __future__ import annotations

import sys

from bot.config import ConfigError, load
from bot.logger import setup
from bot import scheduler


def main() -> None:
    try:
        settings = load()
    except ConfigError as exc:
        print(f"\n{exc}\n\nCopie .env.example para .env e preencha as credenciais.", file=sys.stderr)
        sys.exit(1)

    setup(log_level=settings.log_level, log_file=settings.log_file)
    scheduler.start(settings)


if __name__ == "__main__":
    main()
