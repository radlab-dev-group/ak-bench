import json

import pytest
from walqueue import CorruptStore
from walqueue.codec import MAX_PAYLOAD, decode, encode
from walqueue.files import read_document, replace_bytes, write_document


def test_replacement_is_exact_and_leaves_no_pending_files(tmp_path):
    target = tmp_path / "document"
    replace_bytes(target, b"old")
    replace_bytes(target, b"new longer value")
    assert target.read_bytes() == b"new longer value"
    assert list(tmp_path.glob(".pending-*")) == []


def test_envelope_is_independent_of_dictionary_insertion_order(tmp_path):
    path = tmp_path / "document"
    write_document(path, {"b": [2], "a": 1})
    original = path.read_bytes()
    write_document(path, {"a": 1, "b": [2]})
    assert path.read_bytes() == original
    assert read_document(path) == {"a": 1, "b": [2]}


@pytest.mark.parametrize("document", [b"", b"[]", b"null", b'{"document":{}}', b"bad json"])
def test_envelopes_reject_invalid_shapes(tmp_path, document):
    path = tmp_path / "document"
    path.write_bytes(document)
    with pytest.raises(CorruptStore):
        read_document(path)


def test_envelope_rejects_valid_json_with_changed_content(tmp_path):
    path = tmp_path / "document"
    write_document(path, {"amount": 5})
    envelope = json.loads(path.read_bytes())
    envelope["document"]["amount"] = 6
    path.write_text(json.dumps(envelope))
    with pytest.raises(CorruptStore):
        read_document(path)


@pytest.mark.parametrize("length", [0, MAX_PAYLOAD + 1, 2**32 - 1])
def test_impossible_frame_lengths_are_corruption_even_at_tail(length):
    with pytest.raises(CorruptStore):
        decode(length.to_bytes(4, "big"), allow_torn_tail=True)


def test_every_truncation_of_one_frame_is_a_recoverable_tail():
    frame = encode({"sequence": 1, "commands": [{"op": "put", "value": "unicode: łódź"}]})
    prefix = encode({"sequence": 0})
    for length in range(1, len(frame)):
        decoded = decode(prefix + frame[:length], allow_torn_tail=True)
        assert decoded.valid_bytes == len(prefix)
        assert decoded.torn


def test_large_payload_refused_before_frame_encoding():
    with pytest.raises(ValueError):
        encode({"value": "x" * MAX_PAYLOAD})
