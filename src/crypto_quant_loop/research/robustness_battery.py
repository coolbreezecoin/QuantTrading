from __future__ import annotations

import random
from dataclasses import dataclass

from crypto_quant_loop.backtest import WalkForwardReport


@dataclass(frozen=True)
class RobustnessBatteryReport:
    segments: int
    parameter_trials: int
    min_deflated_oos_sharpe: float
    positive_segment_ratio: float
    aggregate_oos_return_pct: float
    subperiod_return_min_pct: float
    block_bootstrap_mean_return_p05: float
    cost_sensitivity_return_pct: float
    parameter_sensitivity_range_pct: float
    pass_basic_robustness: bool
    failure_reasons: tuple[str, ...]


def run_robustness_battery(
    report: WalkForwardReport,
    *,
    parameter_variant_returns: list[float],
    extra_cost_pct_per_segment: float = 0.05,
    bootstrap_samples: int = 200,
    block_size: int = 3,
    random_seed: int = 7,
) -> RobustnessBatteryReport:
    returns = [segment.oos_report.total_return_pct for segment in report.segments]
    aggregate = sum(returns)
    positive_ratio = (
        sum(1 for value in returns if value > 0) / len(returns)
        if returns
        else 0.0
    )
    min_deflated = min(
        (segment.deflated_oos_sharpe for segment in report.segments),
        default=0.0,
    )
    bootstrap_p05 = _block_bootstrap_p05(
        returns,
        samples=bootstrap_samples,
        block_size=block_size,
        random_seed=random_seed,
    )
    cost_sensitive = aggregate - (len(returns) * extra_cost_pct_per_segment)
    sensitivity_range = (
        max(parameter_variant_returns) - min(parameter_variant_returns)
        if parameter_variant_returns
        else 0.0
    )
    reasons: list[str] = []
    if aggregate <= 0:
        reasons.append("aggregate_oos_return_not_positive")
    if positive_ratio <= 0.5:
        reasons.append("positive_segment_ratio_not_majority")
    if min_deflated <= 0:
        reasons.append("deflated_sharpe_not_positive")
    if bootstrap_p05 <= 0:
        reasons.append("bootstrap_left_tail_not_positive")
    if cost_sensitive <= 0:
        reasons.append("cost_sensitivity_not_positive")
    return RobustnessBatteryReport(
        segments=len(returns),
        parameter_trials=report.parameter_trials,
        min_deflated_oos_sharpe=min_deflated,
        positive_segment_ratio=positive_ratio,
        aggregate_oos_return_pct=aggregate,
        subperiod_return_min_pct=min(returns, default=0.0),
        block_bootstrap_mean_return_p05=bootstrap_p05,
        cost_sensitivity_return_pct=cost_sensitive,
        parameter_sensitivity_range_pct=sensitivity_range,
        pass_basic_robustness=not reasons,
        failure_reasons=tuple(reasons),
    )


def _block_bootstrap_p05(
    returns: list[float],
    *,
    samples: int,
    block_size: int,
    random_seed: int,
) -> float:
    if not returns:
        return 0.0
    rng = random.Random(random_seed)
    means: list[float] = []
    for _ in range(samples):
        sample: list[float] = []
        while len(sample) < len(returns):
            start = rng.randrange(len(returns))
            for offset in range(block_size):
                sample.append(returns[(start + offset) % len(returns)])
                if len(sample) == len(returns):
                    break
        means.append(sum(sample) / len(sample))
    ordered = sorted(means)
    index = max(int(0.05 * len(ordered)) - 1, 0)
    return ordered[index]
