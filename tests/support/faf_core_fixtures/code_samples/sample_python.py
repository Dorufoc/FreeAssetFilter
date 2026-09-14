"""Parity sample: python."""

import os  # keyword: import

CONSTANT = 42  # NUMBER 42


def greet(name: str) -> str:
    """Return greeting."""  # COMMENT docstring
    message = f"hello {name}"  # STRING f-string
    if len(name) > 0:  # keyword: if
        return message
    return "empty"  # STRING
