"""Configuration from VAI_* environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PREFIX = "VAI_"


def _csv(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split(",") if x.strip())


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    retention_days: int = 90
    timezone: str = "UTC"
    request_timeout: float = 90.0

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
    def load(cls, env_file: str = ".env", environ: dict[str, str] | None = None) -> Settings:
        raw: dict[str, str] = {k: v for k, v in dotenv_values(env_file).items() if v is not None}
        raw.update(os.environ if environ is None else environ)

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
    def ha_mcp_url(self) -> str:
        return f"{self.ha_url}/api/mcp"
