from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import duckdb

from crypto_quant_loop.data.funding import FundingRate, write_funding_rates_duckdb
from crypto_quant_loop.data.orderbook import (
    OrderbookLevel,
    OrderbookSnapshot,
    collect_orderbook_snapshots,
    write_orderbook_snapshots_duckdb,
)


def make_snapshot(timestamp_ms: int) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        exchange="okx",
        symbol="BTCUSDT",
        timestamp_ms=timestamp_ms,
        bids=[OrderbookLevel(price=100.0, amount=1.0)],
        asks=[OrderbookLevel(price=101.0, amount=1.5)],
    )


class FlakyOrderbookSource:
    def __init__(self) -> None:
        self.attempts = 0

    async def stream(self, *, symbol: str, depth: int) -> AsyncIterator[OrderbookSnapshot]:
        del symbol, depth
        self.attempts += 1
        if self.attempts == 1:
            yield make_snapshot(1_000)
            raise ConnectionError("simulated websocket disconnect")
        yield make_snapshot(2_000)


def test_orderbook_snapshot_writes_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "market.duckdb"

    write_orderbook_snapshots_duckdb([make_snapshot(1_000)], db_path)

    con = duckdb.connect(str(db_path))
    try:
        snapshot_count = con.execute("SELECT count(*) FROM orderbook_snapshots").fetchone()
        level_count = con.execute("SELECT count(*) FROM orderbook_levels").fetchone()
        assert snapshot_count is not None
        assert level_count is not None
        assert snapshot_count[0] == 1
        assert level_count[0] == 2
    finally:
        con.close()


def test_orderbook_collector_reconnects_after_disconnect(tmp_path: Path) -> None:
    source = FlakyOrderbookSource()

    result = asyncio.run(
        collect_orderbook_snapshots(
            source=source,
            db_path=tmp_path / "market.duckdb",
            symbol="BTCUSDT",
            depth=20,
            max_snapshots=2,
            reconnect_sleep_s=0,
        )
    )

    assert result.snapshots_written == 2
    assert result.reconnects == 1
    assert source.attempts == 2


def test_funding_rates_are_marked_perp_only(tmp_path: Path) -> None:
    db_path = tmp_path / "market.duckdb"
    write_funding_rates_duckdb(
        [
            FundingRate(
                exchange="okx",
                symbol="BTCUSDT",
                timestamp_ms=1_000,
                rate=0.0001,
                interval_hours=8,
            )
        ],
        str(db_path),
    )

    con = duckdb.connect(str(db_path))
    try:
        row = con.execute("SELECT market_type, rate FROM funding_rates").fetchone()
        assert row is not None
        assert row[0] == "perp_only"
        assert row[1] == 0.0001
    finally:
        con.close()

