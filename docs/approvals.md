# 人工批准记录（APPROVALS）

> Append-only 审计日志，记录所有人工门禁的批准决定。由人维护，独立于 Codex 维护的 `STATE.md`。
> 对应门禁定义见 `CODEX-BUILD-LOOP.md` §5。新记录追加到末尾，不修改既有条目。

---

## A-001 — S14 实盘接入脚手架（仅 dry-run）

- **日期**：2026-06-27
- **批准人**：coolbreeze（faithcutpro@gmail.com）
- **门禁**：CODEX-BUILD-LOOP.md §5 / S14
- **决定**：✅ 批准，但**严格限定为脚手架，不启用真实交易**。

**授权范围（允许做）：**
- 实现 live 交易所适配器（ccxt live），复用已有订单状态机与 `clientOrderId` 幂等。
- 实现服务器端保护性止损（stop/OCO）代码路径。
- 密钥只从环境变量读取，无 key 时优雅降级为 no-op。
- 实现以交易所为准的 reconciliation 代码路径。
- 用测试夹具信号走通 live **dry-run** 链路，断言 dry-run 下不发出任何真实订单。

**明确未批准（仍处门禁，需独立再批准）：**
- 把 `config/exchanges.yaml` 的 `dry_run` 改为 `false`。
- 发送任何真实订单 / 连接真实下单通道 / 动用真实资金。
- 在 verifier / `strategy-registry.yaml` 中把任何策略改为 `approved` 或 `max_notional > 0`。
- 启用外部告警渠道。
- 提交或索取任何真实密钥。

**开启真金白银交易的前置条件（S14 之外的独立门禁）：**
1. 有策略通过 walk-forward + verifier 被 `approved`。
2. Fill-Fidelity 偏差验证通过。
3. 人工再次显式批准（届时追加新的 A-00x 记录）。

**备注：**
- 当前两个基础策略已被 verifier 正确判定无 edge（`candidate` / `max_notional=0`），真正瓶颈是策略研究，非脚手架。
- live dry-run 的真实联调需人工在本地 `.env` 提供无提现、开 IP 白名单的 key，由人手动操作；Binance 若仍有 451 地域限制，联调改用 OKX 或先解决网络/辖区问题。
