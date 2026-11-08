"""Vendored third-party-compatible helpers kept for the v1 wire format.

Nothing in this package is a maintenance target, and most of it is unreachable
from the write path. It exists because the v1 client library imports it, and
removing it would break a caller we do not control.
"""
