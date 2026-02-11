SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:
UV_OPTS       ?=
UV            ?= uv $(UV_OPTS)

.EXPORT_ALL_VARIABLES:

.PHONY: help install dev clean lint fmt test docs
.PHONY: type-check ruff security
.PHONY: docs-serve docs-clean
.PHONY: install-uv install-prek upgrade
.PHONY: ci
.PHONY: act act-ci act-docs act-list
.PHONY: test-cov test-fast build destroy
.PHONY: pretalx-generate-http-client pretalx-codegen
.PHONY: test-pretalx-client

help: ## Display this help text for Makefile
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# =============================================================================
# Setup & Installation
# =============================================================================

##@ Setup & Installation

install-uv: ## Install latest version of UV
	@echo "=> Installing uv"
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "=> uv installed"

install-prek: ## Install prek and install hooks
	@echo "=> Installing prek hooks"
	@$(UV) run prek install
	@$(UV) run prek install --hook-type commit-msg
	@$(UV) run prek install --hook-type pre-push
	@echo "=> prek hooks installed"
	@$(UV) run prek autoupdate
	@echo "=> prek installed"

install: ## Install package
	@echo "=> Installing package"
	@$(UV) sync
	@echo "=> Installation complete"

dev: ## Run the example Django dev server (clean slate + migrate + bootstrap + runserver)
	@echo "=> Cleaning previous database"
	@rm -f examples/db.sqlite3
	@echo "=> Migrating database"
	@$(UV) run python examples/manage.py migrate --run-syncdb
	@echo "=> Bootstrapping conference data"
	@$(UV) run python examples/manage.py bootstrap_conference --config conference.example.toml --update --seed-demo || true
	@echo "=> Setting up permission groups"
	@$(UV) run python examples/manage.py setup_groups
	@echo "=> Creating default admin user (admin/admin)"
	@DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_EMAIL=admin@localhost DJANGO_SUPERUSER_PASSWORD=admin \
		$(UV) run python examples/manage.py createsuperuser --noinput 2>/dev/null || true
	@echo "=> Starting dev server at http://localhost:8000/admin/  (login: admin/admin)"
	@$(UV) run python examples/manage.py runserver

upgrade: ## Upgrade all dependencies to the latest stable versions
	@echo "=> Upgrading prek"
	@$(UV) run prek autoupdate
	@$(UV) lock --upgrade
	@echo "=> Dependencies upgraded"

# =============================================================================
# Code Quality
# =============================================================================

##@ Code Quality

lint: ## Runs Ruff linter with auto-fix
	@$(UV) run --no-sync ruff check --fix .

fmt: ## Runs Ruff format and lint with fixes
	@$(UV) run --no-sync ruff format .
	@$(UV) run --no-sync ruff check --fix .

ruff: ## Runs Ruff with unsafe fixes
	@$(UV) run --no-sync ruff check . --unsafe-fixes --fix

type-check: ## Run ty type checker
	@$(UV) run --no-sync ty check

ci: fmt type-check test ## Run all CI checks locally (format, lint, type-check, test)

security: ## Run zizmor GitHub Actions security scanner
	@echo "=> Running zizmor security scan on GitHub Actions workflows"
	@uvx zizmor .github/workflows/

# =============================================================================
# Testing
# =============================================================================

##@ Testing

test: ## Run the tests
	@PYTHONDONTWRITEBYTECODE=1 $(UV) run --no-sync pytest

test-cov: ## Run tests with coverage report
	@PYTHONDONTWRITEBYTECODE=1 $(UV) run --no-sync pytest --cov=src/django_program --cov-report=html --cov-report=term

test-fast: ## Run tests without coverage (faster)
	@PYTHONDONTWRITEBYTECODE=1 $(UV) run --no-sync pytest -x -q

test-pretalx-client: ## Run pretalx-client package tests
	@PYTHONDONTWRITEBYTECODE=1 $(UV) run --no-sync pytest packages/pretalx-client/tests/ -v

# =============================================================================
# Pretalx Codegen
# =============================================================================

##@ Pretalx Codegen

pretalx-generate-http-client: ## Generate HTTP client from OpenAPI schema
	@$(UV) run python scripts/pretalx/generate_http_client.py

pretalx-codegen: ## Full codegen pipeline (validate + models + HTTP client)
	@$(UV) run python scripts/pretalx/validate_schema.py
	@$(UV) run python scripts/pretalx/generate_client.py
	@$(UV) run python scripts/pretalx/generate_http_client.py

# =============================================================================
# Documentation
# =============================================================================

##@ Documentation

docs: docs-clean ## Build documentation
	@echo "=> Building documentation"
	@$(UV) sync --group docs
	@$(UV) run sphinx-build -M html docs docs/_build/ -E -a -j auto --keep-going

docs-serve: docs-clean ## Serve documentation with live reload
	@echo "=> Serving documentation"
	@$(UV) sync --group docs
	@$(UV) run sphinx-autobuild docs docs/_build/ -j auto --port 0

docs-clean: ## Clean built documentation
	@echo "=> Cleaning documentation build assets"
	@rm -rf docs/_build
	@echo "=> Removed existing documentation build assets"

# =============================================================================
# Build & Release
# =============================================================================

##@ Build & Release

build: ## Build package
	@$(UV) build

clean: ## Autogenerated file cleanup
	@echo "=> Cleaning up autogenerated files"
	@rm -rf .pytest_cache .ruff_cache .hypothesis build/ dist/ .eggs/
	@find . -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	@find . -name '*.egg' -exec rm -rf {} + 2>/dev/null || true
	@find . -name '*.pyc' -exec rm -rf {} + 2>/dev/null || true
	@find . -name '*.pyo' -exec rm -rf {} + 2>/dev/null || true
	@find . -name '*~' -exec rm -rf {} + 2>/dev/null || true
	@find . -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .coverage coverage.xml coverage.json htmlcov/
	$(MAKE) docs-clean

destroy: ## Destroy the virtual environment
	@rm -rf .venv

# =============================================================================
# Local GitHub Actions
# =============================================================================

##@ Local GitHub Actions (act)

act: ## Run all CI workflows locally with act
	@echo "=> Running CI workflows locally with act"
	@act -l 2>/dev/null || (echo "Error: 'act' not installed. Install with: brew install act" && exit 1)
	@act push --container-architecture linux/amd64

act-ci: ## Run CI workflow locally
	@echo "=> Running CI workflow locally"
	@act push -W .github/workflows/ci.yml --container-architecture linux/amd64

act-docs: ## Run docs workflow locally
	@echo "=> Running docs workflow locally"
	@act push -W .github/workflows/docs.yml --container-architecture linux/amd64

act-list: ## List available act jobs
	@act -l
