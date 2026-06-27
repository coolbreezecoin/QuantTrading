# STATE — 构建进度与系统状态

> 单一事实来源，断点续跑的依据。每个 step 结束必更新。详见 `CODEX-BUILD-LOOP.md` §3。

## 当前

- 阶段：R1 完成，准备进入 R2
- 进行中 step：无
- **下一步：R2 — 诊断现有策略为何 OOS 差**
- 运行模式：plumbing_test（1000 USDT / A 案，见 `config/risk-policy.yaml`）

## 已完成 step

- S0 — 仓库骨架与工具链
  - 完成时间：2026-06-27T12:18:17Z
  - 产物：`src/` 包结构、`pyproject.toml`、`uv.lock`、ruff/mypy/pytest、pre-commit、CI、gitleaks 配置、空 loop 入口。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；空 loop 已写入 `loop-run-log.jsonl`。
- S1 — 配置加载与校验
  - 完成时间：2026-06-27T12:22:09Z
  - 产物：Pydantic 配置 schema、YAML 加载器、跨文件一致性校验、配置加载测试。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；现有 `config/*.yaml` 加载成功，非法配置会被拒绝并返回可读错误。
- S2 — 数据层：历史 OHLCV
  - 完成时间：2026-06-27T12:28:22Z
  - 产物：OHLCV client、分页拉取、Parquet/DuckDB 写入、质量报告、`cql-fetch-ohlcv` CLI。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；OKX 公共 REST 已落库 BTC/ETH/SOL 各 12,960 根 1h K 线，质量报告覆盖率 100%、缺口 0、重复 0。
- S3 — 数据层：Data Health Loop
  - 完成时间：2026-06-27T12:33:10Z
  - 产物：缺口/重复/异常价格/时间栅格/stale 检测、Data Health loop、`cql-data-health` CLI、健康报告 JSON。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；对 S2 DuckDB 跑真实健康报告，最近 90 天覆盖率 100%、缺口 0、重复 0、halt=false。
- S4 — 数据层：盘口与资金费率采集器（前向）
  - 完成时间：2026-06-27T12:35:41Z
  - 产物：前向盘口 snapshot 模型、DuckDB schema、异步 collector 重连逻辑、资金费率 perp_only 落库、`docs/forward-market-data.md`。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；fake websocket 断线后可重连，盘口与资金费率 schema 可落库。
- S5 — 特征库
  - 完成时间：2026-06-27T12:38:52Z
  - 产物：收益率、滚动波动率、ATR、成交量变化、bar spread bps、lookahead detector。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；同输入同输出复现测试通过，故意泄漏未来 close 的用例会被检出。
- S6 — 策略 SDK 与两个策略
  - 完成时间：2026-06-27T12:42:26Z
  - 产物：`Signal`/`StrategyState`、配置驱动信号生成、动量突破策略、均值回归策略。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；同数据同参数复现同信号，均值回归信号包含硬止损和 `time_stop_bars`。
- S7 — 回测引擎
  - 完成时间：2026-06-27T12:46:27Z
  - 产物：保守历史成交模型、按止损反推仓位、min-notional 跳过、maker/taker 费用、lookahead guard、基础回测报告指标。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；lookahead 注入测试会被拦截，min-notional 地板生效，maker/taker 费用绑定生效。
- S8 — Walk-forward 验证框架
  - 完成时间：2026-06-27T12:49:48Z
  - 产物：滚动 IS/OOS window、purge+embargo、OOS regime 分类、Sharpe 衰减、deflated Sharpe 试验惩罚、walk-forward 报告。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；用 S2 的 BTC 18 个月 1h 历史生成 14 段 OOS smoke report，regime 覆盖 bull/bear/chop。
- S9 — Verifier 与策略注册表
  - 完成时间：2026-06-27T12:53:12Z
  - 产物：`config/strategy-registry.yaml`、registry 加载、approved 准入过滤、Strategy Verifier、拒绝原因 JSONL 日志。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；candidate 策略不能绕过 registry，自我审批会被拒并记录原因。
- S10 — 风控引擎
  - 完成时间：2026-06-27T12:56:31Z
  - 产物：仓位 sizing、单标的/组合敞口限制、连亏 cooldown、滚动 24h 熔断、总回撤、业务硬止损、运行态熔断、kill switch 动作计划。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；阶梯顺序测试确认 cooldown 先于滚动 24h 熔断，kill switch 演练覆盖撤单/halt/可选平仓。
- S11 — Paper Broker 与订单状态机
  - 完成时间：2026-06-27T13:00:11Z
  - 产物：paper broker、订单状态机、clientOrderId 幂等、前向盘口撮合、部分成交、撤单、持仓/PnL、JSON 状态恢复、reconciliation。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；signal→order→fill→position→PnL 跑通，重试不产生双倍仓位，崩溃恢复后无悬挂订单。
- S12 — Loops 运行时
  - 完成时间：2026-06-27T13:04:04Z
  - 产物：`LoopRuntime`、默认 loop specs、APScheduler adapter、heartbeat、`loop-run-log.jsonl` 写入、dead-man switch。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；优先级执行、心跳/run-log 写入、dead-man stale 检测均有测试。
- S13 — 监控、告警、账本、Fill-Fidelity
  - 完成时间：2026-06-27T13:08:11Z
  - 产物：默认关闭的 alert sink、dashboard snapshot、trade ledger Parquet、fill-fidelity Parquet/report、`docs/fill-fidelity-calibration.md` 校准说明。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；alert 默认 disabled，不会发送外部通知。
- S14 — L2 实盘接入脚手架（仅 dry-run）
  - 完成时间：2026-06-27T13:34:57Z
  - 人工批准范围：仅允许写 live 交易所适配器脚手架、env-only 密钥读取、server-side stop/OCO 代码路径、exchange-canonical reconciliation 与 live dry-run 测试；不启用真实交易。
  - 产物：ccxt-shaped `LiveExchangeAdapter`、dry-run hard gate、clientOrderId 幂等复用、保护性止损请求构建/提交路径、环境变量密钥 no-op 降级、exchange-canonical reconciliation、live dry-run fixture。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；live dry-run 链路断言无真实订单可达，`config/exchanges.yaml` 的 `dry_run` 仍为 true，reconciliation 以交易所返回的挂单/持仓为准。
- R1 — 基准与"跑赢"的判定
  - 完成时间：2026-06-27T14:08:52Z
  - 产物：`config/research.yaml` 研究口径、ResearchConfig schema、buy-and-hold BTC 与 BTC/ETH/SOL 等权基准、OOS 扣费后风险调整 beat 谓词、R1 baseline report。
  - 验证：`uv run ruff check .`、`uv run mypy`、`uv run pytest`、`uv run python scripts/secret_scan.py` 全部通过；本地 `data/processed/market.duckdb` 三标的各 12,960 根 1h bar，覆盖 540 天，已生成 `reports/r1_baselines.json`。

## 阻塞 / 未决问题

- Binance 公共 REST 在当前网络位置返回 451 地域限制；S2 使用 OKX 公共 REST 完成历史数据落库。未启用 OKX 交易权限，也未读取任何密钥。
- S3 按当前 `price_deviation_bps=200` 将部分 1h 大波动标为 abnormal price；这只是报告项，不触发 data_gap halt。阈值属于风控配置，未人工批准前不调整。

## 等待人工

- S14 脚手架已按人工批准范围完成，但本次批准仅限 dry-run 代码路径；没有启用真实交易、没有发送真实订单、没有读取或提交真实密钥、没有打开外部告警。
- 开启真金白银交易是 S14 之外的独立门禁，至少需同时满足：(a) 有策略通过 verifier 被 `approved`，(b) Fill-Fidelity 偏差验证通过，(c) 人工再次显式批准。
- R 阶段允许继续做 research/report-only 工作；不得把任何候选策略自我批准为 `approved`，也不得设置正数 `max_notional_quote`。

## 最近决策

- 采用 A 案：1000 USDT 定位为管道测试，不以盈亏评判；实盘先只跑 BTC 单标的。
- 风控/成交参数以 `config/risk-policy.yaml`、`config/fills.yaml` 为准。
- S0 本地验证使用 `uv` 创建的 CPython 3.13 虚拟环境；项目仍声明 `requires-python >=3.12`。
- S1 配置加载只保留密钥环境变量名，不读取真实密钥值。
- S2 历史数据产物位于 `data/` 与 `reports/`，按 `.gitignore` 不入库；代码与审计状态入库。
- S3 的 `halt_required` 当前只按 `auto_halt_on.data_gap` 对缺口/低覆盖/stale 触发，异常价格先报告不自动停机。
- S4 明确 L2 盘口历史不可回填；默认不启动持续 websocket，后续由调度/配置显式开启。
- S5 特征 warmup 使用 `None`，策略层必须显式处理不可用特征。
- S6 策略只生成候选信号，不具备审批、仓位或执行权限；策略注册和 verifier 留到 S9。
- S7 当前是保守的一进一出最小闭环：信号下一根开盘入场，stop/time-stop 或默认下一根收盘出场；更完整的持仓生命周期可在后续扩展。
- S8 smoke report 显示基础策略 OOS 表现很差（14 段中 3 段为正），这不会阻塞框架建设，但会在 S9 verifier 中导致策略保持 candidate/rejected 而非 approved。
- S9 默认两个基础策略均保持 `candidate`，`max_notional_quote=0`，不会进入后续 Signal Loop。
- S10 kill switch 只输出动作计划，真实 broker 执行留给 S11/S12。
- S11 仍为 paper only；live 适配器与真实交易所 reconciliation 留到 S14 门禁脚手架。
- S12 没有启动常驻 scheduler；APScheduler adapter 需后续显式调用。
- S13 alert sink 默认 disabled；当前仅落本地结构化监控数据，不配置外部告警渠道。
- Fill-fidelity 校准只能产出偏差报告与人工复核建议，不能自动修改 `config/fills.yaml`。
- S14 的 live adapter 默认 dry-run；即便构造 `dry_run=false`，未提供新的 `allow_real_trading` 独立门禁也会拒绝真实 order path。
- S14 未修改 `config/exchanges.yaml`、`config/strategy-registry.yaml` 或任何风控阈值；两个基础策略仍为 candidate 且 `max_notional_quote=0`。
- R1 将"跑赢"固定为 OOS、扣费后、风险调整口径：Calmar 优于基准，或 Sharpe 不低于基准且最大回撤不高于基准；负收益候选即使风险指标较好也不算通过。
- R1 真实历史基准结果偏弱：BTC buy-and-hold 540 天扣费后约 -37.59%，等权 BTC/ETH/SOL 约 -52.83%；这只是研究基准，不代表策略通过。
