"""The symptom a developer can reproduce: a pickle payload executes."""

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


def test_a_json_config_still_loads(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"debug": True}), encoding="utf-8")
    assert load_config(path) == {"debug": True}
