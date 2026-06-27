from __future__ import annotations

from pathlib import Path

from crypto_quant_loop.data.orderbook import OrderbookLevel, OrderbookSnapshot
from crypto_quant_loop.execution import Order, PaperBroker


def make_snapshot(timestamp_ms: int = 1_000) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        exchange="okx",
        symbol="BTCUSDT",
        timestamp_ms=timestamp_ms,
        bids=[OrderbookLevel(price=99.0, amount=2.0)],
        asks=[
            OrderbookLevel(price=100.0, amount=1.0),
            OrderbookLevel(price=101.0, amount=2.0),
        ],
    )


def test_signal_to_order_to_fill_to_position_to_pnl() -> None:
    broker = PaperBroker()
    broker.submit_order(
        Order(
            client_order_id="entry-1",
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=1.0,
        )
    )
    broker.process_orderbook(make_snapshot())
    broker.submit_order(
        Order(
            client_order_id="exit-1",
            symbol="BTCUSDT",
            side="sell",
            order_type="limit",
            quantity=1.0,
            limit_price=99.0,
        )
    )
    broker.process_orderbook(make_snapshot(timestamp_ms=2_000))

    position = broker.state.positions["BTCUSDT"]
    assert position.quantity == 0
    assert position.realized_pnl == -1.0
    assert len(broker.state.fills) == 2


def test_client_order_id_is_idempotent() -> None:
    broker = PaperBroker()
    order = Order(
        client_order_id="same-id",
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=1.0,
    )

    first = broker.submit_order(order)
    second = broker.submit_order(
        Order(
            client_order_id="same-id",
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=1.0,
        )
    )
    broker.process_orderbook(make_snapshot())
    broker.process_orderbook(make_snapshot(timestamp_ms=2_000))

    assert first is second
    assert broker.state.positions["BTCUSDT"].quantity == 1.0
    assert len(broker.state.fills) == 1


def test_partial_fill_and_cancel() -> None:
    broker = PaperBroker()
    order = broker.submit_order(
        Order(
            client_order_id="partial",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=2.0,
            limit_price=100.0,
        )
    )

    broker.process_orderbook(make_snapshot())
    broker.cancel_order("partial")

    assert order.status == "canceled"
    assert order.filled_quantity == 1.0
    assert order.remaining_quantity == 1.0


def test_crash_recovery_and_reconciliation(tmp_path: Path) -> None:
    state_path = tmp_path / "paper_state.json"
    broker = PaperBroker()
    broker.submit_order(
        Order(
            client_order_id="dangling",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=1.0,
            limit_price=90.0,
        )
    )
    broker.save(state_path)

    restored = PaperBroker.load(state_path)
    restored.reconcile_open_orders(set())

    assert restored.state.orders["dangling"].status == "canceled"
    restored.save(state_path)
    reloaded = PaperBroker.load(state_path)
    assert reloaded.state.orders["dangling"].status == "canceled"

