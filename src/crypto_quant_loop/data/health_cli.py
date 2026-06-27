from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.health import run_data_health_loop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the OHLCV data health loop.")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--duckdb-path", default="data/processed/market.duckdb")
    parser.add_argument("--report-path", default="reports/data_health.json")
    parser.add_argument("--recent-window-days", type=int, default=90)
    parser.add_argument("--min-coverage-pct", type=float, default=99.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configs = load_all_configs(Path(args.config_dir))
    run_data_health_loop(
        db_path=Path(args.duckdb_path),
        report_path=Path(args.report_path),
        recent_window_days=args.recent_window_days,
        min_coverage_pct=args.min_coverage_pct,
        max_close_move_bps=configs.risk_policy.auto_halt_on.price_deviation_bps,
        heartbeat_miss_factor=configs.risk_policy.auto_halt_on.loop_heartbeat_miss_factor,
        halt_on_data_gap=configs.risk_policy.auto_halt_on.data_gap,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

