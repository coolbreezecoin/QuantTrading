from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.ohlcv import CcxtOhlcvClient, fetch_historical_ohlcv
from crypto_quant_loop.data.quality import build_ohlcv_quality_report, save_quality_report
from crypto_quant_loop.data.storage import write_ohlcv_duckdb, write_ohlcv_parquet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV public market data.")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--raw-dir", default="data/raw/ohlcv")
    parser.add_argument("--duckdb-path", default="data/processed/market.duckdb")
    parser.add_argument("--report-path", default="reports/data_quality.json")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--limit", type=int, default=1000)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configs = load_all_configs(Path(args.config_dir))
    exchange_config = configs.exchanges.exchanges[args.exchange]
    client = CcxtOhlcvClient(
        exchange_id=args.exchange,
        enable_rate_limit=configs.exchanges.defaults.rate_limit,
        timeout_ms=configs.exchanges.defaults.timeout_ms,
    )

    until = datetime.now(UTC)
    since = until - timedelta(days=configs.symbols.history.min_lookback_days)
    all_reports: list[dict[str, object]] = []
    all_bars = []
    for symbol in configs.risk_policy.symbols.research:
        timeframe = configs.symbols.symbols[symbol].timeframe
        bars = fetch_historical_ohlcv(
            client=client,
            exchange=args.exchange,
            symbol=symbol,
            timeframe=timeframe,
            since_ms=int(since.timestamp() * 1000),
            until_ms=int(until.timestamp() * 1000),
            limit=args.limit,
        )
        all_bars.extend(bars)
        write_ohlcv_parquet(bars, Path(args.raw_dir))
        all_reports.append(build_ohlcv_quality_report(bars, timeframe=timeframe))

    write_ohlcv_duckdb(all_bars, Path(args.duckdb_path))
    save_quality_report(
        {
            "exchange": args.exchange,
            "exchange_type": exchange_config.type,
            "generated_at": datetime.now(UTC).isoformat(),
            "reports": all_reports,
        },
        Path(args.report_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

