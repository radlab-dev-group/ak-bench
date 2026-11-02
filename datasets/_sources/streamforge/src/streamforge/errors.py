"""Errors are part of the public processing contract."""


class StreamError(ValueError):
    pass


class OffsetConflict(StreamError):
    pass


class IdentityConflict(StreamError):
    pass


class InvalidCheckpoint(StreamError):
    pass
