from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb


@dataclass(frozen=True)
class FundingRate:
    exchange: str
    symbol: str
    timestamp_ms: int
    rate: float
    interval_hours: float
    market_type: Literal["perp_only"] = "perp_only"

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=UTC)


def write_funding_rates_duckdb(rates: list[FundingRate], db_path: str | Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS funding_rates (
                exchange VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                timestamp_ms BIGINT NOT NULL,
                rate DOUBLE NOT NULL,
                interval_hours DOUBLE NOT NULL,
                market_type VARCHAR NOT NULL,
                PRIMARY KEY (exchange, symbol, timestamp_ms)
            )
            """
        )
        for rate in rates:
            con.execute(
                """
                INSERT OR REPLACE INTO funding_rates
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    rate.exchange,
                    rate.symbol,
                    rate.timestamp_ms,
                    rate.rate,
                    rate.interval_hours,
                    rate.market_type,
                ],
            )
    finally:
        con.close()
