"""Built-in prompts. English is the default; a user-supplied file always wins."""
from __future__ import annotations

from importlib import resources
from pathlib import Path

from ..i18n import normalize_language


def load_voice_prompt(language: str | None = None, custom_file: str | Path | None = None) -> str:
    """Return the voice prompt: the user's custom file if given, else the built-in one for the language."""
    if custom_file:
        text = Path(custom_file).expanduser().read_text(encoding="utf-8").strip()
        if text:
            return text
    name = f"voice.{normalize_language(language)}.md"
    return resources.files(__package__).joinpath(name).read_text(encoding="utf-8").strip()
