"""Backtesting components."""

from crypto_quant_loop.backtest.engine import (
    BacktestReport,
    LookaheadDetectedError,
    Trade,
    run_backtest,
    validate_signal_generator_no_lookahead,
)

__all__ = [
    "BacktestReport",
    "LookaheadDetectedError",
    "Trade",
    "run_backtest",
    "validate_signal_generator_no_lookahead",
]

