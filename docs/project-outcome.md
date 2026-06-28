# 项目收尾：阶段性结论与交付物

> 日期：2026-06-28　决定人：coolbreeze（faithcutpro@gmail.com）
> 本文记录第一轮工程的最终决定，避免日后重新纠结"当初为何停"。配套：`crypto-quant-loop-development-plan.md`、`CODEX-BUILD-LOOP.md`、`docs/approvals.md`。

## 决定

**接受平台为交付物，停止当前的 edge 追逐。不进入 F3（carry 策略实现），不上实盘。**

## 为什么停：三个独立的诚实否定

| 阶段 | 测什么 | 诚实结论 |
| --- | --- | --- |
| R-backlog（价格 TA） | 动量/均值回归及稳健化变体 | 全 regime 亏损；费用 >100% 毛利；verifier 全 reject |
| F2 首轮（funding carry） | delta-neutral carry | ~100 天低费率熊市窗口净 carry 为负 |
| F2 精炼（funding carry） | 540 天多档资金费率 + 机会成本敏感性 + 条件化 | 最佳情形仅 BTC、+0.13%/年、机会成本 ≤3% 才正、5% 转负；择时版因开平成本全负 |

**元结论：1000 USDT + 公开手段 + 诚实成本 = 没有净 edge。** 这是市场事实，不是系统缺陷。系统三次都没有自欺，正确拦下了所有边际/劣质策略。

## 交付了什么（这才是本轮的真正成果）

一套**可观测、可验证、可暂停、可审计**的量化基础设施，从空仓库自主构建、每步有测试（83 passed）、全程未碰真实资金/密钥：

- 数据层（历史 OHLCV + 前向盘口 + 结构性 funding/basis）、特征库（含 lookahead 检测）
- 回测引擎（保守成交、按止损反推仓位、强制时间切片）、walk-forward 验证（purge/embargo、deflated Sharpe）
- Verifier + 策略注册表（maker-checker，策略不能自我批准）
- 风控引擎（内在一致的熔断阶梯、kill switch）、paper broker（订单状态机、幂等、崩溃恢复）
- Loops 运行时（心跳/死人开关）、监控/告警/账本/Fill-Fidelity
- live 适配器脚手架（dry-run 三重硬门禁，默认不可达真实下单）

## 安全终态（已核对）

- `config/exchanges.yaml` `dry_run: true`；无 approved 策略；`max_notional_quote` 全 0
- 未启用外部告警；无真实密钥入库；`.env` 已忽略
- 真实下单需同时满足 dry_run=false + allow_real_trading=true + 有 client，且永续/杠杆入生产配置另需人工门禁

## 什么条件下值得重启（不是"永不"，是"现在/此规模不划算"）

1. **资金费率进入 mania regime**（BTC 年化资金费持续 >25%，本轮 540 天未出现）——carry 的经济性那时才成立。
2. **本金量级显著提高**——thin margin 与两腿/保证金成本在更大资金上才摊得平。
3. **拿到差异化/非公开信号源**——公开价格 TA 是被过度挖掘的红海，已证伪。

> 备战动作（可选，未实施）：加一个轻量资金费率 regime 监视器，当 BTC funding 冲到 mania 水平时告警，提示 carry 前提出现。本轮决定先不实施。

## 一句话

本项目第一版的成功标准是"基础设施可靠、可控、可审计"，**已达成**；"稳定盈利"从一开始就不是本轮的评判标准，三次诚实否定恰恰证明了这套治理在起作用。
