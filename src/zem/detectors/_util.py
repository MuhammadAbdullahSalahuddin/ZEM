from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from typing import Any

# Variation selectors are not "Cf" but are also used to hide data inside text.
_EXTRA_INVISIBLE = {c for r in (range(0xFE00, 0xFE10), range(0xE0100, 0xE01F0)) for c in r}


def clean(text: str) -> str:
    """Make text comparable: NFKC-normalise and drop invisible characters.

    Defeats "cu<zero-width>rl", fullwidth "ｃｕｒｌ" and tag-character smuggling before
    the detectors look at the text. ASCII has nothing to clean, so it returns fast.
    """
    if text.isascii():
        return text
    text = unicodedata.normalize("NFKC", text)
    return "".join(
        ch for ch in text if unicodedata.category(ch) != "Cf" and ord(ch) not in _EXTRA_INVISIBLE
    )


def iter_strings(
    value: Any, key: str = "", *, clean_text: bool = True
) -> Iterator[tuple[str, str]]:
    """Yield (argument_name, text) for every string anywhere inside `value`."""
    if isinstance(value, str):
        yield key, clean(value) if clean_text else value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from iter_strings(v, str(k), clean_text=clean_text)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from iter_strings(item, key, clean_text=clean_text)
