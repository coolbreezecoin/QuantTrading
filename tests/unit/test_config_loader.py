from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crypto_quant_loop.config import ConfigLoadError, load_all_configs
from crypto_quant_loop.config.loader import load_config_file
from crypto_quant_loop.config.models import RiskPolicyConfig, SymbolsConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_load_all_configs_from_repo_config() -> None:
    configs = load_all_configs(PROJECT_ROOT / "config")

    assert configs.risk_policy.account.mode == "plumbing_test"
    assert configs.risk_policy.symbols.live == ["BTCUSDT"]
    assert configs.exchanges.defaults.dry_run is True
    assert configs.fills.backtest_historical.entry_price == "next_bar_open"
    assert "momentum_breakout" in configs.strategies.strategies
    assert configs.research.beat_criteria.metric_scope == "oos"


def test_invalid_numeric_range_is_rejected(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "config" / "risk-policy.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    raw["position_sizing"]["single_trade_risk_pct"] = -0.01
    invalid_path = tmp_path / "risk-policy.yaml"
    invalid_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="single_trade_risk_pct"):
        load_config_file(invalid_path, RiskPolicyConfig)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "config" / "symbols.yaml"
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    del raw["symbols"]["BTCUSDT"]["filters"]["tick_size"]
    invalid_path = tmp_path / "symbols.yaml"
    invalid_path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="tick_size"):
        load_config_file(invalid_path, SymbolsConfig)


def test_cross_file_symbol_mismatch_is_rejected(tmp_path: Path) -> None:
    for path in (PROJECT_ROOT / "config").glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if path.name == "risk-policy.yaml":
            raw["symbols"]["live"] = ["DOGEUSDT"]
        (tmp_path / path.name).write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="DOGEUSDT"):
        load_all_configs(tmp_path)
