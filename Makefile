.PHONY: help temporal stop worker test

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

temporal: ## Start the Temporal dev server (Web UI at http://localhost:8233)
	docker compose up

stop: ## Stop the Temporal dev server
	docker compose down

worker: ## Run the Temporal worker (needs the dev server running)
	uv run python -m delivery.worker

run: ## Start one workflow through the running worker (needs server + worker up)
	uv run python -m delivery.starter

test: ## Run the test suite (no Docker needed; uses the time-skipping test server)
	uv run pytest
