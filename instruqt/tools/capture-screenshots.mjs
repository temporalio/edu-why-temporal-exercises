// Captures the Chaos Panel screenshots used in the track's assignment text.
//
// Drives a running panel into each state through its own API, opens it in
// headless Chrome over the DevTools protocol, and crops each section of the
// panel to its own PNG in ../assets. Rerun it whenever the panel changes.
//
// Needs a running sandbox (the local container maps the panel to port 18085)
// and Google Chrome. Node 20 needs the WebSocket flag:
//
//   node --experimental-websocket instruqt/tools/capture-screenshots.mjs
//
// Leaves every component up and no order running.

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PANEL = process.env.PANEL_URL ?? "http://127.0.0.1:18085/";
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const DEBUG_PORT = 9333;
const ASSETS = new URL("../assets/", import.meta.url).pathname;
const COMPONENTS = ["payment", "restaurant", "dispatch", "app", "worker"];

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// --- the panel's API ---------------------------------------------------------

async function api(method, path, body) {
  const response = await fetch(new URL(path, PANEL), {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${path} answered ${response.status}`);

  return response.json();
}

function stepStatus(state, key) {
  return state.order.steps.find(step => step.key === key)?.status;
}

function isRunning(state) {
  return state.order !== null && state.order.steps.some(step => step.status !== "done");
}

// Polls until `done(state)` holds, releasing either wait it passes on the way.
async function runUntil(done, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const state = await api("GET", "/state");
    if (done(state)) return state;

    if (state.order && stepStatus(state, "kitchen") === "waiting" && !state.signals_sent.includes("order_prepared")) {
      await api("POST", "/signals/order_prepared");
    }
    if (state.order && stepStatus(state, "delivery") === "waiting" && !state.signals_sent.includes("order_delivered")) {
      await api("POST", "/signals/order_delivered");
    }

    await sleep(500);
  }

  throw new Error("timed out waiting for the panel to reach the state to capture");
}

async function allComponentsUp() {
  for (const name of COMPONENTS) {
    await api("PUT", `/components/${name}`, { up: true });
  }
}

// --- headless Chrome ---------------------------------------------------------

async function openPanel() {
  const chrome = spawn(CHROME, [
    "--headless=new",
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${mkdtempSync(join(tmpdir(), "panel-shots-"))}`,
    "--hide-scrollbars",
  ], { stdio: "ignore" });

  for (let i = 0; i < 50; i++) {
    try {
      await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
      break;
    } catch {
      await sleep(100);
    }
  }

  const target = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new?${PANEL}`, { method: "PUT" })).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener("open", resolve));

  let nextId = 0;
  const pending = new Map();
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });

  const send = (method, params = {}) => new Promise(resolve => {
    const id = ++nextId;
    pending.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });

  // Twice the pixels, so the images stay sharp when Instruqt scales them.
  await send("Emulation.setDeviceMetricsOverride", { width: 1100, height: 1000, deviceScaleFactor: 2, mobile: false });

  return {
    send,
    close() {
      socket.close();
      chrome.kill();
    },
  };
}

// Reloads, then waits out the panel's first refresh and a few order polls.
async function redraw(page) {
  await page.send("Page.reload");
  await sleep(3500);
}

// Crops the area covering every selector, plus a margin, to one PNG.
async function capture(page, selectors, file, margin = 8) {
  const result = await page.send("Runtime.evaluate", {
    expression: `JSON.stringify(${JSON.stringify(selectors)}.map(s => document.querySelector(s).getBoundingClientRect()))`,
    returnByValue: true,
  });
  const rects = JSON.parse(result.result.result.value);

  const left = Math.min(...rects.map(rect => rect.left));
  const top = Math.min(...rects.map(rect => rect.top));
  const right = Math.max(...rects.map(rect => rect.right));
  const bottom = Math.max(...rects.map(rect => rect.bottom));

  const shot = await page.send("Page.captureScreenshot", {
    format: "png",
    clip: {
      x: left - margin,
      y: top - margin,
      width: right - left + margin * 2,
      height: bottom - top + margin * 2,
      scale: 1,
    },
  });
  writeFileSync(join(ASSETS, file), Buffer.from(shot.result.data, "base64"));
  console.log(`wrote assets/${file}`);
}

// --- entry point -------------------------------------------------------------

await allComponentsUp();
await runUntil(state => !isRunning(state));

// An order waiting at the kitchen shows finished steps, a Finish button, and
// ledgers both at x1 and at x0. `runUntil` checks before it releases a wait,
// so the kitchen is caught waiting.
await api("POST", "/orders");
await runUntil(state => isRunning(state) && stepStatus(state, "kitchen") === "waiting");

const page = await openPanel();
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
