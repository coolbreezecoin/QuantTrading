from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from crypto_quant_loop.config.models import (
    AllConfigs,
    ExchangesConfig,
    FillsConfig,
    ResearchConfig,
    RiskPolicyConfig,
    StrategiesConfig,
    SymbolsConfig,
)


class ConfigLoadError(ValueError):
    """Raised when a config file is missing, malformed, or cross-inconsistent."""


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigLoadError(f"Config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"Config file must contain a mapping: {path}")
    return cast(dict[str, Any], raw)


def load_config_file[
    ConfigModel: (
        RiskPolicyConfig,
        FillsConfig,
        ExchangesConfig,
        SymbolsConfig,
        StrategiesConfig,
        ResearchConfig,
    )
](path: Path, model_type: type[ConfigModel]) -> ConfigModel:
    raw = load_yaml_file(path)
    try:
        return model_type.model_validate(raw)
    except ValidationError as exc:
        raise ConfigLoadError(f"Invalid config in {path}: {exc}") from exc


def load_all_configs(config_dir: Path = Path("config")) -> AllConfigs:
    try:
        return AllConfigs(
            risk_policy=load_config_file(config_dir / "risk-policy.yaml", RiskPolicyConfig),
            fills=load_config_file(config_dir / "fills.yaml", FillsConfig),
            exchanges=load_config_file(config_dir / "exchanges.yaml", ExchangesConfig),
            symbols=load_config_file(config_dir / "symbols.yaml", SymbolsConfig),
            strategies=load_config_file(config_dir / "strategies.yaml", StrategiesConfig),
            research=load_config_file(config_dir / "research.yaml", ResearchConfig),
        )
    except ValidationError as exc:
        raise ConfigLoadError(f"Config files are inconsistent: {exc}") from exc
