from __future__ import annotations

from dataclasses import dataclass, field

from crypto_quant_loop.config.models import RiskPolicyConfig, SymbolsConfig
from crypto_quant_loop.strategies import Signal


@dataclass(frozen=True)
class Position:
    symbol: str
    notional: float
    beta: float = 1.0


@dataclass(frozen=True)
class PnlEvent:
    timestamp_ms: int
    pnl: float


@dataclass(frozen=True)
class RuntimeHealth:
    data_gap: bool = False
    api_error: bool = False
    heartbeat_missed: bool = False
    price_deviation_bps: float = 0.0


@dataclass(frozen=True)
class KillSwitchActions:
    cancel_all_open_orders: bool
    flatten_positions: bool
    set_global_halt: bool


@dataclass(frozen=True)
class RiskDecision:
    allow_new_orders: bool
    cooldown_required: bool
    halt_required: bool
    reasons: list[str] = field(default_factory=list)
    kill_switch_actions: KillSwitchActions | None = None


def size_signal_notional(
    *,
    signal: Signal,
    equity: float,
    existing_positions: list[Position],
    risk_policy: RiskPolicyConfig,
    symbols: SymbolsConfig,
) -> float | None:
    stop_distance = signal.reference_price - signal.stop_price
    if stop_distance <= 0:
        return None
    risk_budget = equity * risk_policy.position_sizing.single_trade_risk_pct
    raw_notional = risk_budget / (stop_distance / signal.reference_price)
    symbol_cap = equity * risk_policy.position_sizing.single_symbol_notional_cap_pct
    portfolio_cap = equity * risk_policy.position_sizing.portfolio_directional_cap_pct
    existing_symbol = sum(
        position.notional for position in existing_positions if position.symbol == signal.symbol
    )
    existing_portfolio = sum(position.notional * position.beta for position in existing_positions)
    available_symbol = max(symbol_cap - existing_symbol, 0.0)
    available_portfolio = max(portfolio_cap - existing_portfolio, 0.0)
    notional = min(raw_notional, available_symbol, available_portfolio)
    symbol_filter = symbols.symbols[signal.symbol].filters
    min_notional = max(
        risk_policy.position_sizing.min_notional_floor_quote,
        symbol_filter.min_notional_quote,
    )
    if notional < min_notional:
        return None
    return notional


def evaluate_risk(
    *,
    equity: float,
    equity_high: float,
    starting_equity: float,
    pnl_events: list[PnlEvent],
    runtime_health: RuntimeHealth,
    now_ms: int,
    risk_policy: RiskPolicyConfig,
) -> RiskDecision:
    reasons: list[str] = []
    cooldown_required = False
    halt_required = False

    consecutive_losses = _consecutive_losses(pnl_events)
    if consecutive_losses >= risk_policy.circuit_breakers.consecutive_losses.count:
        cooldown_required = True
        reasons.append("consecutive_losses_cooldown")

    rolling_loss = _rolling_24h_pnl(pnl_events, now_ms)
    if rolling_loss < -(equity * risk_policy.circuit_breakers.rolling_24h_loss_halt_pct):
        halt_required = True
        reasons.append("rolling_24h_loss_halt")

    if equity_high > 0:
        drawdown = (equity_high - equity) / equity_high
        if drawdown > risk_policy.circuit_breakers.total_drawdown_pause_pct:
            halt_required = True
            reasons.append("total_drawdown_pause")

    if starting_equity > 0:
        business_loss = (starting_equity - equity) / starting_equity
        if business_loss > risk_policy.circuit_breakers.business_hard_stop_pct:
            halt_required = True
            reasons.append("business_hard_stop")

    runtime_reasons = _runtime_halt_reasons(runtime_health, risk_policy)
    if runtime_reasons:
        halt_required = True
        reasons.extend(runtime_reasons)

    actions = build_kill_switch_actions(risk_policy) if halt_required else None
    return RiskDecision(
        allow_new_orders=not cooldown_required and not halt_required,
        cooldown_required=cooldown_required,
        halt_required=halt_required,
        reasons=reasons,
        kill_switch_actions=actions,
    )


def build_kill_switch_actions(risk_policy: RiskPolicyConfig) -> KillSwitchActions:
    return KillSwitchActions(
        cancel_all_open_orders=risk_policy.kill_switch.cancel_all_open_orders,
        flatten_positions=risk_policy.kill_switch.flatten_positions,
        set_global_halt=risk_policy.kill_switch.set_global_halt,
    )


def _consecutive_losses(events: list[PnlEvent]) -> int:
    count = 0
    for event in reversed(sorted(events, key=lambda item: item.timestamp_ms)):
        if event.pnl < 0:
            count += 1
        else:
            break
    return count


def _rolling_24h_pnl(events: list[PnlEvent], now_ms: int) -> float:
    window_start = now_ms - 86_400_000
    return sum(event.pnl for event in events if event.timestamp_ms >= window_start)


def _runtime_halt_reasons(
    runtime_health: RuntimeHealth,
    risk_policy: RiskPolicyConfig,
) -> list[str]:
    reasons: list[str] = []
    if runtime_health.data_gap and risk_policy.auto_halt_on.data_gap:
        reasons.append("runtime_data_gap")
    if runtime_health.api_error and risk_policy.auto_halt_on.api_error:
        reasons.append("runtime_api_error")
    if runtime_health.heartbeat_missed:
        reasons.append("runtime_heartbeat_missed")
    if runtime_health.price_deviation_bps > risk_policy.auto_halt_on.price_deviation_bps:
        reasons.append("runtime_price_deviation")
    return reasons

