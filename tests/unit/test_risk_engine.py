from __future__ import annotations

from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.risk import (
    PnlEvent,
    Position,
    RuntimeHealth,
    build_kill_switch_actions,
    evaluate_risk,
    size_signal_notional,
)
from crypto_quant_loop.strategies import Signal

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def make_signal(stop: float = 98.0) -> Signal:
    return Signal(
        strategy_name="test",
        strategy_type="momentum",
        symbol="BTCUSDT",
        timestamp_ms=0,
        side="long",
        order_type="market",
        reference_price=100.0,
        stop_price=stop,
    )


def test_position_sizing_respects_caps_and_min_notional() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")

    sized = size_signal_notional(
        signal=make_signal(),
        equity=1000,
        existing_positions=[],
        risk_policy=configs.risk_policy,
        symbols=configs.symbols,
    )
    blocked = size_signal_notional(
        signal=make_signal(),
        equity=1000,
        existing_positions=[Position(symbol="BTCUSDT", notional=150)],
        risk_policy=configs.risk_policy,
        symbols=configs.symbols,
    )

    assert sized == 150
    assert blocked is None


def test_cooldown_triggers_before_rolling_24h_halt() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    now = 100_000_000
    three_losses = [
        PnlEvent(now - 3_000, -7.5),
        PnlEvent(now - 2_000, -7.5),
        PnlEvent(now - 1_000, -7.5),
    ]
    four_losses = [*three_losses, PnlEvent(now, -7.6)]

    cooldown = evaluate_risk(
        equity=1000,
        equity_high=1000,
        starting_equity=1000,
        pnl_events=three_losses,
        runtime_health=RuntimeHealth(),
        now_ms=now,
        risk_policy=configs.risk_policy,
    )
    halted = evaluate_risk(
        equity=1000,
        equity_high=1000,
        starting_equity=1000,
        pnl_events=four_losses,
        runtime_health=RuntimeHealth(),
        now_ms=now,
        risk_policy=configs.risk_policy,
    )

    assert cooldown.cooldown_required is True
    assert cooldown.halt_required is False
    assert "consecutive_losses_cooldown" in cooldown.reasons
    assert halted.halt_required is True
    assert "rolling_24h_loss_halt" in halted.reasons


def test_drawdown_business_and_runtime_halts() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")

    decision = evaluate_risk(
        equity=800,
        equity_high=1000,
        starting_equity=1000,
        pnl_events=[],
        runtime_health=RuntimeHealth(data_gap=True, api_error=True, price_deviation_bps=500),
        now_ms=0,
        risk_policy=configs.risk_policy,
    )

    assert decision.halt_required is True
    assert "total_drawdown_pause" in decision.reasons
    assert "business_hard_stop" in decision.reasons
    assert "runtime_data_gap" in decision.reasons
    assert "runtime_api_error" in decision.reasons
    assert "runtime_price_deviation" in decision.reasons
    assert decision.kill_switch_actions is not None


def test_kill_switch_actions_match_policy() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")

    actions = build_kill_switch_actions(configs.risk_policy)

    assert actions.cancel_all_open_orders is True
    assert actions.set_global_halt is True
    assert actions.flatten_positions is True
