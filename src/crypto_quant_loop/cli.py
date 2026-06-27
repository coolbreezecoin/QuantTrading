from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from crypto_quant_loop.loops.empty_loop import EmptyLoopConfig, run_empty_loop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run crypto-quant-loop utilities.")
    parser.add_argument(
        "--log-path",
        default="loop-run-log.jsonl",
        help="Path to append loop run records.",
    )
    parser.add_argument(
        "--pattern",
        default="empty-loop",
        help="Pattern name to record in the run log.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    run_empty_loop(EmptyLoopConfig(log_path=Path(args.log_path), pattern=args.pattern))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
