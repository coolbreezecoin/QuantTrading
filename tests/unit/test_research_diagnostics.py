from __future__ import annotations

from crypto_quant_loop.backtest import (
    BacktestReport,
    Trade,
    WalkForwardReport,
    WalkForwardSegmentReport,
    WalkForwardWindow,
)
from crypto_quant_loop.research import diagnose_walk_forward_report

HOUR_MS = 3_600_000


def make_trade(index: int, net_pnl: float, gross_pnl: float, fees: float) -> Trade:
    return Trade(
        signal_timestamp_ms=index * HOUR_MS,
        entry_timestamp_ms=(index + 1) * HOUR_MS,
        exit_timestamp_ms=(index + 2) * HOUR_MS,
        symbol="BTCUSDT",
        strategy_name="strategy",
        order_type="market",
        quantity=1,
        entry_price=100,
        exit_price=100 + gross_pnl,
        gross_pnl=gross_pnl,
        fees_paid=fees,
        net_pnl=net_pnl,
        notional=100,
    )


def make_report(trades: list[Trade], *, total_return_pct: float, sharpe: float) -> BacktestReport:
    return BacktestReport(
        starting_equity=1_000,
        ending_equity=1_000 + sum(trade.net_pnl for trade in trades),
        total_return_pct=total_return_pct,
        annualized_return_pct=total_return_pct,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown_pct=5,
        win_rate=0.5,
        profit_factor=1,
        trades=len(trades),
        skipped_signals=0,
        fees_paid=sum(trade.fees_paid for trade in trades),
        turnover=sum(trade.notional * 2 for trade in trades),
        fee_pct_of_turnover=0.1,
        trade_log=trades,
    )


def make_segment(index: int, regime: str, oos_report: BacktestReport) -> WalkForwardSegmentReport:
    window = WalkForwardWindow(
        index=index,
        is_start=0,
        is_end=10,
        oos_start=11,
        oos_end=20,
        purge_bars=1,
        embargo_bars=0,
    )
    return WalkForwardSegmentReport(
        window=window,
        regime=regime,  # type: ignore[arg-type]
        is_report=make_report([], total_return_pct=1, sharpe=1),
        oos_report=oos_report,
        sharpe_decay=0.5,
        deflated_oos_sharpe=oos_report.sharpe,
    )


def test_diagnostics_detect_fee_drag_and_regime_failure() -> None:
    trades = [
        make_trade(0, net_pnl=-1, gross_pnl=1, fees=2),
        make_trade(3, net_pnl=-2, gross_pnl=-1, fees=1),
    ]
    report = WalkForwardReport(
        parameter_trials=1,
        segments=[
            make_segment(0, "bull", make_report(trades, total_return_pct=-1, sharpe=-0.5))
        ],
    )

    diagnostics = diagnose_walk_forward_report(
        strategy_name="momentum_breakout",
        report=report,
        timeframe_ms=HOUR_MS,
    )

    assert diagnostics.total_oos_trades == 2
    assert diagnostics.fees_paid == 3
    assert diagnostics.average_signal_lag_bars == 1
    assert diagnostics.regime_diagnostics[0].regime == "bull"
    assert "fees_larger_than_net_edge" in diagnostics.dominant_failure_modes
    assert "broad_regime_failure" in diagnostics.dominant_failure_modes


def test_diagnostics_marks_no_trades_as_failure_mode() -> None:
    report = WalkForwardReport(
        parameter_trials=1,
        segments=[
            make_segment(0, "chop", make_report([], total_return_pct=0, sharpe=0))
        ],
    )

    diagnostics = diagnose_walk_forward_report(
        strategy_name="mean_reversion",
        report=report,
        timeframe_ms=HOUR_MS,
    )

    assert diagnostics.total_oos_trades == 0
    assert diagnostics.dominant_failure_modes == ("no_oos_trades",)
