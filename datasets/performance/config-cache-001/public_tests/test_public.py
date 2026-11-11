"""The cache, in miniature: one parse, then a reload on change."""

from __future__ import annotations

import json
import os

from configkit.cache import load_config_cached
from configkit.loader import load_config


def test_cached_load_parses_once(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"debug": true}', encoding="utf-8")
    calls = []
    real = json.loads

    def counting(text, *args, **kwargs):
        calls.append(1)
        return real(text, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counting)
    assert load_config_cached(path) == {"debug": True}
    assert load_config_cached(path) == {"debug": True}
    assert load_config_cached(path) == {"debug": True}
    assert len(calls) == 1


def test_cached_load_reloads_on_change(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"debug": true}', encoding="utf-8")
    assert load_config_cached(path) == {"debug": True}
    path.write_text('{"debug": false}', encoding="utf-8")
    os.utime(path, (2_000_000_000, 2_000_000_000))
    assert load_config_cached(path) == {"debug": False}
    assert load_config(path) == {"debug": False}
