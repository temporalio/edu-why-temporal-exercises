.PHONY: help temporal stop control-plane test track-validate track-push track-pull

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

temporal: ## Start the Temporal dev server (Web UI at http://localhost:8233)
	docker compose up

stop: ## Stop the Temporal dev server
	docker compose down

control-plane: ## Run the demo with fresh stub ledgers: the panel, the stubs, the order app, and the Worker (http://localhost:8085)
	rm -f logs/*-ledger.json logs/*-ledger.tmp
	uv run python -m uvicorn delivery.control_plane:app --port 8085

test: ## Run the test suite (no Docker needed; uses the time-skipping test server)
	uv run --group dev python -m pytest

track-validate: ## Check the Instruqt track in instruqt/ with Instruqt's own validator
	cd instruqt && instruqt track validate

track-push: ## Push the Instruqt track to the team named by owner: in instruqt/track.yml
	cd instruqt && instruqt track push

track-pull: ## Pull the Instruqt track into instruqt/, to pick up changes made in Instruqt's web UI
	cd instruqt && instruqt track pull
