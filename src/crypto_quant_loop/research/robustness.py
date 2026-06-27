from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from crypto_quant_loop.backtest import WalkForwardReport
from crypto_quant_loop.backtest.walk_forward import Regime, classify_regime
from crypto_quant_loop.config.models import RiskPolicyConfig, StrategiesConfig
from crypto_quant_loop.data.ohlcv import OhlcvBar, timeframe_to_ms
from crypto_quant_loop.research.diagnostics import StrategyDiagnostics, diagnose_walk_forward_report
from crypto_quant_loop.strategies import Signal, generate_configured_signals


@dataclass(frozen=True)
class RobustSignalSettings:
    strategy_name: str
    allowed_regimes: tuple[Regime, ...]
    regime_lookback_bars: int
    min_spacing_bars: int
    time_stop_bars: int
    params_update: Mapping[str, int | float]
    stop_update: Mapping[str, int | float]


@dataclass(frozen=True)
class RobustnessComparison:
    strategy_name: str
    base: StrategyDiagnostics
    robust: StrategyDiagnostics
    turnover_reduction_pct: float
    fee_reduction_pct: float
    worst_sharpe_decay_base: float
    worst_sharpe_decay_robust: float
    sharpe_decay_improved: bool
    turnover_improved: bool
    fee_drag_improved: bool

    @property
    def improved(self) -> bool:
        return self.sharpe_decay_improved and self.turnover_improved and self.fee_drag_improved


def robust_settings_for(strategy_name: str) -> RobustSignalSettings:
    if strategy_name == "momentum_breakout":
        return RobustSignalSettings(
            strategy_name=strategy_name,
            allowed_regimes=("bull",),
            regime_lookback_bars=24 * 30,
            min_spacing_bars=48,
            time_stop_bars=48,
            params_update={"fast_ma": 50, "slow_ma": 200, "donchian_lookback": 120},
            stop_update={},
        )
    if strategy_name == "mean_reversion":
        return RobustSignalSettings(
            strategy_name=strategy_name,
            allowed_regimes=("chop",),
            regime_lookback_bars=24 * 14,
            min_spacing_bars=12,
            time_stop_bars=48,
            params_update={"rsi_oversold": 25, "rsi_overbought": 75, "bb_std": 2.5},
            stop_update={"time_stop_bars": 48},
        )
    raise ValueError(f"No robust settings registered for {strategy_name}")


def build_robust_strategy_config(
    strategies: StrategiesConfig,
    strategy_name: str,
    *,
    settings: RobustSignalSettings | None = None,
) -> StrategiesConfig:
    selected_settings = settings or robust_settings_for(strategy_name)
    strategy = strategies.strategies[strategy_name]
    params = strategy.params.model_copy(update=dict(selected_settings.params_update))
    stop = strategy.stop.model_copy(update=dict(selected_settings.stop_update))
    robust_strategy = strategy.model_copy(update={"params": params, "stop": stop})
    return strategies.model_copy(update={"strategies": {strategy_name: robust_strategy}})


def generate_robust_signals(
    bars: list[OhlcvBar],
    *,
    strategies: StrategiesConfig,
    risk_policy: RiskPolicyConfig,
    strategy_name: str,
    settings: RobustSignalSettings | None = None,
) -> list[Signal]:
    selected_settings = settings or robust_settings_for(strategy_name)
    robust_strategies = build_robust_strategy_config(
        strategies,
        strategy_name,
        settings=selected_settings,
    )
    raw_signals = generate_configured_signals(
        bars,
        strategies=robust_strategies,
        risk_policy=risk_policy,
    )
    timed_signals = [
        replace(signal, time_stop_bars=selected_settings.time_stop_bars)
        for signal in raw_signals
    ]
    return apply_robust_signal_filters(bars, timed_signals, settings=selected_settings)


def apply_robust_signal_filters(
    bars: list[OhlcvBar],
    signals: list[Signal],
    *,
    settings: RobustSignalSettings,
) -> list[Signal]:
    ordered_bars = sorted(bars, key=lambda item: item.timestamp_ms)
    timeframe_ms = _infer_timeframe_ms(ordered_bars)
    min_spacing_ms = settings.min_spacing_bars * timeframe_ms
    output: list[Signal] = []
    last_accepted_by_symbol: dict[str, int] = {}
    for signal in sorted(signals, key=lambda item: (item.symbol, item.timestamp_ms)):
        regime = _past_regime(
            ordered_bars,
            timestamp_ms=signal.timestamp_ms,
            lookback_bars=settings.regime_lookback_bars,
        )
        if regime not in settings.allowed_regimes:
            continue
        previous_timestamp = last_accepted_by_symbol.get(signal.symbol)
        too_close = (
            previous_timestamp is not None
            and signal.timestamp_ms - previous_timestamp < min_spacing_ms
        )
        if too_close:
            continue
        output.append(signal)
        last_accepted_by_symbol[signal.symbol] = signal.timestamp_ms
    return sorted(output, key=lambda item: (item.timestamp_ms, item.strategy_name, item.symbol))


def compare_robustness(
    *,
    strategy_name: str,
    base_report: WalkForwardReport,
    robust_report: WalkForwardReport,
    timeframe_ms: int,
) -> RobustnessComparison:
    base = diagnose_walk_forward_report(
        strategy_name=strategy_name,
        report=base_report,
        timeframe_ms=timeframe_ms,
    )
    robust = diagnose_walk_forward_report(
        strategy_name=f"{strategy_name}_robust",
        report=robust_report,
        timeframe_ms=timeframe_ms,
    )
    worst_base = _worst_sharpe_decay(base_report)
    worst_robust = _worst_sharpe_decay(robust_report)
    return RobustnessComparison(
        strategy_name=strategy_name,
        base=base,
        robust=robust,
        turnover_reduction_pct=_reduction_pct(base.turnover, robust.turnover),
        fee_reduction_pct=_reduction_pct(base.fees_paid, robust.fees_paid),
        worst_sharpe_decay_base=worst_base,
        worst_sharpe_decay_robust=worst_robust,
        sharpe_decay_improved=worst_robust <= worst_base,
        turnover_improved=robust.turnover < base.turnover,
        fee_drag_improved=robust.fees_paid < base.fees_paid,
    )


def _past_regime(
    bars: list[OhlcvBar],
    *,
    timestamp_ms: int,
    lookback_bars: int,
) -> Regime:
    past = [bar for bar in bars if bar.timestamp_ms <= timestamp_ms]
    return classify_regime(past[-lookback_bars:])


def _infer_timeframe_ms(bars: list[OhlcvBar]) -> int:
    if len(bars) >= 2:
        return bars[1].timestamp_ms - bars[0].timestamp_ms
    if bars:
        return timeframe_to_ms(bars[0].timeframe)
    return timeframe_to_ms("1h")


def _worst_sharpe_decay(report: WalkForwardReport) -> float:
    return max((segment.sharpe_decay for segment in report.segments), default=0.0)


def _reduction_pct(base: float, robust: float) -> float:
    if base <= 0:
        return 0.0
    return ((base - robust) / base) * 100
