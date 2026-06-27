from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from crypto_quant_loop.backtest import (
    LookaheadDetectedError,
    run_backtest,
    validate_signal_generator_no_lookahead,
)
from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.strategies import Signal

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_bar(index: int, close: float) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp_ms=index * 3_600_000,
        open=close,
        high=close + 2,
        low=close - 2,
        close=close,
        volume=100,
    )


def make_signal(
    timestamp_ms: int,
    *,
    order_type: Literal["market", "limit"] = "market",
    stop: float = 99.0,
) -> Signal:
    return Signal(
        strategy_name=f"{order_type}_strategy",
        strategy_type="momentum" if order_type == "market" else "mean_reversion",
        symbol="BTCUSDT",
        timestamp_ms=timestamp_ms,
        side="long",
        order_type=order_type,
        reference_price=100.0,
        stop_price=stop,
    )


def test_backtest_report_is_reproducible() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar(index, 100 + index) for index in range(5)]
    signals = [make_signal(bars[0].timestamp_ms)]

    first = run_backtest(
        bars=bars,
        signals=signals,
        risk_policy=configs.risk_policy,
        fills=configs.fills,
        symbols=configs.symbols,
    )
    second = run_backtest(
        bars=list(reversed(bars)),
        signals=signals,
        risk_policy=configs.risk_policy,
        fills=configs.fills,
        symbols=configs.symbols,
    )

    assert first == second
    assert first.trades == 1


def test_min_notional_floor_skips_tiny_signal() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    tiny_risk = configs.risk_policy.position_sizing.model_copy(
        update={"single_trade_risk_pct": 0.000001}
    )
    risk_policy = configs.risk_policy.model_copy(update={"position_sizing": tiny_risk})
    bars = [make_bar(index, 100 + index) for index in range(3)]

    report = run_backtest(
        bars=bars,
        signals=[make_signal(bars[0].timestamp_ms)],
        risk_policy=risk_policy,
        fills=configs.fills,
        symbols=configs.symbols,
    )

    assert report.trades == 0
    assert report.skipped_signals == 1


def test_fees_follow_maker_taker_order_type() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    fee_config = configs.fills.fees.model_copy(update={"maker_bps": 5.0, "taker_bps": 10.0})
    fills = configs.fills.model_copy(update={"fees": fee_config})
    bars = [make_bar(index, 100 + index) for index in range(4)]

    market_report = run_backtest(
        bars=bars,
        signals=[make_signal(bars[0].timestamp_ms, order_type="market")],
        risk_policy=configs.risk_policy,
        fills=fills,
        symbols=configs.symbols,
    )
    limit_report = run_backtest(
        bars=bars,
        signals=[make_signal(bars[1].timestamp_ms, order_type="limit")],
        risk_policy=configs.risk_policy,
        fills=fills,
        symbols=configs.symbols,
    )

    assert market_report.trade_log[0].fees_paid > limit_report.trade_log[0].fees_paid
    assert market_report.trade_log[0].order_type == "market"
    assert limit_report.trade_log[0].order_type == "limit"


def test_lookahead_injection_is_blocked() -> None:
    bars = [make_bar(index, 100 + index) for index in range(3)]

    def leaky_generator(input_bars: list[OhlcvBar]) -> list[Signal]:
        if len(input_bars) < 2:
            return []
        return [make_signal(input_bars[0].timestamp_ms)]

    with pytest.raises(LookaheadDetectedError):
        validate_signal_generator_no_lookahead(bars, leaky_generator)
