# STATE — 构建进度与系统状态

> 单一事实来源，断点续跑的依据。每个 step 结束必更新。详见 `CODEX-BUILD-LOOP.md` §3。

## 当前

- 阶段：构建未开始
- 进行中 step：无
- **下一步：S0 — 仓库骨架与工具链**
- 运行模式：plumbing_test（1000 USDT / A 案，见 `config/risk-policy.yaml`）

## 已完成 step

（无）

## 阻塞 / 未决问题

（无）

## 等待人工

- 尚未到门禁。S14（L2 实盘接入）及任何真实资金/密钥动作需人工批准（见 `CODEX-BUILD-LOOP.md` §5）。

## 最近决策

- 采用 A 案：1000 USDT 定位为管道测试，不以盈亏评判；实盘先只跑 BTC 单标的。
- 风控/成交参数以 `config/risk-policy.yaml`、`config/fills.yaml` 为准。
