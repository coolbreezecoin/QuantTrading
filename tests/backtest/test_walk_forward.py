from __future__ import annotations

from pathlib import Path

from crypto_quant_loop.backtest import build_walk_forward_windows, run_walk_forward
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


def signal_every_first_bar(bars: list[OhlcvBar]) -> list[Signal]:
    if len(bars) < 2:
        return []
    first = bars[0]
    return [
        Signal(
            strategy_name="test",
            strategy_type="momentum",
            symbol="BTCUSDT",
            timestamp_ms=first.timestamp_ms,
            side="long",
            order_type="market",
            reference_price=first.close,
            stop_price=first.close - 1,
        )
    ]


def test_walk_forward_windows_include_purge_and_embargo() -> None:
    bars = [make_bar(index, 100) for index in range(30)]

    windows = build_walk_forward_windows(
        bars,
        is_bars=10,
        oos_bars=5,
        purge_bars=2,
        embargo_bars=1,
    )

    assert windows[0].is_start == 0
    assert windows[0].is_end == 10
    assert windows[0].oos_start == 13
    assert windows[0].oos_end == 18
    assert windows[1].is_start == 5


def test_walk_forward_report_contains_oos_decay_and_regimes() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [
        *[make_bar(index, 100 + index * 0.2) for index in range(20)],
        *[make_bar(20 + index, 120 - index * 0.5) for index in range(20)],
        *[make_bar(40 + index, 110 + (index % 2)) for index in range(20)],
    ]

    report = run_walk_forward(
        bars=bars,
        signal_generator=signal_every_first_bar,
        risk_policy=configs.risk_policy,
        fills=configs.fills,
        symbols=configs.symbols,
        is_bars=15,
        oos_bars=10,
        purge_bars=1,
        embargo_bars=1,
        parameter_trials=25,
    )

    assert report.parameter_trials == 25
    assert report.segments
    assert all(segment.sharpe_decay >= 0 for segment in report.segments)
    assert {segment.regime for segment in report.segments}


def test_deflated_sharpe_penalizes_many_trials() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar(index, 100 + index) for index in range(40)]

    few_trials = run_walk_forward(
        bars=bars,
        signal_generator=signal_every_first_bar,
        risk_policy=configs.risk_policy,
        fills=configs.fills,
        symbols=configs.symbols,
        is_bars=10,
        oos_bars=10,
        purge_bars=0,
        embargo_bars=0,
        parameter_trials=1,
    )
    many_trials = run_walk_forward(
        bars=bars,
        signal_generator=signal_every_first_bar,
        risk_policy=configs.risk_policy,
        fills=configs.fills,
        symbols=configs.symbols,
        is_bars=10,
        oos_bars=10,
        purge_bars=0,
        embargo_bars=0,
        parameter_trials=100,
    )

    assert many_trials.segments[0].deflated_oos_sharpe < few_trials.segments[0].deflated_oos_sharpe

