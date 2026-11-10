.PHONY: help temporal stop control-plane test image-build image-push image-startup-check image-promote track-validate track-push track-pull

# The sandbox image, tagged with the commit it's built from. The image targets
# assume you're logged in to GHCR, and the track targets that you're logged in
# to Instruqt (or have INSTRUQT_TOKEN set).
IMAGE ?= ghcr.io/temporalio/why-temporal-sandbox
REVISION ?= $(shell git rev-parse HEAD)
STARTUP_BUDGET_SECONDS ?= 90
TRACK_PUSH_FLAGS ?=

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

temporal: ## Start the Temporal dev server (Web UI at http://localhost:8233)
	docker compose up

stop: ## Stop the Temporal dev server
	docker compose down

control-plane: ## Run the demo with fresh stub ledgers: the panel, the stubs, the order app, and the Worker (http://localhost:8085)
	rm -f logs/*-ledger.json logs/*-ledger.tmp
	uv run python -m uvicorn delivery.control_plane:app --port 8085

test: ## Run the test suite (no Docker needed; uses the time-skipping test server)
	uv run --group dev python -m pytest

image-build: ## Build the sandbox image for linux/amd64, with no cache, tagged with the current commit
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Commit or stash your changes first: the image is tagged with the commit it's built from."; \
		exit 1; \
	fi
	docker buildx build --no-cache --platform linux/amd64 --load -f sandbox/Dockerfile -t $(IMAGE):$(REVISION) .

image-push: ## Push the current commit's sandbox image to GHCR
	docker push $(IMAGE):$(REVISION)

image-startup-check: ## Time a cold start of the current commit's image against the budget, and check it starts offline
	bash scripts/time-container-start.sh $(IMAGE):$(REVISION) --cold --offline-probe \
		--budget $(STARTUP_BUDGET_SECONDS) --setup instruqt/track_scripts/setup-workshop

image-promote: ## Point :stable at the current commit's image (CI does this on main; by hand only in an emergency)
	docker buildx imagetools create -t $(IMAGE):stable $(IMAGE):$(REVISION)

track-validate: ## Check the Instruqt track in instruqt/ with Instruqt's own validator
	cd instruqt && instruqt track validate

track-push: ## Push the Instruqt track to the team named by owner: in instruqt/track.yml
	cd instruqt && instruqt track push $(TRACK_PUSH_FLAGS)

track-pull: ## Pull the Instruqt track into instruqt/, to pick up changes made in Instruqt's web UI
	cd instruqt && instruqt track pull
