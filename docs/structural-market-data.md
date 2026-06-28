# Structural Market Data

- F1 structural data is research-only. It does not change `config/exchanges.yaml`,
  `config/risk-policy.yaml`, live permissions, leverage limits, or strategy approvals.
- Funding rates are historical-backfillable through public perpetual endpoints when the
  exchange exposes history. The local OKX pull returned BTC from 2026-03-16 and ETH/SOL from
  2026-03-23 through 2026-06-28, with 100% coverage inside that available window.
- Basis is derived from public perp mark-price OHLCV minus public spot OHLCV. The local OKX
  pull produced BTC/ETH/SOL 1h basis from 2025-01-04 through 2026-06-28 with 100% coverage.
- L2 orderbook depth remains forward-only and is not backfilled, matching the S4/S7 red line.
- Optional open interest is not collected in F1; adding paid or private sources is a separate
  scope decision and may trigger a manual gate.
