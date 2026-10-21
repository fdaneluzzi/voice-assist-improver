"""Serve the panel with made-up example data, to take the README screenshot.

    python scripts/demo_panel.py 8765      # then open http://127.0.0.1:8765/ui/

Everything shown is invented: no real home, no real people, nothing is sent anywhere.
"""
from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

import uvicorn

from voice_assist_improver.backends import EchoBackend
from voice_assist_improver.budget import Budget
from voice_assist_improver.config import Settings
from voice_assist_improver.ollama_api import create_app
from voice_assist_improver.store import Store

DAY = 86400
PHRASES = [
    ("turn on the pendant over the dining table", "Done, the dining pendant is on.", "light__HassTurnOn"),
    ("make it cozy in here", "Done, I set the living room lights to a warm, dim glow.", "light__HassLightSet"),
    ("movie night", "Done, living room lights are off except the sofa lamp.", "light__HassLightSet"),
    ("is anything left open", "The garage door is closed and all windows are shut.", "homeassistant__GetLiveContext"),
    ("how warm is it upstairs", "It is twenty-three degrees upstairs.", "homeassistant__GetLiveContext"),
    ("turn off everything in the kitchen", "Done, the kitchen is off.", "intent__HassTurnOff"),
    ("close the office blinds halfway", "Done, the office blinds are at fifty percent.", "cover__HassSetPosition"),
    ("lights low in the bedroom", "Done, bedroom lights are at twenty percent.", "light__HassLightSet"),
]
WEIGHTS = [6, 5, 4, 3, 3, 2, 2, 2]
PER_DAY = [21, 19, 22, 17, 15, 16, 12, 13, 10, 9, 8, 7, 5, 4]  # the point: it goes down


def populate(store: Store, now: float) -> None:
    rng = random.Random(7)
    for age, count in zip(range(13, -1, -1), PER_DAY, strict=True):
        for i in range(count):
            phrase, reply, tool = rng.choices(PHRASES, WEIGHTS)[0]
            ts = now - age * DAY - rng.randint(0, 40000) if age else now - 600 * (i + 1)
            store.add_interaction(
                utterance=phrase[0].upper() + phrase[1:] + ".", reply=reply, client="10.0.0.4",
                model="claude-haiku-5-5", backend="anthropic", ts=ts, tools=[{"name": tool}],
                latency_ms=rng.randint(1800, 4800),
                usage={"cost_usd": rng.uniform(0.0003, 0.0011)})
    store.add_suggestion(
        fingerprint="a1", kind="alias", entity_id="light.dining_pendant", alias="pendant over the dining table",
        phrase="Turn on the pendant over the dining table.", evidence=14,
        title="Add the alias “pendant over the dining table”",
        detail="People say this name; Assist only knows “Dining Pendant”. The original name keeps working.")
    store.add_suggestion(
        fingerprint="a2", kind="automation", phrase="Make it cozy in here.", evidence=11,
        title="Make “make it cozy in here” instant",
        detail="The AI did the same thing each time: warm, dim lights in the living room.",
        payload={"sentences": ["Make it cozy in here", "cozy mode"], "response": "Cozy.",
                 "plan": ["light.turn_on → Living Room Ceiling, Sofa Lamp (brightness_pct 30, color_temp_kelvin 2700)"]})
    store.add_suggestion(
        fingerprint="a3", kind="scene", phrase="Movie night.", evidence=8,
        title="Create the scene “Movie night”",
        detail="Lights off except the sofa lamp, repeated eight times this week.",
        payload={"sentences": ["Movie night", "movie mode"], "response": "Enjoy the movie.",
                 "plan": ["Living Room Ceiling: off", "Sofa Lamp: on (brightness_pct 10)"]})
    store.add_analysis_run(model="claude-sonnet-5-5", interactions=31, created=3, rejected=1,
                           cost_usd=0.011, ts=now - 5 * 3600)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    tmp = Path(tempfile.mkdtemp(prefix="vai-demo-"))
    settings = Settings(data_dir=tmp, language="en", model="claude-haiku-5-5", monthly_budget_usd=5.0,
                        timezone="UTC")
    store = Store(tmp / "demo.sqlite3")
    populate(store, time.time())
    app = create_app(settings, EchoBackend(), store, Budget(store, 5.0, "UTC"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
