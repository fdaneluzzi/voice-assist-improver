"""Configuration from VAI_* environment variables (and an optional .env file)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PREFIX = "VAI_"
OPTIONS_FILE = "/data/options.json"  # where the Home Assistant Supervisor writes an app's options
# Defaults when running as a Home Assistant app: the Supervisor proxy reaches Core, and only the app network
# (Core, the ingress gateway) may call us.
ADDON_HA_URL = "http://supervisor/core"
ADDON_NETWORKS = ("172.30.32.0/23", "127.0.0.0/8")
ADDON_UI_NETWORKS = ("172.30.32.2/32", "127.0.0.0/8")  # the ingress gateway
ADDON_CONFIG_DIR = "/config"


def _csv(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split(",") if x.strip())


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _addon_defaults(env: dict[str, str]) -> dict[str, str]:
    config_dir = Path(ADDON_CONFIG_DIR)
    prompt = config_dir / "voice_prompt.md"
    defaults = {
        PREFIX + "HA_URL": ADDON_HA_URL,
        PREFIX + "HA_TOKEN": env["SUPERVISOR_TOKEN"],
        PREFIX + "BACKEND": "anthropic",
        PREFIX + "HOST": "0.0.0.0",
        PREFIX + "ALLOWED_NETWORKS": ",".join(ADDON_NETWORKS),
        PREFIX + "UI_NETWORKS": ",".join(ADDON_UI_NETWORKS),
        PREFIX + "DATA_DIR": "/data",
        PREFIX + "MODELS": "default,claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5",
    }
    if env.get("TZ"):
        defaults[PREFIX + "TIMEZONE"] = env["TZ"]
    if prompt.is_file():
        defaults[PREFIX + "CUSTOM_VOICE_PROMPT_FILE"] = str(prompt)
    return defaults


# App option name -> setting name, where they differ. Everything else maps to VAI_<OPTION NAME UPPERCASE>.
_OPTION_ALIASES = {"voice_token": "HA_MCP_TOKEN"}


def _read_options(path: str) -> dict[str, str]:
    """Options written by the Supervisor, as VAI_* strings. Empty values are ignored (use the default)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, list):
            value = ",".join(str(v) for v in value)
        out[PREFIX + _OPTION_ALIASES.get(key, key.upper())] = str(value)
    return out


@dataclass(frozen=True)
class Settings:
    ha_url: str = "http://homeassistant.local:8123"
    # Secrets are excluded from repr() so they can never leak through a log line that prints the settings.
    ha_token: str = field(default="", repr=False)
    # Token for the voice path. Should belong to a NON-admin Home Assistant user. Falls back to ha_token.
    ha_mcp_token: str = field(default="", repr=False)
    # Safe by default: only loopback can call the Ollama-compatible endpoint.
    host: str = "127.0.0.1"
    port: int = 11435
    allowed_networks: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
    backend: str = "echo"
    # Model names advertised to Home Assistant's Ollama integration (/api/tags). A name that starts with
    # "claude-" selects that model for the request; any other name uses `model` below.
    models: tuple[str, ...] = ("default",)
    language: str = "en"
    # Optional file that replaces the built-in voice prompt.
    custom_voice_prompt_file: str = ""
    data_dir: Path = Path("data")
    retention_days: int = 30
    timezone: str = "UTC"
    request_timeout: float = 90.0

    # The web UI (and its JSON API) is more sensitive than the Ollama endpoint, so it has its own allow-list.
    ui_networks: tuple[str, ...] = ("127.0.0.0/8", "::1/128")
    # Local hour (0-23) of the daily analysis; -1 disables the schedule (it can still be run by hand).
    analysis_hour: int = 4
    analysis_days: int = 7

    # --- Anthropic backend ---
    anthropic_api_key: str = field(default="", repr=False)
    # Needed only for API keys that are not scoped to a workspace (the API then asks for this header).
    anthropic_workspace_id: str = ""
    model: str = "claude-sonnet-5-5"
    analysis_model: str = "claude-sonnet-5-5"
    effort: str = "low"  # low | medium | high: lower is faster, which matters for voice
    max_output_tokens: int = 1024
    max_tool_iterations: int = 6
    # Web search is off by default: mixing web content with home control is a prompt-injection risk.
    web_search: bool = False
    web_search_max_uses: int = 3
    # Server-side retry of safety refusals (beta). Only sent for models that support it.
    refusal_fallback: bool = True
    # fnmatch patterns of voice tools that must never be offered to the model.
    voice_tool_denylist: tuple[str, ...] = ()
    tool_cache_seconds: int = 300
    # 0 disables the cap. When the month's estimated spend reaches it, the AI service stops being called.
    monthly_budget_usd: float = 0.0

    @classmethod
    def load(cls, env_file: str = ".env", environ: dict[str, str] | None = None,
             options_file: str | None = None) -> Settings:
        """Precedence, low to high: app defaults, .env, app options (/data/options.json), environment."""
        env = dict(os.environ if environ is None else environ)
        raw: dict[str, str] = {}
        addon = bool(env.get("SUPERVISOR_TOKEN"))
        if addon:
            raw.update(_addon_defaults(env))
        raw.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
        raw.update(_read_options(options_file or env.get(PREFIX + "OPTIONS_FILE") or OPTIONS_FILE))
        raw.update(env)

        def get(name: str, default: str) -> str:
            return raw.get(PREFIX + name, default)

        d = cls()
        return cls(
            ha_url=get("HA_URL", d.ha_url).rstrip("/"),
            ha_token=get("HA_TOKEN", d.ha_token),
            ha_mcp_token=get("HA_MCP_TOKEN", d.ha_mcp_token),
            host=get("HOST", d.host),
            port=int(get("PORT", str(d.port))),
            allowed_networks=_csv(get("ALLOWED_NETWORKS", ",".join(d.allowed_networks))),
            ui_networks=_csv(get("UI_NETWORKS", ",".join(d.ui_networks))),
            analysis_hour=int(get("ANALYSIS_HOUR", str(d.analysis_hour))),
            analysis_days=int(get("ANALYSIS_DAYS", str(d.analysis_days))),
            backend=get("BACKEND", d.backend),
            models=_csv(get("MODELS", ",".join(d.models))),
            language=get("LANGUAGE", d.language),
            custom_voice_prompt_file=get("CUSTOM_VOICE_PROMPT_FILE", d.custom_voice_prompt_file),
            data_dir=Path(get("DATA_DIR", str(d.data_dir))).expanduser().resolve(),
            retention_days=int(get("RETENTION_DAYS", str(d.retention_days))),
            timezone=get("TIMEZONE", d.timezone),
            request_timeout=float(get("REQUEST_TIMEOUT", str(d.request_timeout))),
            anthropic_api_key=get("ANTHROPIC_API_KEY", d.anthropic_api_key),
            anthropic_workspace_id=get("ANTHROPIC_WORKSPACE_ID", d.anthropic_workspace_id),
            model=get("MODEL", d.model),
            analysis_model=get("ANALYSIS_MODEL", d.analysis_model),
            effort=get("EFFORT", d.effort),
            max_output_tokens=int(get("MAX_OUTPUT_TOKENS", str(d.max_output_tokens))),
            max_tool_iterations=int(get("MAX_TOOL_ITERATIONS", str(d.max_tool_iterations))),
            web_search=_bool(get("WEB_SEARCH", str(d.web_search))),
            web_search_max_uses=int(get("WEB_SEARCH_MAX_USES", str(d.web_search_max_uses))),
            refusal_fallback=_bool(get("REFUSAL_FALLBACK", str(d.refusal_fallback))),
            voice_tool_denylist=_csv(get("VOICE_TOOL_DENYLIST", ",".join(d.voice_tool_denylist))),
            tool_cache_seconds=int(get("TOOL_CACHE_SECONDS", str(d.tool_cache_seconds))),
            monthly_budget_usd=float(get("MONTHLY_BUDGET_USD", str(d.monthly_budget_usd))),
        )

    @property
    def is_addon(self) -> bool:
        return self.ha_url.startswith(ADDON_HA_URL)

    @property
    def ha_mcp_url(self) -> str:
        return f"{self.ha_url}/api/mcp"
