.PHONY: sync test lint coverage doctor ic2-doctor help

help:
	@echo "Targets: sync, lint, test, coverage, doctor, ic2-doctor, validate"

sync:
	uv sync --all-packages

lint:
	uv run ruff check .

test:
	uv run pytest -q

coverage:
	uv run python scripts/check_api_coverage.py
	uv run python scripts/check_ic2_coverage.py

doctor:
	uv run peplink-device-mcp doctor --device gateway

ic2-doctor:
	uv run peplink-device-mcp ic2-doctor

validate:
	uv run peplink-device-mcp validate --config examples/config/config.yaml --secrets examples/config/secrets.yaml.example
