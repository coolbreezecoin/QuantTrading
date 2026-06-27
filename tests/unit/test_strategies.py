from __future__ import annotations

from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.strategies import generate_configured_signals

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_bar(
    index: int,
    close: float,
    *,
    high: float | None = None,
    low: float | None = None,
) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp_ms=index * 3_600_000,
        open=close,
        high=high or close + 1,
        low=low or close - 1,
        close=close,
        volume=100,
    )


def test_generate_signals_is_reproducible() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar(index, 100 + index * 0.1) for index in range(80)]

    first = generate_configured_signals(
        bars,
        strategies=configs.strategies,
        risk_policy=configs.risk_policy,
    )
    second = generate_configured_signals(
        list(reversed(bars)),
        strategies=configs.strategies,
        risk_policy=configs.risk_policy,
    )

    assert first == second


def test_momentum_breakout_signal_uses_config_order_type_and_stop() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar(index, 100 + index * 0.1, high=101 + index * 0.1) for index in range(70)]
    bars.append(make_bar(70, 120, high=121, low=118))

    signals = generate_configured_signals(
        bars,
        strategies=configs.strategies,
        risk_policy=configs.risk_policy,
    )
    momentum_signals = [signal for signal in signals if signal.strategy_type == "momentum"]

    assert momentum_signals
    signal = momentum_signals[-1]
    assert signal.order_type == "market"
    assert signal.stop_price < signal.reference_price
    assert "donchian_high" in signal.metadata


def test_mean_reversion_signal_has_hard_stop_and_time_stop() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar(index, 100) for index in range(200)]
    bars.extend(make_bar(200 + index, 120) for index in range(19))
    bars.append(make_bar(219, 105, high=106, low=103))

    signals = generate_configured_signals(
        bars,
        strategies=configs.strategies,
        risk_policy=configs.risk_policy,
    )
    mean_reversion_signals = [
        signal for signal in signals if signal.strategy_type == "mean_reversion"
    ]

    assert mean_reversion_signals
    signal = mean_reversion_signals[-1]
    assert signal.order_type == "limit"
    assert signal.stop_price < signal.reference_price
    assert signal.time_stop_bars == configs.risk_policy.mean_reversion.time_stop_bars
