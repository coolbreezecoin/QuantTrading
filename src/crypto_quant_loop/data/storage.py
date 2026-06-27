from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from crypto_quant_loop.data.ohlcv import OhlcvBar, bars_to_rows

OHLCV_SCHEMA = pa.schema(
    [
        ("exchange", pa.string()),
        ("symbol", pa.string()),
        ("timeframe", pa.string()),
        ("timestamp_ms", pa.int64()),
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("volume", pa.float64()),
    ]
)


def bars_to_table(bars: list[OhlcvBar]) -> pa.Table:
    return pa.Table.from_pylist(bars_to_rows(bars), schema=OHLCV_SCHEMA)


def write_ohlcv_parquet(bars: list[OhlcvBar], root: Path) -> list[Path]:
    if not bars:
        return []

    written: list[Path] = []
    groups: dict[tuple[str, str, str], list[OhlcvBar]] = {}
    for bar in bars:
        groups.setdefault((bar.exchange, bar.symbol, bar.timeframe), []).append(bar)

    for (exchange, symbol, timeframe), group_bars in groups.items():
        output_dir = root / f"exchange={exchange}" / f"symbol={symbol}" / f"timeframe={timeframe}"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "ohlcv.parquet"
        pq.write_table(  # type: ignore[no-untyped-call]
            bars_to_table(sorted(group_bars, key=lambda item: item.timestamp_ms)),
            output_path,
        )
        written.append(output_path)

    return written


def write_ohlcv_duckdb(bars: list[OhlcvBar], db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv (
                exchange VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                timestamp_ms BIGINT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume DOUBLE NOT NULL,
                PRIMARY KEY (exchange, symbol, timeframe, timestamp_ms)
            )
            """
        )
        if not bars:
            return

        table = bars_to_table(bars)
        con.register("incoming_ohlcv", table)
        con.execute(
            """
            INSERT OR REPLACE INTO ohlcv
            SELECT
                exchange, symbol, timeframe, timestamp_ms, timestamp,
                open, high, low, close, volume
            FROM incoming_ohlcv
            """
        )
    finally:
        con.close()
