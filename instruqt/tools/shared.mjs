// Helpers shared by the screenshot scripts: the Chaos Panel's API, headless
// Chrome over the DevTools protocol, and cropping a screenshot to a region.

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const PANEL = process.env.PANEL_URL ?? "http://127.0.0.1:18085/";
export const TEMPORAL_UI = process.env.TEMPORAL_UI_URL ?? "http://127.0.0.1:18233/";
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const ASSETS = new URL("../assets/", import.meta.url).pathname;
const COMPONENTS = ["payment", "restaurant", "dispatch", "app", "worker"];

export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

// --- the panel's API ---------------------------------------------------------

export async function api(method, path, body) {
  const response = await fetch(new URL(path, PANEL), {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`${method} ${path} answered ${response.status}`);

  return response.json();
}

export function setComponent(name, up) {
  return api("PUT", `/components/${name}`, { up });
}

export async function allComponentsUp() {
  for (const name of COMPONENTS) {
    await setComponent(name, true);
  }
}

export function stepStatus(state, key) {
  return state.order.steps.find(step => step.key === key)?.status;
}

export function isRunning(state) {
  return state.order !== null && state.order.steps.some(step => step.status !== "done");
}

// Polls until `done(state)` holds. With `release`, it also sends either wait's
// signal once that wait is reached; it checks `done` first, so a state that
// ends at a wait is caught before the wait is released.
export async function runUntil(done, { release = true, timeoutMs = 90000 } = {}) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const state = await api("GET", "/state");
    if (done(state)) return state;

    if (release && state.order && stepStatus(state, "kitchen") === "waiting" && !state.signals_sent.includes("order_prepared")) {
      await api("POST", "/signals/order_prepared");
    }
    if (release && state.order && stepStatus(state, "delivery") === "waiting" && !state.signals_sent.includes("order_delivered")) {
      await api("POST", "/signals/order_delivered");
    }

    await sleep(500);
  }

  throw new Error("timed out waiting for the panel to reach the state to capture");
}

// --- headless Chrome ---------------------------------------------------------

// Opens `url` in headless Chrome at the given viewport, at twice the pixels so
// the images stay sharp when Instruqt scales them.
export async function openPage(url, { width, height, port }) {
  const chrome = spawn(CHROME, [
    "--headless=new",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${mkdtempSync(join(tmpdir(), "shots-"))}`,
    "--hide-scrollbars",
  ], { stdio: "ignore" });

  for (let i = 0; i < 50; i++) {
    try {
      await fetch(`http://127.0.0.1:${port}/json/version`);
      break;
    } catch {
      await sleep(100);
    }
  }

  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?${url}`, { method: "PUT" })).json();
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

  async function evaluate(expression) {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    return result.result.result.value;
  }

  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 2, mobile: false });

  return {
    send,
    evaluate,
    async goto(nextUrl, settleMs) {
      await send("Page.navigate", { url: nextUrl });
      await sleep(settleMs);
    },
    close() {
      socket.close();
      chrome.kill();
    },
  };
}

// --- cropping ----------------------------------------------------------------

export function union(rects) {
  const left = Math.min(...rects.map(rect => rect.left));
  const top = Math.min(...rects.map(rect => rect.top));
  const right = Math.max(...rects.map(rect => rect.right));
  const bottom = Math.max(...rects.map(rect => rect.bottom));

  return { left, top, right, bottom };
}

// The bounding boxes of the first element matching each CSS selector.
export async function rectsOf(page, selectors) {
  const json = await page.evaluate(
    `JSON.stringify(${JSON.stringify(selectors)}.map(s => document.querySelector(s).getBoundingClientRect()))`,
  );

  return JSON.parse(json);
}

export async function captureRect(page, rect, file, margin = 8) {
  const shot = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: {
      x: rect.left - margin,
      y: rect.top - margin,
      width: rect.right - rect.left + margin * 2,
      height: rect.bottom - rect.top + margin * 2,
      scale: 1,
    },
  });
  writeFileSync(join(ASSETS, file), Buffer.from(shot.result.data, "base64"));
  console.log(`wrote assets/${file}`);
}

// Draws a box around `rect`, on top of the page, to point the reader at it.
// It's a separate element rather than a style on the page's own, so the
// page's styles can't hide it.
export async function highlight(page, rect, padding = 6) {
  await page.evaluate(`(() => {
    const box = document.createElement("div");
    box.dataset.highlight = "";
    // The rect is relative to the viewport; the box sits in the page, so the
    // scroll position is added back.
    Object.assign(box.style, {
      position: "absolute",
      left: (${rect.left - padding} + scrollX) + "px",
      top: (${rect.top - padding} + scrollY) + "px",
      width: "${rect.right - rect.left + padding * 2}px",
      height: "${rect.bottom - rect.top + padding * 2}px",
      border: "3px solid #e5484d",
      borderRadius: "8px",
      pointerEvents: "none",
      zIndex: "2147483647",
    });
    document.body.appendChild(box);
  })()`);
}

export async function clearHighlights(page) {
  await page.evaluate(`document.querySelectorAll("[data-highlight]").forEach(box => box.remove())`);
}

// Crops the area covering every selector, plus a margin, to one PNG.
export async function capture(page, selectors, file, margin = 8) {
  await captureRect(page, union(await rectsOf(page, selectors)), file, margin);
}
