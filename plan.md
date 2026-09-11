# Build Plan: the "How Software Survives Failure" demo

This repo is the hands-on component of the *How Software Survives Failure* course: a single browser-driven demo, the "chaos panel." The course is **no-code**, so this isn't learner-written exercise code, it's the demo app itself.

One food-delivery order, three lenses:

- **Reliability (Part 1).** Place an order, then break the world with a control panel, toggle off dependencies, kill the Worker, kill the order app, and watch the order survive: steps wait and retry through outages, and a killed Worker resumes where it left off, never double-charging.
- **Insight (Part 2).** Open the real Temporal Web UI for that run and read its event history, every retry, wait, and recovery.
- **Velocity (Part 3).** A contrast between what Temporal handled for free and the machinery a team would otherwise build. **Deferred**, and likely a static or animated piece, so the app build here is Parts 1 and 2.

## Decisions

- **Python** Worker, Workflow, and Activities (`temporalio` SDK).
- **Real Temporal.** The server stays up throughout as the always-on durable foundation; everything around it (Worker, service stubs, order app) is what genuinely stops and restarts, never faked.
- **Separate runnable apps** run locally: Temporal, Worker, service stubs, order app, control plane. The Python components run as plain processes; only Temporal is containerized, and that's a pull of its prebuilt image, not a build, so iteration stays fast and the move to Instruqt stays simple.
- **Transient failures only.** No permanent failures or rollbacks (later courses). Every step succeeds eventually while its service is on.
- **Idempotency throughout.** Every mutating step is idempotent on the order, so retries never double-act (no double-charge, second ticket, or second driver). Payment is the visible headline.
- **One order at a time.** No new order until the current one finishes.
- **Real Temporal Web UI** for Insight, not a custom history view.
- **Themed** chaos panel on Temporal's official brand palette; dark, single theme, since Instruqt is dark.
- **Standalone first.** Instruqt packaging is a later, separate phase.
- **Nothing fakes being down.** Every component the panel can switch off is a real child process the control plane starts and stops: the Worker, the three service stubs, and the order app alike. No service carries a "pretend I'm broken" flag, because real services don't have one. The Worker specifically dies by `kill -9`, an ungraceful crash rather than a clean shutdown.
- **Frontend and updates.** A self-contained vanilla HTML/JS chaos panel, no build step, so it's trivial to serve in an Instruqt tab. It polls the control plane for live updates (WebSocket only if polling feels laggy). Stubs keep a tiny ledger so each service acting once, however many times it's called, is visible on screen.

## Design

**Components** (each a separate app; the Python parts as processes, Temporal as a container):

- **Temporal** — dev server plus Web UI (`:8233`), run from its prebuilt Docker image. Always-on (it's the durable foundation the demo rests on), so in-memory persistence is fine and gives a clean slate each session.
- **Order Workflow** — five sequential steps, each idempotent on the order ID. The three service calls (charge, restaurant, dispatch) carry a retry policy and timeout; the two waits (kitchen, delivery) block on an external signal, the honest model, since a real kitchen or driver reports back rather than finishing on a clock:
  1. Charge payment → payment service (call)
  2. Send to the restaurant → restaurant service (call)
  3. Kitchen prep → wait for a "ready" signal from the (simulated) kitchen
  4. Dispatch a driver → dispatch service (call)
  5. Delivery → wait for a "delivered" signal that names the delivering driver
- **Service stubs** (payment, restaurant, dispatch) — plain services carrying no chaos machinery of their own. "Off" means the process is stopped, so the call fails outright and the step retries until it's back.
- **Worker** — runs the Workflow. Killed with `kill -9` (a real, ungraceful crash, no clean shutdown), then respawned. Identical local or in Instruqt, since it's just a process and a signal.
- **Order app** — the front door. A small service that accepts a place-order request and starts the Workflow. Kill it and no new orders can be placed, while anything already running carries on, because Temporal, not the app, is executing it.
- **Process supervisor** — the shared piece under all the chaos: starts, stops, and reports on the managed child processes (Worker, the three stubs, the order app), and waits for a restarted one to become ready. A module first, driven directly by the integration tests, and later by the control plane.
- **Control plane plus themed frontend** — the always-on backend the panel talks to: places orders, drives the supervisor to stop and start components, and reads Workflow progress to drive the view.

**The toggles.** Most follow one pattern, break it, watch the order survive:

- **Dependencies** off (the process is stopped) → the call fails and the step retries until the service is back; the order never fails.
- **Worker** off → the in-flight order *pauses*; on → it *resumes* where it left off, exactly once.
- **Order app** off → you *can't place new orders* (submit disables), but anything in flight *keeps running*, since Temporal, not the app, executes it.

The Worker/app pair is the sharpest teaching moment: the same gesture has opposite effects on an in-flight order, killing the Worker pauses it, killing the app doesn't touch it. That is what each piece is *for*, the Worker is execution, the app is just the front door.

**Pacing and progress.** Per-step latency lives in the *services* (the payment processor takes a beat), is tunable, and is turned off in tests; its only job is to make a step visible on the progress bar. The real interaction windows come from two places: toggles set *before* a run (flip a dependency off, then place the order, and it fails and retries on its own, no stopwatch), and the genuine waits (kitchen, delivery), where the order parks on an external signal for as long as it takes, the calm place to kill the Worker and watch it resume.

## Delivery

Ships as a sequence of small, independently reviewable PRs. Small, self-contained changes are quicker to review with confidence and keep `main` healthy, since each lands working. Build order and PR order are the same:

1. **Scaffold** — Python project, Temporal via Docker, `pytest`, a trivial Workflow end to end.
2. **First slice** — Workflow skeleton plus charge-payment plus payment stub, end to end, idempotent, tested.
3. **Remaining steps** — restaurant, kitchen, dispatch, delivery, added incrementally (one PR each, paired if trivial); each leaves `main` a working, shorter order.
4. **Chaos panel (mocked)** — the self-contained vanilla panel (order, progress, ledgers, and the chaos controls), every interaction faked in the browser. Lands the UI, and by doing so freezes the contract the control plane will have to satisfy. No backend yet.
5. **Process supervisor** — start, stop, and status for the managed child processes, plus waiting for a restarted one to be ready. The shared foundation both chaos steps rest on; a module first, exercised directly by tests.
6. **Dependency outage** — stop a service stub mid-order; the step retries and the order survives; start it again and the order completes. *(Integration test.)*
7. **Worker chaos** — `kill -9` the Worker mid-order, then respawn: it resumes where it left off and nothing double-acts. *(The crown jewel; its own PR.)*
8. **Order app** — the front-door service that accepts a place-order request and starts the Workflow. Killing it stops new orders while in-flight ones keep running.
9. **Control plane** — the panel-facing API: place an order, read progress, and drive the supervisor for every component.
10. **Wire the panel** — swap the panel's faked state for real calls to the control plane, one capability at a time as its endpoint lands.
11. **Finish** — Insight (link the real Web UI), polish, and a one-command run.
12. **Instruqt adaptation** — package the working standalone demo to run in an Instruqt lab: provisioning the environment and exposing the chaos panel and Temporal Web UI as browser tabs. The process-and-signal kills should carry over cleanly, so this is mostly packaging, not a rebuild. A distinct phase, taken on only once the standalone demo is solid.

## Testing

Test-first, red-green-refactor. The **red** step matters most: confirm the test fails for the right reason, the guard against a test that passes without exercising anything. Writing tests first also forces us to state each durability behavior precisely, which is where the subtlety lives. Runner is `pytest`, and tests ship with the PR that adds the behavior.

- **Workflow** — `WorkflowEnvironment` with time-skipping and mocked Activities. Key cases: the happy path completes; a fail-then-succeed Activity is retried and still completes; and the single most important one, **exactly-once**, no mutating step double-acts under retry (payment the headline).
- **Activities** — `ActivityEnvironment`: each Activity's success and its survivable failure.
- **Stubs, supervisor, and control plane** — FastAPI `TestClient` for the stubs (each acts once per idempotency key) and for the control-plane endpoints (with Temporal and the supervisor mocked). The supervisor gets its own tests: start, stop, status, and waiting for readiness.
- **Frontend** — not a priority; the panel is vanilla HTML/JS, so at most a couple of smoke checks.

One honest boundary: anything that turns on really killing a process (the dependency outage, and the Worker kill-and-resume) is an *integration* property, so those are scripted end-to-end checks rather than unit tests.

## Reference

- `temporal.menu` and `github.com/temporalio/samples-typescript/tree/main/food-delivery` — the app to port from.
- `temporal.io/blog/building-reliable-distributed-systems-in-node` — its write-up.
