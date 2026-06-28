from __future__ import annotations

import importlib
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import duckdb

from crypto_quant_loop.data.funding import FundingRate
from crypto_quant_loop.data.ohlcv import OhlcvBar, timeframe_to_ms


@dataclass(frozen=True, order=True)
class BasisSample:
    exchange: str
    symbol: str
    timestamp_ms: int
    spot_price: float
    perp_mark_price: float
    basis_quote: float
    basis_bps: float
    source: str = "perp_mark_minus_spot"

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=UTC)


class FundingHistoryClient(Protocol):
    def fetch_funding_rate_history(
        self,
        symbol: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[Mapping[str, object]]:
        """Fetch ccxt-shaped funding rows for a perpetual contract."""
        ...


class CcxtFundingHistoryClient:
    def __init__(
        self,
        exchange_id: str,
        *,
        enable_rate_limit: bool = True,
        timeout_ms: int = 10_000,
    ) -> None:
        ccxt_module = importlib.import_module("ccxt")
        exchange_factory = getattr(ccxt_module, exchange_id)
        self._exchange = exchange_factory(
            {
                "enableRateLimit": enable_rate_limit,
                "timeout": timeout_ms,
            }
        )

    def fetch_funding_rate_history(
        self,
        symbol: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[Mapping[str, object]]:
        rows = self._exchange.fetch_funding_rate_history(
            to_ccxt_perp_symbol(symbol),
            since=since,
            limit=limit,
        )
        return cast(list[Mapping[str, object]], rows)


class CcxtPerpMarkOhlcvClient:
    def __init__(
        self,
        exchange_id: str,
        *,
        enable_rate_limit: bool = True,
        timeout_ms: int = 10_000,
    ) -> None:
        ccxt_module = importlib.import_module("ccxt")
        exchange_factory = getattr(ccxt_module, exchange_id)
        self._exchange = exchange_factory(
            {
                "enableRateLimit": enable_rate_limit,
                "timeout": timeout_ms,
            }
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[int | float]]:
        rows = self._exchange.fetch_ohlcv(
            to_ccxt_perp_symbol(symbol),
            timeframe=timeframe,
            since=since,
            limit=limit,
            params={"price": "mark"},
        )
        return coerce_mark_ohlcv_rows(cast(Sequence[Sequence[object]], rows))


def to_ccxt_perp_symbol(symbol: str) -> str:
    if ":" in symbol:
        return symbol
    if "/" in symbol:
        base, quote_part = symbol.split("/", 1)
        quote = quote_part.split(":", 1)[0]
        return f"{base}/{quote}:{quote}"
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT:USDT"
    raise ValueError(f"Unsupported perp symbol format: {symbol}")


def coerce_mark_ohlcv_rows(rows: Sequence[Sequence[object]]) -> list[list[int | float]]:
    normalized: list[list[int | float]] = []
    for row in rows:
        if len(row) != 6:
            raise ValueError(f"Expected 6 mark OHLCV columns, got {len(row)}")
        timestamp_ms, open_, high, low, close, volume = row
        normalized.append(
            [
                int(_numeric_value(timestamp_ms)),
                _numeric_value(open_),
                _numeric_value(high),
                _numeric_value(low),
                _numeric_value(close),
                0.0 if volume is None else _numeric_value(volume),
            ]
        )
    return normalized


def normalize_funding_rate_rows(
    *,
    rows: Sequence[Mapping[str, object]],
    exchange: str,
    symbol: str,
    interval_hours: float = 8.0,
) -> list[FundingRate]:
    rates: list[FundingRate] = []
    for row in rows:
        timestamp = _required_number(row, ("timestamp", "fundingTimestamp"))
        rate = _funding_rate_value(row)
        rates.append(
            FundingRate(
                exchange=exchange,
                symbol=symbol,
                timestamp_ms=int(timestamp),
                rate=float(rate),
                interval_hours=interval_hours,
            )
        )
    return rates


def fetch_historical_funding_rates(
    *,
    client: FundingHistoryClient,
    exchange: str,
    symbol: str,
    since_ms: int,
    until_ms: int,
    interval_hours: float = 8.0,
    limit: int = 100,
    max_retries: int = 3,
    retry_sleep_s: float = 1.0,
) -> list[FundingRate]:
    next_since = since_ms
    seen: set[int] = set()
    rates: list[FundingRate] = []

    while next_since < until_ms:
        rows = _fetch_funding_with_retries(
            client=client,
            symbol=symbol,
            since=next_since,
            limit=limit,
            max_retries=max_retries,
            retry_sleep_s=retry_sleep_s,
        )
        if not rows:
            break

        normalized = normalize_funding_rate_rows(
            rows=rows,
            exchange=exchange,
            symbol=symbol,
            interval_hours=interval_hours,
        )
        new_rows = 0
        for rate in sorted(normalized, key=lambda item: item.timestamp_ms):
            if rate.timestamp_ms >= until_ms:
                continue
            if rate.timestamp_ms in seen:
                continue
            seen.add(rate.timestamp_ms)
            rates.append(rate)
            new_rows += 1

        if new_rows == 0:
            break

        next_since = max(rate.timestamp_ms for rate in normalized) + 1

    return sorted(rates, key=lambda item: item.timestamp_ms)


def derive_basis_samples(
    *,
    spot_bars: Sequence[OhlcvBar],
    perp_mark_bars: Sequence[OhlcvBar],
    exchange: str,
    symbol: str,
) -> list[BasisSample]:
    spot_by_timestamp = {
        bar.timestamp_ms: bar.close
        for bar in sorted(spot_bars, key=lambda item: item.timestamp_ms)
    }
    mark_by_timestamp = {
        bar.timestamp_ms: bar.close
        for bar in sorted(perp_mark_bars, key=lambda item: item.timestamp_ms)
    }
    samples: list[BasisSample] = []
    for timestamp_ms in sorted(set(spot_by_timestamp) & set(mark_by_timestamp)):
        spot_price = spot_by_timestamp[timestamp_ms]
        mark_price = mark_by_timestamp[timestamp_ms]
        if spot_price <= 0 or mark_price <= 0:
            continue
        basis_quote = mark_price - spot_price
        samples.append(
            BasisSample(
                exchange=exchange,
                symbol=symbol,
                timestamp_ms=timestamp_ms,
                spot_price=spot_price,
                perp_mark_price=mark_price,
                basis_quote=basis_quote,
                basis_bps=(basis_quote / spot_price) * 10_000,
            )
        )
    return samples


def write_basis_samples_duckdb(samples: Sequence[BasisSample], db_path: str | Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS basis_samples (
                exchange VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                timestamp_ms BIGINT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                spot_price DOUBLE NOT NULL,
                perp_mark_price DOUBLE NOT NULL,
                basis_quote DOUBLE NOT NULL,
                basis_bps DOUBLE NOT NULL,
                source VARCHAR NOT NULL,
                PRIMARY KEY (exchange, symbol, timestamp_ms)
            )
            """
        )
        for sample in samples:
            con.execute(
                """
                INSERT OR REPLACE INTO basis_samples
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    sample.exchange,
                    sample.symbol,
                    sample.timestamp_ms,
                    sample.timestamp,
                    sample.spot_price,
                    sample.perp_mark_price,
                    sample.basis_quote,
                    sample.basis_bps,
                    sample.source,
                ],
            )
    finally:
        con.close()


def load_funding_rates_from_duckdb(db_path: str | Path) -> list[FundingRate]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        if not _table_exists(con, "funding_rates"):
            return []
        rows = con.execute(
            """
            SELECT exchange, symbol, timestamp_ms, rate, interval_hours, market_type
            FROM funding_rates
            ORDER BY exchange, symbol, timestamp_ms
            """
        ).fetchall()
    finally:
        con.close()

    return [
        FundingRate(
            exchange=str(exchange),
            symbol=str(symbol),
            timestamp_ms=int(timestamp_ms),
            rate=float(rate),
            interval_hours=float(interval_hours),
            market_type="perp_only",
        )
        for exchange, symbol, timestamp_ms, rate, interval_hours, market_type in rows
    ]


def load_basis_samples_from_duckdb(db_path: str | Path) -> list[BasisSample]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        if not _table_exists(con, "basis_samples"):
            return []
        rows = con.execute(
            """
            SELECT
                exchange, symbol, timestamp_ms, spot_price, perp_mark_price,
                basis_quote, basis_bps, source
            FROM basis_samples
            ORDER BY exchange, symbol, timestamp_ms
            """
        ).fetchall()
    finally:
        con.close()

    return [
        BasisSample(
            exchange=str(exchange),
            symbol=str(symbol),
            timestamp_ms=int(timestamp_ms),
            spot_price=float(spot_price),
            perp_mark_price=float(perp_mark_price),
            basis_quote=float(basis_quote),
            basis_bps=float(basis_bps),
            source=str(source),
        )
        for (
            exchange,
            symbol,
            timestamp_ms,
            spot_price,
            perp_mark_price,
            basis_quote,
            basis_bps,
            source,
        ) in rows
    ]


def build_funding_quality_report(
    rates: Sequence[FundingRate],
    *,
    interval_hours: float = 8.0,
) -> dict[str, Any]:
    if not rates:
        return _empty_quality_report(kind="funding_rate", cadence="8h")

    ordered = sorted(rates, key=lambda item: item.timestamp_ms)
    timestamps = [rate.timestamp_ms for rate in ordered]
    unique_timestamps = set(timestamps)
    interval_ms = int(interval_hours * 3_600_000)
    expected_slots = ((max(unique_timestamps) - min(unique_timestamps)) // interval_ms) + 1
    duplicate_count = len(timestamps) - len(unique_timestamps)
    gap_count = max(int(expected_slots) - len(unique_timestamps), 0)
    coverage_pct = (len(unique_timestamps) / expected_slots) * 100 if expected_slots else 0.0
    positive_count = sum(1 for rate in ordered if rate.rate > 0)
    first = ordered[0]
    last = ordered[-1]
    return {
        "kind": "funding_rate",
        "exchange": first.exchange,
        "symbol": first.symbol,
        "cadence": f"{interval_hours:g}h",
        "records": len(ordered),
        "start": first.timestamp.isoformat(),
        "end": last.timestamp.isoformat(),
        "duplicate_timestamps": duplicate_count,
        "gap_count": gap_count,
        "coverage_pct": round(coverage_pct, 6),
        "positive_rate_pct": round((positive_count / len(ordered)) * 100, 6),
        "average_rate_bps": round(_average(rate.rate for rate in ordered) * 10_000, 8),
        "historical_backfillable": True,
        "forward_only": False,
    }


def build_basis_quality_report(
    samples: Sequence[BasisSample],
    *,
    timeframe: str,
) -> dict[str, Any]:
    if not samples:
        return _empty_quality_report(kind="basis", cadence=timeframe)

    ordered = sorted(samples, key=lambda item: item.timestamp_ms)
    timestamps = [sample.timestamp_ms for sample in ordered]
    unique_timestamps = set(timestamps)
    timeframe_ms = timeframe_to_ms(timeframe)
    expected_slots = ((max(unique_timestamps) - min(unique_timestamps)) // timeframe_ms) + 1
    duplicate_count = len(timestamps) - len(unique_timestamps)
    gap_count = max(int(expected_slots) - len(unique_timestamps), 0)
    coverage_pct = (len(unique_timestamps) / expected_slots) * 100 if expected_slots else 0.0
    first = ordered[0]
    last = ordered[-1]
    return {
        "kind": "basis",
        "exchange": first.exchange,
        "symbol": first.symbol,
        "cadence": timeframe,
        "records": len(ordered),
        "start": first.timestamp.isoformat(),
        "end": last.timestamp.isoformat(),
        "duplicate_timestamps": duplicate_count,
        "gap_count": gap_count,
        "coverage_pct": round(coverage_pct, 6),
        "average_basis_bps": round(_average(sample.basis_bps for sample in ordered), 8),
        "max_abs_basis_bps": round(max(abs(sample.basis_bps) for sample in ordered), 8),
        "historical_backfillable": True,
        "forward_only": False,
    }


def build_structural_quality_report(
    *,
    funding_rates: Sequence[FundingRate],
    basis_samples: Sequence[BasisSample],
    funding_interval_hours: float = 8.0,
    basis_timeframe: str = "1h",
) -> dict[str, Any]:
    funding_groups = _group_funding_rates(funding_rates)
    basis_groups = _group_basis_samples(basis_samples)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "research_only_structural_edge",
        "data_health_hook": "run_structural_data_health_loop",
        "backfill_capabilities": {
            "funding_rate_history": "historical_public_endpoint",
            "perp_mark_ohlcv": "historical_public_endpoint",
            "spot_ohlcv": "historical_public_endpoint",
            "l2_orderbook_depth": "forward_only_not_backfilled",
            "open_interest": "optional_not_collected_in_F1",
        },
        "funding_reports": [
            build_funding_quality_report(group, interval_hours=funding_interval_hours)
            for group in funding_groups.values()
        ],
        "basis_reports": [
            build_basis_quality_report(group, timeframe=basis_timeframe)
            for group in basis_groups.values()
        ],
    }


def save_structural_quality_report(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def run_structural_data_health_loop(
    *,
    db_path: Path,
    report_path: Path,
    funding_interval_hours: float = 8.0,
    basis_timeframe: str = "1h",
) -> dict[str, Any]:
    report = build_structural_quality_report(
        funding_rates=load_funding_rates_from_duckdb(db_path),
        basis_samples=load_basis_samples_from_duckdb(db_path),
        funding_interval_hours=funding_interval_hours,
        basis_timeframe=basis_timeframe,
    )
    save_structural_quality_report(report, report_path)
    return report


def _fetch_funding_with_retries(
    *,
    client: FundingHistoryClient,
    symbol: str,
    since: int,
    limit: int,
    max_retries: int,
    retry_sleep_s: float,
) -> list[Mapping[str, object]]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return client.fetch_funding_rate_history(symbol, since=since, limit=limit)
        except Exception as exc:  # pragma: no cover - exact ccxt errors vary by exchange
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(retry_sleep_s * (2**attempt))
    raise RuntimeError(f"Failed to fetch funding rates for {symbol} after retries") from last_error


def _funding_rate_value(row: Mapping[str, object]) -> float:
    value = _optional_number(row, ("fundingRate", "rate", "funding_rate"))
    if value is not None:
        return value
    info = row.get("info")
    if isinstance(info, Mapping):
        nested = _optional_number(info, ("fundingRate", "funding_rate", "funding_rate_rate"))
        if nested is not None:
            return nested
    raise ValueError("Funding row is missing fundingRate/rate")


def _required_number(row: Mapping[str, object], keys: Sequence[str]) -> float:
    value = _optional_number(row, keys)
    if value is None:
        key_list = ", ".join(keys)
        raise ValueError(f"Funding row is missing required numeric field: {key_list}")
    return value


def _optional_number(row: Mapping[str, object], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _numeric_value(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise ValueError(f"Expected numeric value, got {type(value).__name__}")


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def _empty_quality_report(*, kind: str, cadence: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "exchange": None,
        "symbol": None,
        "cadence": cadence,
        "records": 0,
        "start": None,
        "end": None,
        "duplicate_timestamps": 0,
        "gap_count": 0,
        "coverage_pct": 0.0,
        "historical_backfillable": kind in {"funding_rate", "basis"},
        "forward_only": False,
    }


def _group_funding_rates(
    rates: Sequence[FundingRate],
) -> dict[tuple[str, str], list[FundingRate]]:
    groups: dict[tuple[str, str], list[FundingRate]] = {}
    for rate in rates:
        groups.setdefault((rate.exchange, rate.symbol), []).append(rate)
    return groups


def _group_basis_samples(
    samples: Sequence[BasisSample],
) -> dict[tuple[str, str], list[BasisSample]]:
    groups: dict[tuple[str, str], list[BasisSample]] = {}
    for sample in samples:
        groups.setdefault((sample.exchange, sample.symbol), []).append(sample)
    return groups


def _average(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def basis_sample_to_dict(sample: BasisSample) -> dict[str, Any]:
    return asdict(sample) | {"timestamp": sample.timestamp.isoformat()}
