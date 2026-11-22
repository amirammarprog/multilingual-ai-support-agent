// Takes the README screenshots from a running stack with a headless Chromium browser (Chrome DevTools
// Protocol, no extra dependencies). Usage:
//   BROWSER="/path/to/chrome" BASE_URL=http://localhost:8080 node scripts/screenshots.mjs ../docs/screenshots
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BROWSER = process.env.BROWSER;
const BASE = process.env.BASE_URL ?? "http://localhost:8080";
const OUT = process.argv[2] ?? "screenshots";
const PASSWORD = process.env.DEMO_PASSWORD ?? "demo-password-2026";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync(OUT, { recursive: true });

const profile = mkdtempSync(join(tmpdir(), "shots-"));
const browser = spawn(BROWSER, ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${profile}`,
  "--no-first-run", "--hide-scrollbars", "--lang=en-US", "about:blank"], { stdio: "ignore" });

let ws;
let nextId = 1;
const pending = new Map();
function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
async function evaluate(expression) {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
}
async function size(width, height, mobile = false) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
}
async function scheme(dark) {
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: dark ? "dark" : "light" }] });
}
async function go(path, wait = 2500) {
  await send("Page.navigate", { url: BASE + path });
  await sleep(wait);
}
async function shot(name) {
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, "base64"));
  console.log("saved", name);
}
async function click(x, y) {
  for (const type of ["mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  }
}
async function prefs(lang, theme) {
  await evaluate(`localStorage.setItem("ui_lang", "${lang}"); localStorage.setItem("theme", "${theme}"); true`);
}
const waitFor = async (expression, timeout = 60000) => {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await evaluate(expression)) return;
    await sleep(500);
  }
  throw new Error(`timeout waiting for ${expression}`);
};

for (let i = 0; i < 40; i++) {
  try {
    const pages = await (await fetch("http://127.0.0.1:9333/json/list")).json();
    const page = pages.find((p) => p.type === "page");
    if (page) {
      ws = new WebSocket(page.webSocketDebuggerUrl);
      break;
    }
  } catch {
    /* not up yet */
  }
  await sleep(250);
}
await new Promise((r) => (ws.onopen = r));
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  }
};
await send("Page.enable");
await send("Runtime.enable");

try {
  // 1. Landing page (light, English)
  await size(1440, 900);
  await scheme(false);
  await go("/");
  await prefs("en", "light");
  await go("/", 3000);
  await shot("landing");

  // 2. Customer chat: order status, Tunisian Arabizi and Arabic questions
  await go("/chat", 4000);
  for (const index of [0, 3, 2, 1]) {
    const before = await evaluate(`document.querySelectorAll("main .whitespace-pre-wrap").length`);
    await evaluate(`document.querySelectorAll("aside ul button")[${index}].click(); true`);
    await waitFor(`document.querySelectorAll("main .whitespace-pre-wrap").length >= ${before + 2}`);
    await sleep(800);
  }
  await sleep(1000);
  await shot("chat");

  // 3. Same app in Arabic, dark mode (right-to-left interface)
  await scheme(true);
  await prefs("ar", "dark");
  await go("/chat", 4000);
  await evaluate(`document.querySelectorAll("aside ul button")[2].click(); true`);
  await waitFor(`document.querySelectorAll("main .whitespace-pre-wrap").length >= 2`);
  await evaluate(`document.querySelectorAll("aside ul button")[3].click(); true`);
  await waitFor(`document.querySelectorAll("main .whitespace-pre-wrap").length >= 4`);
  await sleep(1500);
  await shot("chat-arabic-dark");

  // 4. Admin console
  await scheme(false);
  await prefs("en", "light");
  await evaluate(`fetch("/api/v1/auth/login", {method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({email: "admin@brightcart.example.com", password: "${PASSWORD}"})})
    .then(r => r.json()).then(d => { sessionStorage.setItem("staff_token", d.access_token); return true; })`);
  await go("/admin", 5000);
  await shot("admin-dashboard");

  const conversation = await evaluate(`fetch("/api/v1/admin/conversations?limit=100", {headers: {authorization: "Bearer " + sessionStorage.getItem("staff_token")}})
    .then(r => r.json()).then(d => (d.items.find(c => c.preview.includes("chnowa")) || d.items[0]).id)`);
  await go(`/admin/conversations/${conversation}`, 4000);
  await shot("admin-conversation");

  await go("/admin/knowledge", 3000);
  await evaluate(`(() => { const input = document.querySelector("form input");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, "Is liquid damage covered by the warranty?"); input.dispatchEvent(new Event("input", {bubbles: true}));
    document.querySelector("form button[type=submit]").click(); return true; })()`);
  await waitFor(`document.body.innerText.includes("candidates")`);
  await sleep(1000);
  await send("Runtime.evaluate", { expression: "window.scrollTo(0, document.body.scrollHeight)" });
  await sleep(800);
  await shot("admin-knowledge");

  await go("/admin/evaluations", 5000);
  await shot("admin-evaluations");

  // 5. The embeddable widget on the fictional shop page, on a phone-sized screen
  await size(390, 844, true);
  await go("/demo-store.html", 3000);
  await click(390 - 48, 844 - 48);
  await sleep(2500);
  await click(150, 844 - 70);
  await send("Input.insertText", { text: "Est-ce que le casque Tessio ANC 700 est disponible ?" });
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await sleep(9000);
  await shot("widget-mobile");
} finally {
  ws.close();
  browser.kill();
}
