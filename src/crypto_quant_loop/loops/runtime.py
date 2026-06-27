from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

LoopHandler = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class LoopSpec:
    name: str
    cadence_s: int
    priority: int
    handler: LoopHandler


@dataclass(frozen=True)
class LoopRunRecord:
    run_id: str
    loop: str
    duration_s: float
    outcome: str
    items_found: int = 0
    actions_taken: int = 0
    escalations: int = 0


@dataclass(frozen=True)
class DeadmanAlert:
    loop: str
    last_heartbeat_ms: int
    stale_after_ms: int
    conservative_action: str


class LoopRuntime:
    def __init__(
        self,
        *,
        specs: list[LoopSpec],
        heartbeat_path: Path,
        run_log_path: Path,
    ) -> None:
        self.specs = specs
        self.heartbeat_path = heartbeat_path
        self.run_log_path = run_log_path

    def run_once(self) -> list[LoopRunRecord]:
        records: list[LoopRunRecord] = []
        for spec in sorted(self.specs, key=lambda item: item.priority):
            records.append(self.run_loop(spec))
        return records

    def run_loop(self, spec: LoopSpec) -> LoopRunRecord:
        started = perf_counter()
        run_id = datetime.now(UTC).isoformat()
        result = spec.handler()
        duration = round(perf_counter() - started, 6)
        record = LoopRunRecord(
            run_id=run_id,
            loop=spec.name,
            duration_s=duration,
            outcome=str(result.get("outcome", "success")),
            items_found=int(result.get("items_found", 0)),
            actions_taken=int(result.get("actions_taken", 0)),
            escalations=int(result.get("escalations", 0)),
        )
        self._write_heartbeat(spec.name, int(datetime.now(UTC).timestamp() * 1000))
        self._append_run_log(record)
        return record

    def check_deadman(self, *, now_ms: int, miss_factor: float) -> list[DeadmanAlert]:
        heartbeats = self._read_heartbeats()
        alerts: list[DeadmanAlert] = []
        for spec in self.specs:
            last = int(heartbeats.get(spec.name, 0))
            stale_after = int(spec.cadence_s * miss_factor * 1000)
            if last == 0 or now_ms - last > stale_after:
                alerts.append(
                    DeadmanAlert(
                        loop=spec.name,
                        last_heartbeat_ms=last,
                        stale_after_ms=stale_after,
                        conservative_action="halt_new_orders_and_alert_human",
                    )
                )
        return alerts

    def _write_heartbeat(self, loop_name: str, timestamp_ms: int) -> None:
        heartbeats = self._read_heartbeats()
        heartbeats[loop_name] = timestamp_ms
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path.write_text(json.dumps(heartbeats, indent=2), encoding="utf-8")

    def _read_heartbeats(self) -> dict[str, int]:
        if not self.heartbeat_path.exists():
            return {}
        raw = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
        return {str(key): int(value) for key, value in raw.items()}

    def _append_run_log(self, record: LoopRunRecord) -> None:
        self.run_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.run_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def build_default_loop_specs(handler: LoopHandler | None = None) -> list[LoopSpec]:
    default_handler = handler or (lambda: {"outcome": "no-op"})
    return [
        LoopSpec("risk-sentinel", 60, 10, default_handler),
        LoopSpec("execution-paper", 300, 20, default_handler),
        LoopSpec("data-health", 3600, 30, default_handler),
        LoopSpec("signal", 3600, 40, default_handler),
        LoopSpec("verifier", 86400, 50, default_handler),
        LoopSpec("fill-fidelity", 86400, 60, default_handler),
        LoopSpec("post-trade-review", 86400, 70, default_handler),
    ]


def create_apscheduler(runtime: LoopRuntime) -> Any:
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    for spec in runtime.specs:
        scheduler.add_job(
            runtime.run_loop,
            "interval",
            seconds=spec.cadence_s,
            args=[spec],
            id=spec.name,
            replace_existing=True,
        )
    return scheduler

