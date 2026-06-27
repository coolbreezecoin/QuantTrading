from __future__ import annotations

import json
from pathlib import Path

from crypto_quant_loop.backtest import (
    BacktestReport,
    WalkForwardReport,
    WalkForwardSegmentReport,
    WalkForwardWindow,
)
from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.verifier import (
    approved_strategy_names,
    load_strategy_registry,
    verify_walk_forward_report,
    write_verification_log,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_backtest_report(
    *,
    trades: int,
    total_return_pct: float,
    sharpe: float,
    max_drawdown_pct: float,
) -> BacktestReport:
    return BacktestReport(
        starting_equity=1000,
        ending_equity=1000 * (1 + total_return_pct / 100),
        total_return_pct=total_return_pct,
        annualized_return_pct=total_return_pct,
        sharpe=sharpe,
        sortino=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=0.6,
        profit_factor=1.5,
        trades=trades,
        skipped_signals=0,
        fees_paid=1,
        turnover=100,
        fee_pct_of_turnover=1,
        trade_log=[],
    )


def make_walk_forward_report(
    *,
    trades: int,
    oos_return: float,
    is_sharpe: float,
    oos_sharpe: float,
    max_drawdown_pct: float,
    recent_return: float | None = None,
) -> WalkForwardReport:
    recent = oos_return if recent_return is None else recent_return
    segments = [
        WalkForwardSegmentReport(
            window=WalkForwardWindow(0, 0, 10, 12, 20, 1, 1),
            regime="bull",
            is_report=make_backtest_report(
                trades=trades,
                total_return_pct=oos_return,
                sharpe=is_sharpe,
                max_drawdown_pct=max_drawdown_pct,
            ),
            oos_report=make_backtest_report(
                trades=trades,
                total_return_pct=oos_return,
                sharpe=oos_sharpe,
                max_drawdown_pct=max_drawdown_pct,
            ),
            sharpe_decay=max(0.0, (is_sharpe - oos_sharpe) / is_sharpe) if is_sharpe else 0.0,
            deflated_oos_sharpe=oos_sharpe,
        ),
        WalkForwardSegmentReport(
            window=WalkForwardWindow(1, 10, 20, 22, 30, 1, 1),
            regime="chop",
            is_report=make_backtest_report(
                trades=trades,
                total_return_pct=oos_return,
                sharpe=is_sharpe,
                max_drawdown_pct=max_drawdown_pct,
            ),
            oos_report=make_backtest_report(
                trades=trades,
                total_return_pct=recent,
                sharpe=oos_sharpe,
                max_drawdown_pct=max_drawdown_pct,
            ),
            sharpe_decay=max(0.0, (is_sharpe - oos_sharpe) / is_sharpe) if is_sharpe else 0.0,
            deflated_oos_sharpe=oos_sharpe,
        ),
    ]
    return WalkForwardReport(parameter_trials=1, segments=segments)


def test_candidate_strategies_cannot_bypass_registry() -> None:
    registry = load_strategy_registry(PROJECT_ROOT / "config" / "strategy-registry.yaml")

    assert approved_strategy_names(registry) == set()


def test_verifier_rejects_self_approval_and_logs_reason(tmp_path: Path) -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    report = make_walk_forward_report(
        trades=200,
        oos_return=10,
        is_sharpe=2,
        oos_sharpe=2,
        max_drawdown_pct=5,
    )

    result = verify_walk_forward_report(
        strategy_name="momentum_breakout",
        report=report,
        thresholds=configs.strategies.verification_thresholds,
        maker_id="same-agent",
        verifier_id="same-agent",
    )
    log_path = tmp_path / "verifier.jsonl"
    write_verification_log(result, log_path)

    assert result.approved is False
    assert "maker_checker_violation" in result.reasons
    logged = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert "maker_checker_violation" in logged["reasons"]


def test_verifier_rejects_bad_oos_report() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    report = make_walk_forward_report(
        trades=10,
        oos_return=-5,
        is_sharpe=2,
        oos_sharpe=0.2,
        max_drawdown_pct=20,
        recent_return=-1,
    )

    result = verify_walk_forward_report(
        strategy_name="momentum_breakout",
        report=report,
        thresholds=configs.strategies.verification_thresholds,
        maker_id="maker",
        verifier_id="checker",
    )

    assert result.approved is False
    assert "insufficient_oos_trades" in result.reasons
    assert "not_profitable_after_fees" in result.reasons
    assert "recent_oos_failure" in result.reasons


def test_verifier_can_approve_clean_report() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    permissive_thresholds = configs.strategies.verification_thresholds.model_copy(
        update={
            "min_trades": 100,
            "oos_sharpe_decay_max": 0.5,
            "max_drawdown_max": 0.1,
        }
    )
    report = make_walk_forward_report(
        trades=150,
        oos_return=10,
        is_sharpe=1.5,
        oos_sharpe=1.4,
        max_drawdown_pct=5,
    )

    result = verify_walk_forward_report(
        strategy_name="momentum_breakout",
        report=report,
        thresholds=permissive_thresholds,
        maker_id="maker",
        verifier_id="checker",
    )

    assert result.approved is True
    assert result.reasons == []
