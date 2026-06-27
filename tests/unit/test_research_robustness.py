from __future__ import annotations

from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.research import (
    RobustSignalSettings,
    apply_robust_signal_filters,
    build_robust_strategy_config,
)
from crypto_quant_loop.strategies import Signal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOUR_MS = 3_600_000


def make_bar(index: int, close: float) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp_ms=index * HOUR_MS,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
    )


def make_signal(index: int) -> Signal:
    return Signal(
        strategy_name="momentum_breakout",
        strategy_type="momentum",
        symbol="BTCUSDT",
        timestamp_ms=index * HOUR_MS,
        side="long",
        order_type="market",
        reference_price=100,
        stop_price=95,
        time_stop_bars=1,
    )


def test_robust_filter_uses_past_regime_and_min_spacing() -> None:
    bars = [make_bar(index, 100 + index * 0.2) for index in range(40)]
    future_crash = [make_bar(40 + index, 200 - index * 5) for index in range(10)]
    settings = RobustSignalSettings(
        strategy_name="momentum_breakout",
        allowed_regimes=("bull",),
        regime_lookback_bars=30,
        min_spacing_bars=10,
        time_stop_bars=24,
        params_update={},
        stop_update={},
    )

    accepted_without_future = apply_robust_signal_filters(
        bars,
        [make_signal(30), make_signal(35)],
        settings=settings,
    )
    accepted_with_future = apply_robust_signal_filters(
        [*bars, *future_crash],
        [make_signal(30), make_signal(35)],
        settings=settings,
    )

    assert [signal.timestamp_ms for signal in accepted_without_future] == [30 * HOUR_MS]
    assert accepted_with_future == accepted_without_future


def test_robust_filter_rejects_wrong_regime() -> None:
    bars = [make_bar(index, 100 - index * 0.3) for index in range(40)]
    settings = RobustSignalSettings(
        strategy_name="momentum_breakout",
        allowed_regimes=("bull",),
        regime_lookback_bars=30,
        min_spacing_bars=1,
        time_stop_bars=24,
        params_update={},
        stop_update={},
    )

    accepted = apply_robust_signal_filters(bars, [make_signal(30)], settings=settings)

    assert accepted == []


def test_robust_config_updates_research_only_strategy_params() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")

    robust = build_robust_strategy_config(configs.strategies, "momentum_breakout")

    assert robust.strategies["momentum_breakout"].params.fast_ma == 50
    assert configs.strategies.strategies["momentum_breakout"].params.fast_ma == 20
