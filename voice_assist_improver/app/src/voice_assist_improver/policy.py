"""What suggestions (aliases, automations, scenes) are allowed to involve. Defined by the user's settings."""
from __future__ import annotations

from dataclasses import dataclass

# Out of the box, locks, alarms, garage doors and gates are left out: the improver never helps voice-control
# them unless the user deliberately adds them to the settings.
SAFE_DOMAINS = frozenset({"light", "switch", "climate", "cover", "fan", "valve", "media_player"})
BLOCKED_DEVICE_CLASSES = frozenset({"gate", "garage", "garage_door", "door"})


@dataclass(frozen=True)
class Policy:
    domains: frozenset[str] = SAFE_DOMAINS
    blocked_device_classes: frozenset[str] = BLOCKED_DEVICE_CLASSES

    def allows(self, entity: dict) -> bool:
        blocked = entity.get("device_class") in self.blocked_device_classes
        return entity["domain"] in self.domains and not blocked


DEFAULT_POLICY = Policy()
