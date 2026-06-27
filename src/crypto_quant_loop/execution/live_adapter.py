from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from crypto_quant_loop.config.models import (
    AllConfigs,
    ExchangeConfig,
    ExchangeDefaultsConfig,
)
from crypto_quant_loop.execution.paper_broker import (
    Fill,
    Order,
    OrderSide,
    OrderType,
    PaperBroker,
    PaperBrokerState,
    PaperPosition,
)
from crypto_quant_loop.strategies.sdk import Signal


class LiveTradingDisabled(RuntimeError):
    """Raised when code tries to bypass the live dry-run scaffold."""


class ExchangeClientProtocol(Protocol):
    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class CcxtClientBuild:
    status: Literal["ready", "missing_credentials"]
    client: ExchangeClientProtocol | None
    missing_env_vars: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProtectiveStopRequest:
    client_order_id: str
    parent_client_order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    stop_price: float
    order_kind: Literal["stop_loss", "oco"] = "stop_loss"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveOrderResult:
    status: Literal["dry_run_recorded", "idempotent_replay", "live_submitted", "rejected"]
    order: Order
    fill: Fill | None
    raw_request: dict[str, Any]
    real_order_reachable: bool


@dataclass(frozen=True)
class ProtectiveStopResult:
    status: Literal["dry_run_recorded", "live_submitted"]
    request: ProtectiveStopRequest
    raw_request: dict[str, Any]
    real_order_reachable: bool


@dataclass(frozen=True)
class LiveSignalExecutionResult:
    order_result: LiveOrderResult
    protective_stop_result: ProtectiveStopResult | None
    reconciliation: ReconciliationReport | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    status: Literal["no_client_available", "reconciled"]
    exchange_open_order_ids: tuple[str, ...]
    local_canceled_order_ids: tuple[str, ...]
    exchange_position_symbols: tuple[str, ...]


class LiveExchangeAdapter:
    def __init__(
        self,
        *,
        exchange_id: str,
        dry_run: bool = True,
        client: ExchangeClientProtocol | None = None,
        state: PaperBrokerState | None = None,
        allow_real_trading: bool = False,
    ) -> None:
        self.exchange_id = exchange_id
        self.dry_run = dry_run
        self.client = client
        self.allow_real_trading = allow_real_trading
        self.state = state or PaperBrokerState()
        self._paper = PaperBroker(self.state)
        self.order_intents: list[dict[str, Any]] = []
        self.protective_stop_intents: list[ProtectiveStopRequest] = []

    def submit_signal(
        self,
        signal: Signal,
        *,
        quantity: float,
        client_order_id: str | None = None,
    ) -> LiveSignalExecutionResult:
        order = Order(
            client_order_id=client_order_id or _signal_client_order_id(signal),
            symbol=signal.symbol,
            side="buy",
            order_type=signal.order_type,
            quantity=quantity,
            limit_price=signal.reference_price if signal.order_type == "limit" else None,
        )
        order_result = self.submit_order(
            order,
            expected_fill_price=signal.reference_price,
            timestamp_ms=signal.timestamp_ms,
        )
        stop_result = None
        if order_result.fill is not None:
            stop_request = build_protective_stop_request(
                entry_order=order_result.order,
                stop_price=signal.stop_price,
            )
            stop_result = self.submit_protective_stop(stop_request)
        return LiveSignalExecutionResult(
            order_result=order_result,
            protective_stop_result=stop_result,
        )

    def submit_order(
        self,
        order: Order,
        *,
        expected_fill_price: float | None = None,
        timestamp_ms: int = 0,
    ) -> LiveOrderResult:
        raw_request = _order_request(order)
        existing = self.state.orders.get(order.client_order_id)
        if existing is not None:
            return LiveOrderResult(
                status="idempotent_replay",
                order=existing,
                fill=None,
                raw_request=raw_request,
                real_order_reachable=False,
            )

        submitted = self._paper.submit_order(order)
        if submitted.status == "rejected":
            return LiveOrderResult(
                status="rejected",
                order=submitted,
                fill=None,
                raw_request=raw_request,
                real_order_reachable=False,
            )

        if self.dry_run:
            self.order_intents.append(raw_request)
            fill = self._record_dry_run_fill(
                submitted,
                expected_fill_price=expected_fill_price,
                timestamp_ms=timestamp_ms,
            )
            return LiveOrderResult(
                status="dry_run_recorded",
                order=submitted,
                fill=fill,
                raw_request=raw_request,
                real_order_reachable=False,
            )

        self._assert_real_trading_allowed()
        if self.client is None:
            raise LiveTradingDisabled("live client unavailable; refusing real order path")
        self.client.create_order(
            order.symbol,
            order.order_type,
            order.side,
            order.quantity,
            order.limit_price,
            params=_client_order_params(order.client_order_id),
        )
        return LiveOrderResult(
            status="live_submitted",
            order=submitted,
            fill=None,
            raw_request=raw_request,
            real_order_reachable=True,
        )

    def submit_protective_stop(self, request: ProtectiveStopRequest) -> ProtectiveStopResult:
        raw_request = _protective_stop_order_request(request)
        if self.dry_run:
            self.protective_stop_intents.append(request)
            return ProtectiveStopResult(
                status="dry_run_recorded",
                request=request,
                raw_request=raw_request,
                real_order_reachable=False,
            )

        self._assert_real_trading_allowed()
        if self.client is None:
            raise LiveTradingDisabled("live client unavailable; refusing stop order path")
        self.client.create_order(
            request.symbol,
            "stop_loss_limit",
            request.side,
            request.quantity,
            request.stop_price,
            params=raw_request["params"],
        )
        return ProtectiveStopResult(
            status="live_submitted",
            request=request,
            raw_request=raw_request,
            real_order_reachable=True,
        )

    def reconcile(self, *, symbols: Sequence[str] | None = None) -> ReconciliationReport:
        if self.client is None:
            return ReconciliationReport(
                status="no_client_available",
                exchange_open_order_ids=(),
                local_canceled_order_ids=(),
                exchange_position_symbols=(),
            )

        exchange_orders = self._fetch_open_orders(symbols)
        exchange_order_ids: set[str] = set()
        for raw_order in exchange_orders:
            order = _order_from_exchange(raw_order)
            exchange_order_ids.add(order.client_order_id)
            self.state.orders[order.client_order_id] = order

        local_canceled: list[str] = []
        for order in self.state.orders.values():
            is_open = order.status in {"open", "partially_filled"}
            if is_open and order.client_order_id not in exchange_order_ids:
                order.status = "canceled"
                local_canceled.append(order.client_order_id)

        positions = self._fetch_positions(symbols)
        self.state.positions = {
            position.symbol: position
            for position in positions
            if position.quantity != 0
        }

        return ReconciliationReport(
            status="reconciled",
            exchange_open_order_ids=tuple(sorted(exchange_order_ids)),
            local_canceled_order_ids=tuple(sorted(local_canceled)),
            exchange_position_symbols=tuple(sorted(self.state.positions)),
        )

    def _record_dry_run_fill(
        self,
        order: Order,
        *,
        expected_fill_price: float | None,
        timestamp_ms: int,
    ) -> Fill | None:
        price = expected_fill_price if expected_fill_price is not None else order.limit_price
        if price is None:
            return None
        fill = Fill(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            timestamp_ms=timestamp_ms,
        )
        self._paper.record_fill(order, fill)
        return fill

    def _fetch_open_orders(self, symbols: Sequence[str] | None) -> list[dict[str, Any]]:
        if symbols is None:
            return self.client.fetch_open_orders() if self.client is not None else []
        output: list[dict[str, Any]] = []
        for symbol in symbols:
            if self.client is not None:
                output.extend(self.client.fetch_open_orders(symbol))
        return output

    def _fetch_positions(self, symbols: Sequence[str] | None) -> list[PaperPosition]:
        if self.client is None:
            return []
        fetch_positions = getattr(self.client, "fetch_positions", None)
        if callable(fetch_positions):
            raw_positions = fetch_positions(list(symbols) if symbols is not None else None)
            return [
                position
                for raw_position in raw_positions
                if (position := _position_from_exchange(raw_position)) is not None
            ]
        return []

    def _assert_real_trading_allowed(self) -> None:
        if not self.allow_real_trading:
            raise LiveTradingDisabled("real trading requires a separate explicit gate")


def build_live_adapter_from_config(
    configs: AllConfigs,
    *,
    exchange_id: str = "binance",
    environ: Mapping[str, str] = os.environ,
    client: ExchangeClientProtocol | None = None,
) -> tuple[LiveExchangeAdapter, CcxtClientBuild]:
    exchange = configs.exchanges.exchanges[exchange_id]
    _validate_exchange_safety(exchange)
    client_build = (
        CcxtClientBuild(status="ready", client=client)
        if client is not None
        else build_ccxt_client(exchange_id, exchange, configs.exchanges.defaults, environ=environ)
    )
    adapter = LiveExchangeAdapter(
        exchange_id=exchange_id,
        dry_run=configs.exchanges.defaults.dry_run,
        client=client_build.client,
    )
    return adapter, client_build


def build_ccxt_client(
    exchange_id: str,
    exchange_config: ExchangeConfig,
    defaults: ExchangeDefaultsConfig,
    *,
    environ: Mapping[str, str] = os.environ,
    ccxt_module: Any | None = None,
) -> CcxtClientBuild:
    env_names = [exchange_config.api_key_env, exchange_config.api_secret_env]
    if exchange_config.api_passphrase_env is not None:
        env_names.append(exchange_config.api_passphrase_env)
    missing = tuple(env_name for env_name in env_names if not environ.get(env_name))
    if missing:
        return CcxtClientBuild(status="missing_credentials", client=None, missing_env_vars=missing)

    module = ccxt_module if ccxt_module is not None else __import__("ccxt")
    factory = getattr(module, exchange_id)
    params: dict[str, Any] = {
        "apiKey": environ[exchange_config.api_key_env],
        "secret": environ[exchange_config.api_secret_env],
        "enableRateLimit": defaults.rate_limit,
        "timeout": defaults.timeout_ms,
        "options": {"recvWindow": defaults.recv_window_ms},
    }
    if exchange_config.api_passphrase_env is not None:
        params["password"] = environ[exchange_config.api_passphrase_env]
    return CcxtClientBuild(status="ready", client=cast(ExchangeClientProtocol, factory(params)))


def _validate_exchange_safety(exchange_config: ExchangeConfig) -> None:
    if exchange_config.permissions.withdraw:
        raise LiveTradingDisabled("exchange config must not allow withdrawal permission")
    if not exchange_config.permissions.ip_allowlist:
        raise LiveTradingDisabled("exchange config must require an IP allowlist")


def build_protective_stop_request(
    *,
    entry_order: Order,
    stop_price: float,
    order_kind: Literal["stop_loss", "oco"] = "stop_loss",
) -> ProtectiveStopRequest:
    if entry_order.filled_quantity <= 0:
        raise ValueError("protective stop requires a filled entry quantity")
    stop_side: OrderSide = "sell" if entry_order.side == "buy" else "buy"
    return ProtectiveStopRequest(
        client_order_id=f"stop-{entry_order.client_order_id}",
        parent_client_order_id=entry_order.client_order_id,
        symbol=entry_order.symbol,
        side=stop_side,
        quantity=entry_order.filled_quantity,
        stop_price=stop_price,
        order_kind=order_kind,
        params={"stopPrice": stop_price},
    )


def _signal_client_order_id(signal: Signal) -> str:
    return f"{signal.strategy_name}-{signal.symbol}-{signal.timestamp_ms}"


def _client_order_params(client_order_id: str) -> dict[str, str]:
    return {
        "clientOrderId": client_order_id,
        "newClientOrderId": client_order_id,
    }


def _order_request(order: Order) -> dict[str, Any]:
    return {
        "symbol": order.symbol,
        "type": order.order_type,
        "side": order.side,
        "amount": order.quantity,
        "price": order.limit_price,
        "params": _client_order_params(order.client_order_id),
    }


def _protective_stop_order_request(request: ProtectiveStopRequest) -> dict[str, Any]:
    params = {
        **_client_order_params(request.client_order_id),
        **request.params,
        "parentClientOrderId": request.parent_client_order_id,
        "orderKind": request.order_kind,
    }
    return {
        "symbol": request.symbol,
        "type": "stop_loss_limit",
        "side": request.side,
        "amount": request.quantity,
        "price": request.stop_price,
        "params": params,
    }


def _order_from_exchange(raw: dict[str, Any]) -> Order:
    client_order_id = _raw_client_order_id(raw)
    amount = _raw_float(raw, "amount", "quantity", default=0.0)
    filled = _raw_float(raw, "filled", "filled_quantity", default=0.0)
    order = Order(
        client_order_id=client_order_id,
        symbol=str(raw.get("symbol", "")),
        side=cast(OrderSide, raw.get("side", "buy")),
        order_type=cast(OrderType, raw.get("type", "limit")),
        quantity=max(amount, filled),
        limit_price=_raw_optional_float(raw, "price"),
        status="open",
        filled_quantity=filled,
        average_fill_price=_raw_float(raw, "average", "average_fill_price", default=0.0),
    )
    if order.filled_quantity > 0 and order.remaining_quantity > 0:
        order.status = "partially_filled"
    return order


def _position_from_exchange(raw: dict[str, Any]) -> PaperPosition | None:
    quantity = _raw_float(raw, "contracts", "positionAmt", "amount", "quantity", default=0.0)
    if quantity == 0:
        return None
    return PaperPosition(
        symbol=str(raw.get("symbol", "")),
        quantity=quantity,
        average_price=_raw_float(raw, "entryPrice", "averagePrice", "avgPrice", default=0.0),
        realized_pnl=_raw_float(raw, "realizedPnl", "realized_pnl", default=0.0),
    )


def _raw_client_order_id(raw: dict[str, Any]) -> str:
    info = raw.get("info")
    info_mapping = info if isinstance(info, dict) else {}
    value = (
        raw.get("clientOrderId")
        or raw.get("client_order_id")
        or info_mapping.get("clientOrderId")
        or info_mapping.get("newClientOrderId")
        or raw.get("id")
    )
    return str(value)


def _raw_optional_float(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    return float(value)


def _raw_float(raw: dict[str, Any], *keys: str, default: float) -> float:
    info = raw.get("info")
    info_mapping = info if isinstance(info, dict) else {}
    for key in keys:
        value = raw.get(key, info_mapping.get(key))
        if value is not None:
            return float(value)
    return default
