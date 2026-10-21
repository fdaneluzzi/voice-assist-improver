"""User-facing strings. English is the default; pt-BR is the second supported language."""
from __future__ import annotations

DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "backend_error": "Sorry, I couldn't reach the AI service right now.",
        "bad_request": "Sorry, I didn't catch that.",
    },
    "pt-BR": {
        "backend_error": "Desculpe, não consegui falar com o serviço de IA agora.",
        "bad_request": "Desculpe, não entendi.",
    },
}

SUPPORTED_LANGUAGES = tuple(MESSAGES)


def normalize_language(language: str | None) -> str:
    """Map things like 'pt', 'pt_BR', 'pt-br' to 'pt-BR'; anything unknown falls back to English."""
    key = (language or "").strip().replace("_", "-").lower()
    if key.startswith("pt"):
        return "pt-BR"
    return DEFAULT_LANGUAGE


def t(language: str | None, key: str) -> str:
    return MESSAGES[normalize_language(language)][key]
