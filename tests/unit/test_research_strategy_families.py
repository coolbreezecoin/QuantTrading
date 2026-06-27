from __future__ import annotations

from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.research import (
    generate_regime_switch_signals,
    generate_volatility_target_trend_signals,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOUR_MS = 3_600_000


def make_bar(index: int, close: float) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp_ms=index * HOUR_MS,
        open=close,
        high=close,
        low=close - 0.5,
        close=close,
        volume=100,
    )


def test_volatility_target_trend_is_deterministic_and_spaced() -> None:
    bars = [make_bar(index, 100 + index * 0.2) for index in range(320)]

    first = generate_volatility_target_trend_signals(
        bars,
        fast_ma=20,
        slow_ma=40,
        breakout_lookback=30,
        regime_lookback_bars=30,
        min_spacing_bars=24,
    )
    second = generate_volatility_target_trend_signals(
        list(reversed(bars)),
        fast_ma=20,
        slow_ma=40,
        breakout_lookback=30,
        regime_lookback_bars=30,
        min_spacing_bars=24,
    )

    assert first == second
    assert first
    assert all(
        current.timestamp_ms - previous.timestamp_ms >= 24 * HOUR_MS
        for previous, current in zip(first, first[1:], strict=False)
    )
    assert all(signal.time_stop_bars == 72 for signal in first)


def test_volatility_target_trend_uses_past_regime_only() -> None:
    bull_bars = [make_bar(index, 100 + index * 0.2) for index in range(180)]
    future_bear = [make_bar(180 + index, 160 - index * 2) for index in range(30)]

    without_future = generate_volatility_target_trend_signals(
        bull_bars,
        fast_ma=20,
        slow_ma=40,
        breakout_lookback=30,
        regime_lookback_bars=30,
    )
    with_future = generate_volatility_target_trend_signals(
        [*bull_bars, *future_bear],
        fast_ma=20,
        slow_ma=40,
        breakout_lookback=30,
        regime_lookback_bars=30,
    )

    assert without_future
    past_signals = [
        signal for signal in with_future if signal.timestamp_ms < 180 * HOUR_MS
    ]
    assert past_signals == without_future


def test_regime_switch_combines_existing_robust_families_without_registry_changes() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar(index, 100 + index * 0.2) for index in range(320)]

    signals = generate_regime_switch_signals(
        bars,
        strategies=configs.strategies,
        risk_policy=configs.risk_policy,
    )

    assert all(signal.strategy_name == "regime_switch_existing" for signal in signals)
    assert configs.exchanges.defaults.dry_run is True
