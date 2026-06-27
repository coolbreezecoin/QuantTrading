from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from crypto_quant_loop.config import load_all_configs
from crypto_quant_loop.execution import (
    LiveExchangeAdapter,
    LiveTradingDisabled,
    Order,
    PaperPosition,
    build_live_adapter_from_config,
)
from crypto_quant_loop.strategies.sdk import Signal

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FakeExchangeClient:
    def __init__(
        self,
        *,
        open_orders: list[dict[str, Any]] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.open_orders = open_orders or []
        self.positions = positions or []
        self.create_order_calls: list[tuple[str, str, str, float]] = []

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del price, params
        self.create_order_calls.append((symbol, type, side, amount))
        raise AssertionError("dry-run test must not reach a real order endpoint")

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol is None:
            return self.open_orders
        return [order for order in self.open_orders if order["symbol"] == symbol]

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if symbols is None:
            return self.positions
        return [position for position in self.positions if position["symbol"] in symbols]


def test_live_dry_run_signal_chain_records_no_real_orders() -> None:
    client = FakeExchangeClient(
        positions=[{"symbol": "BTCUSDT", "contracts": 0.01, "entryPrice": 100.0}]
    )
    adapter = LiveExchangeAdapter(exchange_id="binance", dry_run=True, client=client)
    signal = Signal(
        strategy_name="fixture_strategy",
        strategy_type="fixture",
        symbol="BTCUSDT",
        timestamp_ms=1_000,
        side="long",
        order_type="market",
        reference_price=100.0,
        stop_price=95.0,
    )

    result = adapter.submit_signal(signal, quantity=0.01)
    replay = adapter.submit_signal(signal, quantity=0.01)
    before_reconcile_position = adapter.state.positions["BTCUSDT"]
    report = adapter.reconcile(symbols=["BTCUSDT"])

    assert result.order_result.status == "dry_run_recorded"
    assert replay.order_result.status == "idempotent_replay"
    assert result.order_result.real_order_reachable is False
    assert result.order_result.fill is not None
    assert result.protective_stop_result is not None
    assert result.protective_stop_result.status == "dry_run_recorded"
    assert result.protective_stop_result.real_order_reachable is False
    assert len(adapter.protective_stop_intents) == 1
    assert len(adapter.state.fills) == 1
    assert before_reconcile_position.quantity == 0.01
    assert report.status == "reconciled"
    assert adapter.state.positions["BTCUSDT"].quantity == 0.01
    assert client.create_order_calls == []


def test_reconciliation_treats_exchange_state_as_canonical() -> None:
    client = FakeExchangeClient(
        open_orders=[
            {
                "id": "exchange-open",
                "clientOrderId": "exchange-open",
                "symbol": "BTCUSDT",
                "side": "buy",
                "type": "limit",
                "amount": 0.02,
                "price": 90.0,
                "filled": 0.0,
            }
        ],
        positions=[{"symbol": "BTCUSDT", "contracts": 0.25, "entryPrice": 100.0}],
    )
    adapter = LiveExchangeAdapter(exchange_id="binance", dry_run=True, client=client)
    adapter.state.orders["local-dangling"] = Order(
        client_order_id="local-dangling",
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        quantity=0.01,
        limit_price=80.0,
    )
    adapter.state.positions["ETHUSDT"] = PaperPosition(
        symbol="ETHUSDT",
        quantity=1.0,
        average_price=2000.0,
    )

    report = adapter.reconcile(symbols=["BTCUSDT"])

    assert adapter.state.orders["local-dangling"].status == "canceled"
    assert adapter.state.orders["exchange-open"].status == "open"
    assert report.exchange_open_order_ids == ("exchange-open",)
    assert report.local_canceled_order_ids == ("local-dangling",)
    assert tuple(adapter.state.positions) == ("BTCUSDT",)
    assert adapter.state.positions["BTCUSDT"].quantity == 0.25
    assert client.create_order_calls == []


def test_missing_credentials_degrade_to_dry_run_noop() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")

    adapter, client_build = build_live_adapter_from_config(configs, environ={})

    assert configs.exchanges.defaults.dry_run is True
    assert adapter.dry_run is True
    assert client_build.status == "missing_credentials"
    assert client_build.client is None
    assert set(client_build.missing_env_vars) == {"BINANCE_API_KEY", "BINANCE_API_SECRET"}


def test_real_order_path_requires_separate_gate() -> None:
    client = FakeExchangeClient()
    adapter = LiveExchangeAdapter(exchange_id="binance", dry_run=False, client=client)

    with pytest.raises(LiveTradingDisabled, match="separate explicit gate"):
        adapter.submit_order(
            Order(
                client_order_id="blocked-real-order",
                symbol="BTCUSDT",
                side="buy",
                order_type="market",
                quantity=0.01,
            ),
            expected_fill_price=100.0,
        )

    assert client.create_order_calls == []


def test_s14_red_lines_config_remains_dry_run_and_unapproved() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")
    registry = cast(
        dict[str, Any],
        yaml.safe_load((PROJECT_ROOT / "config" / "strategy-registry.yaml").read_text()),
    )

    assert configs.exchanges.defaults.dry_run is True
    assert all(
        item["status"] != "approved" and item["max_notional_quote"] == 0
        for item in registry["strategies"].values()
    )
