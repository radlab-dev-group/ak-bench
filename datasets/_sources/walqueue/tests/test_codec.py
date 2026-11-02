import pytest
from walqueue import CorruptStore
from walqueue.codec import decode, encode


def test_complete_frames_roundtrip():
    first = {"sequence": 1, "commands": [{"op": "put"}]}
    second = {"sequence": 2, "commands": [{"op": "ack"}]}
    data = encode(first) + encode(second)
    decoded = decode(data, allow_torn_tail=False)
    assert decoded.documents == (first, second)
    assert decoded.valid_bytes == len(data)
    assert not decoded.torn


def test_partial_final_frame_is_distinct_from_corruption():
    data = encode({"sequence": 1})
    assert decode(data[:-1], allow_torn_tail=True).torn
    with pytest.raises(CorruptStore):
        decode(data[:-1], allow_torn_tail=False)
    with pytest.raises(CorruptStore):
        decode(data[:-1] + bytes([data[-1] ^ 1]), allow_torn_tail=True)
