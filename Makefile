.PHONY: help temporal stop control-plane test

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

temporal: ## Start the Temporal dev server (Web UI at http://localhost:8233)
	docker compose up

stop: ## Stop the Temporal dev server
	docker compose down

control-plane: ## Run the demo with fresh stub ledgers: the panel, the stubs, the order app, and the Worker (http://localhost:8085)
	rm -f logs/*-ledger.json logs/*-ledger.tmp
	uv run python -m uvicorn delivery.control_plane:app --port 8085

test: ## Run the test suite (no Docker needed; uses the time-skipping test server)
	uv run --group dev python -m pytest
