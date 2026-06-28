# crypto-quant-loop — 便捷运行入口
#
# 注意：本项目目录名含空格（"Loop Engineering"），会破坏 uv 的 editable 安装，
# 导致 `uv run cql-*` 报 ModuleNotFoundError。下面所有命令显式用
# PYTHONPATH=src 并 --no-sync 绕过该问题（详见 README「运行」一节）。
# 永久解法：把项目移到不含空格的路径，例如 ~/code/QuantTrading。

PYRUN = PYTHONPATH=src uv run --no-sync

.PHONY: help setup check test lint typecheck scan \
        empty-loop data-health fetch-ohlcv fetch-structural carry

help:
	@echo "make setup            安装依赖（uv sync）"
	@echo "make check            lint + 类型 + 测试 + 密钥扫描"
	@echo "make test             运行测试"
	@echo "make empty-loop       运行空 loop（写 loop-run-log.jsonl）"
	@echo "make data-health      数据健康报告（需先有数据）"
	@echo "make fetch-ohlcv      拉取历史 OHLCV（公开数据，无需密钥）"
	@echo "make fetch-structural 拉取 funding/basis 结构性数据"
	@echo "make carry            资金费率 carry 可行性分析"

setup:
	uv sync

lint:
	uv run --no-sync ruff check .

typecheck:
	$(PYRUN) mypy

test:
	$(PYRUN) pytest

scan:
	$(PYRUN) python scripts/secret_scan.py

check: lint typecheck test scan

empty-loop:
	$(PYRUN) cql-empty-loop

data-health:
	$(PYRUN) cql-data-health

fetch-ohlcv:
	$(PYRUN) cql-fetch-ohlcv

fetch-structural:
	$(PYRUN) cql-fetch-structural

carry:
	$(PYRUN) cql-carry-feasibility
