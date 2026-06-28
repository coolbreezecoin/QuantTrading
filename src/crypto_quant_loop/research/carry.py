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


@dataclass(frozen=True)
class FundingSourceWindow:
    exchange: str
    symbol: str
    records: int
    start: str
    end: str
    coverage_days: float


@dataclass(frozen=True)
class FundingAprBucket:
    name: str
    min_apr_pct: float | None
    max_apr_pct: float | None
    records: int
    event_pct: float


@dataclass(frozen=True)
class BreakEvenLine:
    principal_quote: float
    margin_cost_apr: float
    break_even_average_funding_bps: float
    break_even_funding_apr_pct: float
    historical_event_frequency_pct: float


@dataclass(frozen=True)
class ConditionalCarryResult:
    principal_quote: float
    margin_cost_apr: float
    threshold_name: str
    threshold_funding_apr_pct: float
    active_events: int
    active_event_pct: float
    episodes: int
    gross_funding_quote: float
    round_trip_cost_quote: float
    margin_cost_quote: float
    net_carry_quote: float
    net_carry_pct_of_principal: float
    min_notional_ok: bool


@dataclass(frozen=True)
class CarryMarginSensitivity:
    margin_cost_apr: float
    all_hold_results: tuple[CarryPrincipalResult, ...]
    break_even_lines: tuple[BreakEvenLine, ...]
    conditional_results: tuple[ConditionalCarryResult, ...]


@dataclass(frozen=True)
class RefinedSymbolCarryFeasibility:
    symbol: str
    selected_exchange: str
    selected_source: FundingSourceWindow
    available_sources: tuple[FundingSourceWindow, ...]
    funding_regime: FundingRegimeStats
    funding_apr_buckets: tuple[FundingAprBucket, ...]
    multi_regime_observed: bool
    basis_samples_in_window: int
    average_basis_bps: float | None
    sensitivities: tuple[CarryMarginSensitivity, ...]
    proposed_entry_rule: str | None
    best_edge_net_at_1000_quote: float | None


@dataclass(frozen=True)
class RefinedCarryFeasibilityReport:
    generated_at: str
    principal_grid: tuple[float, ...]
    margin_cost_aprs: tuple[float, ...]
    symbols: tuple[RefinedSymbolCarryFeasibility, ...]
    conclusion: str
    should_pause_before_strategy: bool
    proposed_entry_rules: tuple[str, ...]
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


def save_refined_carry_feasibility_report(
    report: RefinedCarryFeasibilityReport,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def analyze_refined_carry_feasibility(
    *,
    funding_rates: Sequence[FundingRate],
    basis_samples: Sequence[BasisSample],
    fills: FillsConfig,
    risk_policy: RiskPolicyConfig,
    principal_grid: Sequence[float] = (500.0, 1000.0, 2500.0, 5000.0, 10_000.0),
    margin_cost_aprs: Sequence[float] = (0.0, 0.03, 0.05),
) -> RefinedCarryFeasibilityReport:
    source_groups = _group_funding_by_source(funding_rates)
    selected_sources = _select_longest_sources(source_groups)
    basis_by_symbol = _group_basis(basis_samples)
    refined_symbols = tuple(
        _analyze_refined_symbol_carry(
            symbol=symbol,
            selected_rates=selected_rates,
            source_groups=source_groups,
            basis_samples=basis_by_symbol.get(symbol, []),
            fills=fills,
            risk_policy=risk_policy,
            principal_grid=principal_grid,
            margin_cost_aprs=margin_cost_aprs,
        )
        for symbol, selected_rates in sorted(selected_sources.items())
    )
    proposed_entry_rules = tuple(
        rule
        for item in refined_symbols
        for rule in ([item.proposed_entry_rule] if item.proposed_entry_rule else [])
    )
    only_zero_cost_positive = _has_positive_edge_at_margin(refined_symbols, 0.0)
    reasonable_cost_positive = any(
        _has_positive_edge_at_margin(refined_symbols, margin_cost_apr)
        for margin_cost_apr in margin_cost_aprs
        if margin_cost_apr > 0
    )
    if reasonable_cost_positive:
        conclusion = "edge_condition_found_stop_for_F3_confirmation"
        should_pause = True
    elif only_zero_cost_positive:
        conclusion = "conditional_edge_only_positive_at_zero_opportunity_cost_pause"
        should_pause = True
    else:
        conclusion = "refined_multi_regime_conditional_carry_not_positive_pause"
        should_pause = True
    return RefinedCarryFeasibilityReport(
        generated_at=datetime.now(UTC).isoformat(),
        principal_grid=tuple(float(item) for item in principal_grid),
        margin_cost_aprs=tuple(float(item) for item in margin_cost_aprs),
        symbols=refined_symbols,
        conclusion=conclusion,
        should_pause_before_strategy=should_pause,
        proposed_entry_rules=proposed_entry_rules,
        notes=(
            "Selected source is the longest available funding history per symbol in DuckDB.",
            "Event funding APR is computed from each 8h funding rate annualized to a 365d year.",
            "Conditional carry pays full two-leg open/close costs for every active episode; "
            "open episodes are closed at the backtest end.",
            "Basis mark-to-market remains diagnostic only; it is not credited as "
            "deterministic carry.",
            "Research-only analysis: no production exchange/risk config, registry, or live "
            "path changes.",
        ),
    )


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


def _analyze_refined_symbol_carry(
    *,
    symbol: str,
    selected_rates: Sequence[FundingRate],
    source_groups: Mapping[tuple[str, str], list[FundingRate]],
    basis_samples: Sequence[BasisSample],
    fills: FillsConfig,
    risk_policy: RiskPolicyConfig,
    principal_grid: Sequence[float],
    margin_cost_aprs: Sequence[float],
) -> RefinedSymbolCarryFeasibility:
    ordered = sorted(selected_rates, key=lambda item: item.timestamp_ms)
    if not ordered:
        raise ValueError(f"Funding rates required for {symbol}")
    selected_source = _source_window(ordered)
    windows = tuple(
        sorted(
            (
                _source_window(rates)
                for (exchange, source_symbol), rates in source_groups.items()
                if source_symbol == symbol
            ),
            key=lambda item: (item.coverage_days, item.records),
            reverse=True,
        )
    )
    interval_hours = ordered[0].interval_hours
    regime = _funding_regime_stats(ordered, coverage_days=selected_source.coverage_days)
    apr_buckets = _funding_apr_buckets(ordered, interval_hours=interval_hours)
    basis_window = [
        sample
        for sample in sorted(basis_samples, key=lambda item: item.timestamp_ms)
        if ordered[0].timestamp_ms <= sample.timestamp_ms <= ordered[-1].timestamp_ms
    ]
    sensitivities = tuple(
        _margin_sensitivity(
            funding_rates=ordered,
            assumptions=cost_assumptions_from_configs(
                fills=fills,
                risk_policy=risk_policy,
                symbol=symbol,
                margin_cost_apr=margin_cost_apr,
            ),
            principal_grid=principal_grid,
            coverage_days=selected_source.coverage_days,
            margin_cost_apr=margin_cost_apr,
        )
        for margin_cost_apr in margin_cost_aprs
    )
    proposed_rule, best_net = _best_proposed_entry_rule(
        symbol=symbol,
        selected_exchange=selected_source.exchange,
        sensitivities=sensitivities,
    )
    return RefinedSymbolCarryFeasibility(
        symbol=symbol,
        selected_exchange=selected_source.exchange,
        selected_source=selected_source,
        available_sources=windows,
        funding_regime=regime,
        funding_apr_buckets=apr_buckets,
        multi_regime_observed=sum(1 for bucket in apr_buckets if bucket.records > 0) >= 3,
        basis_samples_in_window=len(basis_window),
        average_basis_bps=_maybe_average(sample.basis_bps for sample in basis_window),
        sensitivities=sensitivities,
        proposed_entry_rule=proposed_rule,
        best_edge_net_at_1000_quote=best_net,
    )


def _source_window(rates: Sequence[FundingRate]) -> FundingSourceWindow:
    ordered = sorted(rates, key=lambda item: item.timestamp_ms)
    interval_ms = int(ordered[0].interval_hours * 3_600_000)
    coverage_days = (
        (ordered[-1].timestamp_ms - ordered[0].timestamp_ms + interval_ms) / 86_400_000
    )
    return FundingSourceWindow(
        exchange=ordered[0].exchange,
        symbol=ordered[0].symbol,
        records=len(ordered),
        start=ordered[0].timestamp.isoformat(),
        end=ordered[-1].timestamp.isoformat(),
        coverage_days=round(coverage_days, 6),
    )


def _funding_apr_buckets(
    rates: Sequence[FundingRate],
    *,
    interval_hours: float,
) -> tuple[FundingAprBucket, ...]:
    event_aprs_pct = [_event_funding_apr(rate.rate, interval_hours) * 100 for rate in rates]
    buckets = (
        ("negative", None, 0.0),
        ("0_to_5pct", 0.0, 5.0),
        ("5_to_10pct", 5.0, 10.0),
        ("10_to_25pct", 10.0, 25.0),
        ("above_25pct", 25.0, None),
    )
    output: list[FundingAprBucket] = []
    for name, min_apr, max_apr in buckets:
        count = sum(
            1
            for apr in event_aprs_pct
            if (min_apr is None or apr > min_apr)
            and (max_apr is None or apr <= max_apr)
        )
        output.append(
            FundingAprBucket(
                name=name,
                min_apr_pct=min_apr,
                max_apr_pct=max_apr,
                records=count,
                event_pct=round((count / len(event_aprs_pct)) * 100, 6)
                if event_aprs_pct
                else 0.0,
            )
        )
    return tuple(output)


def _margin_sensitivity(
    *,
    funding_rates: Sequence[FundingRate],
    assumptions: CarryCostAssumptions,
    principal_grid: Sequence[float],
    coverage_days: float,
    margin_cost_apr: float,
) -> CarryMarginSensitivity:
    all_hold_results = tuple(
        _principal_result(
            principal_quote=float(principal),
            funding_rates=funding_rates,
            coverage_days=coverage_days,
            assumptions=assumptions,
        )
        for principal in principal_grid
    )
    break_even_lines = tuple(
        _break_even_line(
            principal_result=result,
            funding_rates=funding_rates,
            margin_cost_apr=margin_cost_apr,
        )
        for result in all_hold_results
    )
    conditional_results = tuple(
        _conditional_carry_result(
            principal_quote=result.principal_quote,
            funding_rates=funding_rates,
            assumptions=assumptions,
            threshold_name="break_even_all_hold",
            threshold_apr=_break_even_bps_to_apr(
                result.break_even_average_funding_bps,
                funding_rates[0].interval_hours,
            ),
            margin_cost_apr=margin_cost_apr,
        )
        for result in all_hold_results
    )
    return CarryMarginSensitivity(
        margin_cost_apr=margin_cost_apr,
        all_hold_results=all_hold_results,
        break_even_lines=break_even_lines,
        conditional_results=conditional_results,
    )


def _break_even_line(
    *,
    principal_result: CarryPrincipalResult,
    funding_rates: Sequence[FundingRate],
    margin_cost_apr: float,
) -> BreakEvenLine:
    threshold_apr = _break_even_bps_to_apr(
        principal_result.break_even_average_funding_bps,
        funding_rates[0].interval_hours,
    )
    frequency = _event_frequency_above_threshold(funding_rates, threshold_apr)
    return BreakEvenLine(
        principal_quote=principal_result.principal_quote,
        margin_cost_apr=margin_cost_apr,
        break_even_average_funding_bps=principal_result.break_even_average_funding_bps,
        break_even_funding_apr_pct=round(threshold_apr * 100, 8),
        historical_event_frequency_pct=frequency,
    )


def _conditional_carry_result(
    *,
    principal_quote: float,
    funding_rates: Sequence[FundingRate],
    assumptions: CarryCostAssumptions,
    threshold_name: str,
    threshold_apr: float,
    margin_cost_apr: float,
) -> ConditionalCarryResult:
    leg_notional = principal_quote / 2
    active_rates: list[FundingRate] = []
    episodes = 0
    in_episode = False
    for rate in sorted(funding_rates, key=lambda item: item.timestamp_ms):
        active = _event_funding_apr(rate.rate, rate.interval_hours) > threshold_apr
        if active:
            active_rates.append(rate)
            if not in_episode:
                episodes += 1
                in_episode = True
        else:
            in_episode = False
    active_days = sum(rate.interval_hours for rate in active_rates) / 24
    gross_funding_quote = leg_notional * sum(rate.rate for rate in active_rates)
    round_trip_cost_quote = (
        principal_quote
        * (assumptions.spot_per_trade_cost_bps + assumptions.perp_per_trade_cost_bps)
        / 10_000
        * episodes
    )
    margin_cost_quote = leg_notional * margin_cost_apr * (active_days / 365)
    net_carry_quote = gross_funding_quote - round_trip_cost_quote - margin_cost_quote
    return ConditionalCarryResult(
        principal_quote=principal_quote,
        margin_cost_apr=margin_cost_apr,
        threshold_name=threshold_name,
        threshold_funding_apr_pct=round(threshold_apr * 100, 8),
        active_events=len(active_rates),
        active_event_pct=round((len(active_rates) / len(funding_rates)) * 100, 6)
        if funding_rates
        else 0.0,
        episodes=episodes,
        gross_funding_quote=round(gross_funding_quote, 8),
        round_trip_cost_quote=round(round_trip_cost_quote, 8),
        margin_cost_quote=round(margin_cost_quote, 8),
        net_carry_quote=round(net_carry_quote, 8),
        net_carry_pct_of_principal=round((net_carry_quote / principal_quote) * 100, 8),
        min_notional_ok=leg_notional >= assumptions.min_notional_floor_quote,
    )


def _event_funding_apr(rate: float, interval_hours: float) -> float:
    return rate * (24 / interval_hours) * 365


def _break_even_bps_to_apr(break_even_bps: float, interval_hours: float) -> float:
    return (break_even_bps / 10_000) * (24 / interval_hours) * 365


def _event_frequency_above_threshold(
    funding_rates: Sequence[FundingRate],
    threshold_apr: float,
) -> float:
    if not funding_rates:
        return 0.0
    count = sum(
        1
        for rate in funding_rates
        if _event_funding_apr(rate.rate, rate.interval_hours) > threshold_apr
    )
    return round((count / len(funding_rates)) * 100, 6)


def _best_proposed_entry_rule(
    *,
    symbol: str,
    selected_exchange: str,
    sensitivities: Sequence[CarryMarginSensitivity],
) -> tuple[str | None, float | None]:
    candidates = [
        result
        for sensitivity in sensitivities
        if sensitivity.margin_cost_apr > 0
        for result in sensitivity.conditional_results
        if abs(result.principal_quote - 1000.0) < 1e-9
        and result.net_carry_quote > 0
        and result.min_notional_ok
    ]
    if not candidates:
        return _best_all_hold_rule(
            symbol=symbol,
            selected_exchange=selected_exchange,
            sensitivities=sensitivities,
        )
    best = max(candidates, key=lambda item: item.net_carry_quote)
    rule = (
        f"{symbol} on {selected_exchange}: enter delta-neutral carry only when "
        f"event funding APR > {best.threshold_funding_apr_pct:.4f}% "
        f"(margin_cost_apr={best.margin_cost_apr:.2%}); "
        f"historical active events {best.active_event_pct:.2f}%, episodes {best.episodes}, "
        f"net@1000 {best.net_carry_quote:.4f} USDT"
    )
    return rule, best.net_carry_quote


def _best_all_hold_rule(
    *,
    symbol: str,
    selected_exchange: str,
    sensitivities: Sequence[CarryMarginSensitivity],
) -> tuple[str | None, float | None]:
    candidates = [
        (sensitivity, result, break_even)
        for sensitivity in sensitivities
        if sensitivity.margin_cost_apr > 0
        for result in sensitivity.all_hold_results
        for break_even in sensitivity.break_even_lines
        if abs(result.principal_quote - 1000.0) < 1e-9
        and abs(break_even.principal_quote - result.principal_quote) < 1e-9
        and result.net_carry_quote > 0
        and result.min_notional_ok
    ]
    if not candidates:
        return None, None
    sensitivity, best, break_even = max(
        candidates,
        key=lambda item: (item[0].margin_cost_apr, item[1].net_carry_quote),
    )
    rule = (
        f"{symbol} on {selected_exchange}: edge only under low-turnover continuous carry; "
        f"require trailing funding APR > {break_even.break_even_funding_apr_pct:.4f}% "
        f"and margin_cost_apr <= {sensitivity.margin_cost_apr:.2%}; "
        f"avoid event-level churn gates because episode costs dominated the conditional test; "
        f"net@1000 {best.net_carry_quote:.4f} USDT"
    )
    return rule, best.net_carry_quote


def _has_positive_edge_at_margin(
    symbols: Sequence[RefinedSymbolCarryFeasibility],
    margin_cost_apr: float,
) -> bool:
    conditional_positive = any(
        result.net_carry_quote > 0 and result.min_notional_ok
        for symbol in symbols
        for sensitivity in symbol.sensitivities
        if abs(sensitivity.margin_cost_apr - margin_cost_apr) < 1e-12
        for result in sensitivity.conditional_results
        if abs(result.principal_quote - 1000.0) < 1e-9
    )
    all_hold_positive = any(
        result.net_carry_quote > 0 and result.min_notional_ok
        for symbol in symbols
        for sensitivity in symbol.sensitivities
        if abs(sensitivity.margin_cost_apr - margin_cost_apr) < 1e-12
        for result in sensitivity.all_hold_results
        if abs(result.principal_quote - 1000.0) < 1e-9
    )
    return conditional_positive or all_hold_positive


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


def _group_funding_by_source(
    rates: Sequence[FundingRate],
) -> dict[tuple[str, str], list[FundingRate]]:
    groups: dict[tuple[str, str], list[FundingRate]] = {}
    for rate in rates:
        groups.setdefault((rate.exchange, rate.symbol), []).append(rate)
    return groups


def _select_longest_sources(
    source_groups: Mapping[tuple[str, str], list[FundingRate]],
) -> dict[str, list[FundingRate]]:
    selected: dict[str, list[FundingRate]] = {}
    for (_exchange, symbol), rates in source_groups.items():
        current = selected.get(symbol)
        current_days = _source_window(current).coverage_days if current is not None else -1.0
        if _source_window(rates).coverage_days > current_days:
            selected[symbol] = sorted(rates, key=lambda item: item.timestamp_ms)
    return selected


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
