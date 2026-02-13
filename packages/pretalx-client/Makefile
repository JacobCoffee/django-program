SHELL := /bin/bash
.DEFAULT_GOAL := help
.ONESHELL:

# Run uv from the workspace root so doc dependencies resolve.
WORKSPACE_ROOT := $(shell git rev-parse --show-toplevel)
UV             ?= uv

.PHONY: help docs docs-serve docs-clean

help: ## Display this help text
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Documentation

docs: docs-clean ## Build documentation
	@echo "=> Building pretalx-client documentation"
	@cd $(WORKSPACE_ROOT) && $(UV) run sphinx-build -M html packages/pretalx-client/docs packages/pretalx-client/docs/_build/ -E -a -j auto --keep-going
	@echo "=> Build complete: packages/pretalx-client/docs/_build/html/"

docs-serve: docs-clean ## Serve documentation with live reload
	@echo "=> Serving pretalx-client documentation"
	@cd $(WORKSPACE_ROOT) && $(UV) run sphinx-autobuild packages/pretalx-client/docs packages/pretalx-client/docs/_build/ -j auto --port 0

docs-clean: ## Clean built documentation
	@echo "=> Cleaning documentation build assets"
	@rm -rf docs/_build
