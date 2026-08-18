.PHONY: help temporal stop payment worker run test

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

temporal: ## Start the Temporal dev server (Web UI at http://localhost:8233)
	docker compose up

stop: ## Stop the Temporal dev server
	docker compose down

payment: ## Run the payment service stub (http://localhost:8081)
	uv run uvicorn delivery.stubs.payment:app --port 8081

worker: ## Run the Worker (needs the dev server running)
	uv run python -m delivery.worker

run: ## Place an order and watch it flow (needs server, payment, and Worker up)
	uv run python -m delivery.starter

test: ## Run the test suite (no Docker needed; uses the time-skipping test server)
	uv run pytest
