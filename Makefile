.PHONY: install test test-unit test-integration lint format typecheck verify run worker docker-build docker-up docker-down benchmark

install:
	uv sync --frozen --all-extras

test:
	uv run pytest --cov=mfbo_platform --cov-report=term-missing

test-unit:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

lint:
	uv run ruff format --check .
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy src

verify: lint typecheck test

run:
	uv run mfbo-api

worker:
	uv run mfbo-worker

docker-build:
	docker build -f Dockerfile.api -t mfbo-api:local .
	docker build -f Dockerfile.worker --target public-worker -t mfbo-worker:local .

docker-up:
	docker compose up --build

docker-down:
	docker compose down

benchmark:
	uv run python benchmarks/api_latency.py --requests 500

smoke:
	uv run python scripts/smoke_stack.py
