"""
Shared helpers for stage modules.
"""
from __future__ import annotations

from typing import Any

from engine.models import Metric, Verdict


def safe_get(d: dict | None, key: str, default: Any = None) -> Any:
    if not d:
        return default
    v = d.get(key)
    return default if v is None else v


def pct_change(new: float, old: float) -> float | None:
    if old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100


def cagr(end: float, start: float, years: float) -> float | None:
    """Compound annual growth rate."""
    if start is None or start <= 0 or years <= 0 or end is None or end <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def aggregate_verdict(metrics: list[Metric]) -> Verdict:
    """Combine individual metric pass/fail into stage verdict."""
    passes = sum(1 for m in metrics if m.pass_ is True)
    fails = sum(1 for m in metrics if m.pass_ is False)
    total = sum(1 for m in metrics if m.pass_ is not None)
    if total == 0:
        return Verdict.SKIP
    if fails == 0:
        return Verdict.PASS
    if passes >= total * 0.7:
        return Verdict.BORDERLINE
    return Verdict.FAIL


def make_metric(
    name: str,
    value: float | str | None,
    threshold: str,
    pass_: bool | None,
    unit: str = "",
    note: str = "",
) -> Metric:
    return Metric(
        name=name,
        value=value,
        unit=unit,
        threshold=threshold,
        note=note,
        **{"pass": pass_},
    )
