from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_strings(value: Any, key: str = "") -> Iterator[tuple[str, str]]:
    """Yield (argument_name, text) for every string anywhere inside `value`."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from iter_strings(v, str(k))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from iter_strings(item, key)
