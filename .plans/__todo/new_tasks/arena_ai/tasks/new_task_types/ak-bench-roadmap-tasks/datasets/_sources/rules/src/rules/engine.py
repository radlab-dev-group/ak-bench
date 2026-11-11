"""Deciding entry.

``decide(age, has_ticket, is_member)`` returns one of ``"vip"``,
``"standard"`` or ``"deny"``:

- an adult member enters as ``"vip"``;
- an adult with a ticket enters as ``"standard"``;
- a minor with both a ticket and a membership enters as ``"standard"``;
- everyone else is denied.
"""

from __future__ import annotations


def decide(age: int, has_ticket: bool, is_member: bool) -> str:
    """Return the access level for the given facts."""
    if age >= 18:
        if is_member:
            return "vip"
        else:
            if has_ticket:
                return "standard"
            else:
                return "deny"
    else:
        if has_ticket:
            if is_member:
                return "standard"
            else:
                return "deny"
        else:
            return "deny"
