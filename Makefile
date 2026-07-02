.PHONY: help setup db-up migrate run dev worker test test-e2e lint docker-build docker-up docker-down screenshots

VENV := venv
FLASK_APP := esb:create_app
MARIADB_ROOT_PASSWORD ?= esb_dev_password
ESB_DB_HOST_PORT ?= 3306
ESB_DEV_HOST_PORT ?= 5001
LOCAL_DATABASE_URL := mysql+pymysql://root:$(MARIADB_ROOT_PASSWORD)@localhost:$(ESB_DB_HOST_PORT)/esb
LOCAL_ESB_BASE_URL := http://localhost:$(ESB_DEV_HOST_PORT)

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "; printf "Equipment Status Board local commands\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[96m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create venv and install dev requirements
	python -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements-dev.txt

db-up: ## Start the local database container
	docker compose up --wait --wait-timeout 60 db

migrate: ## Run database migrations
	FLASK_APP=$(FLASK_APP) $(VENV)/bin/flask db upgrade

run: ## Run Flask dev server
	FLASK_APP=$(FLASK_APP) $(VENV)/bin/flask run --debug

dev: db-up ## Run Flask dev server with Docker DB and hot reload
	docker compose stop app worker
	DATABASE_URL=$(LOCAL_DATABASE_URL) FLASK_APP=$(FLASK_APP) $(VENV)/bin/flask db upgrade
	DATABASE_URL=$(LOCAL_DATABASE_URL) ESB_BASE_URL=$(LOCAL_ESB_BASE_URL) SLACK_SOCKET_MODE_CONNECT=true FLASK_APP=$(FLASK_APP) FLASK_RUN_PORT=$(ESB_DEV_HOST_PORT) $(VENV)/bin/flask run --debug

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

docker-down: ## Stop Docker Compose stack
	docker compose down

screenshots: ## Generate documentation screenshots
	$(VENV)/bin/python -m playwright install chromium
	PYTHONPATH=. $(VENV)/bin/python scripts/generate_screenshots.py
