# STATE — 构建进度与系统状态

> 单一事实来源，断点续跑的依据。每个 step 结束必更新。详见 `CODEX-BUILD-LOOP.md` §3。

## 当前

- 阶段：S1 完成，准备进入 S2
- 进行中 step：无
- **下一步：S2 — 数据层：历史 OHLCV**
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

## 阻塞 / 未决问题

（无）

## 等待人工

- 尚未到门禁。S14（L2 实盘接入）及任何真实资金/密钥动作需人工批准（见 `CODEX-BUILD-LOOP.md` §5）。

## 最近决策

- 采用 A 案：1000 USDT 定位为管道测试，不以盈亏评判；实盘先只跑 BTC 单标的。
- 风控/成交参数以 `config/risk-policy.yaml`、`config/fills.yaml` 为准。
- S0 本地验证使用 `uv` 创建的 CPython 3.13 虚拟环境；项目仍声明 `requires-python >=3.12`。
- S1 配置加载只保留密钥环境变量名，不读取真实密钥值。
