from __future__ import annotations

from dataclasses import replace

from crypto_quant_loop.backtest.walk_forward import Regime, classify_regime
from crypto_quant_loop.config.models import RiskPolicyConfig, StrategiesConfig
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.features import atr
from crypto_quant_loop.research.robustness import generate_robust_signals
from crypto_quant_loop.strategies import Signal


def generate_volatility_target_trend_signals(
    bars: list[OhlcvBar],
    *,
    name: str = "volatility_target_trend",
    fast_ma: int = 80,
    slow_ma: int = 240,
    breakout_lookback: int = 150,
    atr_period: int = 14,
    atr_mult: float = 3.0,
    regime_lookback_bars: int = 24 * 30,
    allowed_regimes: tuple[Regime, ...] = ("bull",),
    min_spacing_bars: int = 48,
    time_stop_bars: int = 72,
) -> list[Signal]:
    ordered = sorted(bars, key=lambda item: item.timestamp_ms)
    if len(ordered) < max(fast_ma, slow_ma, breakout_lookback, atr_period) + 1:
        return []
    atr_values = atr(ordered, period=atr_period)
    closes = [bar.close for bar in ordered]
    output: list[Signal] = []
    last_signal_timestamp: int | None = None
    timeframe_ms = _infer_timeframe_ms(ordered)
    min_spacing_ms = min_spacing_bars * timeframe_ms
    for index, bar in enumerate(ordered):
        if index < max(fast_ma, slow_ma, breakout_lookback):
            continue
        current_atr = atr_values[index]
        if current_atr is None:
            continue
        regime = classify_regime(ordered[max(0, index - regime_lookback_bars + 1) : index + 1])
        if regime not in allowed_regimes:
            continue
        too_close = (
            last_signal_timestamp is not None
            and bar.timestamp_ms - last_signal_timestamp < min_spacing_ms
        )
        if too_close:
            continue
        fast = _sma(closes, index, fast_ma)
        slow = _sma(closes, index, slow_ma)
        previous_high = max(item.high for item in ordered[index - breakout_lookback : index])
        if fast is None or slow is None:
            continue
        if fast <= slow or bar.close <= previous_high:
            continue
        stop_price = bar.close - (current_atr * atr_mult)
        if stop_price <= 0 or stop_price >= bar.close:
            continue
        output.append(
            Signal(
                strategy_name=name,
                strategy_type="volatility_target_trend",
                symbol=bar.symbol,
                timestamp_ms=bar.timestamp_ms,
                side="long",
                order_type="market",
                reference_price=bar.close,
                stop_price=stop_price,
                time_stop_bars=time_stop_bars,
                metadata={
                    "fast_ma": fast,
                    "slow_ma": slow,
                    "previous_high": previous_high,
                    "atr": current_atr,
                    "regime": regime,
                },
            )
        )
        last_signal_timestamp = bar.timestamp_ms
    return output


def generate_regime_switch_signals(
    bars: list[OhlcvBar],
    *,
    strategies: StrategiesConfig,
    risk_policy: RiskPolicyConfig,
    name: str = "regime_switch_existing",
) -> list[Signal]:
    momentum = generate_robust_signals(
        bars,
        strategies=strategies,
        risk_policy=risk_policy,
        strategy_name="momentum_breakout",
    )
    mean_reversion = generate_robust_signals(
        bars,
        strategies=strategies,
        risk_policy=risk_policy,
        strategy_name="mean_reversion",
    )
    return sorted(
        [
            replace(signal, strategy_name=name, strategy_type="regime_switch")
            for signal in [*momentum, *mean_reversion]
        ],
        key=lambda item: (item.timestamp_ms, item.symbol, item.order_type),
    )


def _sma(values: list[float], index: int, window: int) -> float | None:
    if index + 1 < window:
        return None
    sample = values[index - window + 1 : index + 1]
    return sum(sample) / window


def _infer_timeframe_ms(bars: list[OhlcvBar]) -> int:
    if len(bars) >= 2:
        return bars[1].timestamp_ms - bars[0].timestamp_ms
    return 3_600_000
