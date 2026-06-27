from __future__ import annotations

import json
from pathlib import Path

from crypto_quant_loop.data.health import evaluate_ohlcv_health, run_data_health_loop
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.data.storage import write_ohlcv_duckdb


def make_bar(timestamp_ms: int, close: float = 100.0) -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol="BTCUSDT",
        timeframe="1h",
        timestamp_ms=timestamp_ms,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10,
    )


def test_health_detects_gap_and_halt() -> None:
    bars = [make_bar(0), make_bar(7_200_000)]

    report = evaluate_ohlcv_health(
        bars,
        timeframe="1h",
        checked_at_ms=7_200_000,
        recent_window_days=1,
        heartbeat_miss_factor=10,
        halt_on_data_gap=True,
    )

    assert report.gap_count == 1
    assert report.coverage_pct == 66.666667
    assert report.halt_required is True
    assert any(issue.code == "gap" for issue in report.issues)


def test_health_detects_duplicate_and_bad_price() -> None:
    bars = [
        make_bar(0),
        make_bar(0),
        OhlcvBar(
            exchange="okx",
            symbol="BTCUSDT",
            timeframe="1h",
            timestamp_ms=3_600_000,
            open=100,
            high=99,
            low=101,
            close=100,
            volume=10,
        ),
    ]

    report = evaluate_ohlcv_health(
        bars,
        timeframe="1h",
        checked_at_ms=3_600_000,
        recent_window_days=1,
        heartbeat_miss_factor=10,
    )

    assert report.duplicate_timestamps == 1
    assert report.abnormal_price_count == 1
    assert any(issue.code == "duplicate_timestamp" for issue in report.issues)
    assert any(issue.code == "abnormal_price" for issue in report.issues)


def test_health_loop_writes_visible_report(tmp_path: Path) -> None:
    bars = [make_bar(0), make_bar(7_200_000)]
    db_path = tmp_path / "market.duckdb"
    report_path = tmp_path / "health.json"
    write_ohlcv_duckdb(bars, db_path)

    payload = run_data_health_loop(
        db_path=db_path,
        report_path=report_path,
        checked_at_ms=7_200_000,
        recent_window_days=1,
        heartbeat_miss_factor=10,
    )

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["halt_required"] is True
    assert saved["reports"][0]["symbol"] == "BTCUSDT"
    assert saved["reports"][0]["gap_count"] == 1
