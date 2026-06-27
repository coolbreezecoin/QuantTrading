from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import duckdb


@dataclass(frozen=True)
class OrderbookLevel:
    price: float
    amount: float


@dataclass(frozen=True)
class OrderbookSnapshot:
    exchange: str
    symbol: str
    timestamp_ms: int
    bids: list[OrderbookLevel]
    asks: list[OrderbookLevel]


class OrderbookSource(Protocol):
    def stream(self, *, symbol: str, depth: int) -> AsyncIterator[OrderbookSnapshot]:
        """Return a forward-only websocket-style stream of orderbook snapshots."""
        ...


@dataclass(frozen=True)
class CollectorResult:
    snapshots_written: int
    reconnects: int


async def collect_orderbook_snapshots(
    *,
    source: OrderbookSource,
    db_path: Path,
    symbol: str,
    depth: int,
    max_snapshots: int,
    max_reconnects: int = 3,
    reconnect_sleep_s: float = 1.0,
) -> CollectorResult:
    snapshots_written = 0
    reconnects = 0

    while snapshots_written < max_snapshots:
        try:
            async for snapshot in source.stream(symbol=symbol, depth=depth):
                write_orderbook_snapshots_duckdb([snapshot], db_path)
                snapshots_written += 1
                if snapshots_written >= max_snapshots:
                    return CollectorResult(snapshots_written, reconnects)
        except Exception:
            reconnects += 1
            if reconnects > max_reconnects:
                raise
            await asyncio.sleep(reconnect_sleep_s)

    return CollectorResult(snapshots_written, reconnects)


def write_orderbook_snapshots_duckdb(snapshots: list[OrderbookSnapshot], db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        _ensure_orderbook_schema(con)
        for snapshot in snapshots:
            con.execute(
                """
                INSERT OR REPLACE INTO orderbook_snapshots
                VALUES (?, ?, ?)
                """,
                [snapshot.exchange, snapshot.symbol, snapshot.timestamp_ms],
            )
            con.execute(
                """
                DELETE FROM orderbook_levels
                WHERE exchange = ? AND symbol = ? AND timestamp_ms = ?
                """,
                [snapshot.exchange, snapshot.symbol, snapshot.timestamp_ms],
            )
            _write_levels(con, snapshot, "bid", snapshot.bids)
            _write_levels(con, snapshot, "ask", snapshot.asks)
    finally:
        con.close()


def _ensure_orderbook_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS orderbook_snapshots (
            exchange VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            timestamp_ms BIGINT NOT NULL,
            PRIMARY KEY (exchange, symbol, timestamp_ms)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS orderbook_levels (
            exchange VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            timestamp_ms BIGINT NOT NULL,
            side VARCHAR NOT NULL,
            level_index INTEGER NOT NULL,
            price DOUBLE NOT NULL,
            amount DOUBLE NOT NULL,
            PRIMARY KEY (exchange, symbol, timestamp_ms, side, level_index)
        )
        """
    )


def _write_levels(
    con: duckdb.DuckDBPyConnection,
    snapshot: OrderbookSnapshot,
    side: Literal["bid", "ask"],
    levels: list[OrderbookLevel],
) -> None:
    for index, level in enumerate(levels):
        con.execute(
            """
            INSERT INTO orderbook_levels
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                snapshot.exchange,
                snapshot.symbol,
                snapshot.timestamp_ms,
                side,
                index,
                level.price,
                level.amount,
            ],
        )

