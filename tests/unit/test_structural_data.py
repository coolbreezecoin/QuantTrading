from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import duckdb

from crypto_quant_loop.data.funding import FundingRate, write_funding_rates_duckdb
from crypto_quant_loop.data.ohlcv import OhlcvBar
from crypto_quant_loop.data.structural import (
    BasisSample,
    FundingHistoryClient,
    build_structural_quality_report,
    coerce_mark_ohlcv_rows,
    derive_basis_samples,
    fetch_historical_funding_rates,
    load_basis_samples_from_duckdb,
    run_structural_data_health_loop,
    to_ccxt_perp_symbol,
    write_basis_samples_duckdb,
)


class FakeFundingClient(FundingHistoryClient):
    def __init__(self, pages: list[list[dict[str, object]]]) -> None:
        self.pages = pages
        self.calls: list[int | None] = []

    def fetch_funding_rate_history(
        self,
        symbol: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[Mapping[str, object]]:
        del symbol, limit
        self.calls.append(since)
        if not self.pages:
            return []
        return cast(list[Mapping[str, object]], self.pages.pop(0))


def make_bar(timestamp_ms: int, close: float, symbol: str = "BTCUSDT") -> OhlcvBar:
    return OhlcvBar(
        exchange="okx",
        symbol=symbol,
        timeframe="1h",
        timestamp_ms=timestamp_ms,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10,
    )


def test_perp_symbol_conversion_uses_linear_swap_format() -> None:
    assert to_ccxt_perp_symbol("BTCUSDT") == "BTC/USDT:USDT"
    assert to_ccxt_perp_symbol("ETH/USDT") == "ETH/USDT:USDT"
    assert to_ccxt_perp_symbol("SOL/USDT:USDT") == "SOL/USDT:USDT"


def test_mark_ohlcv_adapter_allows_missing_volume() -> None:
    rows = coerce_mark_ohlcv_rows([[1_000, "100", 101, 99, 100.5, None]])

    assert rows == [[1_000, 100.0, 101.0, 99.0, 100.5, 0.0]]


def test_fetch_historical_funding_rates_pages_and_deduplicates() -> None:
    eight_hours = 8 * 3_600_000
    client = FakeFundingClient(
        pages=[
            [
                {"timestamp": 0, "fundingRate": "0.0001"},
                {"timestamp": eight_hours, "fundingRate": 0.0002},
            ],
            [
                {"timestamp": eight_hours, "fundingRate": 0.0002},
                {"timestamp": eight_hours * 2, "rate": -0.00005},
            ],
        ]
    )

    rates = fetch_historical_funding_rates(
        client=client,
        exchange="okx",
        symbol="BTCUSDT",
        since_ms=0,
        until_ms=(eight_hours * 2) + 1,
        retry_sleep_s=0,
    )

    assert [rate.timestamp_ms for rate in rates] == [0, eight_hours, eight_hours * 2]
    assert [rate.rate for rate in rates] == [0.0001, 0.0002, -0.00005]
    assert client.calls == [0, eight_hours + 1]
    assert all(rate.market_type == "perp_only" for rate in rates)


def test_derive_basis_samples_aligns_spot_and_mark() -> None:
    samples = derive_basis_samples(
        spot_bars=[make_bar(0, 100), make_bar(3_600_000, 110)],
        perp_mark_bars=[make_bar(0, 101), make_bar(7_200_000, 120)],
        exchange="okx",
        symbol="BTCUSDT",
    )

    assert len(samples) == 1
    assert samples[0].timestamp_ms == 0
    assert samples[0].basis_quote == 1
    assert samples[0].basis_bps == 100


def test_basis_samples_write_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "market.duckdb"
    sample = BasisSample(
        exchange="okx",
        symbol="BTCUSDT",
        timestamp_ms=0,
        spot_price=100,
        perp_mark_price=101,
        basis_quote=1,
        basis_bps=100,
    )

    write_basis_samples_duckdb([sample], db_path)
    write_basis_samples_duckdb([sample], db_path)

    con = duckdb.connect(str(db_path))
    try:
        row = con.execute("SELECT count(*), avg(basis_bps) FROM basis_samples").fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == 100
    finally:
        con.close()
    assert load_basis_samples_from_duckdb(db_path)[0].basis_quote == 1


def test_structural_quality_report_marks_backfillable_and_gaps() -> None:
    eight_hours = 8 * 3_600_000
    report = build_structural_quality_report(
        funding_rates=[
            FundingRate("okx", "BTCUSDT", 0, 0.0001, 8),
            FundingRate("okx", "BTCUSDT", eight_hours * 2, 0.0002, 8),
        ],
        basis_samples=[
            BasisSample("okx", "BTCUSDT", 0, 100, 101, 1, 100),
            BasisSample("okx", "BTCUSDT", 7_200_000, 100, 99, -1, -100),
        ],
        basis_timeframe="1h",
    )

    funding_report = report["funding_reports"][0]
    basis_report = report["basis_reports"][0]
    assert funding_report["gap_count"] == 1
    assert funding_report["coverage_pct"] == 66.666667
    assert basis_report["gap_count"] == 1
    assert report["backfill_capabilities"]["l2_orderbook_depth"] == "forward_only_not_backfilled"


def test_structural_data_health_loop_reads_duckdb_and_writes_report(tmp_path: Path) -> None:
    db_path = tmp_path / "market.duckdb"
    report_path = tmp_path / "structural_health.json"
    write_funding_rates_duckdb(
        [FundingRate("okx", "BTCUSDT", 0, 0.0001, 8)],
        db_path,
    )
    write_basis_samples_duckdb(
        [BasisSample("okx", "BTCUSDT", 0, 100, 101, 1, 100)],
        db_path,
    )

    payload = run_structural_data_health_loop(db_path=db_path, report_path=report_path)
    saved = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["funding_reports"][0]["symbol"] == "BTCUSDT"
    assert saved["basis_reports"][0]["average_basis_bps"] == 100
