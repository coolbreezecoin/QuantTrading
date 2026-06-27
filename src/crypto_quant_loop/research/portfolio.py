from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioReport:
    component_count: int
    periods: int
    raw_weights: dict[str, float]
    capped_weights: dict[str, float]
    directional_exposure: float
    aggregate_return_pct: float
    annualized_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    calmar: float
    equity_curve: tuple[float, ...]


def inverse_volatility_weights(
    returns_by_component: Mapping[str, list[float]],
) -> dict[str, float]:
    if not returns_by_component:
        return {}
    inverse_vols: dict[str, float] = {}
    for name, returns in returns_by_component.items():
        volatility = _std(returns)
        inverse_vols[name] = 1.0 / volatility if volatility > 0 else 1.0
    total = sum(inverse_vols.values())
    if total == 0:
        equal = 1.0 / len(inverse_vols)
        return {name: equal for name in inverse_vols}
    return {name: value / total for name, value in inverse_vols.items()}


def apply_directional_cap(
    weights: Mapping[str, float],
    *,
    cap_pct: float,
) -> dict[str, float]:
    gross = sum(abs(value) for value in weights.values())
    if gross == 0:
        return dict(weights)
    scale = min(cap_pct / gross, 1.0)
    return {name: value * scale for name, value in weights.items()}


def combine_weighted_oos_returns(
    returns_by_component: Mapping[str, list[float]],
    *,
    weights: Mapping[str, float],
    starting_equity: float,
    periods_per_year: float = 12.0,
) -> PortfolioReport:
    if not returns_by_component:
        return PortfolioReport(
            component_count=0,
            periods=0,
            raw_weights=dict(weights),
            capped_weights=dict(weights),
            directional_exposure=sum(abs(value) for value in weights.values()),
            aggregate_return_pct=0.0,
            annualized_return_pct=0.0,
            sharpe=0.0,
            max_drawdown_pct=0.0,
            calmar=0.0,
            equity_curve=(starting_equity,),
        )
    periods = min(len(values) for values in returns_by_component.values())
    equity = starting_equity
    equity_curve = [equity]
    portfolio_returns: list[float] = []
    for index in range(periods):
        period_return = sum(
            weights.get(name, 0.0) * (returns[index] / 100)
            for name, returns in returns_by_component.items()
        )
        portfolio_returns.append(period_return)
        equity *= 1.0 + period_return
        equity_curve.append(equity)
    annualized = _annualized_return(equity_curve, periods_per_year=periods_per_year)
    max_drawdown = _max_drawdown(equity_curve) * 100
    return PortfolioReport(
        component_count=len(returns_by_component),
        periods=periods,
        raw_weights=dict(weights),
        capped_weights=dict(weights),
        directional_exposure=sum(abs(value) for value in weights.values()),
        aggregate_return_pct=((equity / starting_equity) - 1.0) * 100,
        annualized_return_pct=annualized,
        sharpe=_sharpe(portfolio_returns, periods_per_year=periods_per_year),
        max_drawdown_pct=max_drawdown,
        calmar=_calmar(annualized, max_drawdown),
        equity_curve=tuple(equity_curve),
    )


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _annualized_return(equity_curve: list[float], *, periods_per_year: float) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    total_return = equity_curve[-1] / equity_curve[0]
    periods = len(equity_curve) - 1
    return float(((total_return ** (periods_per_year / periods)) - 1.0) * 100)


def _sharpe(returns: list[float], *, periods_per_year: float) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    std = _std(returns)
    return (mean / std) * math.sqrt(periods_per_year) if std else 0.0


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
