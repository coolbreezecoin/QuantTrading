from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class FillFidelityRecord:
    signal_id: str
    symbol: str
    expected_price: float
    actual_price: float
    expected_quantity: float
    actual_quantity: float
    timestamp_ms: int

    @property
    def slippage_bps(self) -> float:
        return ((self.actual_price / self.expected_price) - 1.0) * 10_000

    @property
    def fill_quantity_ratio(self) -> float:
        if self.expected_quantity == 0:
            return 0.0
        return self.actual_quantity / self.expected_quantity


def build_fill_fidelity_report(records: list[FillFidelityRecord]) -> dict[str, Any]:
    if not records:
        return {
            "records": 0,
            "avg_slippage_bps": 0.0,
            "max_abs_slippage_bps": 0.0,
            "avg_fill_quantity_ratio": 0.0,
        }
    slippage = [record.slippage_bps for record in records]
    ratios = [record.fill_quantity_ratio for record in records]
    return {
        "records": len(records),
        "avg_slippage_bps": sum(slippage) / len(slippage),
        "max_abs_slippage_bps": max(abs(value) for value in slippage),
        "avg_fill_quantity_ratio": sum(ratios) / len(ratios),
    }


def write_fill_fidelity_parquet(records: list[FillFidelityRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            **asdict(record),
            "slippage_bps": record.slippage_bps,
            "fill_quantity_ratio": record.fill_quantity_ratio,
        }
        for record in records
    ]
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)  # type: ignore[no-untyped-call]
