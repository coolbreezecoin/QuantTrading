from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast


@dataclass(frozen=True, order=True)
class OhlcvBar:
    exchange: str
    symbol: str
    timeframe: str
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp_ms / 1000, tz=UTC)


class OhlcvClient(Protocol):
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[int | float]]:
        """Fetch OHLCV rows as [timestamp_ms, open, high, low, close, volume]."""
        ...


class CcxtOhlcvClient:
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
        ccxt_symbol = to_ccxt_symbol(symbol)
        rows = self._exchange.fetch_ohlcv(
            ccxt_symbol,
            timeframe=timeframe,
            since=since,
            limit=limit,
        )
        return cast(list[list[int | float]], rows)


def to_ccxt_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT"
    raise ValueError(f"Unsupported compact symbol format: {symbol}")


def timeframe_to_ms(timeframe: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    unit = timeframe[-1]
    if unit not in units:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return int(timeframe[:-1]) * units[unit]


def normalize_ohlcv_rows(
    *,
    rows: list[list[int | float]],
    exchange: str,
    symbol: str,
    timeframe: str,
) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    for row in rows:
        if len(row) != 6:
            raise ValueError(f"Expected 6 OHLCV columns, got {len(row)}")
        timestamp_ms, open_, high, low, close, volume = row
        bars.append(
            OhlcvBar(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                timestamp_ms=int(timestamp_ms),
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    return bars


def fetch_historical_ohlcv(
    *,
    client: OhlcvClient,
    exchange: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    limit: int = 1000,
    max_retries: int = 3,
    retry_sleep_s: float = 1.0,
) -> list[OhlcvBar]:
    timeframe_ms = timeframe_to_ms(timeframe)
    next_since = since_ms
    seen: set[int] = set()
    bars: list[OhlcvBar] = []

    while next_since < until_ms:
        rows = _fetch_with_retries(
            client=client,
            symbol=symbol,
            timeframe=timeframe,
            since=next_since,
            limit=limit,
            max_retries=max_retries,
            retry_sleep_s=retry_sleep_s,
        )
        if not rows:
            break

        normalized = normalize_ohlcv_rows(
            rows=rows,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
        )
        new_rows = 0
        for bar in sorted(normalized, key=lambda item: item.timestamp_ms):
            if bar.timestamp_ms >= until_ms:
                continue
            if bar.timestamp_ms in seen:
                continue
            seen.add(bar.timestamp_ms)
            bars.append(bar)
            new_rows += 1

        if new_rows == 0:
            break

        last_ts = max(bar.timestamp_ms for bar in normalized)
        next_since = last_ts + timeframe_ms

    return sorted(bars, key=lambda item: item.timestamp_ms)


def _fetch_with_retries(
    *,
    client: OhlcvClient,
    symbol: str,
    timeframe: str,
    since: int,
    limit: int,
    max_retries: int,
    retry_sleep_s: float,
) -> list[list[int | float]]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return client.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        except Exception as exc:  # pragma: no cover - exact ccxt error types vary by exchange
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(retry_sleep_s * (2**attempt))
    raise RuntimeError(f"Failed to fetch OHLCV for {symbol} after retries") from last_error


def bars_to_rows(bars: list[OhlcvBar]) -> list[dict[str, Any]]:
    return [
        {
            "exchange": bar.exchange,
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "timestamp_ms": bar.timestamp_ms,
            "timestamp": bar.timestamp,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in bars
    ]
