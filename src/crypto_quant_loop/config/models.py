from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountConfig(StrictModel):
    equity_quote: str = Field(min_length=3)
    equity_size: PositiveFloat
    mode: Literal["plumbing_test", "live_sized"]


class RiskSymbolsConfig(StrictModel):
    live: list[str] = Field(min_length=1)
    research: list[str] = Field(min_length=1)


class LeverageConfig(StrictModel):
    spot_max: float = Field(ge=0)
    perp_max: float = Field(ge=0, le=2)


class StopSizingConfig(StrictModel):
    method: Literal["atr"]
    atr_period: PositiveInt
    atr_mult: PositiveFloat


class PositionSizingConfig(StrictModel):
    single_trade_risk_pct: float = Field(gt=0, le=0.05)
    stop: StopSizingConfig
    single_symbol_notional_cap_pct: float = Field(gt=0, le=1)
    portfolio_directional_cap_pct: float = Field(gt=0, le=1)
    min_notional_floor_quote: PositiveFloat


class ConsecutiveLossesConfig(StrictModel):
    count: PositiveInt
    cooldown_hours: PositiveFloat


class CircuitBreakersConfig(StrictModel):
    consecutive_losses: ConsecutiveLossesConfig
    rolling_24h_loss_halt_pct: float = Field(gt=0, le=1)
    total_drawdown_pause_pct: float = Field(gt=0, le=1)
    business_hard_stop_pct: float = Field(gt=0, le=1)
    loss_window: Literal["rolling_24h"]


class AutoHaltConfig(StrictModel):
    data_gap: bool
    api_error: bool
    price_deviation_bps: PositiveFloat
    loop_heartbeat_miss_factor: PositiveFloat


class MeanReversionRiskConfig(StrictModel):
    time_stop_bars: PositiveInt


class KillSwitchConfig(StrictModel):
    cancel_all_open_orders: bool
    flatten_positions: bool
    set_global_halt: bool
    triggers: list[Literal["manual", "risk_sentinel"]] = Field(min_length=1)


class RiskPolicyConfig(StrictModel):
    account: AccountConfig
    symbols: RiskSymbolsConfig
    leverage: LeverageConfig
    position_sizing: PositionSizingConfig
    circuit_breakers: CircuitBreakersConfig
    auto_halt_on: AutoHaltConfig
    mean_reversion: MeanReversionRiskConfig
    kill_switch: KillSwitchConfig


class BacktestHistoricalFillsConfig(StrictModel):
    entry_price: Literal["next_bar_open"]
    cross_half_spread_bps: dict[str, PositiveFloat]
    conservative_buffer_bps: float = Field(ge=0)
    impact_model: Literal["linear"]
    impact_coeff_bps_per_1pct_adv: float = Field(ge=0)
    calibration_note: str = Field(min_length=1)


class PaperForwardFillsConfig(StrictModel):
    use_orderbook_snapshot: bool
    market_order: Literal["walk_the_book"]
    limit_order_fill: Literal["touched"]


class FeesConfig(StrictModel):
    taker_bps: float = Field(ge=0)
    maker_bps: float = Field(ge=0)
    use_bnb_discount: bool
    order_type_by_strategy: dict[str, Literal["market", "limit"]]
    funding_applies: Literal["perp_only"]


class FillsConfig(StrictModel):
    backtest_historical: BacktestHistoricalFillsConfig
    paper_forward: PaperForwardFillsConfig
    fees: FeesConfig


class ExchangeDefaultsConfig(StrictModel):
    quote: str = Field(min_length=3)
    dry_run: bool
    rate_limit: bool
    recv_window_ms: PositiveInt
    timeout_ms: PositiveInt


class ExchangePermissionsConfig(StrictModel):
    withdraw: bool
    ip_allowlist: bool


class ExchangeWebsocketConfig(StrictModel):
    orderbook: bool
    depth: PositiveInt


class ExchangeConfig(StrictModel):
    enabled: bool
    type: Literal["spot", "perp"]
    api_key_env: str = Field(min_length=1)
    api_secret_env: str = Field(min_length=1)
    api_passphrase_env: str | None = None
    permissions: ExchangePermissionsConfig
    fees: dict[str, bool] | None = None
    websocket: ExchangeWebsocketConfig


class ExchangesConfig(StrictModel):
    defaults: ExchangeDefaultsConfig
    exchanges: dict[str, ExchangeConfig]


class SymbolDefaultsConfig(StrictModel):
    quote: str = Field(min_length=3)
    exchange: str = Field(min_length=1)


class SymbolFiltersConfig(StrictModel):
    tick_size: PositiveFloat
    step_size: PositiveFloat
    min_notional_quote: PositiveFloat


class SymbolConfig(StrictModel):
    base: str = Field(min_length=1)
    timeframe: Literal["1h", "15m", "5m"]
    roles: list[Literal["live", "research"]] = Field(min_length=1)
    filters: SymbolFiltersConfig


class HistoryConfig(StrictModel):
    min_lookback_days: PositiveInt
    require_regimes: list[Literal["bull", "bear", "chop"]] = Field(min_length=1)


class SymbolsConfig(StrictModel):
    defaults: SymbolDefaultsConfig
    symbols: dict[str, SymbolConfig]
    history: HistoryConfig


class StrategyParamsConfig(StrictModel):
    fast_ma: PositiveInt | None = None
    slow_ma: PositiveInt | None = None
    donchian_lookback: PositiveInt | None = None
    atr_period: PositiveInt | None = None
    rsi_period: PositiveInt | None = None
    rsi_oversold: float | None = Field(default=None, ge=0, le=100)
    rsi_overbought: float | None = Field(default=None, ge=0, le=100)
    bb_period: PositiveInt | None = None
    bb_std: PositiveFloat | None = None
    trend_filter_ma: PositiveInt | None = None


class StrategyStopConfig(StrictModel):
    method: Literal["atr"]
    atr_mult: PositiveFloat
    time_stop_bars: PositiveInt | None = None


class StrategyConfig(StrictModel):
    type: Literal["momentum", "mean_reversion"]
    enabled: bool
    order_type: Literal["market", "limit"]
    params: StrategyParamsConfig
    stop: StrategyStopConfig


class VerificationThresholdsConfig(StrictModel):
    oos_sharpe_decay_max: float = Field(ge=0, le=1)
    max_drawdown_max: float = Field(gt=0, le=1)
    min_trades: PositiveInt
    must_be_profitable_after_fees: bool
    no_recent_30d_failure: bool


class StrategiesConfig(StrictModel):
    strategies: dict[str, StrategyConfig]
    verification_thresholds: VerificationThresholdsConfig


class AllConfigs(StrictModel):
    risk_policy: RiskPolicyConfig
    fills: FillsConfig
    exchanges: ExchangesConfig
    symbols: SymbolsConfig
    strategies: StrategiesConfig

    @model_validator(mode="after")
    def validate_cross_file_consistency(self) -> AllConfigs:
        configured_symbols = set(self.symbols.symbols)
        live_symbols = set(self.risk_policy.symbols.live)
        research_symbols = set(self.risk_policy.symbols.research)
        missing = (live_symbols | research_symbols) - configured_symbols
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(
                "risk-policy references symbols missing from symbols.yaml: "
                f"{missing_list}"
            )

        for symbol in live_symbols:
            roles = set(self.symbols.symbols[symbol].roles)
            if "live" not in roles:
                raise ValueError(
                    f"{symbol} is live in risk-policy but lacks live role in symbols.yaml"
                )

        for symbol in research_symbols:
            roles = set(self.symbols.symbols[symbol].roles)
            if "research" not in roles:
                raise ValueError(
                    f"{symbol} is research in risk-policy but lacks research role in symbols.yaml"
                )

        order_type_by_strategy = self.fills.fees.order_type_by_strategy
        strategy_types = {
            strategy.type: strategy.order_type
            for strategy in self.strategies.strategies.values()
        }
        for strategy_type, order_type in strategy_types.items():
            expected_order_type = order_type_by_strategy.get(strategy_type)
            if expected_order_type != order_type:
                raise ValueError(
                    f"strategy type {strategy_type} order type {order_type} does not match "
                    f"fills.yaml mapping {expected_order_type}"
                )

        return self
