from __future__ import annotations


def slugify(text: str, separator: str = "-") -> str:
    """Build a URL slug from ``text``.

    The contract (see the task statement for the full specification):

    - the result is lowercase;
    - every character that is not an ASCII letter or digit becomes the
      separator;
    - runs of separators collapse to a single one;
    - the result never starts or ends with the separator;
    - an empty or all-separator input yields an empty string.
    """
    raise NotImplementedError("implement slugify for the slugify-001 task")
