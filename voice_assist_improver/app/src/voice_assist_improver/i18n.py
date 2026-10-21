"""User-facing strings. English is the default; pt-BR is the second supported language."""
from __future__ import annotations

DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "backend_error": "Sorry, I couldn't reach the AI service right now.",
        "bad_request": "Sorry, I didn't catch that.",
        "refusal": "Sorry, I can't help with that one.",
        "budget_reached": "The monthly AI budget has been reached, so I can't use the AI service right now.",
        "too_many_steps": "Sorry, that took too many steps and I gave up.",
        "not_configured": "Voice Assist Improver is not set up yet. Add your API key in the app settings.",
    },
    "pt-BR": {
        "backend_error": "Desculpe, não consegui falar com o serviço de IA agora.",
        "bad_request": "Desculpe, não entendi.",
        "refusal": "Desculpe, não posso ajudar com isso.",
        "budget_reached": "O orçamento mensal de IA foi atingido; não posso usar o serviço de IA agora.",
        "too_many_steps": "Desculpe, isso exigiu passos demais e eu desisti.",
        "not_configured": "O Voice Assist Improver ainda não foi configurado. "
                          "Coloque sua chave de API nas opções do app.",
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
