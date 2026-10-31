from __future__ import annotations


def casefold_word(word: str) -> str:
    """Casefold a single word without touching its surrounding characters.

    Unlike ``str.casefold`` on the whole string, this helper is defined for
    exactly one token and never strips or splits anything: punctuation stays
    attached to the word it is part of.
    """
    return word.lower()
