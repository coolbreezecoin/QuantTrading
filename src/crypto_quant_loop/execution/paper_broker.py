from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from crypto_quant_loop.data.orderbook import OrderbookLevel, OrderbookSnapshot

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["open", "partially_filled", "filled", "canceled", "rejected"]


@dataclass
class Order:
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None = None
    status: OrderStatus = "open"
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0

    @property
    def remaining_quantity(self) -> float:
        return max(self.quantity - self.filled_quantity, 0.0)


@dataclass(frozen=True)
class Fill:
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    timestamp_ms: int


@dataclass
class PaperPosition:
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class PaperBrokerState:
    orders: dict[str, Order] = field(default_factory=dict)
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)


class PaperBroker:
    def __init__(self, state: PaperBrokerState | None = None) -> None:
        self.state = state or PaperBrokerState()

    def submit_order(self, order: Order) -> Order:
        existing = self.state.orders.get(order.client_order_id)
        if existing is not None:
            return existing
        if order.quantity <= 0:
            order.status = "rejected"
        self.state.orders[order.client_order_id] = order
        return order

    def cancel_order(self, client_order_id: str) -> Order:
        order = self.state.orders[client_order_id]
        if order.status in {"open", "partially_filled"}:
            order.status = "canceled"
        return order

    def process_orderbook(self, snapshot: OrderbookSnapshot) -> list[Fill]:
        fills: list[Fill] = []
        for order in list(self.state.orders.values()):
            if order.symbol != snapshot.symbol or order.status not in {"open", "partially_filled"}:
                continue
            fills.extend(self._fill_order(order, snapshot))
        return fills

    def reconcile_open_orders(self, ledger_open_order_ids: set[str]) -> None:
        for order in self.state.orders.values():
            is_open = order.status in {"open", "partially_filled"}
            missing_from_ledger = order.client_order_id not in ledger_open_order_ids
            if is_open and missing_from_ledger:
                order.status = "canceled"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "orders": {key: asdict(order) for key, order in self.state.orders.items()},
            "positions": {key: asdict(position) for key, position in self.state.positions.items()},
            "fills": [asdict(fill) for fill in self.state.fills],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> PaperBroker:
        raw = json.loads(path.read_text(encoding="utf-8"))
        state = PaperBrokerState(
            orders={key: Order(**value) for key, value in raw["orders"].items()},
            positions={key: PaperPosition(**value) for key, value in raw["positions"].items()},
            fills=[Fill(**value) for value in raw["fills"]],
        )
        return cls(state)

    def _fill_order(self, order: Order, snapshot: OrderbookSnapshot) -> list[Fill]:
        book = snapshot.asks if order.side == "buy" else snapshot.bids
        fills: list[Fill] = []
        for level in book:
            if order.remaining_quantity <= 0:
                break
            if not _level_crosses_order(order, level):
                break
            quantity = min(order.remaining_quantity, level.amount)
            fill = Fill(
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=quantity,
                price=level.price,
                timestamp_ms=snapshot.timestamp_ms,
            )
            self._apply_fill(order, fill)
            fills.append(fill)
        if order.remaining_quantity == 0 and order.status != "rejected":
            order.status = "filled"
        elif fills:
            order.status = "partially_filled"
        return fills

    def _apply_fill(self, order: Order, fill: Fill) -> None:
        previous_value = order.average_fill_price * order.filled_quantity
        order.filled_quantity += fill.quantity
        order.average_fill_price = (
            previous_value + fill.price * fill.quantity
        ) / order.filled_quantity
        self.state.fills.append(fill)

        position = self.state.positions.setdefault(fill.symbol, PaperPosition(symbol=fill.symbol))
        if fill.side == "buy":
            total_quantity = position.quantity + fill.quantity
            if total_quantity > 0:
                position.average_price = (
                    (position.average_price * position.quantity) + (fill.price * fill.quantity)
                ) / total_quantity
            position.quantity = total_quantity
        else:
            closed_quantity = min(position.quantity, fill.quantity)
            position.realized_pnl += (fill.price - position.average_price) * closed_quantity
            position.quantity -= closed_quantity
            if position.quantity == 0:
                position.average_price = 0.0


def _level_crosses_order(order: Order, level: OrderbookLevel) -> bool:
    if order.order_type == "market":
        return True
    if order.limit_price is None:
        return False
    if order.side == "buy":
        return level.price <= order.limit_price
    return level.price >= order.limit_price
