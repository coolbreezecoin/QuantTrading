from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_quant_loop.config.models import FillsConfig, RiskPolicyConfig
from crypto_quant_loop.data.funding import FundingRate
from crypto_quant_loop.data.structural import BasisSample


@dataclass(frozen=True)
class CarryCostAssumptions:
    effective_taker_fee_bps: float
    spot_half_spread_bps: float
    perp_half_spread_bps: float
    conservative_buffer_bps: float
    margin_cost_apr: float
    min_notional_floor_quote: float

    @property
    def spot_per_trade_cost_bps(self) -> float:
        return (
            self.effective_taker_fee_bps
            + self.spot_half_spread_bps
            + self.conservative_buffer_bps
        )

    @property
    def perp_per_trade_cost_bps(self) -> float:
        return (
            self.effective_taker_fee_bps
            + self.perp_half_spread_bps
            + self.conservative_buffer_bps
        )


@dataclass(frozen=True)
class FundingRegimeStats:
    records: int
    positive_rate_pct: float
    negative_rate_pct: float
    average_rate_bps: float
    median_rate_bps: float
    cumulative_funding_rate_pct: float
    annualized_funding_rate_pct: float


@dataclass(frozen=True)
class CarryPrincipalResult:
    principal_quote: float
    leg_notional_quote: float
    gross_funding_quote: float
    round_trip_cost_quote: float
    margin_cost_quote: float
    net_carry_quote: float
    net_carry_pct_of_principal: float
    break_even_average_funding_bps: float
    min_notional_ok: bool


@dataclass(frozen=True)
class SymbolCarryFeasibility:
    symbol: str
    funding_window_start: str
    funding_window_end: str
    funding_coverage_days: float
    funding_regime: FundingRegimeStats
    cost_assumptions: CarryCostAssumptions
    basis_samples_in_window: int
    average_basis_bps: float | None
    start_basis_bps: float | None
    end_basis_bps: float | None
    max_abs_basis_bps: float | None
    basis_mtm_if_held_at_1000_quote: float | None
    principal_results: tuple[CarryPrincipalResult, ...]
    net_carry_positive_at_1000: bool
    minimum_positive_principal_quote: float | None
    primary_net_excludes_basis_mtm: bool = True


@dataclass(frozen=True)
class CarryFeasibilityReport:
    generated_at: str
    symbols: tuple[SymbolCarryFeasibility, ...]
    principal_grid: tuple[float, ...]
    net_carry_positive_at_1000: bool
    should_pause_before_strategy: bool
    conclusion: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cost_assumptions_from_configs(
    *,
    fills: FillsConfig,
    risk_policy: RiskPolicyConfig,
    symbol: str,
    margin_cost_apr: float = 0.05,
) -> CarryCostAssumptions:
    try:
        half_spread_bps = fills.backtest_historical.cross_half_spread_bps[symbol]
    except KeyError as exc:
        raise ValueError(f"Missing half-spread bps assumption for {symbol}") from exc
    effective_fee_bps = fills.fees.taker_bps
    if fills.fees.use_bnb_discount:
        effective_fee_bps *= 0.75
    return CarryCostAssumptions(
        effective_taker_fee_bps=effective_fee_bps,
        spot_half_spread_bps=half_spread_bps,
        perp_half_spread_bps=half_spread_bps,
        conservative_buffer_bps=fills.backtest_historical.conservative_buffer_bps,
        margin_cost_apr=margin_cost_apr,
        min_notional_floor_quote=risk_policy.position_sizing.min_notional_floor_quote,
    )


def analyze_carry_feasibility(
    *,
    funding_rates: Sequence[FundingRate],
    basis_samples: Sequence[BasisSample],
    fills: FillsConfig,
    risk_policy: RiskPolicyConfig,
    principal_grid: Sequence[float] = (500.0, 1000.0, 2500.0, 5000.0, 10_000.0),
    margin_cost_apr: float = 0.05,
) -> CarryFeasibilityReport:
    funding_by_symbol = _group_funding(funding_rates)
    basis_by_symbol = _group_basis(basis_samples)
    symbols = tuple(
        _analyze_symbol_carry(
            symbol=symbol,
            funding_rates=rates,
            basis_samples=basis_by_symbol.get(symbol, []),
            assumptions=cost_assumptions_from_configs(
                fills=fills,
                risk_policy=risk_policy,
                symbol=symbol,
                margin_cost_apr=margin_cost_apr,
            ),
            principal_grid=principal_grid,
        )
        for symbol, rates in sorted(funding_by_symbol.items())
    )
    positive_at_1000 = any(symbol.net_carry_positive_at_1000 for symbol in symbols)
    positive_above_1000 = any(
        symbol.minimum_positive_principal_quote is not None
        and symbol.minimum_positive_principal_quote > 1000
        for symbol in symbols
    )
    should_pause = not positive_at_1000
    conclusion = _carry_conclusion(
        symbols=symbols,
        positive_at_1000=positive_at_1000,
        positive_above_1000=positive_above_1000,
    )
    return CarryFeasibilityReport(
        generated_at=datetime.now(UTC).isoformat(),
        symbols=symbols,
        principal_grid=tuple(float(item) for item in principal_grid),
        net_carry_positive_at_1000=positive_at_1000,
        should_pause_before_strategy=should_pause,
        conclusion=conclusion,
        notes=(
            "Primary net carry counts funding cashflows minus two-leg open/close costs "
            "and fully collateralized perp margin opportunity cost.",
            "Basis mark-to-market is reported as risk diagnostic and is not credited as "
            "guaranteed carry edge.",
            "Research-only assumptions do not modify production risk or exchange config.",
        ),
    )


def save_carry_feasibility_report(report: CarryFeasibilityReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def _analyze_symbol_carry(
    *,
    symbol: str,
    funding_rates: Sequence[FundingRate],
    basis_samples: Sequence[BasisSample],
    assumptions: CarryCostAssumptions,
    principal_grid: Sequence[float],
) -> SymbolCarryFeasibility:
    ordered = sorted(funding_rates, key=lambda item: item.timestamp_ms)
    if not ordered:
        raise ValueError(f"Funding rates required for {symbol}")
    funding_window_start_ms = ordered[0].timestamp_ms
    funding_window_end_ms = ordered[-1].timestamp_ms
    interval_ms = int(ordered[0].interval_hours * 3_600_000)
    coverage_days = (
        (funding_window_end_ms - funding_window_start_ms + interval_ms) / 86_400_000
    )
    regime = _funding_regime_stats(ordered, coverage_days=coverage_days)
    principal_results = tuple(
        _principal_result(
            principal_quote=float(principal),
            funding_rates=ordered,
            coverage_days=coverage_days,
            assumptions=assumptions,
        )
        for principal in principal_grid
    )
    net_1000 = next(
        (result for result in principal_results if abs(result.principal_quote - 1000.0) < 1e-9),
        None,
    )
    minimum_positive_principal = next(
        (
            result.principal_quote
            for result in sorted(principal_results, key=lambda item: item.principal_quote)
            if result.net_carry_quote > 0 and result.min_notional_ok
        ),
        None,
    )
    basis_window = [
        sample
        for sample in sorted(basis_samples, key=lambda item: item.timestamp_ms)
        if funding_window_start_ms <= sample.timestamp_ms <= funding_window_end_ms
    ]
    basis_mtm_at_1000 = _basis_mtm_if_held_quote(basis_window, principal_quote=1000.0)
    return SymbolCarryFeasibility(
        symbol=symbol,
        funding_window_start=ordered[0].timestamp.isoformat(),
        funding_window_end=ordered[-1].timestamp.isoformat(),
        funding_coverage_days=round(coverage_days, 6),
        funding_regime=regime,
        cost_assumptions=assumptions,
        basis_samples_in_window=len(basis_window),
        average_basis_bps=_maybe_average(sample.basis_bps for sample in basis_window),
        start_basis_bps=basis_window[0].basis_bps if basis_window else None,
        end_basis_bps=basis_window[-1].basis_bps if basis_window else None,
        max_abs_basis_bps=max((abs(sample.basis_bps) for sample in basis_window), default=None),
        basis_mtm_if_held_at_1000_quote=basis_mtm_at_1000,
        principal_results=principal_results,
        net_carry_positive_at_1000=net_1000 is not None and net_1000.net_carry_quote > 0,
        minimum_positive_principal_quote=minimum_positive_principal,
    )


def _funding_regime_stats(
    funding_rates: Sequence[FundingRate],
    *,
    coverage_days: float,
) -> FundingRegimeStats:
    rates = [item.rate for item in funding_rates]
    positive = sum(1 for rate in rates if rate > 0)
    negative = sum(1 for rate in rates if rate < 0)
    cumulative = sum(rates)
    annualized = (cumulative / coverage_days) * 365 if coverage_days > 0 else 0.0
    return FundingRegimeStats(
        records=len(rates),
        positive_rate_pct=round((positive / len(rates)) * 100, 6),
        negative_rate_pct=round((negative / len(rates)) * 100, 6),
        average_rate_bps=round((sum(rates) / len(rates)) * 10_000, 8),
        median_rate_bps=round(statistics.median(rates) * 10_000, 8),
        cumulative_funding_rate_pct=round(cumulative * 100, 8),
        annualized_funding_rate_pct=round(annualized * 100, 8),
    )


def _principal_result(
    *,
    principal_quote: float,
    funding_rates: Sequence[FundingRate],
    coverage_days: float,
    assumptions: CarryCostAssumptions,
) -> CarryPrincipalResult:
    leg_notional = principal_quote / 2
    gross_funding_quote = leg_notional * sum(rate.rate for rate in funding_rates)
    round_trip_cost_quote = (
        principal_quote
        * (assumptions.spot_per_trade_cost_bps + assumptions.perp_per_trade_cost_bps)
        / 10_000
    )
    margin_cost_quote = leg_notional * assumptions.margin_cost_apr * (coverage_days / 365)
    net_carry_quote = gross_funding_quote - round_trip_cost_quote - margin_cost_quote
    total_cost_quote = round_trip_cost_quote + margin_cost_quote
    break_even_average_funding_bps = (
        (total_cost_quote / leg_notional / len(funding_rates)) * 10_000
        if leg_notional > 0 and funding_rates
        else 0.0
    )
    return CarryPrincipalResult(
        principal_quote=principal_quote,
        leg_notional_quote=leg_notional,
        gross_funding_quote=round(gross_funding_quote, 8),
        round_trip_cost_quote=round(round_trip_cost_quote, 8),
        margin_cost_quote=round(margin_cost_quote, 8),
        net_carry_quote=round(net_carry_quote, 8),
        net_carry_pct_of_principal=round((net_carry_quote / principal_quote) * 100, 8),
        break_even_average_funding_bps=round(break_even_average_funding_bps, 8),
        min_notional_ok=leg_notional >= assumptions.min_notional_floor_quote,
    )


def _basis_mtm_if_held_quote(
    basis_window: Sequence[BasisSample],
    *,
    principal_quote: float,
) -> float | None:
    if len(basis_window) < 2:
        return None
    leg_notional = principal_quote / 2
    basis_change_bps = basis_window[-1].basis_bps - basis_window[0].basis_bps
    return round(-(basis_change_bps / 10_000) * leg_notional, 8)


def _carry_conclusion(
    *,
    symbols: Sequence[SymbolCarryFeasibility],
    positive_at_1000: bool,
    positive_above_1000: bool,
) -> str:
    if not symbols:
        return "no_funding_data_available_pause_before_strategy"
    if positive_at_1000:
        return "net_carry_positive_at_1000_research_can_continue_to_F3"
    if positive_above_1000:
        return "net_carry_only_positive_above_1000_pause_before_strategy"
    return "net_carry_not_positive_after_full_costs_pause_before_strategy"


def _group_funding(rates: Sequence[FundingRate]) -> dict[str, list[FundingRate]]:
    groups: dict[str, list[FundingRate]] = {}
    for rate in rates:
        groups.setdefault(rate.symbol, []).append(rate)
    return groups


def _group_basis(samples: Sequence[BasisSample]) -> dict[str, list[BasisSample]]:
    groups: dict[str, list[BasisSample]] = {}
    for sample in samples:
        groups.setdefault(sample.symbol, []).append(sample)
    return groups


def _maybe_average(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return round(sum(items) / len(items), 8)


def carry_report_summary(report: CarryFeasibilityReport) -> Mapping[str, Any]:
    return {
        "conclusion": report.conclusion,
        "should_pause_before_strategy": report.should_pause_before_strategy,
        "symbols": {
            item.symbol: {
                "average_funding_bps": item.funding_regime.average_rate_bps,
                "annualized_funding_pct": item.funding_regime.annualized_funding_rate_pct,
                "net_1000_quote": _net_for_principal(item, 1000.0),
                "minimum_positive_principal_quote": item.minimum_positive_principal_quote,
            }
            for item in report.symbols
        },
    }


def _net_for_principal(symbol: SymbolCarryFeasibility, principal_quote: float) -> float | None:
    for result in symbol.principal_results:
        if abs(result.principal_quote - principal_quote) < 1e-9:
            return result.net_carry_quote
    return None
