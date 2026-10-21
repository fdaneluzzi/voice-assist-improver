"""Text helpers shared across modules."""
from __future__ import annotations

import re
import unicodedata


def norm(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces: a stable key for comparing phrases."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())
