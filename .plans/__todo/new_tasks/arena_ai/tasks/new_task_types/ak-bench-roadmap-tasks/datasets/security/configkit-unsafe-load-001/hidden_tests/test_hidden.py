"""The vulnerability, proven from every side.

These tests fail on the base commit (the vulnerability is in the base
code) and pass once loading is JSON-only.
"""

from __future__ import annotations

import json
import pickle

import pytest

from configkit import load_config


class Exploit:
    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        import os

        return (os.system, (f"touch {self.marker}",))


def test_a_pickle_payload_does_not_execute(tmp_path):
    marker = tmp_path / "pwned"
    path = tmp_path / "config.pkl"
    path.write_bytes(pickle.dumps(Exploit(marker)))
    with pytest.raises(ValueError):
        load_config(path)
    assert not marker.exists()


def test_a_pickle_dict_payload_is_refused(tmp_path):
    path = tmp_path / "config.pkl"
    path.write_bytes(pickle.dumps({"debug": True}))
    with pytest.raises(ValueError):
        load_config(path)


def test_a_plain_text_file_is_refused(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("debug = true", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_a_json_config_loads(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"debug": True, "port": 8080}), encoding="utf-8")
    assert load_config(path) == {"debug": True, "port": 8080}


def test_a_nested_json_config_loads(tmp_path):
    path = tmp_path / "config.json"
    payload = {"server": {"host": "localhost", "ports": [80, 443]}, "tags": ["a", "b"]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_config(path) == payload
