from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.funding import write_funding_rates_duckdb
from crypto_quant_loop.data.ohlcv import CcxtOhlcvClient, fetch_historical_ohlcv
from crypto_quant_loop.data.structural import (
    CcxtFundingHistoryClient,
    CcxtPerpMarkOhlcvClient,
    build_structural_quality_report,
    derive_basis_samples,
    fetch_historical_funding_rates,
    fetch_paged_historical_funding_rates,
    load_basis_samples_from_duckdb,
    save_structural_quality_report,
    write_basis_samples_duckdb,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch historical funding and perp basis public market data."
    )
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--duckdb-path", default="data/processed/market.duckdb")
    parser.add_argument("--report-path", default="reports/f1_structural_data_quality.json")
    parser.add_argument("--exchange", default="okx")
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--funding-only", action="store_true")
    parser.add_argument("--funding-mode", choices=["since", "paged"], default="since")
    parser.add_argument("--funding-page-param", default="page_num")
    parser.add_argument("--max-pages", type=int, default=100)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configs = load_all_configs(Path(args.config_dir))
    lookback_days = args.lookback_days or configs.symbols.history.min_lookback_days
    since = datetime.now(UTC) - timedelta(days=lookback_days)
    until = datetime.now(UTC)

    funding_client = CcxtFundingHistoryClient(
        exchange_id=args.exchange,
        enable_rate_limit=configs.exchanges.defaults.rate_limit,
        timeout_ms=configs.exchanges.defaults.timeout_ms,
    )
    spot_client = CcxtOhlcvClient(
        exchange_id=args.exchange,
        enable_rate_limit=configs.exchanges.defaults.rate_limit,
        timeout_ms=configs.exchanges.defaults.timeout_ms,
    )
    mark_client = CcxtPerpMarkOhlcvClient(
        exchange_id=args.exchange,
        enable_rate_limit=configs.exchanges.defaults.rate_limit,
        timeout_ms=configs.exchanges.defaults.timeout_ms,
    )

    all_funding = []
    all_basis = []
    for symbol in configs.risk_policy.symbols.research:
        timeframe = configs.symbols.symbols[symbol].timeframe
        if args.funding_mode == "paged":
            funding = fetch_paged_historical_funding_rates(
                client=funding_client,
                exchange=args.exchange,
                symbol=symbol,
                until_ms=int(until.timestamp() * 1000),
                limit=args.limit,
                page_param=args.funding_page_param,
                max_pages=args.max_pages,
            )
        else:
            funding = fetch_historical_funding_rates(
                client=funding_client,
                exchange=args.exchange,
                symbol=symbol,
                since_ms=int(since.timestamp() * 1000),
                until_ms=int(until.timestamp() * 1000),
                limit=args.limit,
            )
        basis = []
        if not args.funding_only:
            spot_bars = fetch_historical_ohlcv(
                client=spot_client,
                exchange=args.exchange,
                symbol=symbol,
                timeframe=timeframe,
                since_ms=int(since.timestamp() * 1000),
                until_ms=int(until.timestamp() * 1000),
                limit=1000,
            )
            mark_bars = fetch_historical_ohlcv(
                client=mark_client,
                exchange=args.exchange,
                symbol=symbol,
                timeframe=timeframe,
                since_ms=int(since.timestamp() * 1000),
                until_ms=int(until.timestamp() * 1000),
                limit=1000,
            )
            basis = derive_basis_samples(
                spot_bars=spot_bars,
                perp_mark_bars=mark_bars,
                exchange=args.exchange,
                symbol=symbol,
            )
        all_funding.extend(funding)
        all_basis.extend(basis)

    db_path = Path(args.duckdb_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    write_funding_rates_duckdb(all_funding, db_path)
    write_basis_samples_duckdb(all_basis, db_path)
    report_basis = load_basis_samples_from_duckdb(db_path) if args.funding_only else all_basis
    report = build_structural_quality_report(
        funding_rates=all_funding,
        basis_samples=report_basis,
        basis_timeframe=configs.research.benchmarks.timeframe,
    )
    save_structural_quality_report(report, Path(args.report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
