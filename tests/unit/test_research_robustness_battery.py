from __future__ import annotations

from crypto_quant_loop.backtest import (
    BacktestReport,
    WalkForwardReport,
    WalkForwardSegmentReport,
    WalkForwardWindow,
)
from crypto_quant_loop.research import run_robustness_battery


def make_report(total_return_pct: float, sharpe: float) -> BacktestReport:
    return BacktestReport(
        starting_equity=1_000,
        ending_equity=1_000 * (1 + total_return_pct / 100),
        total_return_pct=total_return_pct,
        annualized_return_pct=total_return_pct,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown_pct=2,
        win_rate=0.5,
        profit_factor=1,
        trades=20,
        skipped_signals=0,
        fees_paid=1,
        turnover=100,
        fee_pct_of_turnover=1,
        trade_log=[],
    )


def make_walk_forward(returns: list[float]) -> WalkForwardReport:
    segments = []
    for index, value in enumerate(returns):
        segments.append(
            WalkForwardSegmentReport(
                window=WalkForwardWindow(index, 0, 10, 11, 20, 1, 0),
                regime="bull",
                is_report=make_report(value + 1, 1),
                oos_report=make_report(value, 1),
                sharpe_decay=0,
                deflated_oos_sharpe=0.5 if value > 0 else -0.5,
            )
        )
    return WalkForwardReport(parameter_trials=3, segments=segments)


def test_robustness_battery_passes_clean_positive_returns() -> None:
    battery = run_robustness_battery(
        make_walk_forward([1, 2, 1, 1.5, 2]),
        parameter_variant_returns=[5, 6, 5.5],
    )

    assert battery.pass_basic_robustness is True
    assert battery.failure_reasons == ()


def test_robustness_battery_rejects_weak_left_tail_and_cost_sensitivity() -> None:
    battery = run_robustness_battery(
        make_walk_forward([1, -2, -0.5, -1, 0.2]),
        parameter_variant_returns=[-1, 0, 1],
    )

    assert battery.pass_basic_robustness is False
    assert "positive_segment_ratio_not_majority" in battery.failure_reasons
    assert "bootstrap_left_tail_not_positive" in battery.failure_reasons
