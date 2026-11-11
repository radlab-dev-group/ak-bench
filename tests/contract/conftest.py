"""Make the contract-suite helpers importable by module name.

The suite is written against plain imports (``adapter_contract``,
``fake_agent``, ``agent_server_stub``) so an adapter can be tested without
knowing the repository layout; the helpers live in this directory and in
``stubs/``, and both go on the path before collection.
"""

from __future__ import annotations

import sys
from pathlib import Path

for directory in (Path(__file__).parent, Path(__file__).parent / "stubs"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
