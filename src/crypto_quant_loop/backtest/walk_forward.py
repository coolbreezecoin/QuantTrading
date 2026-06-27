from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from crypto_quant_loop.backtest.engine import BacktestReport, run_backtest
from crypto_quant_loop.config.models import FillsConfig, RiskPolicyConfig, SymbolsConfig
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.strategies import Signal

Regime = Literal["bull", "bear", "chop"]
SignalGenerator = Callable[[list[OhlcvBar]], list[Signal]]


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    is_start: int
    is_end: int
    oos_start: int
    oos_end: int
    purge_bars: int
    embargo_bars: int


@dataclass(frozen=True)
class WalkForwardSegmentReport:
    window: WalkForwardWindow
    regime: Regime
    is_report: BacktestReport
    oos_report: BacktestReport
    sharpe_decay: float
    deflated_oos_sharpe: float


@dataclass(frozen=True)
class WalkForwardReport:
    parameter_trials: int
    segments: list[WalkForwardSegmentReport]

    @property
    def oos_positive_segments(self) -> int:
        return sum(1 for segment in self.segments if segment.oos_report.total_return_pct > 0)

    @property
    def average_oos_sharpe(self) -> float:
        if not self.segments:
            return 0.0
        return sum(segment.oos_report.sharpe for segment in self.segments) / len(self.segments)


def build_walk_forward_windows(
    bars: list[OhlcvBar],
    *,
    is_bars: int,
    oos_bars: int,
    purge_bars: int,
    embargo_bars: int,
    step_bars: int | None = None,
) -> list[WalkForwardWindow]:
    if is_bars <= 0 or oos_bars <= 0 or purge_bars < 0 or embargo_bars < 0:
        raise ValueError("Invalid walk-forward window sizes")
    step = step_bars or oos_bars
    windows: list[WalkForwardWindow] = []
    start = 0
    index = 0
    total_gap = purge_bars + embargo_bars
    while True:
        is_start = start
        is_end = is_start + is_bars
        oos_start = is_end + total_gap
        oos_end = oos_start + oos_bars
        if oos_end > len(bars):
            break
        windows.append(
            WalkForwardWindow(
                index=index,
                is_start=is_start,
                is_end=is_end,
                oos_start=oos_start,
                oos_end=oos_end,
                purge_bars=purge_bars,
                embargo_bars=embargo_bars,
            )
        )
        start += step
        index += 1
    return windows


def run_walk_forward(
    *,
    bars: list[OhlcvBar],
    signal_generator: SignalGenerator,
    risk_policy: RiskPolicyConfig,
    fills: FillsConfig,
    symbols: SymbolsConfig,
    is_bars: int,
    oos_bars: int,
    purge_bars: int,
    embargo_bars: int,
    parameter_trials: int,
) -> WalkForwardReport:
    ordered = sorted(bars, key=lambda item: item.timestamp_ms)
    windows = build_walk_forward_windows(
        ordered,
        is_bars=is_bars,
        oos_bars=oos_bars,
        purge_bars=purge_bars,
        embargo_bars=embargo_bars,
    )
    segments: list[WalkForwardSegmentReport] = []
    for window in windows:
        is_slice = ordered[window.is_start : window.is_end]
        oos_slice = ordered[window.oos_start : window.oos_end]
        is_report = run_backtest(
            bars=is_slice,
            signals=signal_generator(is_slice),
            risk_policy=risk_policy,
            fills=fills,
            symbols=symbols,
        )
        oos_report = run_backtest(
            bars=oos_slice,
            signals=signal_generator(oos_slice),
            risk_policy=risk_policy,
            fills=fills,
            symbols=symbols,
        )
        segments.append(
            WalkForwardSegmentReport(
                window=window,
                regime=classify_regime(oos_slice),
                is_report=is_report,
                oos_report=oos_report,
                sharpe_decay=_sharpe_decay(is_report.sharpe, oos_report.sharpe),
                deflated_oos_sharpe=_deflate_sharpe(
                    oos_report.sharpe,
                    parameter_trials=parameter_trials,
                    trades=oos_report.trades,
                ),
            )
        )
    return WalkForwardReport(parameter_trials=parameter_trials, segments=segments)


def classify_regime(bars: list[OhlcvBar]) -> Regime:
    if len(bars) < 2:
        return "chop"
    change = (bars[-1].close / bars[0].close) - 1.0
    if change > 0.05:
        return "bull"
    if change < -0.05:
        return "bear"
    return "chop"


def _sharpe_decay(is_sharpe: float, oos_sharpe: float) -> float:
    if is_sharpe <= 0:
        return 0.0 if oos_sharpe >= 0 else 1.0
    return max(0.0, (is_sharpe - oos_sharpe) / is_sharpe)


def _deflate_sharpe(sharpe: float, *, parameter_trials: int, trades: int) -> float:
    trials = max(parameter_trials, 1)
    sample = max(trades, 1)
    penalty = math.sqrt(math.log(trials + 1) / sample)
    return sharpe - penalty

