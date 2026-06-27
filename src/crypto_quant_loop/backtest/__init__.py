"""Backtesting components."""

from crypto_quant_loop.backtest.engine import (
    BacktestReport,
    LookaheadDetectedError,
    Trade,
    run_backtest,
    validate_signal_generator_no_lookahead,
)
from crypto_quant_loop.backtest.walk_forward import (
    WalkForwardReport,
    WalkForwardSegmentReport,
    WalkForwardWindow,
    build_walk_forward_windows,
    run_walk_forward,
)

__all__ = [
    "BacktestReport",
    "LookaheadDetectedError",
    "Trade",
    "WalkForwardReport",
    "WalkForwardSegmentReport",
    "WalkForwardWindow",
    "build_walk_forward_windows",
    "run_backtest",
    "run_walk_forward",
    "validate_signal_generator_no_lookahead",
]

