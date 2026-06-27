from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from crypto_quant_loop.monitoring import (
    AlertConfig,
    FillFidelityRecord,
    TradeLedgerRecord,
    build_dashboard_snapshot,
    build_fill_fidelity_report,
    send_alert,
    write_fill_fidelity_parquet,
    write_trade_ledger_parquet,
)


def test_alerts_are_disabled_by_default() -> None:
    result = send_alert(AlertConfig(), title="Risk", body="halt")

    assert result["status"] == "alert_disabled"


def test_trade_ledger_and_fill_fidelity_parquet(tmp_path: Path) -> None:
    ledger_path = tmp_path / "trade-ledger.parquet"
    fidelity_path = tmp_path / "fill-fidelity.parquet"
    write_trade_ledger_parquet(
        [
            TradeLedgerRecord(
                signal_id="sig-1",
                order_id="order-1",
                fill_id="fill-1",
                symbol="BTCUSDT",
                side="buy",
                quantity=1,
                price=100,
                realized_pnl=0,
                timestamp_ms=1_000,
            )
        ],
        ledger_path,
    )
    write_fill_fidelity_parquet(
        [
            FillFidelityRecord(
                signal_id="sig-1",
                symbol="BTCUSDT",
                expected_price=100,
                actual_price=101,
                expected_quantity=2,
                actual_quantity=1,
                timestamp_ms=1_000,
            )
        ],
        fidelity_path,
    )

    assert pq.ParquetFile(ledger_path).read().num_rows == 1  # type: ignore[no-untyped-call]
    assert pq.ParquetFile(fidelity_path).read().num_rows == 1  # type: ignore[no-untyped-call]


def test_fill_fidelity_report_and_dashboard_snapshot() -> None:
    records = [
        FillFidelityRecord(
            signal_id="sig-1",
            symbol="BTCUSDT",
            expected_price=100,
            actual_price=101,
            expected_quantity=2,
            actual_quantity=1,
            timestamp_ms=1_000,
        )
    ]
    report = build_fill_fidelity_report(records)
    snapshot = build_dashboard_snapshot(
        data_health={"halt_required": False},
        strategy_status={"approved": 0},
        risk_status={"halt_required": False},
        fill_fidelity=report,
        loop_heartbeats={"risk-sentinel": 1_000},
    )

    assert report["avg_slippage_bps"] == pytest.approx(100.0)
    assert report["avg_fill_quantity_ratio"] == 0.5
    assert snapshot["data_health"]["halt_required"] is False
    assert snapshot["fill_fidelity"]["records"] == 1
