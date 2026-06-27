from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from crypto_quant_loop.config.models import FillsConfig, RiskPolicyConfig, SymbolsConfig
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.strategies import Signal


class LookaheadDetectedError(ValueError):
    """Raised when a signal generator changes past outputs after seeing future bars."""


@dataclass(frozen=True)
class Trade:
    signal_timestamp_ms: int
    entry_timestamp_ms: int
    exit_timestamp_ms: int
    symbol: str
    strategy_name: str
    order_type: str
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees_paid: float
    net_pnl: float
    notional: float
    skipped_reason: str | None = None


@dataclass(frozen=True)
class BacktestReport:
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    annualized_return_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    trades: int
    skipped_signals: int
    fees_paid: float
    turnover: float
    fee_pct_of_turnover: float
    trade_log: list[Trade]


SignalGenerator = Callable[[list[OhlcvBar]], list[Signal]]


def validate_signal_generator_no_lookahead(
    bars: list[OhlcvBar],
    signal_generator: SignalGenerator,
) -> None:
    ordered = _ordered(bars)
    full_keys = {_signal_key(signal) for signal in signal_generator(ordered)}
    for index in range(len(ordered)):
        prefix = ordered[: index + 1]
        prefix_keys = {_signal_key(signal) for signal in signal_generator(prefix)}
        past_full_keys = {
            key for key in full_keys if key[0] <= ordered[index].timestamp_ms
        }
        if prefix_keys != past_full_keys:
            raise LookaheadDetectedError(
                f"Signal generator output changes after seeing future bars at index {index}"
            )


def run_backtest(
    *,
    bars: list[OhlcvBar],
    signals: list[Signal],
    risk_policy: RiskPolicyConfig,
    fills: FillsConfig,
    symbols: SymbolsConfig,
) -> BacktestReport:
    ordered = _ordered(bars)
    bar_by_timestamp = {bar.timestamp_ms: index for index, bar in enumerate(ordered)}
    equity = risk_policy.account.equity_size
    starting_equity = equity
    equity_curve = [equity]
    trades: list[Trade] = []
    skipped = 0
    total_turnover = 0.0
    total_fees = 0.0

    for signal in sorted(signals, key=lambda item: item.timestamp_ms):
        signal_index = bar_by_timestamp.get(signal.timestamp_ms)
        if signal_index is None or signal_index + 1 >= len(ordered):
            skipped += 1
            continue

        entry_bar = ordered[signal_index + 1]
        exit_index = _exit_index(signal_index + 1, signal, len(ordered))
        exit_bar = ordered[exit_index]
        sizing = _position_notional(signal, equity, risk_policy, symbols)
        if sizing is None:
            skipped += 1
            continue
        notional = sizing
        entry_price = _entry_price(entry_bar, signal, fills, notional)
        quantity = notional / entry_price
        exit_price = signal.stop_price if exit_bar.low <= signal.stop_price else exit_bar.close
        gross_pnl = (exit_price - entry_price) * quantity
        fees_paid = _fees_paid(notional, abs(exit_price * quantity), signal, fills)
        net_pnl = gross_pnl - fees_paid
        equity += net_pnl
        equity_curve.append(equity)
        total_turnover += notional + abs(exit_price * quantity)
        total_fees += fees_paid
        trades.append(
            Trade(
                signal_timestamp_ms=signal.timestamp_ms,
                entry_timestamp_ms=entry_bar.timestamp_ms,
                exit_timestamp_ms=exit_bar.timestamp_ms,
                symbol=signal.symbol,
                strategy_name=signal.strategy_name,
                order_type=signal.order_type,
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_pnl=gross_pnl,
                fees_paid=fees_paid,
                net_pnl=net_pnl,
                notional=notional,
            )
        )

    returns = _equity_returns(equity_curve)
    return BacktestReport(
        starting_equity=starting_equity,
        ending_equity=equity,
        total_return_pct=((equity / starting_equity) - 1.0) * 100,
        annualized_return_pct=_annualized_return(equity_curve),
        sharpe=_sharpe(returns),
        sortino=_sortino(returns),
        max_drawdown_pct=_max_drawdown(equity_curve) * 100,
        win_rate=_win_rate(trades),
        profit_factor=_profit_factor(trades),
        trades=len(trades),
        skipped_signals=skipped,
        fees_paid=total_fees,
        turnover=total_turnover,
        fee_pct_of_turnover=(total_fees / total_turnover) * 100 if total_turnover else 0.0,
        trade_log=trades,
    )


def _signal_key(signal: Signal) -> tuple[int, str, str, str]:
    return (
        signal.timestamp_ms,
        signal.strategy_name,
        signal.symbol,
        signal.side,
    )


def _ordered(bars: list[OhlcvBar]) -> list[OhlcvBar]:
    return sorted(bars, key=lambda item: item.timestamp_ms)


def _position_notional(
    signal: Signal,
    equity: float,
    risk_policy: RiskPolicyConfig,
    symbols: SymbolsConfig,
) -> float | None:
    stop_distance = signal.reference_price - signal.stop_price
    if stop_distance <= 0:
        return None
    risk_budget = equity * risk_policy.position_sizing.single_trade_risk_pct
    stop_distance_pct = stop_distance / signal.reference_price
    raw_notional = risk_budget / stop_distance_pct
    symbol_cap = equity * risk_policy.position_sizing.single_symbol_notional_cap_pct
    portfolio_cap = equity * risk_policy.position_sizing.portfolio_directional_cap_pct
    notional = min(raw_notional, symbol_cap, portfolio_cap)
    symbol_filter = symbols.symbols[signal.symbol].filters
    min_notional = max(
        risk_policy.position_sizing.min_notional_floor_quote,
        symbol_filter.min_notional_quote,
    )
    if notional < min_notional:
        return None
    return notional


def _entry_price(
    entry_bar: OhlcvBar,
    signal: Signal,
    fills: FillsConfig,
    notional: float,
) -> float:
    spread_bps = fills.backtest_historical.cross_half_spread_bps.get(signal.symbol, 0.0)
    impact_bps = fills.backtest_historical.impact_coeff_bps_per_1pct_adv * (notional / 1_000_000)
    total_bps = spread_bps + fills.backtest_historical.conservative_buffer_bps + impact_bps
    return entry_bar.open * (1.0 + (total_bps / 10_000))


def _fees_paid(
    entry_notional: float,
    exit_notional: float,
    signal: Signal,
    fills: FillsConfig,
) -> float:
    bps = fills.fees.taker_bps if signal.order_type == "market" else fills.fees.maker_bps
    if fills.fees.use_bnb_discount:
        bps *= 0.75
    return (entry_notional + exit_notional) * (bps / 10_000)


def _exit_index(entry_index: int, signal: Signal, total_bars: int) -> int:
    holding_bars = signal.time_stop_bars or 1
    return min(entry_index + holding_bars, total_bars - 1)


def _equity_returns(equity_curve: list[float]) -> list[float]:
    output: list[float] = []
    for previous, current in zip(equity_curve, equity_curve[1:], strict=False):
        if previous == 0:
            continue
        output.append((current / previous) - 1.0)
    return output


def _annualized_return(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2 or equity_curve[0] <= 0:
        return 0.0
    total_return = equity_curve[-1] / equity_curve[0]
    periods = len(equity_curve) - 1
    return float(((total_return ** (365 * 24 / periods)) - 1.0) * 100)


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    return (mean / std) * math.sqrt(365 * 24) if std else 0.0


def _sortino(returns: list[float]) -> float:
    if not returns:
        return 0.0
    downside = [min(item, 0.0) for item in returns]
    downside_variance = sum(item**2 for item in downside) / len(downside)
    downside_std = math.sqrt(downside_variance)
    mean = sum(returns) / len(returns)
    return (mean / downside_std) * math.sqrt(365 * 24) if downside_std else 0.0


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0] if equity_curve else 0.0
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    winners = sum(1 for trade in trades if trade.net_pnl > 0)
    return winners / len(trades)


def _profit_factor(trades: list[Trade]) -> float:
    gross_profit = sum(trade.net_pnl for trade in trades if trade.net_pnl > 0)
    gross_loss = abs(sum(trade.net_pnl for trade in trades if trade.net_pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss
