# crypto-quant-loop — 便捷运行入口（可选；也可直接用 uv run）

.PHONY: help setup check test lint typecheck scan \
        empty-loop data-health fetch-ohlcv fetch-structural carry

help:
	@echo "make setup            安装依赖（含 dev 工具）"
	@echo "make check            lint + 类型 + 测试 + 密钥扫描"
	@echo "make test             运行测试"
	@echo "make empty-loop       运行空 loop（写 loop-run-log.jsonl）"
	@echo "make data-health      数据健康报告（需先有数据）"
	@echo "make fetch-ohlcv      拉取历史 OHLCV（公开数据，无需密钥）"
	@echo "make fetch-structural 拉取 funding/basis 结构性数据"
	@echo "make carry            资金费率 carry 可行性分析"

setup:
	uv sync --extra dev

lint:
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run pytest

scan:
	uv run python scripts/secret_scan.py

check: lint typecheck test scan

empty-loop:
	uv run cql-empty-loop

data-health:
	uv run cql-data-health

fetch-ohlcv:
	uv run cql-fetch-ohlcv

fetch-structural:
	uv run cql-fetch-structural

carry:
	uv run cql-carry-feasibility
