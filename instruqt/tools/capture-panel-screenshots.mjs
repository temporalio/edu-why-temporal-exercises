// Captures the Chaos Panel screenshots used in the track's assignment text.
//
// Drives a running panel into each state through its own API, opens it in
// headless Chrome over the DevTools protocol, and crops each section of the
// panel to its own PNG in ../assets. Rerun it whenever the panel changes.
//
// Needs a running sandbox (the local container maps the panel to port 18085)
// and Google Chrome. To capture from the local stack instead, such as a panel
// change not yet in the sandbox image, set PANEL_URL=http://127.0.0.1:8085/.
// Node 20 needs the WebSocket flag:
//
//   node --experimental-websocket instruqt/tools/capture-panel-screenshots.mjs
//
// Leaves every component up and no order running.

import { PANEL, allComponentsUp, api, capture, isRunning, openPage, runUntil, setComponent, sleep, stepStatus } from "./shared.mjs";

// Longer than the panel's 2s refresh, so the panel sees each change made
// through the API before the next one.
const SETTLE_MS = 3000;

// Reloads, then waits out the panel's first refresh and a few order polls.
async function redraw(page) {
  await page.send("Page.reload");
  await sleep(3500);
}

// The Velocity exercise's list of what Temporal handled. The panel builds the
// list as it watches, so the page is open before the order is placed, and the
// order goes through every disruption the list has a line for: payment down
// at the start, the Worker killed at the kitchen with Finish sent while it's
// down, and the Order app switched off mid-order.
async function captureHandled() {
  await runUntil(state => !isRunning(state));
  const page = await openPage(new URL("?velocity", PANEL).href, { width: 1100, height: 1400, port: 9334 });

  try {
    await sleep(3500);

    await setComponent("payment", false);
    await sleep(SETTLE_MS);
    await api("POST", "/orders");
    await runUntil(state => isRunning(state) && stepStatus(state, "charge") === "retrying", { release: false });
    await sleep(SETTLE_MS);
    await setComponent("payment", true);

    await runUntil(state => isRunning(state) && stepStatus(state, "kitchen") === "waiting", { release: false });
    await sleep(SETTLE_MS);
    await setComponent("worker", false);
    await sleep(SETTLE_MS);
    await api("POST", "/signals/order_prepared");
    await sleep(SETTLE_MS);
    await setComponent("worker", true);

    await runUntil(state => isRunning(state) && stepStatus(state, "delivery") === "waiting", { release: false });
    await sleep(SETTLE_MS);
    await setComponent("app", false);
    await sleep(SETTLE_MS * 2);
    await setComponent("app", true);
    await api("POST", "/signals/order_delivered");

    await runUntil(state => !isRunning(state));
    await sleep(SETTLE_MS);
    await capture(page, ["#handled-card"], "panel-handled.png");
  } finally {
    page.close();
  }
}

// --- entry point -------------------------------------------------------------

await allComponentsUp();
await runUntil(state => !isRunning(state));

// An order waiting at the kitchen shows finished steps, a Finish button, and
// ledgers both at x1 and at x0. `runUntil` checks before it releases a wait,
// so the kitchen is caught waiting.
await api("POST", "/orders");
await runUntil(state => isRunning(state) && stepStatus(state, "kitchen") === "waiting");

const page = await openPage(PANEL, { width: 1100, height: 1000, port: 9333 });
try {
  await redraw(page);
  await capture(page, [".stage-head", ".narration"], "panel-status.png");
  await capture(page, [".pipeline"], "panel-stages.png");
  await capture(page, ["#ledgers"], "panel-ledgers.png");

  // The bottom row reads "Place order" only once no order is running.
  await runUntil(state => !isRunning(state));
  await redraw(page);
  await capture(page, [".levers"], "panel-controls.png");
} finally {
  page.close();
}

await captureHandled();
