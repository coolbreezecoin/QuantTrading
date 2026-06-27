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
from crypto_quant_loop.research.robustness import (
    RobustnessComparison,
    RobustSignalSettings,
    apply_robust_signal_filters,
    build_robust_strategy_config,
    compare_robustness,
    generate_robust_signals,
    robust_settings_for,
)

__all__ = [
    "BeatDecision",
    "BenchmarkMetrics",
    "PerformanceSnapshot",
    "RegimeDiagnostics",
    "StrategyDiagnostics",
    "RobustSignalSettings",
    "RobustnessComparison",
    "apply_robust_signal_filters",
    "beats_benchmark",
    "build_baseline_report",
    "build_robust_strategy_config",
    "compare_robustness",
    "compute_buy_and_hold",
    "compute_equal_weight_basket",
    "diagnose_walk_forward_report",
    "generate_robust_signals",
    "load_ohlcv_from_duckdb",
    "robust_settings_for",
    "snapshot_from_backtest",
]
