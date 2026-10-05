"""RFC 6901 JSON pointers: walk a JSON tree, resolve a pointer."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

_MISSING = object()


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def join(parent: str, token: str | int) -> str:
    return f"{parent}/{escape(str(token))}"


def walk(node: Any, pointer: str = "") -> Iterator[tuple[str, Any, bool]]:
    """Yield ``(pointer, value, is_leaf)`` for every node, containers included.

    Empty containers count as leaves: ``"activities": []`` is a meaningful fact.
    """
    if isinstance(node, dict):
        yield pointer, node, not node
        for k, v in node.items():
            yield from walk(v, join(pointer, k))
    elif isinstance(node, list):
        yield pointer, node, not node
        for i, v in enumerate(node):
            yield from walk(v, join(pointer, i))
    else:
        yield pointer, node, True


def resolve(node: Any, pointer: str, default: Any = _MISSING) -> Any:
    """Return the value at ``pointer``; raise ``KeyError`` (or return ``default``) if absent."""
    if pointer == "":
        return node
    current = node
    for raw in pointer.lstrip("/").split("/"):
        token = unescape(raw)
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise KeyError(pointer)
        except (KeyError, IndexError, ValueError):
            if default is _MISSING:
                raise KeyError(pointer) from None
            return default
    return current


_ABSENT = object()


def exists(node: Any, pointer: str) -> bool:
    return resolve(node, pointer, default=_ABSENT) is not _ABSENT


def parent_of(pointer: str) -> str:
    return pointer.rsplit("/", 1)[0]
