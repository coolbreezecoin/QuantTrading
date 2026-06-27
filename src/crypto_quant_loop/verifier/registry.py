from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

StrategyStatus = Literal["candidate", "approved", "rejected", "paused"]


class StrategyRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: StrategyStatus
    maker_id: str = Field(min_length=1)
    verifier_id: str | None
    approved_at: str | None
    max_notional_quote: float = Field(ge=0)
    reason: str = Field(min_length=1)


class StrategyRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategies: dict[str, StrategyRegistryEntry]


def load_strategy_registry(path: Path) -> StrategyRegistry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Strategy registry must be a mapping: {path}")
    return StrategyRegistry.model_validate(raw)


def approved_strategy_names(registry: StrategyRegistry) -> set[str]:
    return {
        name
        for name, entry in registry.strategies.items()
        if entry.status == "approved" and entry.max_notional_quote > 0
    }

