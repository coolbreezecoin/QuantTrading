from __future__ import annotations

from crypto_quant_loop.research import (
    apply_directional_cap,
    combine_weighted_oos_returns,
    inverse_volatility_weights,
)


def test_inverse_volatility_weights_favor_lower_volatility_component() -> None:
    weights = inverse_volatility_weights(
        {
            "quiet": [1.0, 1.1, 0.9, 1.0],
            "noisy": [3.0, -2.0, 4.0, -3.0],
        }
    )

    assert weights["quiet"] > weights["noisy"]
    assert round(sum(weights.values()), 10) == 1.0


def test_directional_cap_scales_gross_exposure() -> None:
    capped = apply_directional_cap({"a": 0.6, "b": 0.4}, cap_pct=0.25)

    assert round(sum(capped.values()), 10) == 0.25
    assert capped["a"] > capped["b"]


def test_combine_weighted_oos_returns_reports_risk_metrics() -> None:
    raw_weights = inverse_volatility_weights(
        {
            "a": [2.0, -1.0, 1.0],
            "b": [1.0, 1.0, -0.5],
        }
    )
    weights = apply_directional_cap(raw_weights, cap_pct=0.25)

    report = combine_weighted_oos_returns(
        {
            "a": [2.0, -1.0, 1.0],
            "b": [1.0, 1.0, -0.5],
        },
        weights=weights,
        starting_equity=1_000,
    )

    assert report.component_count == 2
    assert report.periods == 3
    assert report.directional_exposure <= 0.25
    assert len(report.equity_curve) == 4
