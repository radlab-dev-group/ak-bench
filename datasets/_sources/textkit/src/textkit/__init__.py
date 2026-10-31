"""A tiny text-utility package used by the slugify-001 benchmark task."""

from textkit.casefold import casefold_word
from textkit.slugify import slugify

__all__ = ["casefold_word", "slugify"]
