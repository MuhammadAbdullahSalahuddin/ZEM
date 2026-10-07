.PHONY: check lint type test fmt
check: lint type test
lint:
	uv run ruff check src tests demo
type:
	uv run mypy --strict src/zem/contracts
test:
	uv run pytest -q
fmt:
	uv run ruff format src tests demo
