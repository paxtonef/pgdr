"""Text normalization shared by complaint_parser and safety_engine.

French input is not guaranteed to include diacritics (mobile autocorrect,
fast typing, ASCII-only sources). Every place that matches user-typed text
against a keyword list must normalize both sides the same way, or a rule
can silently fail to fire — which is a safety concern when it's a
PGDR-SAF-* rule that never triggers because the user typed "fumee" instead
of "fumée".
"""
from __future__ import annotations

import unicodedata


def normalize(text: str) -> str:
    """Lowercase and strip diacritics (é -> e, à -> a, ç -> c, ...)."""
    text = text.lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
