from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from crypto_quant_loop.backtest import Trade, WalkForwardReport
from crypto_quant_loop.backtest.walk_forward import Regime


@dataclass(frozen=True)
class RegimeDiagnostics:
    regime: Regime
    segments: int
    trades: int
    net_pnl: float
    total_return_pct: float
    fees_paid: float


@dataclass(frozen=True)
class StrategyDiagnostics:
    strategy_name: str
    segments: int
    total_oos_trades: int
    aggregate_oos_return_pct: float
    average_oos_sharpe: float
    net_pnl: float
    gross_pnl: float
    fees_paid: float
    turnover: float
    fee_pct_of_turnover: float
    fee_drag_pct_of_gross_profit: float
    win_rate: float
    average_win: float
    average_loss: float
    average_win_loss_ratio: float
    average_signal_lag_bars: float
    regime_diagnostics: tuple[RegimeDiagnostics, ...]
    dominant_failure_modes: tuple[str, ...]

    def to_report(self) -> dict[str, Any]:
        return asdict(self)


def diagnose_walk_forward_report(
    *,
    strategy_name: str,
    report: WalkForwardReport,
    timeframe_ms: int,
) -> StrategyDiagnostics:
    oos_reports = [segment.oos_report for segment in report.segments]
    trades = [trade for oos_report in oos_reports for trade in oos_report.trade_log]
    net_pnl = sum(trade.net_pnl for trade in trades)
    gross_pnl = sum(trade.gross_pnl for trade in trades)
    fees_paid = sum(oos_report.fees_paid for oos_report in oos_reports)
    turnover = sum(oos_report.turnover for oos_report in oos_reports)
    gross_profit = sum(trade.net_pnl for trade in trades if trade.net_pnl > 0)
    wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losses = [abs(trade.net_pnl) for trade in trades if trade.net_pnl < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    average_signal_lag_bars = _average_signal_lag_bars(trades, timeframe_ms)
    regime_diagnostics = _regime_diagnostics(report)
    return StrategyDiagnostics(
        strategy_name=strategy_name,
        segments=len(report.segments),
        total_oos_trades=len(trades),
        aggregate_oos_return_pct=sum(
            oos_report.total_return_pct for oos_report in oos_reports
        ),
        average_oos_sharpe=report.average_oos_sharpe,
        net_pnl=net_pnl,
        gross_pnl=gross_pnl,
        fees_paid=fees_paid,
        turnover=turnover,
        fee_pct_of_turnover=(fees_paid / turnover) * 100 if turnover else 0.0,
        fee_drag_pct_of_gross_profit=(fees_paid / gross_profit) * 100
        if gross_profit
        else 0.0,
        win_rate=_win_rate(trades),
        average_win=average_win,
        average_loss=average_loss,
        average_win_loss_ratio=(average_win / average_loss) if average_loss else 0.0,
        average_signal_lag_bars=average_signal_lag_bars,
        regime_diagnostics=regime_diagnostics,
        dominant_failure_modes=_dominant_failure_modes(
            total_oos_trades=len(trades),
            aggregate_return_pct=sum(
                oos_report.total_return_pct for oos_report in oos_reports
            ),
            net_pnl=net_pnl,
            gross_pnl=gross_pnl,
            fees_paid=fees_paid,
            win_rate=_win_rate(trades),
            average_win_loss_ratio=(average_win / average_loss) if average_loss else 0.0,
            average_signal_lag_bars=average_signal_lag_bars,
            regime_diagnostics=regime_diagnostics,
        ),
    )


def _regime_diagnostics(report: WalkForwardReport) -> tuple[RegimeDiagnostics, ...]:
    output: list[RegimeDiagnostics] = []
    for regime in ("bull", "bear", "chop"):
        segments = [segment for segment in report.segments if segment.regime == regime]
        if not segments:
            continue
        oos_reports = [segment.oos_report for segment in segments]
        trades = [trade for oos_report in oos_reports for trade in oos_report.trade_log]
        output.append(
            RegimeDiagnostics(
                regime=regime,
                segments=len(segments),
                trades=len(trades),
                net_pnl=sum(trade.net_pnl for trade in trades),
                total_return_pct=sum(
                    oos_report.total_return_pct for oos_report in oos_reports
                ),
                fees_paid=sum(oos_report.fees_paid for oos_report in oos_reports),
            )
        )
    return tuple(output)


def _dominant_failure_modes(
    *,
    total_oos_trades: int,
    aggregate_return_pct: float,
    net_pnl: float,
    gross_pnl: float,
    fees_paid: float,
    win_rate: float,
    average_win_loss_ratio: float,
    average_signal_lag_bars: float,
    regime_diagnostics: tuple[RegimeDiagnostics, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if total_oos_trades == 0:
        return ("no_oos_trades",)
    if aggregate_return_pct <= 0:
        reasons.append("negative_oos_return")
    if gross_pnl > 0 and net_pnl <= 0 and fees_paid >= gross_pnl:
        reasons.append("fee_drag_dominated")
    elif fees_paid >= abs(net_pnl):
        reasons.append("fees_larger_than_net_edge")
    losing_regimes = [
        item.regime
        for item in regime_diagnostics
        if item.trades > 0 and item.net_pnl < 0
    ]
    if len(losing_regimes) == len([item for item in regime_diagnostics if item.trades > 0]):
        reasons.append("broad_regime_failure")
    elif losing_regimes:
        reasons.extend(f"weak_in_{regime}_regime" for regime in losing_regimes)
    if win_rate < 0.45:
        reasons.append("low_win_rate")
    if average_win_loss_ratio and average_win_loss_ratio < 1.0:
        reasons.append("poor_payoff_ratio")
    if average_signal_lag_bars > 1.5:
        reasons.append("signal_lag_above_one_bar")
    return tuple(dict.fromkeys(reasons)) or ("no_dominant_failure_detected",)


def _average_signal_lag_bars(trades: list[Trade], timeframe_ms: int) -> float:
    if not trades:
        return 0.0
    return (
        sum(
            (trade.entry_timestamp_ms - trade.signal_timestamp_ms) / timeframe_ms
            for trade in trades
        )
        / len(trades)
    )


def _win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    return sum(1 for trade in trades if trade.net_pnl > 0) / len(trades)
