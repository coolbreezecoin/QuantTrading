from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter


@dataclass(frozen=True)
class EmptyLoopConfig:
    log_path: Path
    pattern: str = "empty-loop"


def run_empty_loop(config: EmptyLoopConfig) -> dict[str, object]:
    started = perf_counter()
    run_id = datetime.now(UTC).isoformat()
    record: dict[str, object] = {
        "run_id": run_id,
        "pattern": config.pattern,
        "duration_s": 0.0,
        "items_found": 0,
        "actions_taken": 0,
        "escalations": 0,
        "tokens_estimate": 0,
        "outcome": "no-op",
    }
    record["duration_s"] = round(perf_counter() - started, 6)

    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    with config.log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")

    return record

