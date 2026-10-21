from __future__ import annotations

import logging

import uvicorn

from .backends import create_backend
from .budget import Budget
from .config import Settings
from .ollama_api import create_app
from .store import Store


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full URLs at INFO; those can carry credentials, so keep them out of the logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    settings = Settings.load()
    store = Store(settings.data_dir / "voice-assist-improver.sqlite3")
    store.purge_older_than(settings.retention_days)
    budget = Budget(store, settings.monthly_budget_usd, settings.timezone)
    app = create_app(settings, create_backend(settings), store, budget)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
