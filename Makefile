.PHONY: install db ingest dev test test-integration lint up down

TEST_DATABASE_URL ?= postgresql://postgres:postgres@localhost:5433/docs_agent_test

install:
	uv sync

db: ## start PostgreSQL with pgvector on localhost:5433
	docker compose up -d --wait db

ingest: ## chunk, embed and store the sample knowledge base
	uv run docs-agent-ingest knowledge_base

dev: ## run the API with auto-reload on http://localhost:8000
	uv run uvicorn docs_agent.main:app --reload --port 8000

test: ## unit tests, no database or API key needed
	uv run pytest

test-integration: db ## all tests, including the ones that need PostgreSQL
	docker compose exec -T db createdb -U postgres docs_agent_test 2>/dev/null || true
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

up: ## run the database and the API in containers
	docker compose up -d --build --wait
	docker compose exec -T api docs-agent-ingest knowledge_base

down:
	docker compose down
