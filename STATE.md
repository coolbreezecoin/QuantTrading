# STATE — 构建进度与系统状态

> 单一事实来源，断点续跑的依据。每个 step 结束必更新。详见 `CODEX-BUILD-LOOP.md` §3。

## 当前

- 阶段：S8 完成，准备进入 S9
- 进行中 step：无
- **下一步：S9 — Verifier 与策略注册表**
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

## 阻塞 / 未决问题

- Binance 公共 REST 在当前网络位置返回 451 地域限制；S2 使用 OKX 公共 REST 完成历史数据落库。未启用 OKX 交易权限，也未读取任何密钥。
- S3 按当前 `price_deviation_bps=200` 将部分 1h 大波动标为 abnormal price；这只是报告项，不触发 data_gap halt。阈值属于风控配置，未人工批准前不调整。

## 等待人工

- 尚未到门禁。S14（L2 实盘接入）及任何真实资金/密钥动作需人工批准（见 `CODEX-BUILD-LOOP.md` §5）。

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
