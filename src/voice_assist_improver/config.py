"""Configuration from VAI_* environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PREFIX = "VAI_"


def _csv(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""
    # Safe by default: only loopback can call the Ollama-compatible endpoint.
    host: str = "127.0.0.1"
    port: int = 11435
    allowed_networks: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
    backend: str = "echo"
    # Model names advertised to Home Assistant's Ollama integration (/api/tags).
    models: tuple[str, ...] = ("default",)
    language: str = "en"
    # Optional file that replaces the built-in voice prompt.
    custom_voice_prompt_file: str = ""
    data_dir: Path = Path("data")
    retention_days: int = 90
    timezone: str = "UTC"
    request_timeout: float = 90.0

    @classmethod
    def load(cls, env_file: str = ".env", environ: dict[str, str] | None = None) -> Settings:
        raw: dict[str, str] = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
        raw.update(os.environ if environ is None else environ)

        def get(name: str, default: str) -> str:
            return raw.get(PREFIX + name, default)

        d = cls()
        return cls(
            ha_url=get("HA_URL", d.ha_url).rstrip("/"),
            ha_token=get("HA_TOKEN", d.ha_token),
            host=get("HOST", d.host),
            port=int(get("PORT", str(d.port))),
            allowed_networks=_csv(get("ALLOWED_NETWORKS", ",".join(d.allowed_networks))),
            backend=get("BACKEND", d.backend),
            models=_csv(get("MODELS", ",".join(d.models))),
            language=get("LANGUAGE", d.language),
            custom_voice_prompt_file=get("CUSTOM_VOICE_PROMPT_FILE", d.custom_voice_prompt_file),
            data_dir=Path(get("DATA_DIR", str(d.data_dir))).expanduser().resolve(),
            retention_days=int(get("RETENTION_DAYS", str(d.retention_days))),
            timezone=get("TIMEZONE", d.timezone),
            request_timeout=float(get("REQUEST_TIMEOUT", str(d.request_timeout))),
        )
