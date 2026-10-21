"""A monthly spending cap, so a misconfiguration can never become a surprise bill."""
from __future__ import annotations

from .store import Store


class Budget:
    def __init__(self, store: Store, monthly_limit_usd: float, timezone: str = "UTC"):
        self.store = store
        self.limit = monthly_limit_usd
        self.timezone = timezone

    def exceeded(self) -> bool:
        """True when a cap is set and this month's estimated spend has reached it."""
        return self.limit > 0 and self.store.month_cost(self.timezone) >= self.limit
