from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from crypto_quant_loop.data.ohlcv import OhlcvBar, timeframe_to_ms


@dataclass(frozen=True)
class DataHealthIssue:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class DataHealthReport:
    exchange: str | None
    symbol: str | None
    timeframe: str
    checked_at: str
    bars_checked: int
    window_start: str | None
    window_end: str | None
    coverage_pct: float
    duplicate_timestamps: int
    gap_count: int
    off_grid_count: int
    abnormal_price_count: int
    stale: bool
    halt_required: bool
    issues: list[DataHealthIssue]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_ohlcv_health(
    bars: list[OhlcvBar],
    *,
    timeframe: str,
    checked_at_ms: int | None = None,
    recent_window_days: int = 90,
    min_coverage_pct: float = 99.0,
    max_close_move_bps: float = 2_000.0,
    heartbeat_miss_factor: float = 3.0,
    halt_on_data_gap: bool = True,
) -> DataHealthReport:
    checked_at = (
        datetime.now(UTC)
        if checked_at_ms is None
        else datetime.fromtimestamp(checked_at_ms / 1000, tz=UTC)
    )
    timeframe_ms = timeframe_to_ms(timeframe)
    window_start_ms = int(checked_at.timestamp() * 1000) - recent_window_days * 86_400_000
    window_bars = [bar for bar in bars if bar.timestamp_ms >= window_start_ms]
    ordered = sorted(window_bars, key=lambda item: item.timestamp_ms)
    issues: list[DataHealthIssue] = []

    if not ordered:
        issues.append(DataHealthIssue("no_data", "critical", "No OHLCV bars in health window"))
        return DataHealthReport(
            exchange=None,
            symbol=None,
            timeframe=timeframe,
            checked_at=checked_at.isoformat(),
            bars_checked=0,
            window_start=None,
            window_end=None,
            coverage_pct=0.0,
            duplicate_timestamps=0,
            gap_count=0,
            off_grid_count=0,
            abnormal_price_count=0,
            stale=True,
            halt_required=halt_on_data_gap,
            issues=issues,
        )

    timestamps = [bar.timestamp_ms for bar in ordered]
    unique_timestamps = set(timestamps)
    duplicate_count = len(timestamps) - len(unique_timestamps)
    expected_slots = ((max(unique_timestamps) - min(unique_timestamps)) // timeframe_ms) + 1
    gap_count = max(int(expected_slots) - len(unique_timestamps), 0)
    coverage_pct = (len(unique_timestamps) / expected_slots) * 100 if expected_slots else 0.0
    off_grid_count = sum(1 for timestamp in unique_timestamps if timestamp % timeframe_ms != 0)
    abnormal_price_count = _count_abnormal_prices(ordered, max_close_move_bps)
    stale = (int(checked_at.timestamp() * 1000) - max(unique_timestamps)) > (
        timeframe_ms * heartbeat_miss_factor
    )

    if duplicate_count:
        issues.append(DataHealthIssue("duplicate_timestamp", "error", "Duplicate OHLCV timestamps"))
    if gap_count:
        issues.append(DataHealthIssue("gap", "critical", "Missing OHLCV bars detected"))
    if coverage_pct < min_coverage_pct:
        issues.append(
            DataHealthIssue(
                "coverage_below_threshold",
                "critical",
                f"Coverage {coverage_pct:.4f}% below {min_coverage_pct:.4f}%",
            )
        )
    if off_grid_count:
        issues.append(DataHealthIssue("off_grid_timestamp", "error", "Timestamp not aligned"))
    if abnormal_price_count:
        issues.append(DataHealthIssue("abnormal_price", "error", "Invalid OHLC or extreme move"))
    if stale:
        issues.append(DataHealthIssue("stale_data", "critical", "Latest OHLCV bar is stale"))

    halt_required = halt_on_data_gap and (gap_count > 0 or coverage_pct < min_coverage_pct or stale)
    first = ordered[0]
    last = ordered[-1]
    return DataHealthReport(
        exchange=first.exchange,
        symbol=first.symbol,
        timeframe=timeframe,
        checked_at=checked_at.isoformat(),
        bars_checked=len(ordered),
        window_start=first.timestamp.isoformat(),
        window_end=last.timestamp.isoformat(),
        coverage_pct=round(coverage_pct, 6),
        duplicate_timestamps=duplicate_count,
        gap_count=gap_count,
        off_grid_count=off_grid_count,
        abnormal_price_count=abnormal_price_count,
        stale=stale,
        halt_required=halt_required,
        issues=issues,
    )


def _count_abnormal_prices(bars: list[OhlcvBar], max_close_move_bps: float) -> int:
    count = 0
    previous_close: float | None = None
    for bar in bars:
        invalid_ohlc = (
            bar.open <= 0
            or bar.high <= 0
            or bar.low <= 0
            or bar.close <= 0
            or bar.volume < 0
            or bar.high < bar.low
            or not (bar.low <= bar.open <= bar.high)
            or not (bar.low <= bar.close <= bar.high)
        )
        if invalid_ohlc:
            count += 1
            previous_close = bar.close
            continue
        if previous_close is not None:
            move_bps = abs((bar.close / previous_close) - 1.0) * 10_000
            if move_bps > max_close_move_bps:
                count += 1
        previous_close = bar.close
    return count


def run_data_health_loop(
    *,
    db_path: Path,
    report_path: Path,
    checked_at_ms: int | None = None,
    recent_window_days: int = 90,
    min_coverage_pct: float = 99.0,
    max_close_move_bps: float = 2_000.0,
    heartbeat_miss_factor: float = 3.0,
    halt_on_data_gap: bool = True,
) -> dict[str, Any]:
    groups = load_ohlcv_groups_from_duckdb(db_path)
    reports = [
        evaluate_ohlcv_health(
            bars,
            timeframe=timeframe,
            checked_at_ms=checked_at_ms,
            recent_window_days=recent_window_days,
            min_coverage_pct=min_coverage_pct,
            max_close_move_bps=max_close_move_bps,
            heartbeat_miss_factor=heartbeat_miss_factor,
            halt_on_data_gap=halt_on_data_gap,
        ).to_dict()
        for (_exchange, _symbol, timeframe), bars in groups.items()
    ]
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "halt_required": any(report["halt_required"] for report in reports),
        "reports": reports,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def load_ohlcv_groups_from_duckdb(db_path: Path) -> dict[tuple[str, str, str], list[OhlcvBar]]:
    if not db_path.exists():
        raise FileNotFoundError(f"DuckDB database not found: {db_path}")

    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT exchange, symbol, timeframe, timestamp_ms, open, high, low, close, volume
            FROM ohlcv
            ORDER BY exchange, symbol, timeframe, timestamp_ms
            """
        ).fetchall()
    finally:
        con.close()

    groups: dict[tuple[str, str, str], list[OhlcvBar]] = {}
    for row in rows:
        exchange, symbol, timeframe, timestamp_ms, open_, high, low, close, volume = row
        key = (str(exchange), str(symbol), str(timeframe))
        groups.setdefault(key, []).append(
            OhlcvBar(
                exchange=str(exchange),
                symbol=str(symbol),
                timeframe=str(timeframe),
                timestamp_ms=int(timestamp_ms),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    return groups
