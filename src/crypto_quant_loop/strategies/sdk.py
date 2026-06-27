from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from crypto_quant_loop.config.models import RiskPolicyConfig, StrategiesConfig, StrategyConfig
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.features import atr

Side = Literal["long"]
OrderType = Literal["market", "limit"]


@dataclass(frozen=True)
class Signal:
    strategy_name: str
    strategy_type: str
    symbol: str
    timestamp_ms: int
    side: Side
    order_type: OrderType
    reference_price: float
    stop_price: float
    time_stop_bars: int | None = None
    metadata: dict[str, float | int | str] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyState:
    open_positions: dict[str, str] = field(default_factory=dict)


def generate_configured_signals(
    bars: list[OhlcvBar],
    *,
    strategies: StrategiesConfig,
    risk_policy: RiskPolicyConfig,
    state: StrategyState | None = None,
) -> list[Signal]:
    del state
    signals: list[Signal] = []
    for name, config in strategies.strategies.items():
        if not config.enabled:
            continue
        if config.type == "momentum":
            signals.extend(_generate_momentum_signals(name, config, bars))
        elif config.type == "mean_reversion":
            signals.extend(_generate_mean_reversion_signals(name, config, bars, risk_policy))
    return sorted(signals, key=lambda signal: (signal.timestamp_ms, signal.strategy_name))


def _generate_momentum_signals(
    name: str,
    config: StrategyConfig,
    bars: list[OhlcvBar],
) -> list[Signal]:
    ordered = _ordered(bars)
    params = config.params
    if params.fast_ma is None or params.slow_ma is None or params.donchian_lookback is None:
        raise ValueError("momentum strategy requires fast_ma, slow_ma, and donchian_lookback")
    fast_ma = params.fast_ma
    slow_ma = params.slow_ma
    donchian_lookback = params.donchian_lookback
    atr_values = atr(ordered, period=params.atr_period or 14)
    closes = [bar.close for bar in ordered]
    signals: list[Signal] = []

    for index, bar in enumerate(ordered):
        if index < max(fast_ma, slow_ma, donchian_lookback):
            continue
        fast = _sma(closes, index, fast_ma)
        slow = _sma(closes, index, slow_ma)
        previous_high = max(item.high for item in ordered[index - donchian_lookback : index])
        current_atr = atr_values[index]
        if fast is None or slow is None or current_atr is None:
            continue
        if fast > slow and bar.close > previous_high:
            signals.append(
                _build_signal(
                    name=name,
                    config=config,
                    bar=bar,
                    stop_price=bar.close - (current_atr * config.stop.atr_mult),
                    metadata={"fast_ma": fast, "slow_ma": slow, "donchian_high": previous_high},
                )
            )
    return signals


def _generate_mean_reversion_signals(
    name: str,
    config: StrategyConfig,
    bars: list[OhlcvBar],
    risk_policy: RiskPolicyConfig,
) -> list[Signal]:
    ordered = _ordered(bars)
    params = config.params
    if (
        params.rsi_period is None
        or params.rsi_oversold is None
        or params.bb_period is None
        or params.bb_std is None
        or params.trend_filter_ma is None
    ):
        raise ValueError("mean reversion strategy missing RSI/Bollinger/trend parameters")

    rsi_values = _rsi([bar.close for bar in ordered], params.rsi_period)
    lower_band = _bollinger_lower(
        [bar.close for bar in ordered],
        params.bb_period,
        params.bb_std,
    )
    trend_ma = _rolling_sma([bar.close for bar in ordered], params.trend_filter_ma)
    atr_values = atr(ordered, period=risk_policy.position_sizing.stop.atr_period)
    time_stop_bars = config.stop.time_stop_bars or risk_policy.mean_reversion.time_stop_bars
    signals: list[Signal] = []

    for index, bar in enumerate(ordered):
        rsi_value = rsi_values[index]
        lower = lower_band[index]
        trend = trend_ma[index]
        current_atr = atr_values[index]
        if rsi_value is None or lower is None or trend is None or current_atr is None:
            continue
        if (
            rsi_value <= params.rsi_oversold
            and bar.close <= lower
            and bar.close >= trend
        ):
            signals.append(
                _build_signal(
                    name=name,
                    config=config,
                    bar=bar,
                    stop_price=bar.close - (current_atr * config.stop.atr_mult),
                    time_stop_bars=time_stop_bars,
                    metadata={"rsi": rsi_value, "lower_band": lower, "trend_ma": trend},
                )
            )
    return signals


def _build_signal(
    *,
    name: str,
    config: StrategyConfig,
    bar: OhlcvBar,
    stop_price: float,
    time_stop_bars: int | None = None,
    metadata: dict[str, float | int | str] | None = None,
) -> Signal:
    if stop_price >= bar.close:
        raise ValueError("Long signal stop price must be below reference price")
    return Signal(
        strategy_name=name,
        strategy_type=config.type,
        symbol=bar.symbol,
        timestamp_ms=bar.timestamp_ms,
        side="long",
        order_type=config.order_type,
        reference_price=bar.close,
        stop_price=stop_price,
        time_stop_bars=time_stop_bars,
        metadata=metadata or {},
    )


def _ordered(bars: list[OhlcvBar]) -> list[OhlcvBar]:
    return sorted(bars, key=lambda item: item.timestamp_ms)


def _sma(values: list[float], index: int, window: int) -> float | None:
    if index + 1 < window:
        return None
    sample = values[index - window + 1 : index + 1]
    return sum(sample) / window


def _rolling_sma(values: list[float], window: int) -> list[float | None]:
    return [_sma(values, index, window) for index in range(len(values))]


def _bollinger_lower(values: list[float], window: int, std_mult: float) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            output.append(None)
            continue
        sample = values[index - window + 1 : index + 1]
        mean = sum(sample) / window
        variance = sum((item - mean) ** 2 for item in sample) / window
        output.append(mean - (std_mult * (variance**0.5)))
    return output


def _rsi(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None]
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:], strict=False):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
        if len(gains) < period:
            output.append(None)
            continue
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]
        average_gain = sum(recent_gains) / period
        average_loss = sum(recent_losses) / period
        if average_loss == 0:
            output.append(100.0)
        else:
            relative_strength = average_gain / average_loss
            output.append(100.0 - (100.0 / (1.0 + relative_strength)))
    return output[: len(values)]
