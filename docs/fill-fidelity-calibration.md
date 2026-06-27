# Fill-Fidelity Calibration Loop

Use forward paper/dry-run fills to calibrate historical backtest assumptions.

1. Historical backtests use `config/fills.yaml.backtest_historical`.
2. Forward paper/dry-run records actual orderbook-based fills.
3. Fill-Fidelity compares expected price/quantity against actual fill price/quantity.
4. Daily reports summarize average and worst slippage bps plus fill quantity ratio.
5. Only after enough forward observations should a human update placeholder bps in `config/fills.yaml`.
6. After any fill-model update, rerun backtests and walk-forward verification.

Do not automatically modify `config/fills.yaml`; fill calibration is a human-reviewed config change.
