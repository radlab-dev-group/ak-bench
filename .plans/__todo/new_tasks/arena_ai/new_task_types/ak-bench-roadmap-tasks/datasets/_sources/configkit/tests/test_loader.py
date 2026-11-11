"""The finished part of the fixture: well-formed JSON configs.

The suite deliberately never loads a non-JSON file, so an unsafe
deserialization defect is invisible here.
"""

from __future__ import annotations

import json

from configkit import load_config


def test_loads_a_json_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"debug": True, "port": 8080}), encoding="utf-8")
    assert load_config(path) == {"debug": True, "port": 8080}
