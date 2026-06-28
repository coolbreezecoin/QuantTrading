from __future__ import annotations

import json
from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.funding import FundingRate
from crypto_quant_loop.data.structural import BasisSample
from crypto_quant_loop.research.carry import (
    analyze_carry_feasibility,
    carry_report_summary,
    cost_assumptions_from_configs,
    save_carry_feasibility_report,
)


def funding_series(symbol: str, rates: list[float]) -> list[FundingRate]:
    interval_ms = 8 * 3_600_000
    return [
        FundingRate(
            exchange="okx",
            symbol=symbol,
            timestamp_ms=index * interval_ms,
            rate=rate,
            interval_hours=8,
        )
        for index, rate in enumerate(rates)
    ]


def basis_series(symbol: str) -> list[BasisSample]:
    return [
        BasisSample("okx", symbol, 0, 100, 100.1, 0.1, 10),
        BasisSample("okx", symbol, 8 * 3_600_000, 100, 99.9, -0.1, -10),
    ]


def test_cost_assumptions_follow_existing_fills_config() -> None:
    configs = load_all_configs(Path("config"))

    assumptions = cost_assumptions_from_configs(
        fills=configs.fills,
        risk_policy=configs.risk_policy,
        symbol="BTCUSDT",
    )

    assert assumptions.effective_taker_fee_bps == 7.5
    assert assumptions.spot_half_spread_bps == 1.0
    assert assumptions.perp_half_spread_bps == 1.0
    assert assumptions.conservative_buffer_bps == 5


def test_negative_net_carry_pauses_before_strategy() -> None:
    configs = load_all_configs(Path("config"))

    report = analyze_carry_feasibility(
        funding_rates=funding_series("BTCUSDT", [0.00001, 0.00001, 0.00001]),
        basis_samples=basis_series("BTCUSDT"),
        fills=configs.fills,
        risk_policy=configs.risk_policy,
        principal_grid=[1000],
        margin_cost_apr=0.05,
    )

    symbol = report.symbols[0]
    result = symbol.principal_results[0]
    assert result.gross_funding_quote > 0
    assert result.net_carry_quote < 0
    assert report.should_pause_before_strategy is True
    assert report.conclusion == "net_carry_not_positive_after_full_costs_pause_before_strategy"
    assert symbol.primary_net_excludes_basis_mtm is True


def test_strong_funding_can_clear_full_costs() -> None:
    configs = load_all_configs(Path("config"))

    report = analyze_carry_feasibility(
        funding_rates=funding_series("BTCUSDT", [0.003, 0.003, 0.003]),
        basis_samples=basis_series("BTCUSDT"),
        fills=configs.fills,
        risk_policy=configs.risk_policy,
        principal_grid=[1000],
        margin_cost_apr=0.0,
    )

    assert report.net_carry_positive_at_1000 is True
    assert report.should_pause_before_strategy is False
    assert report.symbols[0].minimum_positive_principal_quote == 1000


def test_report_serializes_summary(tmp_path: Path) -> None:
    configs = load_all_configs(Path("config"))
    report = analyze_carry_feasibility(
        funding_rates=funding_series("BTCUSDT", [0.00001, 0.00001, 0.00001]),
        basis_samples=basis_series("BTCUSDT"),
        fills=configs.fills,
        risk_policy=configs.risk_policy,
        principal_grid=[500, 1000],
        margin_cost_apr=0.05,
    )
    report_path = tmp_path / "carry.json"

    save_carry_feasibility_report(report, report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = carry_report_summary(report)

    assert payload["principal_grid"] == [500.0, 1000.0]
    assert summary["symbols"]["BTCUSDT"]["net_1000_quote"] < 0
