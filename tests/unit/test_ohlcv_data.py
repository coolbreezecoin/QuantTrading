from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from crypto_quant_loop.data.ohlcv import OhlcvClient, fetch_historical_ohlcv
from crypto_quant_loop.data.quality import build_ohlcv_quality_report, save_quality_report
from crypto_quant_loop.data.storage import write_ohlcv_duckdb, write_ohlcv_parquet


class FakeOhlcvClient(OhlcvClient):
    def __init__(self, pages: list[list[list[int | float]]]) -> None:
        self.pages = pages
        self.calls: list[int | None] = []

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[int | float]]:
        del symbol, timeframe, limit
        self.calls.append(since)
        if not self.pages:
            return []
        return self.pages.pop(0)


def test_fetch_historical_ohlcv_pages_and_deduplicates() -> None:
    one_hour = 3_600_000
    client = FakeOhlcvClient(
        pages=[
            [
                [0, 1, 2, 0.5, 1.5, 100],
                [one_hour, 1.5, 2, 1, 1.8, 120],
            ],
            [
                [one_hour, 1.5, 2, 1, 1.8, 120],
                [one_hour * 2, 1.8, 2.2, 1.7, 2.0, 90],
            ],
            [],
        ]
    )

    bars = fetch_historical_ohlcv(
        client=client,
        exchange="binance",
        symbol="BTCUSDT",
        timeframe="1h",
        since_ms=0,
        until_ms=one_hour * 4,
        retry_sleep_s=0,
    )

    assert [bar.timestamp_ms for bar in bars] == [0, one_hour, one_hour * 2]
    assert client.calls == [0, one_hour * 2, one_hour * 3]


def test_write_parquet_and_duckdb(tmp_path: Path) -> None:
    bars = fetch_historical_ohlcv(
        client=FakeOhlcvClient(
            pages=[
                [
                    [0, 1, 2, 0.5, 1.5, 100],
                    [3_600_000, 1.5, 2, 1, 1.8, 120],
                ],
                [],
            ]
        ),
        exchange="binance",
        symbol="BTCUSDT",
        timeframe="1h",
        since_ms=0,
        until_ms=7_200_000,
        retry_sleep_s=0,
    )

    parquet_paths = write_ohlcv_parquet(bars, tmp_path / "raw")
    db_path = tmp_path / "processed" / "market.duckdb"
    write_ohlcv_duckdb(bars, db_path)
    write_ohlcv_duckdb(bars, db_path)

    assert len(parquet_paths) == 1
    assert pq.ParquetFile(parquet_paths[0]).read().num_rows == 2  # type: ignore[no-untyped-call]
    con = duckdb.connect(str(db_path))
    try:
        row = con.execute("SELECT count(*) FROM ohlcv").fetchone()
        assert row is not None
        assert row[0] == 2
    finally:
        con.close()


def test_quality_report_detects_gap_and_saves(tmp_path: Path) -> None:
    bars = fetch_historical_ohlcv(
        client=FakeOhlcvClient(
            pages=[
                [
                    [0, 1, 2, 0.5, 1.5, 100],
                    [7_200_000, 1.5, 2, 1, 1.8, 120],
                ],
                [],
            ]
        ),
        exchange="binance",
        symbol="BTCUSDT",
        timeframe="1h",
        since_ms=0,
        until_ms=10_800_000,
        retry_sleep_s=0,
    )
    report = build_ohlcv_quality_report(bars, timeframe="1h")
    report_path = tmp_path / "report.json"

    save_quality_report(report, report_path)

    assert report["gap_count"] == 1
    assert report["coverage_pct"] == 66.666667
    assert "BTCUSDT" in report_path.read_text(encoding="utf-8")
