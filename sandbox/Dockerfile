# Sandbox image for the Instruqt track: Python 3.12, uv, the Temporal CLI, and this
# repo with its dependencies installed, so starting a lab only starts processes.
#
# Build from the repo root, for linux/amd64 (Instruqt sandboxes are amd64):
#   docker build --platform linux/amd64 -f sandbox/Dockerfile -t <tag> .
#
# Both images this build starts from are pinned by digest, with the tag kept
# alongside so it's clear which release each one is. Find a tag's current
# digest with `docker buildx imagetools inspect <image>:<tag>`.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

# procps provides pkill and pgrep, which the control plane's supervisor uses to
# start and stop the demo's processes.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates procps less \
    && rm -rf /var/lib/apt/lists/*

# uv runs every process the control plane starts (`uv run python -m ...`).
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /usr/local/bin/

# Temporal CLI, which bundles the dev server and the Web UI.
ARG TEMPORAL_CLI_VERSION=1.8.2
RUN curl -sSL \
      "https://github.com/temporalio/cli/releases/download/v${TEMPORAL_CLI_VERSION}/temporal_cli_${TEMPORAL_CLI_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin temporal \
    && chmod +x /usr/local/bin/temporal

# The lab runs the repo from here. The virtual environment is built in place,
# because it records absolute paths and wouldn't survive being moved.
WORKDIR /root/workshop

# Dependencies first, so a source change doesn't rebuild them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# `uv run` checks the environment on every call. Frozen, it never re-resolves the
# lockfile. It would still rebuild this project if it judged the install stale,
# and part of that judgment is the inode of src/, which changes when the image
# runs on a different storage backend from the one it was built on. A rebuild
# needs the network, so with no sync at all, `uv run` uses the environment
# installed above as it is.
ENV UV_FROZEN=1
ENV UV_NO_SYNC=1

CMD ["/bin/bash"]
