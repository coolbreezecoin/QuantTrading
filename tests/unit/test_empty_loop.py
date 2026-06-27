from __future__ import annotations

import json
from pathlib import Path

from crypto_quant_loop.loops.empty_loop import EmptyLoopConfig, run_empty_loop


def test_empty_loop_writes_append_only_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "loop-run-log.jsonl"

    first = run_empty_loop(EmptyLoopConfig(log_path=log_path))
    second = run_empty_loop(EmptyLoopConfig(log_path=log_path, pattern="smoke"))

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == first
    assert json.loads(lines[1]) == second
    assert second["pattern"] == "smoke"
    assert second["outcome"] == "no-op"

