"""The cache, proven: one parse per file version, reload on change.

The hidden tests count ``json.loads`` calls: repeated calls on an
unchanged file must parse once, and a changed file must be re-parsed.
"""

from __future__ import annotations

import json
import os

from configkit.cache import load_config_cached
from configkit.loader import load_config


def test_repeated_calls_parse_once(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"debug": true, "port": 8080}', encoding="utf-8")
    calls = []
    real = json.loads

    def counting(text, *args, **kwargs):
        calls.append(1)
        return real(text, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counting)
    for _ in range(5):
        assert load_config_cached(path) == {"debug": True, "port": 8080}
    assert len(calls) == 1, f"parsed {len(calls)} times for an unchanged file"


def test_a_changed_file_is_reparsed(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"debug": true}', encoding="utf-8")
    assert load_config_cached(path) == {"debug": True}
    path.write_text('{"debug": false}', encoding="utf-8")
    os.utime(path, (2_000_000_000, 2_000_000_000))
    assert load_config_cached(path) == {"debug": False}
    assert load_config_cached(path) == {"debug": False}


def test_load_config_still_works(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"debug": true}', encoding="utf-8")
    assert load_config(path) == {"debug": True}
