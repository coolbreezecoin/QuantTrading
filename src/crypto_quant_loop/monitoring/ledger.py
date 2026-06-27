from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class TradeLedgerRecord:
    signal_id: str
    order_id: str
    fill_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    realized_pnl: float
    timestamp_ms: int


def write_trade_ledger_parquet(records: list[TradeLedgerRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([asdict(record) for record in records])
    pq.write_table(table, path)  # type: ignore[no-untyped-call]
