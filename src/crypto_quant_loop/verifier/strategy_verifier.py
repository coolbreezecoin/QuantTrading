from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from crypto_quant_loop.backtest import WalkForwardReport
from crypto_quant_loop.config.models import VerificationThresholdsConfig


@dataclass(frozen=True)
class StrategyVerificationResult:
    strategy_name: str
    status: str
    maker_id: str
    verifier_id: str
    reasons: list[str]
    metrics: dict[str, float | int]

    @property
    def approved(self) -> bool:
        return self.status == "approved"


def verify_walk_forward_report(
    *,
    strategy_name: str,
    report: WalkForwardReport,
    thresholds: VerificationThresholdsConfig,
    maker_id: str,
    verifier_id: str,
) -> StrategyVerificationResult:
    reasons: list[str] = []
    if maker_id == verifier_id:
        reasons.append("maker_checker_violation")

    total_oos_trades = sum(segment.oos_report.trades for segment in report.segments)
    max_oos_drawdown = max(
        (segment.oos_report.max_drawdown_pct / 100 for segment in report.segments),
        default=0.0,
    )
    worst_decay = max((segment.sharpe_decay for segment in report.segments), default=0.0)
    aggregate_oos_return = sum(segment.oos_report.total_return_pct for segment in report.segments)
    recent_oos_return = report.segments[-1].oos_report.total_return_pct if report.segments else 0.0
    positive_segments = report.oos_positive_segments

    if worst_decay > thresholds.oos_sharpe_decay_max:
        reasons.append("oos_sharpe_decay_too_high")
    if max_oos_drawdown > thresholds.max_drawdown_max:
        reasons.append("max_drawdown_too_high")
    if total_oos_trades < thresholds.min_trades:
        reasons.append("insufficient_oos_trades")
    if thresholds.must_be_profitable_after_fees and aggregate_oos_return <= 0:
        reasons.append("not_profitable_after_fees")
    if thresholds.no_recent_30d_failure and recent_oos_return < 0:
        reasons.append("recent_oos_failure")
    if report.segments and positive_segments <= len(report.segments) // 2:
        reasons.append("not_majority_positive_oos_segments")

    return StrategyVerificationResult(
        strategy_name=strategy_name,
        status="approved" if not reasons else "rejected",
        maker_id=maker_id,
        verifier_id=verifier_id,
        reasons=reasons,
        metrics={
            "segments": len(report.segments),
            "positive_oos_segments": positive_segments,
            "total_oos_trades": total_oos_trades,
            "max_oos_drawdown": max_oos_drawdown,
            "worst_sharpe_decay": worst_decay,
            "aggregate_oos_return_pct": aggregate_oos_return,
            "recent_oos_return_pct": recent_oos_return,
            "average_oos_sharpe": report.average_oos_sharpe,
        },
    )


def write_verification_log(result: StrategyVerificationResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), sort_keys=True) + "\n")

