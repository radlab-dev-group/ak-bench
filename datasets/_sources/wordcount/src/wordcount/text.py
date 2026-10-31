from __future__ import annotations


def count_words(text: str) -> int:
    """Count the whitespace-separated words in ``text``.

    An empty or whitespace-only string contains zero words, no matter how many
    blank lines it has.
    """
    return len(text.split())


def top_words(text: str, limit: int = 3) -> list[tuple[str, int]]:
    """The most frequent words, case-insensitive, with their counts."""
    counts: dict[str, int] = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[: max(limit, 0)]
