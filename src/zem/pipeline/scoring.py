from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from zem.policy.loader import Thresholds


class Route(str, Enum):
    ALLOW = "allow"
    JUDGE = "judge"
    DEEP = "deep"  # R3
    DENY = "deny"


def noisy_or(weights: Iterable[float]) -> float:
    """Combine independent weak signals: 1 - (1-w1)(1-w2)... Rounded so 0.85 stays 0.85."""
    p = 1.0
    for w in weights:
        p *= 1.0 - w
    return round(1.0 - p, 6)


def route(risk: float, th: Thresholds, *, deep_enabled: bool) -> Route:
    if risk >= th.deny:
        return Route.DENY
    if risk >= th.deep_judge:
        return Route.DEEP if deep_enabled else Route.DENY  # R2: "high -> deny"
    if risk >= th.fast_judge:
        return Route.JUDGE
    return Route.ALLOW
