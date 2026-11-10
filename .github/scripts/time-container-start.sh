#!/usr/bin/env bash
# time-container-start.sh - measure an Instruqt sandbox image against the
# 90-second startup budget, and prove it does not download anything at lab
# start.
#
# Static analysis (audit-dockerfile.sh) catches the patterns it can see.
# This script catches the rest by actually running the thing.
#
# Usage:
#   time-container-start.sh <image> [options]
#
# Options:
#   --budget <seconds>   Startup budget. Default 90 (the hard requirement).
#   --setup <path>        Lifecycle script to run as lab start
#                         (e.g. instruqt/track_scripts/setup-workshop).
#   --ready <cmd>         Shell command run inside the container that exits 0
#                         once the sandbox is genuinely usable. Repeatable.
#                         Default probes the Temporal dev server on 7233.
#   --cold                Remove the local copy first and time a fresh pull
#                         from the registry. Pull time then counts against
#                         the budget (pull + start). Use this for the release
#                         gate: an Instruqt host may not have the image cached.
#   --offline-probe       Also run the whole start with --network none. If it
#                         still works, the image provably pulls nothing at
#                         runtime. This is the supply-chain test.
#   --runs <n>            Timed runs to average. Default 1.
#   --platform <p>        Default linux/amd64 (what Instruqt runs).
#   --keep                Leave the container running for inspection.
#
# Exit: 0 within budget and offline-clean, 1 over budget or a runtime
#       download was detected, 2 usage/environment error.
#
# Example:
#   time-container-start.sh <registry>/workshop-py:abc123 --cold \
#     --setup python/instruqt/track_scripts/setup-workshop \
#     --ready 'temporal operator cluster health' \
#     --offline-probe

set -uo pipefail

IMAGE=""; BUDGET=90; SETUP=""; RUNS=1; PLATFORM="linux/amd64"
OFFLINE=0; KEEP=0; COLD=0; PULL_MS=0; declare -a READY=()

c_red=''; c_yel=''; c_grn=''; c_dim=''; c_bold=''; c_off=''
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  c_red=$'\033[31m'; c_yel=$'\033[33m'; c_grn=$'\033[32m'
  c_dim=$'\033[2m'; c_bold=$'\033[1m'; c_off=$'\033[0m'
fi

usage() { sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --budget)   BUDGET="${2:?}"; shift 2 ;;
    --setup)    SETUP="${2:?}";  shift 2 ;;
    --ready)    READY+=("${2:?}"); shift 2 ;;
    --runs)     RUNS="${2:?}";   shift 2 ;;
    --platform) PLATFORM="${2:?}"; shift 2 ;;
    --offline-probe) OFFLINE=1; shift ;;
    --cold)     COLD=1; shift ;;
    --keep)     KEEP=1; shift ;;
    -h|--help)  usage ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *)  [ -z "$IMAGE" ] && IMAGE="$1" || { echo "unexpected arg: $1" >&2; usage; }; shift ;;
  esac
done

[ -n "$IMAGE" ] || usage
command -v docker >/dev/null 2>&1 || {
  echo "${c_red}docker not found on PATH.${c_off}" >&2
  echo "This script measures a real container start; it cannot be faked." >&2
  echo "Install Docker Desktop (or colima/orbstack) and re-run." >&2
  exit 2; }
docker info >/dev/null 2>&1 || {
  echo "${c_red}docker is installed but the daemon is not responding.${c_off}" >&2
  echo "Start Docker and re-run." >&2; exit 2; }

[ "${#READY[@]}" -gt 0 ] || READY=(
  'temporal operator cluster health >/dev/null 2>&1 || (command -v nc >/dev/null && nc -z 127.0.0.1 7233) || bash -c ":</dev/tcp/127.0.0.1/7233"'
)
if [ -n "$SETUP" ] && [ ! -f "$SETUP" ]; then
  echo "${c_red}--setup script not found: $SETUP${c_off}" >&2; exit 2
fi

CIDS=()
cleanup() {
  [ "$KEEP" = 1 ] && { printf '\n%skept containers: %s%s\n' "$c_dim" "${CIDS[*]:-none}" "$c_off"; return; }
  for c in "${CIDS[@]:-}"; do [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1; done
}
trap cleanup EXIT INT TERM

now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }
fmt() { python3 -c "print(f'{$1/1000:.1f}s')"; }

# ---------------------------------------------------------------------------
# Image presence. With --cold the local copy is removed and a fresh pull is
# timed and counted against the budget, because an Instruqt host is not
# guaranteed to have the image cached. Without --cold, pull time is reported
# only.
# ---------------------------------------------------------------------------
printf '%s%s== image%s\n' "$c_bold" "$c_dim" "$c_off"
if [ "$COLD" = 1 ] && docker image inspect "$IMAGE" >/dev/null 2>&1; then
  printf '  --cold: removing local copy of %s\n' "$IMAGE"
  docker rmi -f "$IMAGE" >/dev/null 2>&1 || {
    printf '  %sFAIL%s could not remove local image (in use by a container?)\n' "$c_red" "$c_off"; exit 2; }
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  printf '  pulling %s ...\n' "$IMAGE"
  t0=$(now_ms)
  docker pull --platform "$PLATFORM" "$IMAGE" >/dev/null 2>&1 || {
    printf '  %sFAIL%s could not pull %s\n' "$c_red" "$c_off" "$IMAGE"
    [ "$COLD" = 1 ] && printf '        --cold needs the image pushed to the registry first.\n'
    exit 2; }
  PULL_MS=$(( $(now_ms) - t0 ))
  if [ "$COLD" = 1 ]; then
    printf '  pull: %s %s(counted against the budget: --cold)%s\n' "$(fmt "$PULL_MS")" "$c_dim" "$c_off"
  else
    printf '  pull: %s %s(not counted; use --cold for the release gate)%s\n' \
      "$(fmt "$PULL_MS")" "$c_dim" "$c_off"
    PULL_MS=0
  fi
fi
SIZE_B=$(docker image inspect "$IMAGE" --format '{{.Size}}' 2>/dev/null || echo 0)
SIZE_MB=$(( SIZE_B / 1024 / 1024 ))
printf '  size: %s MB\n' "$SIZE_MB"
if [ "$SIZE_MB" -gt 6000 ]; then
  printf '  %sWARN%s image is very large (>6GB). Slows pre-staging and hot start fill.\n' "$c_yel" "$c_off"
fi
ARCH=$(docker image inspect "$IMAGE" --format '{{.Architecture}}' 2>/dev/null || echo '?')
if [ "$ARCH" != "amd64" ]; then
  printf '  %sWARN%s image architecture is %s. Instruqt runs linux/amd64; build with --platform linux/amd64.\n' \
    "$c_yel" "$c_off" "$ARCH"
fi

# ---------------------------------------------------------------------------
# start_once <label> <extra docker args...>
# Boots the container, runs the setup script, polls readiness. Echoes elapsed
# ms on success, or "FAIL:<phase>" on failure.
# ---------------------------------------------------------------------------
start_once() {
  local label="$1"; shift
  local cid t0 elapsed rc out
  t0=$(now_ms)
  cid=$(docker run -d --rm --platform "$PLATFORM" "$@" "$IMAGE" \
          sleep infinity 2>/dev/null) || { echo "FAIL:run"; return; }
  CIDS+=("$cid")

  if [ -n "$SETUP" ]; then
    docker cp "$SETUP" "$cid:/tmp/lab-setup" >/dev/null 2>&1 || { echo "FAIL:copy"; return; }
    docker exec "$cid" chmod +x /tmp/lab-setup >/dev/null 2>&1
    out=$(docker exec "$cid" bash /tmp/lab-setup 2>&1); rc=$?
    if [ $rc -ne 0 ]; then
      printf '%s\n' "$out" > "/tmp/lab-setup-${label}.log"
      echo "FAIL:setup"; return
    fi
  fi

  # Poll readiness until budget + 50% grace, so we can report how far over.
  local deadline=$(( BUDGET * 1500 ))
  while :; do
    elapsed=$(( $(now_ms) - t0 ))
    for probe in "${READY[@]}"; do
      if docker exec "$cid" bash -lc "$probe" >/dev/null 2>&1; then
        echo "$elapsed"; return
      fi
    done
    [ "$elapsed" -gt "$deadline" ] && { echo "FAIL:ready"; return; }
    sleep 1
  done
}

explain_fail() {
  case "$1" in
    FAIL:run)   echo "container would not start at all" ;;
    FAIL:copy)  echo "could not copy the setup script in" ;;
    FAIL:setup) echo "the setup script exited non-zero" ;;
    FAIL:ready) echo "readiness probe never passed" ;;
  esac
}

# ---------------------------------------------------------------------------
# Phase 1: offline probe. THE supply-chain test.
# ---------------------------------------------------------------------------
OFFLINE_VERDICT="skipped"
if [ "$OFFLINE" = 1 ]; then
  printf '\n%s%s== offline probe (--network none)%s\n' "$c_bold" "$c_dim" "$c_off"
  printf '  %sIf the lab starts with no network, it provably downloads nothing.%s\n' "$c_dim" "$c_off"
  r=$(start_once offline --network none)
  if [[ "$r" == FAIL:* ]]; then
    OFFLINE_VERDICT="fail"
    printf '  %sFAIL%s %s with networking disabled.\n' "$c_red" "$c_off" "$(explain_fail "$r")"
    printf '        The lab needs the network at start, which means it is pulling\n'
    printf '        content as it comes up. That is the pattern that turns a 90s\n'
    printf '        start into 10 minutes. Bake it into the image.\n'
    [ -f /tmp/lab-setup-offline.log ] && {
      printf '        %slast lines of setup output:%s\n' "$c_dim" "$c_off"
      tail -n 12 /tmp/lab-setup-offline.log | sed 's/^/          /'; }
    printf '        %sLegitimate exception: the allowlisted credential fetch\n' "$c_dim"
    printf '        (LiteLLM key). If that is all it is, re-run without\n'
    printf '        --offline-probe and note it in the PR.%s\n' "$c_off"
  else
    OFFLINE_VERDICT="pass"
    printf '  %sok%s   started fully offline in %s. No runtime downloads.\n' \
      "$c_grn" "$c_off" "$(fmt "$r")"
  fi
fi

# ---------------------------------------------------------------------------
# Phase 2: timed starts
# ---------------------------------------------------------------------------
printf '\n%s%s== timed start (budget %ss)%s\n' "$c_bold" "$c_dim" "$BUDGET" "$c_off"
declare -a TIMES=()
for i in $(seq 1 "$RUNS"); do
  r=$(start_once "timed$i")
  if [[ "$r" == FAIL:* ]]; then
    printf '  run %d: %sFAIL%s %s\n' "$i" "$c_red" "$c_off" "$(explain_fail "$r")"
    [ -f "/tmp/lab-setup-timed$i.log" ] && tail -n 12 "/tmp/lab-setup-timed$i.log" | sed 's/^/        /'
    printf '\n%sVERDICT: FAIL%s - the sandbox does not come up.\n' "$c_red" "$c_off"
    exit 1
  fi
  TIMES+=("$r")
  within=$([ "$r" -le $(( BUDGET * 1000 )) ] && echo "within" || echo "OVER")
  printf '  run %d: %s (%s budget)\n' "$i" "$(fmt "$r")" "$within"
done

AVG=$(python3 -c "
t=[$(IFS=,; echo "${TIMES[*]}")]
print(int(sum(t)/len(t)))")

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
printf '\n%s──────────────────────────────────────────────%s\n' "$c_dim" "$c_off"
printf 'image:        %s\n' "$IMAGE"
printf 'size:         %s MB\n' "$SIZE_MB"
printf 'startup:      %s (avg of %d)\n' "$(fmt "$AVG")" "$RUNS"
if [ "$COLD" = 1 ]; then
  printf 'cold pull:    %s\n' "$(fmt "$PULL_MS")"
  AVG=$(( AVG + PULL_MS ))
  printf 'pull + start: %s\n' "$(fmt "$AVG")"
fi
printf 'budget:       %ss\n' "$BUDGET"
printf 'offline:      %s\n' "$OFFLINE_VERDICT"

RC=0
if [ "$AVG" -gt $(( BUDGET * 1000 )) ]; then
  RC=1
  over=$(python3 -c "print(f'{($AVG/1000 - $BUDGET):.1f}')")
  printf '\n%sVERDICT: FAIL%s - %ss over the %ss budget.\n' "$c_red" "$c_off" "$over" "$BUDGET"
  printf '\nWhere the time goes, in the order worth checking:\n'
  printf '  1. Runtime downloads in the setup script (run audit-dockerfile.sh --track).\n'
  printf '  2. Dependency resolution not warmed at build time (uv sync / mvn / npm ci).\n'
  printf '  3. Services started serially that could start in parallel.\n'
  printf '  4. A large image slowing the pull and unpack.\n'
  printf '\nDo not paper over this with a bigger hot start pool. That is how we\n'
  printf 'got to 913%% over the hot start contract.\n'
elif [ "$OFFLINE_VERDICT" = "fail" ]; then
  RC=1
  printf '\n%sVERDICT: FAIL%s - inside the time budget, but it needs the network\n' "$c_red" "$c_off"
  printf 'at lab start. Fix the runtime pull, or document the allowlisted\n'
  printf 'credential fetch and re-run without --offline-probe.\n'
else
  headroom=$(python3 -c "print(f'{($BUDGET - $AVG/1000):.1f}')")
  printf '\n%sVERDICT: PASS%s - %ss of headroom.\n' "$c_grn" "$c_off" "$headroom"
  [ "$OFFLINE_VERDICT" = "skipped" ] && \
    printf '%sRun again with --offline-probe to prove there are no runtime downloads.%s\n' "$c_yel" "$c_off"
  [ "$COLD" = 0 ] && \
    printf '%sRun again with --cold to include a fresh registry pull. That is the release gate.%s\n' "$c_yel" "$c_off"
fi
exit $RC
