from __future__ import annotations

import pytest

from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.features import (
    atr,
    bar_spread_bps,
    detect_lookahead,
    returns,
    rolling_volatility,
    volume_change,
)


def make_bar(index: int, close: float, volume: float = 100.0) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp_ms=index * 3_600_000,
        open=close - 1,
        high=close + 2,
        low=close - 2,
        close=close,
        volume=volume,
    )


def test_features_are_deterministic() -> None:
    bars = [make_bar(0, 100), make_bar(1, 110), make_bar(2, 99)]

    assert returns(bars) == returns(list(reversed(bars)))
    assert atr(bars, period=2) == atr(list(reversed(bars)), period=2)
    assert volume_change(bars) == volume_change(list(reversed(bars)))


def test_basic_feature_values() -> None:
    bars = [make_bar(0, 100, 100), make_bar(1, 110, 150), make_bar(2, 121, 75)]

    assert returns(bars) == pytest.approx([None, 0.1, 0.1])
    assert volume_change(bars) == pytest.approx([None, 0.5, -0.5])
    assert bar_spread_bps([bars[0]]) == [400.0]
    assert atr(bars, period=2) == pytest.approx([None, 8.0, 12.5])
    assert rolling_volatility(bars, window=2) == [None, None, 0.0]


def test_detect_lookahead_rejects_future_leakage() -> None:
    bars = [make_bar(0, 100), make_bar(1, 110), make_bar(2, 90)]

    def leaky_next_return(input_bars: list[OhlcvBar]) -> list[float | None]:
        values: list[float | None] = []
        for index, bar in enumerate(input_bars):
            if index + 1 >= len(input_bars):
                values.append(None)
            else:
                values.append((input_bars[index + 1].close / bar.close) - 1.0)
        return values

    assert detect_lookahead(bars, leaky_next_return) == [0, 1]
    assert detect_lookahead(bars, returns) == []
