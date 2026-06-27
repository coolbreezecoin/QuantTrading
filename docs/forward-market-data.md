# Forward Market Data Boundary

L2 orderbook snapshots are forward-only data.

- Historical OHLCV can be fetched from public REST APIs.
- Historical L2 orderbook depth is not available from the configured public exchange APIs.
- Backtests must not pretend historical L2 orderbook replay exists.
- Paper trading and dry-run execution may use orderbook snapshots collected after the collector starts.
- Fill-Fidelity compares historical backtest assumptions against forward paper/live dry-run fills and feeds calibration back into `config/fills.yaml`.
- The collector defaults to an explicit caller-controlled run; it should not start a persistent external websocket connection unless scheduling/configuration enables it.

