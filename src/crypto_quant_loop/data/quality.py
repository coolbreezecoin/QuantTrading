from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crypto_quant_loop.data.ohlcv import OhlcvBar, timeframe_to_ms


def build_ohlcv_quality_report(bars: list[OhlcvBar], *, timeframe: str) -> dict[str, Any]:
    if not bars:
        return {
            "exchange": None,
            "symbol": None,
            "timeframe": timeframe,
            "bars": 0,
            "start": None,
            "end": None,
            "duplicate_timestamps": 0,
            "gap_count": 0,
            "coverage_pct": 0.0,
        }

    ordered = sorted(bars, key=lambda item: item.timestamp_ms)
    timestamps = [bar.timestamp_ms for bar in ordered]
    duplicate_count = len(timestamps) - len(set(timestamps))
    timeframe_ms = timeframe_to_ms(timeframe)
    expected_slots = ((timestamps[-1] - timestamps[0]) // timeframe_ms) + 1
    gap_count = max(int(expected_slots) - len(set(timestamps)), 0)
    coverage_pct = (len(set(timestamps)) / expected_slots) * 100 if expected_slots else 0.0

    first = ordered[0]
    last = ordered[-1]
    return {
        "exchange": first.exchange,
        "symbol": first.symbol,
        "timeframe": timeframe,
        "bars": len(ordered),
        "start": first.timestamp.isoformat(),
        "end": last.timestamp.isoformat(),
        "duplicate_timestamps": duplicate_count,
        "gap_count": gap_count,
        "coverage_pct": round(coverage_pct, 6),
    }


def save_quality_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

