from __future__ import annotations

import logging

import uvicorn

from .analysis import Analyzer
from .backends import Backend, create_backend
from .backends.unconfigured import UnconfiguredBackend
from .budget import Budget
from .config import Settings
from .ollama_api import create_app
from .store import Store


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full URLs at INFO; those can carry credentials, so keep them out of the logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build_backend(settings: Settings) -> Backend:
    """The configured backend, or a stand-in that explains what is missing (so the app still starts and the
    UI can show the problem instead of the app crash-looping)."""
    try:
        return create_backend(settings)
    except ValueError as exc:
        logging.getLogger(__name__).error("not configured: %s", exc)
        return UnconfiguredBackend(settings, str(exc))


def main() -> None:
    configure_logging()
    settings = Settings.load()
    store = Store(settings.data_dir / "voice-assist-improver.sqlite3")
    store.purge_older_than(settings.retention_days)
    budget = Budget(store, settings.monthly_budget_usd, settings.timezone)
    backend = build_backend(settings)
    client = getattr(backend, "client", None)  # only the Anthropic backend can run the analysis
    analyzer = Analyzer(settings, store, client, budget) if client is not None else None
    app = create_app(settings, backend, store, budget, analyzer)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
