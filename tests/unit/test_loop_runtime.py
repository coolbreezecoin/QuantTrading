from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from crypto_quant_loop.loops import LoopRuntime, LoopSpec, build_default_loop_specs


def test_runtime_runs_loops_by_priority_and_writes_heartbeat_and_log(tmp_path: Path) -> None:
    order: list[str] = []

    def make_handler(name: str) -> Callable[[], dict[str, object]]:
        def handler() -> dict[str, object]:
            order.append(name)
            return {"outcome": "success", "actions_taken": 1}

        return handler

    specs = [
        LoopSpec("low", 60, 20, make_handler("low")),
        LoopSpec("high", 60, 10, make_handler("high")),
    ]
    runtime = LoopRuntime(
        specs=specs,
        heartbeat_path=tmp_path / "heartbeats.json",
        run_log_path=tmp_path / "loop-run-log.jsonl",
    )

    records = runtime.run_once()

    heartbeats = json.loads((tmp_path / "heartbeats.json").read_text(encoding="utf-8"))
    log_lines = (tmp_path / "loop-run-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert order == ["high", "low"]
    assert [record.loop for record in records] == ["high", "low"]
    assert set(heartbeats) == {"high", "low"}
    assert len(log_lines) == 2


def test_deadman_switch_flags_missing_loop(tmp_path: Path) -> None:
    specs = build_default_loop_specs()
    runtime = LoopRuntime(
        specs=specs,
        heartbeat_path=tmp_path / "heartbeats.json",
        run_log_path=tmp_path / "loop-run-log.jsonl",
    )
    (tmp_path / "heartbeats.json").write_text(
        json.dumps({"risk-sentinel": 1_000}),
        encoding="utf-8",
    )

    alerts = runtime.check_deadman(now_ms=10_000_000, miss_factor=3)

    alert_names = {alert.loop for alert in alerts}
    assert "risk-sentinel" in alert_names
    assert "data-health" in alert_names
    assert all(alert.conservative_action == "halt_new_orders_and_alert_human" for alert in alerts)


def test_default_loop_specs_have_expected_priority_order() -> None:
    specs = build_default_loop_specs()

    assert [spec.name for spec in sorted(specs, key=lambda item: item.priority)][:3] == [
        "risk-sentinel",
        "execution-paper",
        "data-health",
    ]
