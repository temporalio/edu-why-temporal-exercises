// Captures the Chaos Panel screenshots used in the track's assignment text.
//
// Drives a running panel into each state through its own API, opens it in
// headless Chrome over the DevTools protocol, and crops each section of the
// panel to its own PNG in ../assets. Rerun it whenever the panel changes.
//
// Needs a running sandbox (the local container maps the panel to port 18085)
// and Google Chrome. Node 20 needs the WebSocket flag:
//
//   node --experimental-websocket instruqt/tools/capture-panel-screenshots.mjs
//
// Leaves every component up and no order running.

import { PANEL, allComponentsUp, api, capture, isRunning, openPage, runUntil, sleep, stepStatus } from "./shared.mjs";

// Reloads, then waits out the panel's first refresh and a few order polls.
async function redraw(page) {
  await page.send("Page.reload");
  await sleep(3500);
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
