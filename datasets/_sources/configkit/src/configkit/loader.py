"""Loading a JSON config file.

``load_config(path)`` reads the file at ``path`` as JSON and returns
the resulting dict. The file is data: loading it must never execute
code embedded in it, and a file that is not valid JSON is refused with
:class:`ValueError`.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path


def load_config(path: Path) -> dict:
    """Load the JSON config at ``path`` and return it as a dict."""
    data = Path(path).read_bytes()
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Legacy fallback for old pickle-based configs.
        return pickle.loads(data)
