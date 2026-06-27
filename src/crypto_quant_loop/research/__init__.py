"""Strategy research helpers."""

from crypto_quant_loop.research.baselines import (
    BeatDecision,
    BenchmarkMetrics,
    PerformanceSnapshot,
    beats_benchmark,
    build_baseline_report,
    compute_buy_and_hold,
    compute_equal_weight_basket,
    load_ohlcv_from_duckdb,
    snapshot_from_backtest,
)
from crypto_quant_loop.research.diagnostics import (
    RegimeDiagnostics,
    StrategyDiagnostics,
    diagnose_walk_forward_report,
)
from crypto_quant_loop.research.portfolio import (
    PortfolioReport,
    apply_directional_cap,
    combine_weighted_oos_returns,
    inverse_volatility_weights,
)
from crypto_quant_loop.research.robustness import (
    RobustnessComparison,
    RobustSignalSettings,
    apply_robust_signal_filters,
    build_robust_strategy_config,
    compare_robustness,
    generate_robust_signals,
    robust_settings_for,
)
from crypto_quant_loop.research.strategy_families import (
    generate_regime_switch_signals,
    generate_volatility_target_trend_signals,
)

__all__ = [
    "BeatDecision",
    "BenchmarkMetrics",
    "PerformanceSnapshot",
    "PortfolioReport",
    "RegimeDiagnostics",
    "StrategyDiagnostics",
    "RobustSignalSettings",
    "RobustnessComparison",
    "apply_robust_signal_filters",
    "apply_directional_cap",
    "beats_benchmark",
    "build_baseline_report",
    "build_robust_strategy_config",
    "combine_weighted_oos_returns",
    "compare_robustness",
    "compute_buy_and_hold",
    "compute_equal_weight_basket",
    "diagnose_walk_forward_report",
    "generate_robust_signals",
    "generate_regime_switch_signals",
    "generate_volatility_target_trend_signals",
    "inverse_volatility_weights",
    "load_ohlcv_from_duckdb",
    "robust_settings_for",
    "snapshot_from_backtest",
]
