from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.data.structural import (
    load_basis_samples_from_duckdb,
    load_funding_rates_from_duckdb,
)
from crypto_quant_loop.research.carry import (
    analyze_carry_feasibility,
    save_carry_feasibility_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Quantify delta-neutral funding carry feasibility before strategy work."
    )
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--duckdb-path", default="data/processed/market.duckdb")
    parser.add_argument("--report-path", default="reports/f2_carry_feasibility.json")
    parser.add_argument("--margin-cost-apr", type=float, default=0.05)
    parser.add_argument(
        "--principal",
        type=float,
        action="append",
        dest="principals",
        help="Principal grid value in quote currency; can be provided multiple times.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configs = load_all_configs(Path(args.config_dir))
    principal_grid = tuple(args.principals or [500.0, 1000.0, 2500.0, 5000.0, 10_000.0])
    report = analyze_carry_feasibility(
        funding_rates=load_funding_rates_from_duckdb(Path(args.duckdb_path)),
        basis_samples=load_basis_samples_from_duckdb(Path(args.duckdb_path)),
        fills=configs.fills,
        risk_policy=configs.risk_policy,
        principal_grid=principal_grid,
        margin_cost_apr=args.margin_cost_apr,
    )
    save_carry_feasibility_report(report, Path(args.report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
