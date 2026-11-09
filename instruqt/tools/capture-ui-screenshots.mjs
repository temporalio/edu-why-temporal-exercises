// Captures the Temporal UI screenshots used in the Insight exercise.
//
// Puts one order through the chaos a learner would cause: payment down when
// it's placed, the Worker killed while the kitchen Signal arrives, and the
// rest released normally. It captures the order's page in the Temporal UI at
// each point, cropped to the part the text talks about, into ../assets.
//
// Needs a running sandbox (the local container maps the panel to port 18085
// and the Temporal UI to 18233) and Google Chrome. Node 20 needs the
// WebSocket flag:
//
//   node --experimental-websocket instruqt/tools/capture-ui-screenshots.mjs
//
// Leaves every component up and no order running.

import {
  TEMPORAL_UI, allComponentsUp, api, captureRect, clearHighlights, highlight, isRunning, openPage, runUntil, setComponent,
  sleep, stepStatus, union,
} from "./shared.mjs";

// How long the Temporal UI needs to fetch and draw a page.
const UI_SETTLE_MS = 4000;

// How long payment stays down, long enough for several retries to show.
const PAYMENT_OUTAGE_MS = 25000;

// --- finding things on the page ----------------------------------------------

// The bounding box of the smallest visible element whose text is exactly
// `text`. Visible, because the UI keeps hidden copies of some controls.
async function rectOfText(page, text) {
  const json = await page.evaluate(`(() => {
    const matches = [...document.querySelectorAll("body *")]
      .filter(e => e.innerText && e.innerText.trim() === ${JSON.stringify(text)})
      .filter(e => e.getBoundingClientRect().width > 0);
    const smallest = matches.sort((a, b) => a.innerText.length - b.innerText.length || a.contains(b) - b.contains(a)).pop();
    return smallest ? JSON.stringify(smallest.getBoundingClientRect()) : null;
  })()`);
  if (!json) throw new Error(`no element with the text ${JSON.stringify(text)}`);

  return JSON.parse(json);
}

// The bounding box of the first visible element `selector` matches whose text
// includes `text`. Uses textContent, since SVG elements have no innerText.
async function rectOfMatch(page, selector, text) {
  const json = await page.evaluate(`(() => {
    const match = [...document.querySelectorAll(${JSON.stringify(selector)})]
      .find(e => e.textContent.includes(${JSON.stringify(text)}) && e.getBoundingClientRect().width > 0);
    return match ? JSON.stringify(match.getBoundingClientRect()) : null;
  })()`);
  if (!json) throw new Error(`no ${selector} containing ${JSON.stringify(text)}`);

  return JSON.parse(json);
}

// The Event History rows from `before` rows above the first row containing
// `text` to `after` rows below it.
async function rowsAround(page, text, before, after) {
  const json = await page.evaluate(`(() => {
    const rows = [...document.querySelectorAll("tbody tr")];
    const index = rows.findIndex(row => row.innerText.includes(${JSON.stringify(text)}));
    if (index < 0) return null;
    const picked = rows.slice(Math.max(0, index - ${before}), index + ${after} + 1);
    return JSON.stringify(picked.map(row => row.getBoundingClientRect()));
  })()`);
  if (!json) throw new Error(`no Event History row containing ${JSON.stringify(text)}`);

  return union(JSON.parse(json));
}

// Clicks the first link or button whose label starts with `text`. Starts with,
// because a tab's label carries a count after its name.
async function clickText(page, text) {
  const clicked = await page.evaluate(`(() => {
    const target = [...document.querySelectorAll("a, button")].find(e => e.innerText.trim().startsWith(${JSON.stringify(text)}));
    if (target) target.click();
    return !!target;
  })()`);
  if (!clicked) throw new Error(`nothing to click with the text ${JSON.stringify(text)}`);
}

// The content column, from the left of "Back to Workflows" to the page's
// right margin, with the top and bottom of `rect`.
async function inContentColumn(page, rect) {
  const back = await rectOfText(page, "Back to Workflows");
  const width = await page.evaluate("innerWidth");

  return { left: back.left - 12, right: width - 20, top: rect.top, bottom: rect.bottom };
}

// --- entry point -------------------------------------------------------------

await allComponentsUp();
await runUntil(state => !isRunning(state));

// Payment is down when the order is placed, so the first step retries.
await setComponent("payment", false);
const { order_id: orderId } = await api("POST", "/orders");
const orderUrl = new URL(`namespaces/default/workflows/${orderId}`, TEMPORAL_UI).href;

// Wide enough that the Last Failure box shows the error without much wrapping.
const page = await openPage(orderUrl, { width: 1600, height: 1100, port: 9336 });
try {
  await sleep(PAYMENT_OUTAGE_MS);

  // Pending Activities, while payment is still down: the attempt count, the
  // next retry and the error.
  await page.goto(orderUrl, UI_SETTLE_MS);
  await clickText(page, "Pending Activities");
  await sleep(UI_SETTLE_MS);
  const tabs = await rectOfMatch(page, "a", "Pending Activities");
  // Ends above the Stack Trace, which runs far down the page.
  const stackTrace = await rectOfText(page, "Stack Trace");
  await captureRect(page, await inContentColumn(page, { top: tabs.top - 8, bottom: stackTrace.top - 8 }), "ui-pending-activities.png");

  // With payment back, the order runs on to the kitchen and waits there.
  await setComponent("payment", true);
  await runUntil(state => isRunning(state) && stepStatus(state, "kitchen") === "waiting", { release: false });

  // The order's page: its status, its ID and its input.
  await page.goto(orderUrl, UI_SETTLE_MS);
  const back = await rectOfText(page, "Back to Workflows");
  const input = await rectOfMatch(page, ".cm-editor", "amount_cents");
  await captureRect(page, await inContentColumn(page, { top: back.top, bottom: input.bottom + 12 }), "ui-order.png");

  // Where to find the Queries tab: the order's header and its tabs.
  const queriesTab = await rectOfMatch(page, "a", "Queries");
  await highlight(page, queriesTab);
  await captureRect(page, await inContentColumn(page, { top: back.top, bottom: queriesTab.bottom + 6 }), "ui-queries-tab.png");
  await clearHighlights(page);

  // Queries: ask the order where it is.
  await clickText(page, "Queries");
  await sleep(UI_SETTLE_MS);
  await clickText(page, "Run Query");
  await sleep(UI_SETTLE_MS);
  const queryType = await rectOfText(page, "Query Type");
  // Once it has run, "Run Query" becomes "Refresh Query".
  const refreshQuery = await rectOfText(page, "Refresh Query");
  await captureRect(page, await inContentColumn(page, { top: queryType.top - 16, bottom: refreshQuery.bottom + 24 }), "ui-query.png");

  // The Workflows list with the running order on top, and the Refresh button
  // outlined: the list doesn't always show a new order until it's refreshed.
  await page.goto(new URL("namespaces/default/workflows", TEMPORAL_UI).href, UI_SETTLE_MS);
  await highlight(page, await rectOfText(page, "Refresh"));
  const heading = await rectOfMatch(page, "h1, h2", "Workflows");
  const firstRows = JSON.parse(await page.evaluate(
    `JSON.stringify([...document.querySelectorAll("tbody tr")].slice(0, 4).map(row => row.getBoundingClientRect()))`,
  ));
  const width = await page.evaluate("innerWidth");
  await captureRect(page, { left: heading.left - 12, right: width - 20, top: heading.top - 12, bottom: union(firstRows).bottom }, "ui-workflows.png");

  // The Worker dies, the kitchen's Signal arrives while it's down, and a new
  // Worker picks the order up.
  await setComponent("worker", false);
  await sleep(2000);
  await api("POST", "/signals/order_prepared");
  await sleep(5000);
  await setComponent("worker", true);
  await runUntil(state => !isRunning(state));

  // The Timeline of the finished order: the long payment bar is the outage.
  await page.goto(orderUrl, UI_SETTLE_MS);
  const timelineHeading = await rectOfText(page, "Timeline");
  const timeline = await rectOfMatch(page, "svg", "charge_payment");
  await captureRect(page, await inContentColumn(page, { top: timelineHeading.top - 8, bottom: timeline.bottom + 8 }), "ui-timeline.png");

  // Where to find the Event History tab: the finished order's header and tabs.
  const finishedBack = await rectOfText(page, "Back to Workflows");
  const historyTab = await rectOfMatch(page, "a", "Event History");
  await highlight(page, historyTab);
  await captureRect(page, await inContentColumn(page, { top: finishedBack.top, bottom: historyTab.bottom + 6 }), "ui-history-tab.png");
  await clearHighlights(page);

  // Event History: the payment step's attempts, and the crash. The table
  // draws only the rows near the screen, so the window is made tall enough to
  // hold the whole history, and the order is switched to oldest first.
  await page.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 2800, deviceScaleFactor: 2, mobile: false });
  await clickText(page, "Event History");
  await sleep(UI_SETTLE_MS);
  // Where to flip the order: the Event History heading and its buttons, with
  // Descending highlighted.
  const historyHeading = await rectOfMatch(page, "h1, h2, h3", "Event History");
  const descending = await rectOfMatch(page, "button", "Descending");
  const tableHeader = await rectOfMatch(page, "thead tr", "Event Type");
  await highlight(page, descending);
  await captureRect(page, await inContentColumn(page, { top: historyHeading.top - 12, bottom: tableHeader.bottom - 8 }), "ui-history-order.png");
  await clearHighlights(page);

  await clickText(page, "Descending");
  await sleep(UI_SETTLE_MS);
  // Scheduled, started (with the attempt count) and completed (with the result).
  await captureRect(page, await rowsAround(page, "charge_payment", 0, 2), "ui-history-payment.png", 0);
  // The last task the old Worker finished, the Signal arriving while no Worker
  // is running, the timeout, and the new Worker picking the order up.
  await captureRect(page, await rowsAround(page, "Workflow Task Timed Out", 3, 3), "ui-history-crash.png", 0);
} finally {
  page.close();
}
