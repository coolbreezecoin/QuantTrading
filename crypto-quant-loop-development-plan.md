# 币圈量化系统开发计划：基于 Loop Engineering

> 目标：先建设一个可观测、可验证、可暂停的量化交易循环系统，而不是追求一开始就自动实盘盈利。所有实盘交易默认需要人工门禁，直到系统通过 L1/L2 验收。
>
> **第一版的成功标准是基础设施级的：系统可靠、可审计、可控、可一键停机，而不是稳定盈利。** 用两个公开的基础策略（均线突破、RSI 回归）在 BTC/ETH/SOL 现货上长期跑赢 buy-and-hold 的概率本就不高，所以严禁用"是否盈利"来评判这一阶段的成败——盈利能力是后续策略迭代的问题，本计划交付的是承载策略的安全骨架。

## 0. 默认假设

- 市场：先支持 Binance/OKX 的 BTC、ETH、SOL，现货优先，永续合约作为第二阶段。报价币种统一用 USDT（注意 USDT 脱锚是尾部风险，见 8 节）。
- **本金 = 1000 USDT，定位为"管道测试"，不指望盈利（A 案）**。基于这个本金的实算结论：
  - **交易所合规没问题**：单标的 15% 上限 = 150 USDT 名义，远高于交易所最小名义（~5 USDT），能开出合规仓位、能跑 L2 小额实盘。
  - **风控阶梯在此本金下基本休眠**：15% 仓位上限会先于"0.75% 单笔风险"截死仓位，真实单笔风险只有约 0.15%-0.33%（BTC/ETH/SOL 因 ATR 不同而异），所以"连亏 3 笔→cooldown"等阶梯实际约只亏 0.5%-0.9%，远到不了设计阈值。**这是有意接受的**：1000 USDT 阶段的目标是硬化 signal→order→fill→position→对账→止损这条管道，等本金涨上去再让 0.75% 规则与熔断阶梯真正生效。
  - **手续费是头号杀手**：150 USDT 名义、taker 往返 ~0.2%（BNB 抵扣 ~0.15%）≈ 每笔 0.3 USDT，会吃掉 1h 主流币策略的大部分边际收益。所以这个体量**严禁用盈亏评判系统**。
  - 落地三条约束：**先只跑 BTC 单标的**（别分散到 3 个，否则仓位更碎、费用占比更高、样本更稀）；**加 min-notional 地板**（风险法算出的名义 < 20-30 USDT 就跳过该信号，避免费用主导的微型单）；**开 BNB 手续费抵扣**，均值回归尽量挂限价以不吃点差。
  - 本金增长后再重新做一次本测算，并视情况切到 B 案（放宽单标的名义上限、让风险预算当家）。
- 周期：第一版用 1h K 线，之后扩展到 15m/5m。
- 交易模式：L1 只报告信号，L2 paper trading + 人工确认小额实盘，L3 才允许受限自动交易。
- 策略：第一版只做动量/趋势、均值回归两个基础策略，不做复杂多因子和机器学习。
- 技术栈：Python、ccxt、DuckDB/Postgres、Parquet、Polars/Pandas、vectorbt/backtrader、FastAPI、APScheduler/Prefect、Prometheus/Grafana。

## 1. Loop Engineering 映射

| Loop Engineering 原语 | 量化系统中的落地方式 |
| --- | --- |
| Automations / Scheduling | 数据采集、信号生成、回测验证、风控扫描、复盘报告的定时任务 |
| Worktrees | 策略研究、参数实验、执行引擎改动使用独立分支/环境，不污染主系统 |
| Skills | `SKILL.md`/规则文档记录交易规则、回测约束、风控红线、交易所 API 约定 |
| Plugins & Connectors | 交易所 API、数据库、告警渠道、GitHub/任务系统、监控系统 |
| Sub-agents / Maker-Checker | 策略生成者不能批准自己的策略；独立 verifier 检查回测、滑点、风险、订单 |
| Memory / State | `STATE.md`、策略注册表、组合状态、run log、交易审计日志 |

对应成熟度：

- L0 Draft：只有设计文档和模拟数据。
- L1 Report-only：系统生成信号和报告，但没有任何下单权限。
- L2 Assisted：paper trading 自动执行；小额实盘需要人工确认。
- L3 Unattended：只允许已批准策略在严格风控下自动下单。

## 2. 系统模块

### 2.1 数据层

- 行情：OHLCV、成交量、盘口快照、资金费率（仅永续阶段用）、未平仓量。
- **采集方式**：OHLCV/资金费率走 REST 历史拉取；**盘口深度用 websocket 流式订阅，不要用 REST 高频轮询**（3 个标的 + 高频会迅速撞 Binance 权重限频）。所有调用做限频退避。
- **盘口只能前向采集、无法回填**：历史 L2 盘口拿不到，所以盘口快照库是从上线那天起向前积累的，供前向 paper 撮合用；历史回测不依赖它（见 2.3）。
- 存储：原始数据写 Parquet，标准化数据写 DuckDB/Postgres。
- 校验：缺口、重复 K 线、异常价格、时区、交易所停机。
- 验收：核心交易对最近 90 天数据完整率大于 99%，每次采集有审计日志。（注意：90 天是**数据健康/完整率**窗口，不是策略验证所需的历史长度——后者见 2.3。）

### 2.2 策略与特征层

- 策略接口：`generate_signals(data, state) -> signals`。
- 第一版策略：
  - 趋势/动量：均线突破、Donchian breakout、收益率动量。
  - 均值回归：RSI/Bollinger band 回归，但必须过滤趋势行情。
- 特征：收益率、波动率、ATR、成交量变化、资金费率、价差。
- 验收：同一数据与同一参数可复现同一信号。

### 2.3 回测与验证层

- 必须扣除手续费、滑点、资金费率和最小订单限制。
- 防止 lookahead bias：策略只能读取当前时间点以前的数据。
- **成交真实性（最重要的一条）**：禁止默认"按收盘价全额成交"。区分两种场景，因为它们能拿到的数据根本不同：
  - **历史回测**：交易所**不提供历史 L2 盘口深度，无法回填**，所以历史回测拿不到真实盘口。必须用基于"点差 + ATR + 成交量"标定的**保守滑点/冲击成本模型**，并在下一根开盘价（而非信号收盘价）成交，宁可高估成本。不要假装历史回测有盘口撮合。
  - **前向 paper / dry-run**：此时才有数据层实时采集的**真实盘口快照**，用它做撮合——市价单按盘口深度算冲击成本，限价单按是否被触及判断成交。两者偏差由 Fill-Fidelity Loop 量化，并据此反过来校准回测的滑点模型。
- **手续费按 maker/taker 分别建模，并与订单类型绑定**：taker（市价/突破）约 0.04%-0.1%，maker（限价/挂单）更低甚至有返佣。动量/突破用市价单（吃 taker），均值回归尽量用限价单（争取 maker）——回测必须按各策略实际用的订单类型扣费，否则费用估计系统性偏低。
- **遵守交易所 filter**：下单要满足 `MIN_NOTIONAL`、`LOT_SIZE`/步长、`PRICE_FILTER`/tick；仓位规模按这些过滤后再校验，小账户上这些是硬约束（见 0. 默认假设的最小本金）。
- 输出指标：年化收益、Sharpe、Sortino、最大回撤、胜率、盈亏比、换手率、交易次数、手续费占比。
- **验证所需历史长度：至少 1-2 年的 1h 历史，且必须覆盖牛市、熊市、震荡至少各一段。** 90 天（约 2000 根 K 线、基本是单一行情）远不足以验证一个 1h 策略，只会得到行情幻觉。1-2 年的历史 OHLCV 在交易所免费可得，没有理由不拉满。
- **验证方法：用 walk-forward 滚动样本外，而非单次 IS/OOS 切分。**
  - 滚动多个"训练窗口 → 紧邻的样本外窗口"，统计每段 OOS 的表现。
  - 相邻窗口之间做 purge + embargo，防止信息泄漏（用到滚动特征、重叠持仓时尤其必要）。
  - 把"参数搜索"和"验收门槛"隔离：搜参只能在 IS 内进行，门槛只在它从未见过的 OOS 段上评估。
  - **记录参数搜索的试验次数**：试得越多，最好 Sharpe 越虚高。优先选少量稳健参数（参数平台而非尖峰），并用 deflated Sharpe 或对试验次数的惩罚来折价，避免多重检验自欺。
- 验收门槛建议（注意：这些是**诊断指标**，不是供参数拟合的目标函数）：
  - 多段滚动 OOS 中，IS→OOS 的绩效衰减幅度在阈值内（如 Sharpe 衰减不超过 50%），且多数 OOS 段为正——而非只看"一次样本外为正"。
  - 在牛/熊/震荡各段都不致命亏损（允许某段平庸，但不允许某段爆仓）。
  - 最大回撤小于 8%-12%。
  - 交易次数足够多，避免小样本幻觉。
  - 扣费后仍有效。
  - 最近 30 天没有明显失效。

### 2.4 执行层

- 第一阶段只支持 paper broker。
- 第二阶段接入交易所，但 API key 禁止提现，开启 IP 白名单。
- 订单管理：下单、撤单、重试、成交回报、部分成交、订单状态 reconciliation。
- **保护性止损必须挂在交易所服务器端**：每个持仓一旦成交，立刻在交易所下一个 server-side 止损单（stop/OCO）。绝不能让止损只活在自己的进程里——一旦 VM 宕机、进程崩溃、网络中断，本地止损就失效，持仓裸奔。这是头号实盘安全要求。
- **下单幂等**：每个订单带客户端自定义 `clientOrderId`，重试时复用同一 ID。否则"超时→重试"会变成重复下单、双倍仓位。提交逻辑必须幂等。
- **重启以交易所为准对账**：进程重启后，先从交易所拉取真实持仓与挂单，与本地 state 对账，以交易所为准修正，再恢复交易。本地 state 要持久化以支持崩溃恢复，不能只靠内存或 `STATE.md` 文档。
- 验收：paper 与 live dry-run 都能完整记录 signal -> order -> fill -> position；崩溃重启后能正确恢复并对账。

### 2.5 风控层

硬性规则优先于策略信号。下面这套阈值经过一次**内在一致性推演**，确保各级熔断"先轻后重、不互相吞没"——较轻的限制（cooldown）一定先于较重的限制（日内熔断、总回撤暂停）触发，而不是被后者抢先盖掉：

- **单笔风险固定为净值 0.75%**（不用 1%，给下面的连亏 cooldown 留出触发空间）。
  - **"0.75% 风险"必须有止损才有定义**：仓位规模 = 净值 × 0.75% ÷ (入场价 − 止损价)，止损距离用 ATR 的倍数（如 1.5×-2×ATR）。没有止损就没有"单笔风险"这个量，规则会落空。
  - **均值回归没有自然止损**：必须额外配硬止损 + 时间止损（持仓超过 N 根 K 线未回归就平），否则一笔逆势单可以吃掉远超 0.75% 的风险。
  - **注意 1000 USDT 本金下本条阶梯休眠**：15% 仓位上限会先截死仓位，真实单笔风险约 0.15%-0.33%，cooldown/日内熔断难以按设计触发（见 0. 默认假设的 A 案）。本金增长后这些阈值才真正生效。
- **连续 3 笔亏损（约 -2.25%）→ 进入 cooldown**（暂停开新仓 N 小时）。2.25% < 3% 的日内熔断线，因此这条仍会先触发。
- **滚动 24h 亏损超过 3% → 当窗口内停止开新仓**。约等于 4 笔满额止损，确保 cooldown 有机会先生效。
- **总回撤（相对净值高点）超过 6% → 暂停所有策略，转人工复核**。
- **业务层硬止损：累计亏损达到分配资金的 15%-20% → 整个系统停机，重新评估是否真有 edge**，而不是"再调一版参数"。这是防沉没成本陷阱的人类决策线，独立于技术熔断。
- **"单日"的定义**：加密市场 24/7 无收盘，统一采用**滚动 24h 窗口**做风控判断；审计记录另以 UTC 自然日为对账边界。
- 单标的最大仓位不超过净值 10%-15%。
- **组合层方向性敞口上限：BTC/ETH/SOL 在 risk-off 时相关性趋近 1，"单标的 ≤15%"挡不住三者同时满仓 = 实质 ~45% 的单一 beta 暴露。** 因此追加一条：组合总方向性（beta 调整后）净敞口不超过净值 20%-25%。
- 初期不使用杠杆；永续阶段杠杆上限 1x-2x。
- 交易所 API 异常、数据缺口、价格偏离过大时自动熔断。

## 3. 核心 Loops

| Loop | Cadence | L1 行为 | L2/L3 行为 |
| --- | --- | --- | --- |
| Data Health Loop | 5m-1h | 检查数据完整性并报告 | 异常时暂停信号和执行 |
| Strategy Research Loop | 1d | 生成候选策略报告 | 只允许进入候选池，不可直接交易 |
| Signal Loop | 15m-1h | 生成信号并写入 state | 只处理 approved 策略信号 |
| Verifier Loop | 每次策略/信号变更 | 独立验证回测与风险 | 拒绝未通过策略 |
| Execution Loop | 1m-5m | paper order/dry-run | 受限实盘下单 |
| Risk Sentinel Loop | 30s-1m | 报告风险状态 | 可撤单、暂停、平仓 |
| Fill-Fidelity Loop | 1d | 对比回测引擎"预期成交价/量" vs paper/dry-run 的"实际成交"，量化偏差 | 偏差超阈值则阻止该策略升级 |
| Post-trade Review Loop | 1d | 复盘交易与偏差 | 降级或暂停失效策略 |

> **Fill-Fidelity Loop 是上 L3 的真实门禁。** "连续 30 天稳定"信息量不足；能不能放开自动交易，取决于"同一信号在回测里的预期成交 vs 实盘/dry-run 的实际成交"偏差有多大。这个偏差才是回测可信度的直接度量。

> **心跳 / 死人开关（dead-man's switch）**：每个 loop 每次运行写心跳；若某 loop 超过预期 cadence 的 N 倍仍无心跳（进程静默死掉、卡死、被 OOM），独立监控立即告警，并对持仓类 loop 触发保守动作（停止开新仓，必要时依赖交易所端止损保护）。无人值守系统最常见的失效不是"判断错"，而是"程序悄悄死了没人知道"。

> **kill switch 的具体动作要写死**：触发后 = 撤销所有挂单 + 设置全局 halt 标志阻止新单 +（可配置）按市价平掉所有持仓。人工和自动（风控 Sentinel）都能触发。L3 前必须演练。

优先级：Risk Sentinel > Execution > Data Health > Signal > Verifier > Fill-Fidelity > Strategy Research > Post-trade Review。

## 4. 项目结构

```text
crypto-quant-loop/
  LOOP.md
  STATE.md
  loop-budget.md
  loop-run-log.jsonl
  config/
    exchanges.yaml
    symbols.yaml
    risk-policy.yaml
    strategies.yaml
  data/
    raw/
    processed/
  src/
    data/
    features/
    strategies/
    backtest/
    verifier/
    execution/
    risk/
    loops/
    monitoring/
  tests/
    unit/
    integration/
    backtest/
  reports/
  docs/
    trading-rules.md
    strategy-approval.md
    incident-runbook.md
```

## 5. 状态与审计文件

- `LOOP.md`：活跃 loop、频率、权限、人工门禁、kill switch。
- `STATE.md`：当前系统状态、人类待办、暂停原因、最近决策。
- `loop-run-log.jsonl`：每次 loop 运行的 append-only 记录。
- `strategy-registry.yaml`：策略版本、状态、参数、审批人、资金上限。
- `risk-policy.yaml`：所有风控红线，策略不得覆盖。
- `trade-ledger.parquet`：信号、订单、成交、仓位、PnL 的审计链。
- `fill-fidelity.parquet`：每笔信号的"回测预期成交 vs 实盘/dry-run 实际成交"对比与偏差，是上 L3 的依据。

## 6. 10-14 周实施计划

> 说明：相比最初的 8-12 周估计上调到 10-14 周。主要把回测引擎从 1.5 周扩到约 3 周、实盘订单状态机/reconciliation 从 2 周扩到 3 周——这两块是量化系统最容易被低估、也最容易因赶工埋雷的地方。

### 第 1 周：框架与安全边界

- 建仓库、配置 Python 项目、测试框架、lint、CI。
- 写 `LOOP.md`、`STATE.md`、`risk-policy.yaml`。
- 明确禁止项：不自动改 API key、不自动提高仓位、不自动开启提现/杠杆。
- **密钥与资金安全工程化（第 1 周就定死，别拖到实盘）**：
  - 密钥只存于环境变量 / KMS / 密钥管理器，**绝不进 git**；区分只读 key 与交易 key。
  - CI 加入 secret-scan（如 gitleaks），防止密钥误提交。
  - **时钟与时区**：本地与交易所服务器时间漂移会直接影响下单和 K 线对齐——配置 NTP 校准，调用接口统一处理 `recvWindow`/时间戳。
- 交付物：可运行的空 loop、run log、风控配置、项目骨架、secret-scan 通过的 CI。

### 第 2 周：数据系统

- 接入 ccxt，采集 OHLCV、资金费率、盘口快照（盘口快照后续供回测撮合使用，务必落库）。
- 建 Parquet + DuckDB/Postgres 存储。
- 实现 Data Health Loop。
- 交付物：90 天历史数据、数据质量报告、缺口自动检测。

### 第 3-5 周：回测引擎与策略 SDK（这里别压缩）

> 一个**没有 lookahead bias、能正确处理资金费率/部分成交/盘口撮合**的回测引擎本身就是 2-3 周的工作。用 vectorbt/backtrader 可加速，但必须吃透它们各自的成交假设，否则等于把 bias 藏进第三方库。

- 实现策略接口、费用/滑点模型、基于盘口的成交撮合、基础回测 runner。
- 实现 walk-forward 滚动验证框架（含 purge + embargo）。
- 实现动量和均值回归两个策略。
- 加入 lookahead bias 检查（强制时间切片，并写测试用例验证泄漏会被捕获）。
- 交付物：可复现回测报告、滚动 OOS 报告、策略参数配置化。

### 第 6 周：Verifier 与策略注册

- 实现 Strategy Verifier：回测指标、滚动 OOS 衰减、手续费、交易次数、最大回撤检查。
- 建 `strategy-registry.yaml`，只有 approved 策略能进入 Signal Loop。
- 交付物：候选策略不能绕过 verifier。

### 第 7-8 周：Paper Trading 与执行链

- 实现 paper broker、订单状态机、基于盘口的成交模拟、仓位管理。
- Signal Loop 接入 Execution Loop，但只 paper。
- 交付物：完整链路 signal -> order -> fill -> position -> PnL。

### 第 9 周：监控、告警、复盘

- Prometheus/Grafana 或轻量 dashboard。
- Telegram/Discord/Slack 告警。
- 每个 loop 写心跳 + 死人开关告警（loop 静默死掉立即报警）。
- Post-trade Review Loop 与 Fill-Fidelity Loop 输出日报（含回测/实盘成交偏差）。
- 交付物：数据健康、策略表现、风险状态、订单异常、成交偏差、loop 存活都可见。

### 第 10-12 周：L2 小额实盘（订单状态机别低估）

> 订单状态机的边界情况（超时后到底成没成交、部分成交后撤单、限频退避）是实盘最磨人的部分，真实工时常翻倍，所以给足 3 周。

- 接入交易所 live API，但使用子账户、小资金、禁止提现、IP 白名单。
- 默认人工确认后下单。
- 持仓成交后立即挂交易所服务器端保护性止损；下单用 clientOrderId 幂等。
- 做订单 reconciliation 和异常撤单，覆盖超时/部分成交/限频退避等边界；重启以交易所为准对账。
- 交付物：小额实盘跑通，所有订单可审计，reconciliation 无悬挂订单，崩溃重启可恢复。

### 第 13-14 周：L3 候选，不急着放开

- 连续 30 天 paper 或小额 L2 稳定、且 **Fill-Fidelity 偏差在阈值内**后，才考虑 L3。
- 只允许 approved 策略、approved symbol、approved max notional。
- 滚动 24h 亏损、总回撤、数据异常、API 异常触发自动暂停。
- 交付物：可以无人值守，但默认小资金、强熔断。

## 7. 验收标准

### L1 Report-only

- 无实盘 API 写权限。
- 数据完整率大于 99%。
- 每天生成策略和风险报告。
- Verifier 可以拒绝不合格策略。
- `STATE.md` 和 run log 每次更新。

### L2 Assisted

- paper trading 至少 2 周无链路错误。
- 小额实盘需要人工确认。
- API key 无提现权限，IP 白名单开启。
- 所有实盘订单都有 signal/order/fill/position 审计链。
- 每个持仓都有交易所服务器端保护性止损；下单用 clientOrderId 幂等；崩溃重启能以交易所为准对账恢复。
- 风控系统可以阻止下单。

### L3 Unattended

- 至少 30 天稳定记录。
- **Fill-Fidelity 偏差在阈值内**：回测预期成交与实盘实际成交的差异已量化且可接受（这比单纯"30 天稳定"更能证明回测可信）。
- kill switch 演练通过。
- 风控 Sentinel 可自动撤单和暂停策略。
- **业务层硬止损线已配置并演练**：累计亏损达分配资金的 15%-20% 时整体停机、转人工重评，而非自动续命。
- 任何策略参数、仓位上限、交易标的变更都需要人工审批。
- 周报必须由人阅读，避免 comprehension debt。

## 8. 主要风险与控制

- 过拟合：walk-forward 滚动样本外 + purge/embargo，搜参与验收严格隔离；禁止只看历史最佳参数。
- Lookahead bias：回测引擎强制时间切片，并有测试用例验证泄漏会被捕获。
- 流动性幻觉：按盘口深度和成交量限制订单规模。
- 滑点低估：paper 阶段即用真实盘口撮合 + 冲击成本，禁止按收盘价全额成交。
- 回测失真：Fill-Fidelity Loop 量化回测 vs 实盘成交偏差，超阈值不得升级。
- 相关性集中：BTC/ETH/SOL 高相关，单标的上限挡不住组合 beta 暴露，需组合层方向性敞口上限。
- API 风险：超时、限频、部分成交都要有状态机。
- 下单重复：超时重试用 `clientOrderId` 保证幂等，杜绝双倍仓位。
- 单点故障：自有进程/VM 宕机时本地止损失效——保护性止损一律挂交易所服务器端；loop 配心跳/死人开关。
- 密钥与时钟：密钥不进 git、区分读写 key、CI secret-scan；NTP 校准 + `recvWindow` 处理。
- 数据污染：数据缺口触发暂停，不允许用坏数据交易。
- 辖区与合规：交易所可能地域限制 / 需 KYC / 单方面停服或下架；USDT 脱锚是尾部风险。这些不在代码控制内，需在 runbook 里有应对预案。
- 自动化失控：最大尝试次数、人工门禁、kill switch。
- 沉没成本陷阱：业务层硬止损（累计亏损 15%-20% 停机重评），不靠"再调一版参数"续命。
- AI 误判：AI 可做研究和报告，不直接越过 deterministic verifier 与风控下单。

## 9. 第一版 MVP 范围

第一版只做这些：

- **实盘先只跑 BTC 单标的**（1000 USDT / A 案，见 0. 默认假设）；回测/paper 可同时覆盖 BTC/ETH/SOL，跑顺、且本金增长后再把 ETH/SOL 纳入实盘。
- 1h K 线。
- 现货或无杠杆永续。
- 两个策略：动量、均值回归。
- L1 report-only + paper trading。
- 每日策略报告、风险报告、交易复盘。
- 不做自动实盘，不做 ML，不做跨交易所套利。

## 10. 参考来源

- Loop Engineering repo: https://github.com/cobusgreyling/loop-engineering
- Primitives: https://github.com/cobusgreyling/loop-engineering/blob/main/docs/primitives.md
- Loop Design Checklist: https://github.com/cobusgreyling/loop-engineering/blob/main/docs/loop-design-checklist.md
- Operating Loops: https://github.com/cobusgreyling/loop-engineering/blob/main/docs/operating-loops.md
- Safety: https://github.com/cobusgreyling/loop-engineering/blob/main/docs/safety.md
- Failure Modes: https://github.com/cobusgreyling/loop-engineering/blob/main/docs/failure-modes.md
- Anti-patterns: https://github.com/cobusgreyling/loop-engineering/blob/main/docs/anti-patterns.md

## 11. 附录：配置示例

> 以下是把前文规则落成机器可读配置的起点。**标注 `# 占位` 的值都需要用前向 paper 的 Fill-Fidelity 数据校准后再上线**，不要直接当最终参数。

### 11.1 `risk-policy.yaml`（风控红线，策略不得覆盖）

```yaml
# 账户与运行模式
account:
  equity_quote: USDT
  equity_size: 1000          # 当前本金
  mode: plumbing_test        # A 案：管道测试，不以盈亏评判（见 0. 默认假设）
  # 本金增长后改 mode: live_sized，并重做最小本金测算、考虑切 B 案

# 标的：实盘与研究分离
symbols:
  live: [BTCUSDT]                       # A 案：实盘先只跑 BTC 单标的
  research: [BTCUSDT, ETHUSDT, SOLUSDT] # 回测/paper 可全覆盖

# 杠杆
leverage:
  spot_max: 0                # 现货无杠杆
  perp_max: 1                # 永续阶段上限，初期 1x；最高 2x 需人工审批

# 仓位规模：由止损反推（"0.75% 风险"必须有止损才有定义）
position_sizing:
  single_trade_risk_pct: 0.0075   # 净值 0.75%
  stop:
    method: atr
    atr_period: 14
    atr_mult: 2.0                 # 止损距离 = 2×ATR
  # 名义 = equity * risk_pct / (止损距离占价比)
  single_symbol_notional_cap_pct: 0.15   # 单标的名义上限 15%（1000U 下此条主导，风险阶梯休眠）
  portfolio_directional_cap_pct: 0.25    # 组合 beta 调整后净敞口上限 25%
  min_notional_floor_quote: 25           # 风险法名义 < 25 USDT 的信号直接跳过，避免费用主导的微型单

# 熔断阶梯（先轻后重，互不吞没；1000U 下休眠，本金增长后生效）
circuit_breakers:
  consecutive_losses:
    count: 3                 # 连亏 3 笔（满额时约 -2.25%）
    cooldown_hours: 12       # 占位：暂停开新仓时长
  rolling_24h_loss_halt_pct: 0.03    # 滚动 24h 亏损 >3% → 当窗口停开新仓
  total_drawdown_pause_pct: 0.06     # 相对净值高点回撤 >6% → 暂停所有策略转人工
  business_hard_stop_pct: 0.175      # 累计亏损 ~17.5% → 整体停机重评（占位，区间 15-20%）
  loss_window: rolling_24h           # 24/7 无收盘，用滚动 24h；对账边界用 UTC 自然日

# 自动熔断触发器（与盈亏无关的运行态）
auto_halt_on:
  data_gap: true             # 数据缺口
  api_error: true            # 交易所 API 异常
  price_deviation_bps: 200   # 占位：价格偏离参考 >2% 视为异常
  loop_heartbeat_miss_factor: 3   # 某 loop 超过 cadence 的 3 倍无心跳 → 告警 + 保守动作

# 均值回归专属：无自然止损，需时间止损
mean_reversion:
  time_stop_bars: 24         # 占位：持仓超过 24 根 1h 未回归则平

# kill switch 动作
kill_switch:
  cancel_all_open_orders: true
  flatten_positions: true    # 可配置：是否市价平掉所有持仓
  set_global_halt: true
  triggers: [manual, risk_sentinel]
```

### 11.2 `fills.yaml`（成交与费用模型）

```yaml
# 历史回测：拿不到历史 L2 盘口，用保守滑点模型，宁可高估成本
backtest_historical:
  entry_price: next_bar_open       # 在下一根开盘价成交，不用信号收盘价
  cross_half_spread_bps:           # 市价单穿越半个点差（占位，按标的）
    BTCUSDT: 1.0
    ETHUSDT: 1.5
    SOLUSDT: 2.5
  conservative_buffer_bps: 5       # 占位：1h 路径不可知的额外保守惩罚
  impact_model: linear
  impact_coeff_bps_per_1pct_adv: 10  # 占位：吃掉 1% ADV 的冲击 bps（150U 名义下几乎可忽略）
  calibration_note: "用前向 paper 的 Fill-Fidelity 偏差回校这些 bps"

# 前向 paper / dry-run：有实时盘口快照，按盘口撮合
paper_forward:
  use_orderbook_snapshot: true
  market_order: walk_the_book      # 市价单按盘口深度逐档吃，算真实冲击
  limit_order_fill: touched        # 限价单按是否被触及判断成交

# 手续费（Binance spot base 档；maker/taker 与订单类型绑定）
fees:
  taker_bps: 10
  maker_bps: 10
  use_bnb_discount: true           # 约 -25% → 有效 ~7.5 bps
  order_type_by_strategy:
    momentum: market               # 吃 taker
    mean_reversion: limit          # 争取 maker / 至少不吃点差
  funding_applies: perp_only       # 资金费率只在永续阶段计入
```

### 11.3 校准回路

1. 先用上面的占位值跑历史回测与前向 paper。
2. Fill-Fidelity Loop 每日对比"回测预期成交 vs paper 实际成交"，输出各标的的真实滑点/费用 bps。
3. 用实测 bps 回填 `fills.yaml` 的占位项，重跑回测验证策略是否仍成立（很多策略扣真实成本后会失效，这正是要提前发现的）。
4. 本金增长后改 `risk-policy.yaml` 的 `account.mode` 与仓位上限，重做最小本金测算。
