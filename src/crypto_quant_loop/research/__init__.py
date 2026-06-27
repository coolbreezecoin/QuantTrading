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

__all__ = [
    "BeatDecision",
    "BenchmarkMetrics",
    "PerformanceSnapshot",
    "beats_benchmark",
    "build_baseline_report",
    "compute_buy_and_hold",
    "compute_equal_weight_basket",
    "load_ohlcv_from_duckdb",
    "snapshot_from_backtest",
]
