from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

from crypto_quant_loop.backtest import BacktestReport
from crypto_quant_loop.config.models import BeatCriteriaConfig, FillsConfig, ResearchConfig
from crypto_quant_loop.data.ohlcv import OhlcvBar


@dataclass(frozen=True)
class PerformanceSnapshot:
    name: str
    total_return_pct: float
    annualized_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    calmar: float
    fees_paid: float


@dataclass(frozen=True)
class BenchmarkMetrics:
    name: str
    symbols: tuple[str, ...]
    start_timestamp_ms: int
    end_timestamp_ms: int
    periods: int
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    annualized_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    calmar: float
    fees_paid: float

    def to_snapshot(self) -> PerformanceSnapshot:
        return PerformanceSnapshot(
            name=self.name,
            total_return_pct=self.total_return_pct,
            annualized_return_pct=self.annualized_return_pct,
            sharpe=self.sharpe,
            max_drawdown_pct=self.max_drawdown_pct,
            calmar=self.calmar,
            fees_paid=self.fees_paid,
        )


@dataclass(frozen=True)
class BeatDecision:
    candidate: str
    benchmark: str
    beats: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float]


def load_ohlcv_from_duckdb(
    db_path: Path,
    *,
    symbols: Sequence[str],
    timeframe: str,
) -> dict[str, list[OhlcvBar]]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT exchange, symbol, timeframe, timestamp_ms, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol IN (SELECT * FROM UNNEST(?))
              AND timeframe = ?
            ORDER BY symbol, timestamp_ms
            """,
            [list(symbols), timeframe],
        ).fetchall()
    finally:
        con.close()

    output: dict[str, list[OhlcvBar]] = {symbol: [] for symbol in symbols}
    for exchange, symbol, row_timeframe, timestamp_ms, open_, high, low, close, volume in rows:
        output[str(symbol)].append(
            OhlcvBar(
                exchange=str(exchange),
                symbol=str(symbol),
                timeframe=str(row_timeframe),
                timestamp_ms=int(timestamp_ms),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    return output


def build_baseline_report(
    bars_by_symbol: Mapping[str, list[OhlcvBar]],
    *,
    research: ResearchConfig,
    fills: FillsConfig,
    starting_equity: float,
) -> dict[str, Any]:
    primary = research.benchmarks.primary_symbol
    benchmarks = {
        "buy_and_hold_btc": compute_buy_and_hold(
            bars_by_symbol[primary],
            fills=fills,
            starting_equity=starting_equity,
            name="buy_and_hold_btc",
        ),
        "equal_weight_basket": compute_equal_weight_basket(
            {
                symbol: bars_by_symbol[symbol]
                for symbol in research.benchmarks.basket_symbols
            },
            weights=research.benchmarks.basket_weights,
            fills=fills,
            starting_equity=starting_equity,
            name="equal_weight_basket",
        ),
    }
    return {
        "criteria": research.beat_criteria.model_dump(),
        "benchmarks": {
            name: asdict(metrics)
            for name, metrics in benchmarks.items()
        },
    }


def compute_buy_and_hold(
    bars: list[OhlcvBar],
    *,
    fills: FillsConfig,
    starting_equity: float,
    name: str,
) -> BenchmarkMetrics:
    ordered = _ordered(bars)
    if len(ordered) < 2:
        raise ValueError("buy-and-hold baseline requires at least two bars")
    fee_rate = _fee_rate(fills)
    quantity = (starting_equity * (1.0 - fee_rate)) / ordered[0].close
    equity_curve = [starting_equity]
    for bar in ordered:
        equity_curve.append(quantity * bar.close)
    ending_before_exit_fee = quantity * ordered[-1].close
    exit_fee = ending_before_exit_fee * fee_rate
    equity_curve[-1] = ending_before_exit_fee - exit_fee
    return _metrics_from_curve(
        name=name,
        symbols=(ordered[0].symbol,),
        start_timestamp_ms=ordered[0].timestamp_ms,
        end_timestamp_ms=ordered[-1].timestamp_ms,
        starting_equity=starting_equity,
        equity_curve=equity_curve,
        fees_paid=(starting_equity * fee_rate) + exit_fee,
    )


def compute_equal_weight_basket(
    bars_by_symbol: Mapping[str, list[OhlcvBar]],
    *,
    weights: Mapping[str, float],
    fills: FillsConfig,
    starting_equity: float,
    name: str,
) -> BenchmarkMetrics:
    if set(bars_by_symbol) != set(weights):
        raise ValueError("basket symbols and weights must match")
    aligned = _align_by_common_timestamps(bars_by_symbol)
    if len(aligned) < 2:
        raise ValueError("equal-weight basket requires at least two aligned bars")
    fee_rate = _fee_rate(fills)
    symbols = tuple(sorted(bars_by_symbol))
    first_prices = aligned[0][1]
    quantities = {
        symbol: (starting_equity * weights[symbol] * (1.0 - fee_rate)) / first_prices[symbol]
        for symbol in symbols
    }
    entry_fees = starting_equity * fee_rate
    equity_curve = [starting_equity]
    for _timestamp_ms, price_by_symbol in aligned:
        equity_curve.append(
            sum(quantities[symbol] * price_by_symbol[symbol] for symbol in symbols)
        )
    final_value = equity_curve[-1]
    exit_fee = final_value * fee_rate
    equity_curve[-1] = final_value - exit_fee
    return _metrics_from_curve(
        name=name,
        symbols=symbols,
        start_timestamp_ms=aligned[0][0],
        end_timestamp_ms=aligned[-1][0],
        starting_equity=starting_equity,
        equity_curve=equity_curve,
        fees_paid=entry_fees + exit_fee,
    )


def snapshot_from_backtest(name: str, report: BacktestReport) -> PerformanceSnapshot:
    return PerformanceSnapshot(
        name=name,
        total_return_pct=report.total_return_pct,
        annualized_return_pct=report.annualized_return_pct,
        sharpe=report.sharpe,
        max_drawdown_pct=report.max_drawdown_pct,
        calmar=_calmar(report.annualized_return_pct, report.max_drawdown_pct),
        fees_paid=report.fees_paid,
    )


def beats_benchmark(
    *,
    candidate: PerformanceSnapshot,
    benchmark: PerformanceSnapshot,
    criteria: BeatCriteriaConfig,
) -> BeatDecision:
    reasons: list[str] = []
    if criteria.metric_scope != "oos":
        reasons.append("metric_scope_not_oos")
    if not criteria.fee_adjusted:
        reasons.append("fee_adjustment_required")
    if not criteria.risk_adjusted:
        reasons.append("risk_adjustment_required")
    if criteria.require_positive_oos_return and candidate.total_return_pct <= 0:
        reasons.append("candidate_not_positive_after_fees")

    calmar_delta = candidate.calmar - benchmark.calmar
    sharpe_delta = candidate.sharpe - benchmark.sharpe
    allowed_drawdown = benchmark.max_drawdown_pct * criteria.max_drawdown_ratio
    drawdown_delta = candidate.max_drawdown_pct - benchmark.max_drawdown_pct
    calmar_beats = calmar_delta >= criteria.calmar_min_delta
    sharpe_drawdown_beats = (
        sharpe_delta >= criteria.sharpe_min_delta
        and candidate.max_drawdown_pct <= allowed_drawdown
    )
    if not (calmar_beats or sharpe_drawdown_beats):
        reasons.append("risk_adjusted_metrics_do_not_beat_benchmark")

    return BeatDecision(
        candidate=candidate.name,
        benchmark=benchmark.name,
        beats=not reasons,
        reasons=tuple(reasons),
        metrics={
            "candidate_total_return_pct": candidate.total_return_pct,
            "benchmark_total_return_pct": benchmark.total_return_pct,
            "calmar_delta": calmar_delta,
            "sharpe_delta": sharpe_delta,
            "drawdown_delta_pct": drawdown_delta,
            "allowed_drawdown_pct": allowed_drawdown,
        },
    )


def _metrics_from_curve(
    *,
    name: str,
    symbols: tuple[str, ...],
    start_timestamp_ms: int,
    end_timestamp_ms: int,
    starting_equity: float,
    equity_curve: list[float],
    fees_paid: float,
) -> BenchmarkMetrics:
    ending_equity = equity_curve[-1]
    returns = _equity_returns(equity_curve)
    annualized = _annualized_return(equity_curve)
    max_drawdown = _max_drawdown(equity_curve) * 100
    return BenchmarkMetrics(
        name=name,
        symbols=symbols,
        start_timestamp_ms=start_timestamp_ms,
        end_timestamp_ms=end_timestamp_ms,
        periods=len(equity_curve) - 1,
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        total_return_pct=((ending_equity / starting_equity) - 1.0) * 100,
        annualized_return_pct=annualized,
        sharpe=_sharpe(returns),
        max_drawdown_pct=max_drawdown,
        calmar=_calmar(annualized, max_drawdown),
        fees_paid=fees_paid,
    )


def _align_by_common_timestamps(
    bars_by_symbol: Mapping[str, list[OhlcvBar]],
) -> list[tuple[int, dict[str, float]]]:
    close_by_symbol = {
        symbol: {bar.timestamp_ms: bar.close for bar in _ordered(bars)}
        for symbol, bars in bars_by_symbol.items()
    }
    common_timestamps = set.intersection(
        *(set(close_by_timestamp) for close_by_timestamp in close_by_symbol.values())
    )
    return [
        (
            timestamp_ms,
            {
                symbol: close_by_symbol[symbol][timestamp_ms]
                for symbol in sorted(close_by_symbol)
            },
        )
        for timestamp_ms in sorted(common_timestamps)
    ]


def _fee_rate(fills: FillsConfig) -> float:
    bps = fills.fees.taker_bps
    if fills.fees.use_bnb_discount:
        bps *= 0.75
    return bps / 10_000


def _ordered(bars: list[OhlcvBar]) -> list[OhlcvBar]:
    return sorted(bars, key=lambda item: item.timestamp_ms)


def _equity_returns(equity_curve: list[float]) -> list[float]:
    output: list[float] = []
    for previous, current in zip(equity_curve, equity_curve[1:], strict=False):
        if previous == 0:
            continue
        output.append((current / previous) - 1.0)
    return output


def _annualized_return(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    total_return = equity_curve[-1] / equity_curve[0]
    periods = len(equity_curve) - 1
    return float(((total_return ** (365 * 24 / periods)) - 1.0) * 100)


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    return (mean / std) * math.sqrt(365 * 24) if std else 0.0


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0] if equity_curve else 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _calmar(annualized_return_pct: float, max_drawdown_pct: float) -> float:
    if max_drawdown_pct == 0:
        if annualized_return_pct > 0:
            return float("inf")
        if annualized_return_pct < 0:
            return float("-inf")
        return 0.0
    return annualized_return_pct / max_drawdown_pct
