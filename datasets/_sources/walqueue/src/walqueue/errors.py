"""Distinguish rejected requests, damaged storage, and simulated process death."""


class QueueError(ValueError):
    pass


class CorruptStore(QueueError):
    pass


class KeyConflict(QueueError):
    pass


class StaleLease(QueueError):
    pass


class InjectedCrash(BaseException):
    pass
