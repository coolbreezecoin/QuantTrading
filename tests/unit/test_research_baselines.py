from __future__ import annotations

from pathlib import Path

import pytest

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.research import (
    PerformanceSnapshot,
    beats_benchmark,
    build_baseline_report,
    compute_buy_and_hold,
    compute_equal_weight_basket,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_bar(symbol: str, index: int, close: float) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol=symbol,
        timeframe="1h",
        timestamp_ms=index * 3_600_000,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
    )


def test_buy_and_hold_baseline_is_fee_adjusted() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars = [make_bar("BTCUSDT", index, close) for index, close in enumerate([100, 110, 120])]

    metrics = compute_buy_and_hold(
        bars,
        fills=configs.fills,
        starting_equity=1_000,
        name="buy_and_hold_btc",
    )

    assert metrics.symbols == ("BTCUSDT",)
    assert metrics.fees_paid > 0
    assert metrics.total_return_pct < 20
    assert metrics.total_return_pct > 19


def test_equal_weight_basket_uses_common_history_and_weights() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars_by_symbol = {
        "BTCUSDT": [make_bar("BTCUSDT", 0, 100), make_bar("BTCUSDT", 1, 110)],
        "ETHUSDT": [make_bar("ETHUSDT", 0, 200), make_bar("ETHUSDT", 1, 200)],
        "SOLUSDT": [make_bar("SOLUSDT", 0, 50), make_bar("SOLUSDT", 1, 40)],
    }

    metrics = compute_equal_weight_basket(
        bars_by_symbol,
        weights=configs.research.benchmarks.basket_weights,
        fills=configs.fills,
        starting_equity=1_000,
        name="equal_weight_basket",
    )

    assert metrics.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert metrics.periods == 2
    assert metrics.total_return_pct < 0


def test_build_baseline_report_contains_primary_and_basket() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    bars_by_symbol = {
        symbol: [make_bar(symbol, index, 100 + index) for index in range(3)]
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    }

    report = build_baseline_report(
        bars_by_symbol,
        research=configs.research,
        fills=configs.fills,
        starting_equity=configs.risk_policy.account.equity_size,
    )

    assert report["criteria"]["metric_scope"] == "oos"
    assert set(report["benchmarks"]) == {"buy_and_hold_btc", "equal_weight_basket"}


def test_beat_predicate_requires_oos_fee_adjusted_risk_adjusted_edge() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    benchmark = PerformanceSnapshot(
        name="benchmark",
        total_return_pct=5,
        annualized_return_pct=10,
        sharpe=1.0,
        max_drawdown_pct=10,
        calmar=1.0,
        fees_paid=1,
    )
    candidate = PerformanceSnapshot(
        name="candidate",
        total_return_pct=6,
        annualized_return_pct=12,
        sharpe=1.0,
        max_drawdown_pct=8,
        calmar=1.5,
        fees_paid=1,
    )

    decision = beats_benchmark(
        candidate=candidate,
        benchmark=benchmark,
        criteria=configs.research.beat_criteria,
    )

    assert decision.beats is True
    assert decision.reasons == ()


def test_beat_predicate_rejects_negative_or_worse_risk_adjusted_candidate() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    benchmark = PerformanceSnapshot(
        name="benchmark",
        total_return_pct=5,
        annualized_return_pct=10,
        sharpe=1.0,
        max_drawdown_pct=10,
        calmar=1.0,
        fees_paid=1,
    )
    negative = PerformanceSnapshot(
        name="negative",
        total_return_pct=-1,
        annualized_return_pct=-2,
        sharpe=2.0,
        max_drawdown_pct=5,
        calmar=-0.4,
        fees_paid=1,
    )
    worse_risk = PerformanceSnapshot(
        name="worse_risk",
        total_return_pct=8,
        annualized_return_pct=8,
        sharpe=0.5,
        max_drawdown_pct=15,
        calmar=0.53,
        fees_paid=1,
    )

    negative_decision = beats_benchmark(
        candidate=negative,
        benchmark=benchmark,
        criteria=configs.research.beat_criteria,
    )
    worse_risk_decision = beats_benchmark(
        candidate=worse_risk,
        benchmark=benchmark,
        criteria=configs.research.beat_criteria,
    )

    assert negative_decision.beats is False
    assert "candidate_not_positive_after_fees" in negative_decision.reasons
    assert worse_risk_decision.beats is False
    assert "risk_adjusted_metrics_do_not_beat_benchmark" in worse_risk_decision.reasons


def test_basket_requires_matching_weights() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    with pytest.raises(ValueError, match="symbols and weights"):
        compute_equal_weight_basket(
            {"BTCUSDT": [make_bar("BTCUSDT", 0, 100), make_bar("BTCUSDT", 1, 101)]},
            weights=configs.research.benchmarks.basket_weights,
            fills=configs.fills,
            starting_equity=1_000,
            name="bad_basket",
        )
