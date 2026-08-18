# Build Plan: the "How Software Survives Failure" demo

This repo is the hands-on component of the *How Software Survives Failure* course: a single browser-driven demo, the "chaos panel." The course is **no-code**, so this isn't learner-written exercise code, it's the demo app itself.

One food-delivery order, three lenses:

- **Reliability (Part 1).** Place an order, then break the world with a control panel, toggle off dependencies, kill the worker, kill the order app, and watch the order survive: steps wait and retry through outages, and a killed worker resumes where it left off, never double-charging.
- **Insight (Part 2).** Open the real Temporal Web UI for that run and read its event history, every retry, wait, and recovery.
- **Velocity (Part 3).** A contrast between what Temporal handled for free and the machinery a team would otherwise build. **Deferred**, and likely a static or animated piece, so the app build here is Parts 1 and 2.

## Decisions

- **Python** worker, workflow, and activities (`temporalio` SDK).
- **Real Temporal.** The server stays up throughout as the always-on durable foundation; the worker is the thing genuinely stopped and restarted, never faked.
- **Separate runnable apps** run locally: Temporal, worker, service stubs, control plane, order client. The Python components run as plain processes; only Temporal is containerized, and that's a pull of its prebuilt image, not a build, so iteration stays fast and the move to Instruqt stays simple.
- **Transient failures only.** No permanent failures or rollbacks (later courses). Every step succeeds eventually while its service is on.
- **Idempotency throughout.** Every mutating step is idempotent on the order, so retries never double-act (no double-charge, second ticket, or second driver). Payment is the visible headline.
- **One order at a time.** No new order until the current one finishes.
- **Real Temporal Web UI** for Insight, not a custom history view.
- **Themed** chaos panel in the Temporal palette (dark background, text `#F8FAFC`, green `#59FDA0`, pink `#FF79C6`, cyan `#8BE9FD`).
- **Standalone first.** Instruqt packaging is a later, separate phase.
- **Worker kill** with `kill -9` on a control-plane-managed child process, then respawn. A real, ungraceful crash, not a container stop.
- **Frontend and updates.** React for the chaos panel, polling for live updates (WebSocket only if it feels laggy), and stubs that keep a tiny ledger so "charged exactly once" is visible on screen.

## Design

**Components** (each a separate app; the Python parts as processes, Temporal as a container):

- **Temporal** — dev server plus Web UI (`:8233`), run from its prebuilt Docker image. Always-on (it's the durable foundation the demo rests on), so in-memory persistence is fine and gives a clean slate each session.
- **Order workflow** — five sequential activities, each with its own retry policy and timeout, each idempotent on the order ID:
  1. Charge payment → payment service
  2. Send to the restaurant → restaurant service
  3. Kitchen prep → a timer (natural wait)
  4. Dispatch a driver → driver service
  5. Delivery → a timer (en route) plus a driver-service confirm
- **Service stubs** (payment, restaurant, driver) — each with an on/off switch; off makes the call fail so the step retries.
- **Worker** — runs the workflow. The control plane launches it as a child process and kills it with `kill -9` (a real, ungraceful crash, no clean shutdown), then respawns it. Identical local or in Instruqt, since it's just a process and a signal.
- **Control plane plus themed frontend** — the always-on backend the panel talks to: places orders, toggles the stubs, stops and starts the worker, models the order app up or down, and reads workflow progress to drive the view.

**The toggles.** Most follow one pattern, break it, watch the order survive:

- **Dependencies** off → the step waits and retries until back on; the order never fails.
- **Worker** off → the in-flight order *pauses*; on → it *resumes* where it left off, exactly once.
- **Order app** off → you *can't place new orders* (submit disables), but anything in flight *keeps running*, since Temporal, not the app, executes it.

The worker/app pair is the sharpest teaching moment: the same gesture has opposite effects on an in-flight order, killing the worker pauses it, killing the app doesn't touch it. That is what each piece is *for*, the worker is execution, the app is just the front door.

**Pacing and progress.** Steps need short, tunable delays (`workflow.sleep` timers, themselves durable) so there's a window to break things; where the domain already waits (kitchen prep, driver en route) we lean on that. Time-skipping keeps these delays out of the test suite. A simple progress indicator shows which steps are done and which is current. Progress comes from a workflow Query the frontend polls; while the worker is off the Query can't answer, but the bar just holds at the last step and the worker toggle explains it.

## Delivery

Ships as a sequence of small, independently reviewable PRs. Small, self-contained changes are quicker to review with confidence and keep `main` healthy, since each lands working. Build order and PR order are the same:

1. **Scaffold** — Python project, Temporal via Docker, `pytest`, a trivial workflow end to end.
2. **First slice** — workflow skeleton plus charge-payment plus payment stub, end to end, idempotent, tested.
3. **Remaining steps** — restaurant, kitchen timer, dispatch, delivery, added incrementally (one PR each, paired if trivial); each leaves `main` a working, shorter order.
4. **Dependency chaos** — toggleable stubs plus a "survives an outage" integration test.
5. **Worker chaos** — stop/restart plus a "resumes after a kill, exactly once" integration test. *(The crown jewel; its own PR.)*
6. **Control plane** — place-order, read-progress, and the toggle endpoints.
7. **Chaos panel** — frontend: order plus progress view plus toggle controls, wired to the full interaction.
8. **Finish** — theming, Insight (link the real Web UI), polish, and a one-command run.
9. **Instruqt adaptation** — package the working standalone demo to run in an Instruqt lab: provisioning the environment and exposing the chaos panel and Temporal Web UI as browser tabs. The process-and-signal worker kill should carry over cleanly, so this is mostly packaging, not a rebuild. A distinct phase, taken on only once the standalone demo is solid.

## Testing

Test-first, red-green-refactor. The **red** step matters most: confirm the test fails for the right reason, the guard against a test that passes without exercising anything. Writing tests first also forces us to state each durability behavior precisely, which is where the subtlety lives. Runner is `pytest`, and tests ship with the PR that adds the behavior.

- **Workflow** — `WorkflowEnvironment` with time-skipping and mocked activities. Key cases: the happy path completes; a fail-then-succeed activity is retried and still completes; and the single most important one, **exactly-once**, no mutating step double-acts under retry (payment the headline).
- **Activities** — `ActivityEnvironment`: each activity's success and its survivable failure.
- **Stubs and control plane** — FastAPI `TestClient`: toggles behave, each stub acts once per idempotency key, endpoints behave with Temporal and worker-control mocked.
- **Frontend** — light Testing Library tests if we use React; not a priority.

One honest boundary: the worker-kill-and-resume is an *integration* property (a real `kill -9`, Temporal continuing the run), so it's a scripted end-to-end check, not a unit test.

## Reference

- `temporal.menu` and `github.com/temporalio/samples-typescript/tree/main/food-delivery` — the app to port from.
- `temporal.io/blog/building-reliable-distributed-systems-in-node` — its write-up.
