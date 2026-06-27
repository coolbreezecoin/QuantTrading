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

__all__ = [
    "BeatDecision",
    "BenchmarkMetrics",
    "PerformanceSnapshot",
    "RegimeDiagnostics",
    "StrategyDiagnostics",
    "beats_benchmark",
    "build_baseline_report",
    "compute_buy_and_hold",
    "compute_equal_weight_basket",
    "diagnose_walk_forward_report",
    "load_ohlcv_from_duckdb",
    "snapshot_from_backtest",
]
