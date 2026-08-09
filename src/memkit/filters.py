"""Small domain-neutral filter algebra for context and record values."""

from __future__ import annotations

from typing import Any


class InvalidFilter(ValueError):
    pass


def matches(document: dict[str, Any], expression: dict[str, Any] | None) -> bool:
    if not expression:
        return True
    if set(expression) == {"all"}:
        children = expression["all"]
        if not isinstance(children, list):
            raise InvalidFilter("all must be a list")
        return all(matches(document, child) for child in children)
    allowed = {"field", "op", "value"}
    if not set(expression) <= allowed or "field" not in expression or "op" not in expression:
        raise InvalidFilter("filter must contain field and op")
    field = expression["field"]
    op = expression["op"]
    if not isinstance(field, str) or not field:
        raise InvalidFilter("filter field must be a non-empty string")
    value: Any = document
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            value = None
            break
        value = value[part]
    expected = expression.get("value")
    if op == "exists":
        return value is not None
    if op == "absent":
        return value is None
    if op == "eq":
        return value == expected
    if op == "in":
        if not isinstance(expected, list):
            raise InvalidFilter("in value must be a list")
        if isinstance(value, list):
            return any(item in expected for item in value)
        return value in expected
    raise InvalidFilter(f"unsupported filter operator: {op}")
