# crypto-quant-loop

> 一套**可观测、可验证、可暂停、可审计**的加密货币量化交易循环系统,基于 loop engineering 方式构建。
> **第一版的目标是安全骨架,不是盈利。** 系统在每个门禁都默认人工把关,实盘下单受多重硬门禁保护。

---

## ⚠️ 项目状态(请先读这一段)

本仓库是**基础设施交付物**,不是一个会赚钱的交易机器人,也**不应被直接用于实盘**。

经过三轮诚实的策略验证,结论是:**在 1000 USDT 体量、用公开手段、扣诚实成本的前提下,没有可利用的净 edge。**

| 验证阶段 | 结论 |
| --- | --- |
| 价格 TA(动量 / 均值回归) | 全 regime 亏损,费用 >100% 毛利,verifier 全部拒绝 |
| 资金费率 carry(首轮) | 低费率熊市窗口净 carry 为负 |
| 资金费率 carry(540 天多 regime 精炼) | 最佳仅 BTC、+0.13%/年、机会成本 ≤3% 才正,择时版全负 |

系统三次都**没有自欺**,正确拦下了所有边际/劣质策略——这正是它的价值所在。完整收尾见 [`docs/project-outcome.md`](docs/project-outcome.md)。

**安全终态**:`dry_run: true`、无 approved 策略、`max_notional_quote` 全 0、无外部告警、无真实密钥入库。

---

## 成熟度阶梯

- **L0 Draft** — 设计文档与模拟数据
- **L1 Report-only** — 生成信号与报告,无下单权限
- **L2 Assisted** — paper trading 自动执行;小额实盘需人工确认 ← *脚手架已就绪,未启用*
- **L3 Unattended** — 仅已批准策略在严格风控下自动下单 ← *未进入*

当前停在 **L2 脚手架(dry-run)**,因无 approved 策略,实盘路径不可达。

## 系统能力一览

| 模块 | 内容 |
| --- | --- |
| `data/` | 历史 OHLCV、前向盘口快照、结构性 funding/basis;DuckDB + Parquet 存储;数据健康检测 |
| `features/` | 收益率、波动率、ATR、成交量变化、点差;含 lookahead 泄漏检测 |
| `strategies/` | 策略 SDK(`generate_signals`),动量突破 + 均值回归(带硬止损/时间止损) |
| `backtest/` | 保守成交模型、按 ATR 止损反推仓位、强制时间切片;walk-forward(purge/embargo、deflated Sharpe) |
| `verifier/` | Strategy Verifier + 策略注册表;maker-checker,策略不能自我批准 |
| `risk/` | 内在一致的熔断阶梯(单笔/连亏/24h/总回撤/业务止损)、kill switch |
| `execution/` | paper broker(订单状态机、幂等、崩溃恢复);live 适配器脚手架(dry-run 三重硬门禁) |
| `loops/` | loop 运行时、APScheduler 调度、心跳 / 死人开关 |
| `monitoring/` | dashboard 快照、告警(默认关)、交易账本、Fill-Fidelity 偏差 |
| `research/` | R/F 阶段研究:基准、诊断、稳健性电池、组合、carry 可行性 |

## 实盘下单的多重门禁(为什么默认安全)

真实订单要发出,必须**同时**满足:

1. `config/exchanges.yaml` 的 `dry_run` = `false`,且
2. 适配器 `allow_real_trading` = `true`(配置构造器**默认不设**,光改 config 不够),且
3. 存在有效 exchange client(无密钥则为 None,真实路径直接抛错)

此外:API key 必须无提现权限 + IP 白名单(`_validate_exchange_safety` 强制);永续/杠杆进入生产配置另需人工门禁;每个持仓需交易所服务器端止损;下单用 `clientOrderId` 幂等。

## 仓库结构

```text
crypto-quant-loop/
  crypto-quant-loop-development-plan.md   # 需求与设计(权威)
  CODEX-BUILD-LOOP.md                     # 自主构建协议 + S/R/F backlog
  STATE.md                                # 进度 / 断点续跑锚点
  config/                                 # 风控、成交、交易所、标的、策略、注册表
  src/crypto_quant_loop/                  # 实现(data/features/strategies/backtest/
                                          #   verifier/risk/execution/loops/monitoring/research)
  tests/                                  # 单元 / 集成 / 回测测试
  scripts/secret_scan.py                  # CI 密钥扫描
  docs/                                   # approvals、project-outcome、数据说明、校准、build-notes
  reports/  data/                         # 运行产物(gitignore,不入库)
```

## 运行

环境:Python ≥ 3.12,用 [uv](https://github.com/astral-sh/uv) 管理。

```bash
uv sync          # 安装依赖
make help        # 查看所有可用命令
make check       # lint + 类型 + 测试 + 密钥扫描(当前 83 passed)
```

命令行任务(均为只读 / 研究用途,走交易所**公开**数据,不下真实单):

```bash
make empty-loop        # 运行空 loop,写 loop-run-log.jsonl
make fetch-ohlcv       # 拉取历史 OHLCV 到 DuckDB/Parquet
make data-health       # 数据健康报告(缺口/重复/异常)
make fetch-structural  # 拉取 funding / basis 结构性数据
make carry             # 资金费率 carry 可行性分析
```

> ⚠️ **目录名含空格的坑**:本项目路径是 `…/Loop Engineering/`,空格会破坏 uv 的 editable 安装,导致直接 `uv run cql-*` 报 `ModuleNotFoundError: No module named 'crypto_quant_loop'`。
> `Makefile` 已用 `PYTHONPATH=src uv run --no-sync …` 绕过,所以**请用 `make` 命令**。若想脱离 make,手动跑也要带上前缀,例如:
> ```bash
> PYTHONPATH=src uv run --no-sync cql-data-health
> ```
> **永久解法**:把项目移到不含空格的路径(如 `~/code/QuantTrading`),之后普通 `uv run cql-*` 即可正常工作。

> 数据采集无需密钥。涉及账户/下单的真实联调需自行在本地 `.env` 提供**无提现 + IP 白名单**的 key,且仅在你明确解除 dry-run 门禁后——本仓库默认不做这件事。

## 技术栈

纯 Python,刻意精简:`ccxt`(交易所)、`duckdb` + `pyarrow`(存储)、`pydantic`(配置 schema)、`apscheduler`(调度)、`PyYAML`、`pytz`。开发:`ruff` + `mypy` + `pytest` + `pre-commit` + gitleaks(CI secret-scan)。

## 怎么构建出来的

S0–S14(构建)与 R/F(研究)两阶段,均由编码 agent 按 [`CODEX-BUILD-LOOP.md`](CODEX-BUILD-LOOP.md) 的内层 loop 协议(写→测→查→改→记录→下一步)自主推进,每步有测试、在人工门禁前停下。决策留痕见 [`docs/approvals.md`](docs/approvals.md)。

## 什么条件下值得重启 edge 追逐

不是"永不",是"现在 / 此规模不划算"。触发条件(见 `docs/project-outcome.md`):

1. 资金费率进入 mania regime(BTC 年化资金费持续 >25%,本轮 540 天未出现)
2. 本金量级显著提高
3. 拿到差异化 / 非公开信号源

## 免责声明

本项目用于量化系统**工程与研究**,非投资建议。加密货币交易风险极高,可能损失全部本金。任何实盘使用风险自负。

## 关键文档

- [开发计划](crypto-quant-loop-development-plan.md) · [构建协议](CODEX-BUILD-LOOP.md) · [项目收尾](docs/project-outcome.md) · [人工批准记录](docs/approvals.md)
