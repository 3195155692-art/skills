#!/usr/bin/env node
// 用本机 Chrome（无头、独立临时配置）抓取开放获取 PDF。
//
// 为什么需要它：MDPI、Europe PMC render、部分 PMC 页面会对普通 HTTP 客户端返回 403
// （Cloudflare 之类的人机校验）。真实浏览器能正常打开，因此这里驱动 Chrome 去取同一份
// 公开文件。只用于开放获取内容，不做任何登录、付费墙或验证码绕过。
//
// 用法：
//   node browser_pdf_fetch.mjs --url <PDF直链> [--page <落地页>] --out <输出文件> [--timeout 60000]
// 输出：stdout 打印一行 JSON {ok, strategy, bytes, status, type}

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  process.env.LKY_CHROME || "",
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function parseArgs(argv) {
  const args = { port: 9401, timeout: 60000, wait: 4000 };
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (key === "--url") args.url = argv[++i];
    else if (key === "--page") args.page = argv[++i];
    else if (key === "--out") args.out = argv[++i];
    else if (key === "--timeout") args.timeout = Number(argv[++i]);
    else if (key === "--port") args.port = Number(argv[++i]);
    else if (key === "--wait") args.wait = Number(argv[++i]);
    else if (key === "--proxy") args.proxy = argv[++i];
    else if (key === "--headful") args.headful = true;
  }
  if (!args.url || !args.out) throw new Error("需要 --url 与 --out");
  return args;
}

function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error("找不到 Chrome / Chromium / Edge");
}

class Cdp {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.id = 0;
    this.pending = new Map();
    this.listeners = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", () => reject(new Error("CDP 连接失败")), { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(`${message.error.message} (${message.error.code})`));
        else resolve(message.result);
        return;
      }
      if (message.method && this.listeners.has(message.method)) {
        for (const handler of this.listeners.get(message.method)) handler(message.params);
      }
    });
  }

  on(method, handler) {
    if (!this.listeners.has(method)) this.listeners.set(method, new Set());
    this.listeners.get(method).add(handler);
    return () => this.listeners.get(method).delete(handler);
  }

  send(method, params = {}, timeoutMs = 60000) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP ${method} 超时`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
  }
}

async function waitForDebugPort(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`, {
        signal: AbortSignal.timeout(3000),
      });
      if (response.ok) {
        const targets = await response.json();
        const page = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
        if (page) return page.webSocketDebuggerUrl;
      }
    } catch {
      /* 继续等待 */
    }
    await sleep(300);
  }
  throw new Error("Chrome 调试端口未就绪");
}

async function launch(cdpUrl, port, profileDir) {
  const chrome = findChrome();
  const flags = [
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate",
    `--user-data-dir=${profileDir}`,
    `--remote-debugging-port=${port}`,
    "about:blank",
  ];
  // macOS 上 Chrome 不读 http_proxy 环境变量，必须显式指定代理，否则访问不了境外站点。
  if (globalThis.__LKY_PROXY) flags.unshift(`--proxy-server=${globalThis.__LKY_PROXY}`);
  if (!globalThis.__LKY_HEADFUL) flags.unshift("--headless=new");
  const child = spawn(chrome, flags, { stdio: "ignore", detached: false });
  const wsUrl = await waitForDebugPort(port, 20000);
  const cdp = new Cdp(wsUrl);
  await cdp.connect();
  await cdp.send("Page.enable");
  await cdp.send("Network.enable");
  return { child, cdp };
}

function asPdfBytes(body) {
  const bytes = Buffer.from(body.body, body.base64Encoded ? "base64" : "latin1");
  return bytes.subarray(0, 5).toString("latin1") === "%PDF-" ? bytes : null;
}

// 策略 1：先打开落地页，再在页面上下文里 fetch PDF（带上正确的 referer 与 Cookie）
async function viaPageContext(cdp, args) {
  if (!args.page) return null;
  await cdp.send("Page.navigate", { url: args.page });
  await sleep(2500);
  const expression = `(async () => {
    try {
      const res = await fetch(${JSON.stringify(args.url)}, { credentials: 'include',
        headers: { 'Accept': 'application/pdf,*/*' } });
      const buf = new Uint8Array(await res.arrayBuffer());
      let s = '';
      const CH = 0x8000;
      for (let i = 0; i < buf.length; i += CH) s += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
      return JSON.stringify({ status: res.status, type: res.headers.get('content-type') || '', b64: btoa(s) });
    } catch (error) { return JSON.stringify({ error: String(error) }); }
  })()`;
  const evaluated = await cdp.send("Runtime.evaluate",
    { expression, awaitPromise: true, returnByValue: true }, args.timeout);
  if (evaluated.exceptionDetails || !evaluated.result?.value) return null;
  const payload = JSON.parse(evaluated.result.value);
  if (!payload.b64) return null;
  const bytes = Buffer.from(payload.b64, "base64");
  return bytes.subarray(0, 5).toString("latin1") === "%PDF-"
    ? { bytes, status: payload.status, type: payload.type, strategy: "page-context" }
    : null;
}

// 策略 2：直接导航到 PDF，拦截响应体（Chrome 内置阅读器会先拿到原始字节）
async function viaInterception(cdp, args) {
  let captured = null;
  const off = cdp.on("Fetch.requestPaused", (params) => {
    (async () => {
      try {
        if (params.responseStatusCode && !captured) {
          const body = await cdp.send("Fetch.getResponseBody", { requestId: params.requestId }, 60000);
          const bytes = asPdfBytes(body);
          if (bytes) captured = { bytes, status: params.responseStatusCode, strategy: "interception" };
        }
      } catch {
        /* 响应体可能已被回收 */
      }
      try {
        await cdp.send("Fetch.continueRequest", { requestId: params.requestId });
      } catch {
        try {
          await cdp.send("Fetch.continueResponse", { requestId: params.requestId });
        } catch {
          /* 已由浏览器处理 */
        }
      }
    })();
  });
  await cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Response" }] });
  await cdp.send("Page.navigate", { url: args.url }).catch(() => {});
  const deadline = Date.now() + Math.min(args.timeout, 45000);
  while (!captured && Date.now() < deadline) await sleep(400);
  off();
  await cdp.send("Fetch.disable").catch(() => {});
  return captured;
}

// 策略 3：让 Chrome 自己把文件下载到目录（处理 Content-Disposition: attachment）
async function viaDownload(cdp, args, downloadDir) {
  const before = new Set(fs.existsSync(downloadDir) ? fs.readdirSync(downloadDir) : []);
  try {
    await cdp.send("Browser.setDownloadBehavior",
      { behavior: "allow", downloadPath: downloadDir, eventsEnabled: true });
  } catch {
    await cdp.send("Page.setDownloadBehavior", { behavior: "allow", downloadPath: downloadDir });
  }
  await cdp.send("Page.navigate", { url: args.url }).catch(() => {});
  const deadline = Date.now() + Math.min(args.timeout, 60000);
  while (Date.now() < deadline) {
    const fresh = fs.existsSync(downloadDir)
      ? fs.readdirSync(downloadDir).filter((f) => !before.has(f) && !f.endsWith(".crdownload"))
      : [];
    if (fresh.length) {
      const candidate = path.join(downloadDir, fresh[0]);
      const bytes = fs.readFileSync(candidate);
      if (bytes.subarray(0, 5).toString("latin1") === "%PDF-") {
        return { bytes, status: 200, strategy: "download" };
      }
    }
    await sleep(500);
  }
  return null;
}

async function main() {
  const args = parseArgs(process.argv);
  globalThis.__LKY_PROXY = args.proxy || process.env.LKY_CHROME_PROXY || "";
  globalThis.__LKY_HEADFUL = Boolean(args.headful);
  const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "lky-chrome-"));
  const downloadDir = fs.mkdtempSync(path.join(os.tmpdir(), "lky-dl-"));
  let chrome = null;
  let cdp = null;
  let result = null;
  try {
    const launched = await launch(null, args.port, profileDir);
    chrome = launched.child;
    cdp = launched.cdp;
    for (const attempt of [viaPageContext, viaInterception,
                           (c, a) => viaDownload(c, a, downloadDir)]) {
      try {
        result = await attempt(cdp, args);
      } catch {
        result = null;
      }
      if (result?.bytes) break;
      await sleep(500);
    }
    if (result?.bytes) {
      fs.mkdirSync(path.dirname(args.out), { recursive: true });
      fs.writeFileSync(args.out, result.bytes);
      process.stdout.write(JSON.stringify({
        ok: true, strategy: result.strategy, bytes: result.bytes.length,
        status: result.status || 200, type: "application/pdf",
      }) + "\n");
    } else {
      process.stdout.write(JSON.stringify({ ok: false, reason: "三种浏览器策略都未取到 PDF" }) + "\n");
    }
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, reason: String(error.message || error) }) + "\n");
  } finally {
    if (cdp) cdp.close();
    if (chrome) chrome.kill("SIGKILL");
    for (const dir of [profileDir, downloadDir]) {
      try {
        fs.rmSync(dir, { recursive: true, force: true });
      } catch {
        /* 临时目录清理失败不影响结果 */
      }
    }
  }
}

main();
