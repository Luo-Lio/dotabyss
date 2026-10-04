#!/usr/bin/env node
/**
 * ドットアビスX 诊断包自托管接收端(零依赖,Node 18+)—— 加固版
 *
 * 收 launcher 的 upload_diagnostics:POST multipart/form-data,含文件字段 "file"(zip)
 * 与文本字段 "summary"(摘要);可选 Authorization: Bearer <TOKEN>。收到即按日期落盘。
 *
 * 防滥用 & 隐身:
 *  - SECRET_PATH:仅接受该精确路径的 POST;其它任何路径/方法一律 404(对外像不存在)。
 *  - RATE_MAX/RATE_WINDOW_MS:按来源 IP 令牌桶限速,超限 429。
 *  - MAX_CONC:并发接收上限。MAX_BYTES:单包大小上限。
 *  - 不打印任何产品/品牌标识,响应体最小化。
 *
 * 运行(示例):
 *   HOST=0.0.0.0 PORT=41787 SECRET_PATH=/ingest/9f3c2a1b \
 *   TOKEN=<上传口令> STORE_DIR=/srv/diag-inbox \
 *   RATE_MAX=6 RATE_WINDOW_MS=60000 MAX_CONC=4 node diag_server.js
 */
const http = require("http");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const HOST = process.env.HOST || "0.0.0.0";
const PORT = parseInt(process.env.PORT || "41787", 10);
const TOKEN = process.env.TOKEN || "";              // 空则不校验令牌
const SECRET_PATH = process.env.SECRET_PATH || "";   // 空则任意路径都收(不建议)
const RATE_MAX = parseInt(process.env.RATE_MAX || "6", 10);
const RATE_WINDOW_MS = parseInt(process.env.RATE_WINDOW_MS || "60000", 10);
const MAX_CONC = parseInt(process.env.MAX_CONC || "4", 10);
const MAX_BYTES = 64 * 1024 * 1024;
const STORE_DIR = process.env.STORE_DIR || path.join(process.cwd(), "diag-inbox");

function log(...a) { console.log(new Date().toISOString(), ...a); }
function safeName(n) {
  return path.basename(String(n || "diag.zip")).replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120) || "diag.zip";
}

// 按 IP 的滑动窗口计数限速。
const buckets = new Map();
function rateOk(ip) {
  const now = Date.now();
  let arr = buckets.get(ip);
  if (!arr) { arr = []; buckets.set(ip, arr); }
  arr.push(now);
  while (arr.length && now - arr[0] > RATE_WINDOW_MS) arr.shift();
  if (buckets.size > 5000) {                     // 防内存膨胀:清掉窗口外的 IP
    for (const [k, v] of buckets) { if (!v.length || now - v[v.length - 1] > RATE_WINDOW_MS) buckets.delete(k); }
  }
  return arr.length <= RATE_MAX;
}

let active = 0;

function parseMultipart(buf, boundary) {
  const delim = Buffer.from("--" + boundary);
  const parts = [];
  let idx = buf.indexOf(delim);
  while (idx !== -1) {
    const next = buf.indexOf(delim, idx + delim.length);
    if (next === -1) break;
    let seg = buf.slice(idx + delim.length, next);
    if (seg[0] === 0x0d && seg[1] === 0x0a) seg = seg.slice(2);
    if (seg.length >= 2 && seg[seg.length - 2] === 0x0d && seg[seg.length - 1] === 0x0a) seg = seg.slice(0, -2);
    const hdrEnd = seg.indexOf("\r\n\r\n");
    if (hdrEnd !== -1) {
      const headerText = seg.slice(0, hdrEnd).toString("utf8");
      const content = seg.slice(hdrEnd + 4);
      const nameM = /name="([^"]*)"/.exec(headerText);
      const fileM = /filename="([^"]*)"/.exec(headerText);
      parts.push({ name: nameM ? nameM[1] : "", filename: fileM ? fileM[1] : null, content });
    }
    idx = next;
  }
  return parts;
}
function boundaryFromType(ct) {
  const m = /boundary=(.+)$/i.exec(ct || "");
  return m ? m[1].replace(/^"|"$/g, "").trim() : "";
}

function deny(res, code, msg) { res.writeHead(code); res.end(msg || ""); }

const server = http.createServer((req, res) => {
  const ip = (req.socket.remoteAddress || "").replace(/^::ffff:/, "");
  const pathname = (() => { try { return new URL(req.url, "http://h").pathname; } catch { return req.url; } })();

  // 隐身:设了 SECRET_PATH 时,非该路径的 POST 一律当不存在(404)。GET 也 404。
  if (req.method !== "POST" || (SECRET_PATH && pathname !== SECRET_PATH)) {
    return deny(res, 404);
  }
  if (!rateOk(ip)) { log("429 限速", ip); return deny(res, 429); }
  if (active >= MAX_CONC) { log("429 并发满", ip); return deny(res, 429); }
  if (TOKEN && (req.headers.authorization || "") !== `Bearer ${TOKEN}`) {
    log("401 未授权", ip); return deny(res, 401);
  }

  active++;
  const chunks = [];
  let total = 0, aborted = false;
  req.on("data", (c) => {
    total += c.length;
    if (total > MAX_BYTES) {
      aborted = true; deny(res, 413); req.destroy(); return;
    }
    chunks.push(c);
  });
  req.on("end", () => {
    active--;
    if (aborted) return;
    try {
      const boundary = boundaryFromType(req.headers["content-type"]);
      if (!boundary) return deny(res, 400);
      const parts = parseMultipart(Buffer.concat(chunks), boundary);
      const filePart = parts.find((p) => p.name === "file");
      const summaryPart = parts.find((p) => p.name === "summary");
      if (!filePart || !filePart.content || !filePart.content.length) return deny(res, 400);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const day = stamp.slice(0, 10);
      const dir = path.join(STORE_DIR, day);
      fs.mkdirSync(dir, { recursive: true });
      const out = path.join(dir, `${stamp}-${crypto.randomUUID().slice(0, 8)}-${safeName(filePart.filename)}`);
      fs.writeFileSync(out, filePart.content);
      if (summaryPart && summaryPart.content.length) fs.writeFileSync(out + ".summary.txt", summaryPart.content);
      log("收到", out, filePart.content.length, "字节", "from", ip);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));   // 不回显路径,信息最小化
    } catch (e) {
      log("处理失败", String(e));
      deny(res, 500);
    }
  });
  req.on("error", (e) => { active--; log("req error", String(e)); });
});

fs.mkdirSync(STORE_DIR, { recursive: true });
server.listen(PORT, HOST, () =>
  log(`诊断接收端 ${HOST}:${PORT} 存储:${STORE_DIR} 令牌:${TOKEN ? "有" : "无"} 路径隐身:${SECRET_PATH ? "有" : "无"} 限速:${RATE_MAX}/${RATE_WINDOW_MS}ms 并发:${MAX_CONC}`));
