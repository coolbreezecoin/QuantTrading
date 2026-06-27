from __future__ import annotations

import math
from collections.abc import Callable

from crypto_quant_loop.data.ohlcv import OhlcvBar

FeatureSeries = list[float | None]
FeatureFunction = Callable[[list[OhlcvBar]], FeatureSeries]


def returns(bars: list[OhlcvBar]) -> FeatureSeries:
    ordered = _ordered(bars)
    values: FeatureSeries = [None]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        values.append((current.close / previous.close) - 1.0)
    return values[: len(ordered)]


def rolling_volatility(bars: list[OhlcvBar], *, window: int) -> FeatureSeries:
    _require_positive_window(window)
    ret = returns(bars)
    values: FeatureSeries = []
    for index in range(len(ret)):
        if index < window:
            values.append(None)
            continue
        sample = [item for item in ret[index - window + 1 : index + 1] if item is not None]
        if len(sample) < window:
            values.append(None)
            continue
        mean = sum(sample) / len(sample)
        variance = sum((item - mean) ** 2 for item in sample) / len(sample)
        values.append(math.sqrt(variance))
    return values


def atr(bars: list[OhlcvBar], *, period: int) -> FeatureSeries:
    _require_positive_window(period)
    ordered = _ordered(bars)
    true_ranges: list[float] = []
    for index, bar in enumerate(ordered):
        if index == 0:
            true_ranges.append(bar.high - bar.low)
            continue
        previous_close = ordered[index - 1].close
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )

    values: FeatureSeries = []
    for index in range(len(true_ranges)):
        if index + 1 < period:
            values.append(None)
            continue
        window = true_ranges[index - period + 1 : index + 1]
        values.append(sum(window) / period)
    return values


def volume_change(bars: list[OhlcvBar]) -> FeatureSeries:
    ordered = _ordered(bars)
    values: FeatureSeries = [None]
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous.volume == 0:
            values.append(None)
        else:
            values.append((current.volume / previous.volume) - 1.0)
    return values[: len(ordered)]


def bar_spread_bps(bars: list[OhlcvBar]) -> FeatureSeries:
    ordered = _ordered(bars)
    values: FeatureSeries = []
    for bar in ordered:
        if bar.close <= 0:
            values.append(None)
        else:
            values.append(((bar.high - bar.low) / bar.close) * 10_000)
    return values


def detect_lookahead(bars: list[OhlcvBar], feature_fn: FeatureFunction) -> list[int]:
    ordered = _ordered(bars)
    full = feature_fn(ordered)
    if len(full) != len(ordered):
        raise ValueError("Feature function must return the same length as input bars")

    leaking_indices: list[int] = []
    for index in range(len(ordered)):
        prefix = ordered[: index + 1]
        prefix_values = feature_fn(prefix)
        if len(prefix_values) != len(prefix):
            raise ValueError("Feature function must return the same length as input bars")
        if prefix_values[-1] != full[index]:
            leaking_indices.append(index)
    return leaking_indices


def _ordered(bars: list[OhlcvBar]) -> list[OhlcvBar]:
    return sorted(bars, key=lambda item: item.timestamp_ms)


def _require_positive_window(window: int) -> None:
    if window <= 0:
        raise ValueError("window must be positive")

