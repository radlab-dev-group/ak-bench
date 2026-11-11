"""Registering a user.

``register_user(name, email, age)`` validates the fields and returns a
dict with the cleaned values. The rules: the name must be non-empty
after stripping, the email must contain exactly one ``@`` with text on
both sides, and the age must be between 0 and 150 inclusive.
"""

from __future__ import annotations


def register_user(name: str, email: str, age: int) -> dict:
    """Validate the fields and return the cleaned user dict."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("name must not be empty")
    clean_email = email.strip()
    if clean_email.count("@") != 1:
        raise ValueError("email must contain exactly one @")
    local, _, domain = clean_email.partition("@")
    if not local or not domain:
        raise ValueError("email must have text on both sides of @")
    if not 0 <= age <= 150:
        raise ValueError("age must be between 0 and 150")
    return {"name": clean_name, "email": clean_email, "age": age}
