from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_dashboard_snapshot(
    *,
    data_health: dict[str, Any],
    strategy_status: dict[str, Any],
    risk_status: dict[str, Any],
    fill_fidelity: dict[str, Any],
    loop_heartbeats: dict[str, int],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "data_health": data_health,
        "strategy_status": strategy_status,
        "risk_status": risk_status,
        "fill_fidelity": fill_fidelity,
        "loop_heartbeats": loop_heartbeats,
    }
