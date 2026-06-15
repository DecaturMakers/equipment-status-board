.PHONY: help setup db-up migrate run worker test test-e2e lint docker-build docker-up screenshots

VENV := venv
FLASK_APP := esb:create_app

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "; printf "Equipment Status Board local commands\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[96m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create venv and install dev requirements
	python -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements-dev.txt

db-up: ## Start the local database container
	docker compose up -d db

migrate: ## Run database migrations
	FLASK_APP=$(FLASK_APP) $(VENV)/bin/flask db upgrade

run: ## Run Flask dev server
	FLASK_APP=$(FLASK_APP) $(VENV)/bin/flask run --debug

worker: ## Run notification worker
	FLASK_APP=$(FLASK_APP) $(VENV)/bin/flask worker run

test: ## Run pytest suite
	$(VENV)/bin/python -m pytest tests/ -v

test-e2e: ## Run e2e tests
	$(VENV)/bin/python -m pytest tests/e2e/ -v

lint: ## Run ruff
	$(VENV)/bin/ruff check esb/ tests/

docker-build: ## Build Docker images
	docker compose build

docker-up: ## Start Docker Compose stack
	docker compose up

screenshots: ## Generate documentation screenshots
	$(VENV)/bin/python -m playwright install chromium
	PYTHONPATH=. $(VENV)/bin/python scripts/generate_screenshots.py
