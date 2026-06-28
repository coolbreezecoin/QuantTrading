# Codex Build Loop — 自主开发执行手册

> 给执行型编码 agent（Codex）的指令。目标：以 loop engineering 的方式，一步步、不间断地把本量化系统从空仓库构建到"可跑 paper trading + 完整监控"的程度。**触及真实资金/密钥/实盘下单的部分必须停下来等人工批准，其余全部自主完成。**

## 0. 权威来源与本文定位

- 需求与设计的唯一权威：`crypto-quant-loop-development-plan.md`（下称"计划"）。
- 风控与成交参数的唯一权威：`config/risk-policy.yaml`、`config/fills.yaml`。配置与计划第 11 节冲突时**以 `config/` 为准**。
- 本文件只定义"怎么执行"，不重复"做什么"。每个 step 的细节回到计划对应章节。
- 技术栈以计划 0 节为准：Python、ccxt、DuckDB/Postgres、Parquet、Polars/Pandas、vectorbt/backtrader、FastAPI、APScheduler/Prefect、Prometheus/Grafana。

## 1. 操作契约（不可逾越的红线）

这些是硬约束，任何 step 都不得违反，违反即视为失败：

1. **绝不触碰真实资金或下真实订单**，除非到达明确标注 `[人工门禁]` 的 step 且已获人工批准。默认一切为 paper / dry-run。
2. **绝不把密钥写进代码或提交进 git**。密钥只从环境变量/密钥管理器读取。CI 必须有 secret-scan（gitleaks），扫到即 fail。
3. **绝不让 AI 越过 deterministic verifier 与风控下单**。AI 只做研究、生成、报告。
4. **绝不削弱风控来让测试通过**。测试失败就改实现，不准改红线配置迁就代码。
5. **绝不假装历史回测有 L2 盘口**（交易所不提供历史盘口）。历史回测用 `fills.yaml` 的保守滑点模型；盘口撮合只用于前向 paper。
6. **每个持仓在实盘阶段必须有交易所服务器端止损**；下单必须用 `clientOrderId` 幂等。（实现代码现在就写，启用在人工门禁后。）
7. **不引入未声明的外部网络副作用**（发消息、发邮件、调用付费 API）без 明确配置开关，默认关闭。

## 2. 内层 Loop 协议（每个 step 都这样做）

对 backlog 里的**每一个 step**，执行以下闭环，然后自动进入下一个 step，**中间不停顿**（除非命中 §5 门禁或 §7 停止条件）：

```
1. SELECT  读 STATE.md 与本 backlog，选下一个未完成且依赖已满足的 step。
2. DESIGN  在 docs/build-notes/<step-id>.md 写 5-15 行设计要点（接口、数据流、边界）。
3. BRANCH  开独立分支/worktree：build/<step-id>，不污染主干。
4. IMPLEMENT  实现最小可用版本，代码风格与既有代码一致。
5. TEST  先写或同步写测试，然后跑全套：
         - 单元测试 pytest
         - lint（ruff/flake8）+ 类型检查（mypy/pyright）
         - 该 step 的 Definition of Done 里列的专项测试
6. SELF-REVIEW  自查：正确性 bug + 可简化/可复用之处；该 step 的红线没被违反。
7. FIX  有失败或问题就改，回到第 5 步。单 step 最多 6 轮；仍不过 → §7。
8. RECORD  DoD 全绿后：
         - 更新 STATE.md（当前 step、状态、下一步、未决问题）
         - 追加一行到 build-log.jsonl（step-id、结果、测试数、耗时、commit）
         - commit（信息写清做了什么）；合回主干。
9. NEXT  无条件进入下一个 step。
```

**"不间断"的含义**：完成一个 step 后立刻开始下一个，不要停下来问"要不要继续"。只有命中 §5 人工门禁或 §7 硬阻塞才停。

## 3. 状态与续跑

- `STATE.md`：人类可读的当前态——已完成 step、进行中 step、下一步、阻塞项、未决问题。每个 step 结束必更新。这是**断点续跑的依据**：任何时候重启，先读 STATE.md 决定从哪继续。
- `build-log.jsonl`：append-only，每个 step（及每轮重试）一条结构化记录。
- `docs/build-notes/`：每个 step 的设计要点，供后续 step 和人类回溯。
- 续跑规则：重启时**不重做已标 done 的 step**；从 STATE.md 指向的 step 继续。

## 4. 构建 Backlog（有序步骤）

每个 step 自包含、可独立验收。`DoD` = Definition of Done，必须全部满足才算完成。带 `[人工门禁]` 的 step **写代码可以，但启用/上线必须停下等人**。

### S0 — 仓库骨架与工具链
- 产物：按计划第 4 节建 `src/` 目录树；`pyproject.toml`、依赖锁定；ruff + mypy + pytest 配置；pre-commit；CI（lint + 类型 + 测试 + gitleaks secret-scan）；可运行的空 loop 入口。
- DoD：`pytest` 通过（哪怕只有占位测试）；CI 全绿；secret-scan 生效；一条空 loop 能起停并写 `loop-run-log.jsonl`。

### S1 — 配置加载与校验
- 产物：用 pydantic 为 `risk-policy.yaml`、`fills.yaml`、`exchanges.yaml`、`symbols.yaml`、`strategies.yaml` 建 schema；加载器；非法配置直接拒绝并报清晰错误。
- DoD：加载现有 `config/*.yaml` 成功；故意写错的配置被拒并有可读报错；schema 测试覆盖必填项与取值范围。

### S2 — 数据层：历史 OHLCV
- 产物：ccxt REST 拉取 BTC/ETH/SOL 的 1h OHLCV，**至少 1-2 年、覆盖牛熊震荡**（计划 2.3）；写 Parquet + DuckDB；限频退避。
- DoD：研究标的历史落库；可复现拉取；数据质量报告生成。

### S3 — 数据层：Data Health Loop
- 产物：缺口、重复 K 线、异常价格、时区、停机检测；最近 90 天完整率 >99% 的健康检查；异常时按 `risk-policy.yaml` 的 `auto_halt_on.data_gap` 触发暂停信号。
- DoD：注入缺口/重复的测试能被检出；健康报告每次运行可见。

### S4 — 数据层：盘口与资金费率采集器（前向）
- 产物：websocket 盘口快照采集器（**前向、不回填**），落库供 paper 撮合；资金费率采集（标记 perp_only）。
- DoD：盘口快照按 schema 落库；采集器掉线能重连；明确文档化"历史不可回填"。

### S5 — 特征库
- 产物：收益率、波动率、ATR、成交量变化、价差等；纯函数、确定性。
- DoD：同输入同输出（复现测试）；**无 lookahead 测试**：构造一个会泄漏未来信息的用例，断言被检出。

### S6 — 策略 SDK 与两个策略
- 产物：`generate_signals(data, state) -> signals` 接口；动量（均线突破/Donchian/收益率动量）与均值回归（RSI/Bollinger，带趋势过滤 + 硬止损 + 时间止损，见 `risk-policy.yaml`）。
- DoD：同数据同参数复现同信号；均值回归带止损与 `time_stop_bars`；参数全部走配置。

### S7 — 回测引擎
- 产物：按 `fills.yaml.backtest_historical` 实现保守滑点（下一根开盘价 + 半点差 + 缓冲 + 冲击）；按 `risk-policy.position_sizing` 由 ATR 止损反推仓位、套用单标的/组合上限与 min-notional 地板；强制时间切片防 lookahead；输出计划 2.3 的全套指标。
- DoD：回测报告可复现；**lookahead 注入测试**断言被引擎拦截；费用按 maker/taker 与订单类型扣减；min-notional 地板生效（过小信号被跳过）。

### S8 — Walk-forward 验证框架
- 产物：滚动 IS→OOS、purge + embargo；记录参数搜索试验次数；deflated Sharpe 或试验惩罚；搜参与验收严格隔离。
- DoD：在 1-2 年历史上输出多段滚动 OOS 报告；IS→OOS 衰减指标可得；牛/熊/震荡分段表现可见。

### S9 — Verifier 与策略注册表
- 产物：Strategy Verifier 检查（OOS 衰减、最大回撤、交易次数、扣费后有效、近 30 天未失效）；`strategy-registry.yaml`，只有 approved 策略能进 Signal Loop。
- DoD：候选策略**无法绕过** verifier；被拒策略与原因入日志；maker-checker——策略生成者不能批准自己。

### S10 — 风控引擎
- 产物：实现 `risk-policy.yaml` 全部红线——仓位规模、单标的/组合敞口上限、连亏 cooldown、滚动 24h 熔断、总回撤暂停、业务硬止损、运行态自动熔断（数据缺口/API/心跳/价格偏离）；kill switch 动作。
- DoD：每条熔断有单元测试；**阶梯顺序测试**：构造亏损序列断言 cooldown 先于日内熔断触发；kill switch 演练测试（撤单 + halt + 可选平仓）。

### S11 — Paper Broker 与订单状态机
- 产物：paper broker；订单状态机（下单/撤单/重试/部分成交/成交回报/reconciliation）；`clientOrderId` 幂等；前向盘口撮合；崩溃恢复（重启以交易所/账本为准对账）；仓位与 PnL 管理。
- DoD：完整链路 signal→order→fill→position→PnL 跑通；**幂等测试**（重试不产生双倍仓位）；**崩溃重启测试**（恢复后无悬挂订单、对账一致）。

### S12 — Loops 运行时
- 产物：调度器（APScheduler/Prefect）跑计划第 3 节所有 loop（Data Health/Signal/Verifier/Execution-paper/Risk Sentinel/Fill-Fidelity/Post-trade Review）；按优先级；每个 loop 写心跳 + `loop-run-log.jsonl`；死人开关（超 cadence×N 无心跳即告警 + 保守动作）。
- DoD：各 loop 按 cadence 运行；**心跳/死人开关测试**（杀掉一个 loop 触发告警）；优先级在资源争用下被遵守。

### S13 — 监控、告警、账本、Fill-Fidelity
- 产物：dashboard（Grafana 或轻量）；Telegram/Discord/Slack 告警（默认关，配置开启）；`trade-ledger.parquet`、`fill-fidelity.parquet`；Fill-Fidelity Loop 对比回测预期 vs paper 实际成交并输出偏差；日报。
- DoD：数据健康/策略表现/风险状态/成交偏差/loop 存活全部可见；偏差报告生成；§3 校准回路文档化（用实测 bps 回填 `fills.yaml`）。

### S14 — `[人工门禁]` L2 实盘接入脚手架（写代码，不启用）
- 产物：交易所 live 适配器，**默认 dry-run 硬开关**；服务器端保护性止损、IP 白名单、无提现 key 经环境变量/KMS 读取；reconciliation 以交易所为准。
- DoD：live **dry-run** 记录完整链路并对账；**启用真实下单需人工显式批准，Codex 到此停止并在 STATE.md 标注等待人工**。L3 无人值守不在自主范围内。

## 5. 人工门禁清单（必须停下来问人）

命中以下任一，**停止自主推进，更新 STATE.md 说明原因，等待人工**：

- 到达 S14，或任何会用到真实 API key / 真实下单 / 真实资金的动作。
- 需要新的密钥、付费 API、或开启对外告警渠道。
- 验收门槛、风控红线、仓位上限、交易标的需要变更（这些只能人工改配置）。
- 计划与配置之间出现无法自洽消解的矛盾。

## 6. 全局质量基线

- 每个 step 都要有测试；关键路径（回测无 lookahead、风控阶梯、订单幂等、崩溃恢复、心跳）必须有专项测试。
- lint + 类型检查零报错才算 done。
- 确定性优先：同输入同输出，回测/信号可复现。
- 提交粒度：一个 step 一组提交，信息说明"做了什么 + 为什么"。
- 不留 TODO 占坑当完成；未做的明确写进 STATE.md 的未决项。

## 7. 失败处理与停止条件

- 单 step 内层 loop 最多 6 轮仍不过：记录到 STATE.md + build-log，尝试一个**无依赖关系的并行 step**继续推进；若无可并行项，则停止并向人工报告（附已尝试方案与错误）。
- 连续 2 个 step 受阻：停止，向人工报告全局状况。
- 命中红线（§1）或门禁（§5）：立即停止。
- 浏览器/外部服务/工具连续失败 2-3 次：停止，不要无脑重试。

## 8. 启动指令（人类把这句话发给 Codex）

> 阅读 `CODEX-BUILD-LOOP.md`、`crypto-quant-loop-development-plan.md`、`config/`。按 §2 内层 Loop 协议，从 S0 开始，依 §4 backlog 顺序自主、不间断地构建，每个 step 完成即更新 `STATE.md` 与 `build-log.jsonl` 并自动进入下一步。遵守 §1 红线与 §5 门禁。到 S14 或任一门禁处停下等我。开始。

---

# 第二阶段：策略研究 Loop（R-backlog）

> 前置：S0–S14 已完成，管道闭环。本阶段目标是**找到至少一个能稳健跑赢 buy-and-hold 的策略**，让 verifier 能 approve 它。沿用 §1 红线、§2 内层 Loop、§3 状态续跑、§5 门禁、§6 质量基线、§7 停止条件——只是 backlog 换成下面的 R 步骤。

## 9. 研究阶段的目标与纪律

- **目标（务实）**：稳健地跑赢基准，而非追高 Sharpe。一个稳定、可控、扣费后 OOS 不败的平庸策略，胜过一个回测惊艳但过拟合的策略。
- **"跑赢"的定义在 R1 中明确**，且必须是：样本外、扣真实费用、风险调整后。绝不用样本内或扣费前的数字宣称胜利。
- **先修后加**：先诊断并稳健化已有两个策略（R2-R3），再考虑新增（R4）。不堆因子、不上 ML、不搞跨所套利。
- **诚实是硬要求**：如果穷尽 R-backlog 仍无策略能稳健跑赢基准，**这是一个有效且必须如实上报的结论**，不许把参数调到过拟合来"制造" edge。负结果照样写进 STATE.md 与研究报告。
- **maker-checker 不变**：Codex 只产出**候选**策略与研究报告，**绝不自我批准**、绝不把 `status` 改成 `approved`、绝不把 `max_notional_quote` 改成正数、绝不启用实盘。批准只能由 verifier + 人工完成。

## 10. 研究 Backlog（R 步骤）

### R1 — 基准与"跑赢"的判定
- 产物：基准模块（buy-and-hold BTC，以及等权 BTC/ETH/SOL）；在与策略同一历史与同一扣费口径下计算；把"跑赢"落成可测谓词（如 OOS 扣费后 Calmar > 基准，或 Sharpe ≥ 基准且最大回撤 ≤ 基准）。判定阈值写进配置，作为研究阶段的验收口径。
- DoD：基准在 1-2 年历史上算出；"beat" 谓词有单元测试；口径与 verifier 一致。

### R2 — 诊断现有策略为何 OOS 差
- 产物：对现有动量与均值回归做归因报告——换手率、费用拖累、各 regime 分段 PnL、胜率、平均盈亏比、信号滞后。定位主要失效原因（1000 USDT 下"费用"很可能是头号）。
- DoD：两个策略各有一份诊断报告，明确指出主导失效模式；不臆测、用数据说话。

### R3 — 稳健化现有策略
- 产物：基于 R2 改进——降换手以减费用拖累、加 regime 过滤（动量只在趋势段、回归只在震荡段）、参数选在平台而非尖峰、适当拉长持仓。保持简单。
- DoD：walk-forward 显示 IS→OOS 衰减改善、换手/费用拖累下降；改进后仍走 verifier，不自我批准。

### R4 — 克制地新增稳健策略族（至多 1-2 个）
- 产物：只加少量充分理解、稳健的策略，如波动率目标的趋势跟踪，或把现有两策略按 regime 切换的组合器。**不上 ML、不堆因子**。
- DoD：每个新策略走同一 walk-forward 门槛，过不了就 reject；参数搜索试验次数记录在案（喂给 deflated Sharpe）。

### R5 — 组合层与波动率目标
- 产物：把通过的策略在（高相关的）主流币上做波动率目标 / 风险平价组合，遵守 `risk-policy.yaml` 的组合方向性敞口上限。"风险调整后跑赢基准"常常是在这一层、靠压回撤赢的，而非信号层。
- DoD：组合回测在 R1 口径下 OOS 扣费后跑赢基准——**或如实报告未能跑赢**。

### R6 — 稳健性终检与 verifier 提交
- 产物：过拟合/稳健性电池——全量试验次数的 deflated Sharpe、参数敏感性、子区间稳定性、收益的 block bootstrap、交易成本敏感性。把最佳候选**提交 verifier**（不自我批准）。
- DoD：稳健性报告产出；候选提交 verifier；结果（approve / reject）入 `strategy-registry.yaml` 的审计；若拟批准，**停下等人工**追加新的批准记录（A-002），`max_notional_quote` 由人工设定。

## 11. 研究阶段启动指令（人类把这句话发给 Codex）

> 阅读 `CODEX-BUILD-LOOP.md` 第二阶段（§9-§10）。按 §2 内层 Loop 协议，从 R1 开始依序自主推进，每步更新 `STATE.md` 与 `build-log.jsonl`。遵守 §9 纪律：务实稳健、先修后加、诚实上报负结果、绝不自我批准策略、绝不启用实盘。到 R6 拟批准处或任一门禁处停下等我。开始。

---

# 第三阶段：结构性 edge（F-backlog，funding / basis / carry 优先）

> 背景：R-backlog 诚实证明价格 TA 族在 1h 主流币上无 edge（全 regime 亏损、费用 >100% 毛利）。本阶段转向**结构性 edge**——最可能真有 edge 的方向，但代价是有意扩大范围。

## 12. 范围扩大的明确代价与纪律

**本阶段有意突破原计划的几条范围边界，必须清醒对待：**

- **引入永续合约**（原计划"第二阶段"）、**做空腿**、**保证金/杠杆**（原 spot leverage=0）。这带来**清算风险、基差风险、保证金管理**——风险量级高于现货。
- **可能涉及跨所**（原 MVP 明确排除）与**链上数据**（新数据源、可能付费）。
- **1000 USDT 下 delta-neutral carry 是资本临界的**（两条腿 + 费用 + 保证金缓冲）。所以本阶段目标是**证明 edge 存在且扣成本后为正**，不是"现在赚钱"。沿用 A 案定位。

**纪律（在 §1/§9 基础上追加）：**
- **先量化 edge，再写策略**：F2 必须先用历史数据测出"扣费扣资金费后净 carry 是否为正"，为负就如实上报并停，不许硬写策略。
- **研究可自主，生产配置改动是人工门禁**：F1–F3、F5 的回测研究在**不修改** `config/risk-policy.yaml`、`config/exchanges.yaml` 的前提下自主进行（永续/做空只存在于研究代码与回测，不进生产红线）。**任何把永续/杠杆/做空/跨所写进生产配置的改动，是 §5 人工门禁**，停下等人工批准并追加 A-00x 记录。
- **delta-neutral 优先**：carry 策略必须保持市场中性（spot 多 + perp 空对冲），有效杠杆 ≤1x；不做裸方向永续。
- maker-checker、不自我批准、不启用实盘、诚实上报负结果——全部不变。

## 13. 结构性 edge Backlog（F 步骤）

### F1 — 结构性数据层（历史可回填，与 L2 盘口不同）
- 产物：历史 + 前向**资金费率**（交易所提供 8h 历史，可回填）、**基差**（perp mark − spot）、可选未平仓量；落库并接入 Data Health。
- DoD：BTC/ETH/SOL 的历史资金费率/基差可回测；数据质量报告；明确哪些可回填、哪些只能前向。

### F2 — edge 量化与可行性（先测 edge，后写策略）【精炼版】
> 首轮 F2 在 ~100 天低费率熊市窗口、且写死 5% 机会成本下得出负 carry（见 `reports/f2_carry_feasibility.json`）。该结论被"regime + 单一假设"主导，不足以当最终判决。本步骤把问题从"有没有 edge"升级为"**edge 在什么条件下成立**"。
- 产物：
  1. **多 regime 资金费率历史**：把资金费率历史拉到交易所可提供的最长跨度（通常数年，含牛市高费率与狂热期），覆盖多个 funding regime，而非只测最近 ~100 天。明确标注各 symbol 实际可得的历史长度。
  2. **机会成本敏感性**：净 carry 在 `margin_cost_apr ∈ {0%, 3%, 5%}` 三档下分别报告，让结论不被单一假设绑架；并报出"funding APR 需高于多少才扣成本转正"的盈亏平衡线。
  3. **条件化 carry**：模拟"只在 funding 年化 > 门槛（如 > 机会成本 + 交易拖累）时持有 carry，否则空仓"的收割器；报告该条件历史上多久成立、条件化后的净 carry。
  4. 不同本金规模（500–10000+）网格仍保留。
- DoD：报告回答三问——(a) 历史多 regime 下净 carry 在各机会成本假设下分别如何；(b) funding 转正的盈亏平衡门槛是多少、历史满足频率多高；(c) 条件化收割器扣成本后是否为正、在什么本金量级。**若多 regime + 条件化 + 合理机会成本下仍不成立，则这是稳健的否定结论，停在 F2 等人工；若在某条件下成立，提出该条件作为 F3 策略的入场规则，并停下等人工确认再进 F3。**

### F3 — Delta-neutral carry 策略（spot 多 + perp 空）
- 产物：现金套利式 carry——中性持仓构建、资金费收割、按费率阈值进出、再平衡维持 delta≈0；费用与资金费全计入；跟踪 delta 与基差。
- DoD：在历史资金费率/基差上回测；delta 中性可验证；扣成本后净值曲线产出。

### F4 — `[人工门禁]` 永续/杠杆风控扩展（提议，不自动启用）
- 产物：为永续提议风控参数——有效杠杆上限（≤1x、中性）、清算距离监控、基差暴走熔断、资金费翻转处理、保证金缓冲；扩展 kill switch 覆盖两腿。
- DoD：**提议**写成草案（不改生产 `risk-policy.yaml`）；清算距离监控 + 测试；**停下等人工批准**，批准后由人工写入配置并追加 A-00x。

### F5 — 验证与 verifier 提交
- 产物：对 carry 策略做 walk-forward + 同款稳健性电池（重点：成本敏感性、资金费翻转压力、基差冲击）；提交 verifier。
- DoD：verifier 判定入 registry 审计；诚实报告；若拟批准，停下等人工（A-00x，`max_notional` 由人工设）。

### F6 — `[人工门禁/可选]` 其他结构性来源（仅在 F2–F5 值得时）
- 候选：资金费率方向性/情绪信号（单腿，更简单更弱）；跨所价差/费率差（需两所资金、转账风险）；链上资金流（需新数据源、可能付费、噪声大）。
- DoD：每个来源单独评估，**各自带范围/风险/数据成本说明并走人工门禁**；不在本阶段一次性铺开。

## 14. 第三阶段启动指令（人类把这句话发给 Codex）

> 阅读 `CODEX-BUILD-LOOP.md` 第三阶段（§12-§13）。按 §2 内层 Loop 协议，从 F1 开始依序自主推进，每步更新 `STATE.md` 与 `build-log.jsonl`。遵守 §12 纪律：先量化 edge 再写策略、研究不改生产红线配置、delta-neutral 优先、诚实上报负结果、绝不自我批准、绝不启用实盘。到 F2 若净 carry 不成立、或 F4/F6 任一门禁处，停下等我。开始。

**F2 精炼重测启动指令（F1 已完成，从精炼版 F2 起跑）：**

> 阅读 `CODEX-BUILD-LOOP.md` §13 的 F2【精炼版】。F1 数据层已就绪。重跑 F2：拉长资金费率历史到交易所最长可得跨度（多 regime）、对 `margin_cost_apr ∈ {0%,3%,5%}` 做敏感性、增加"只在高费率时段入场"的条件化 carry 模拟，并保留本金网格。遵守 §12 纪律。把结论从"有无 edge"升级为"edge 在什么条件下成立"。若多 regime + 条件化 + 合理机会成本下仍不成立，停在 F2 等我；若某条件下成立，提出入场门槛并停下等我确认再进 F3。开始。
