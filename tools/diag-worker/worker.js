/**
 * ドットアビスX 离线诊断包接收端 —— Cloudflare Worker(存 R2 + 转发开 GitHub Issue)
 *
 * 接收 launcher 的 upload_diagnostics:multipart/form-data,含
 *   - 文件字段 "file"(诊断 zip)
 *   - 文本字段 "summary"(diag_summary.txt 纯文本,便于无需解压即成文)
 * 可选 Authorization: Bearer <UPLOAD_TOKEN> 校验来源。
 *
 * 落点:1) 原始 zip 存入 R2(数据源,永不丢);2) 用服务端令牌在 GitHub 仓库开一个 Issue,
 * 正文贴诊断摘要并给出取回 zip 的命令。GitHub 令牌只存 Worker secret,绝不下发给玩家。
 *
 * 配置:wrangler.toml 里 [vars] GITHUB_REPO=owner/name、BUCKET_NAME=dotabyss-diag;
 * secret:UPLOAD_TOKEN(可选)、GITHUB_TOKEN(fine-grained PAT,目标仓库 Issues:write)。
 */

const CRASH_KEYS = [
  "runtime.json", "TextDataProvider", "Player Content", "Unable to load runtime",
  "asset is null", "BitConverter", "Value cannot be null", "CriSound",
  "LoadBuiltinSound", "InitializeAsync", "InitializeServicesAsync",
];

function pickTitle(summary, stamp) {
  const lines = (summary || "").split(/\r?\n/);
  for (const line of lines) {
    const low = line.toLowerCase();
    if (CRASH_KEYS.some((k) => low.includes(k.toLowerCase()))) {
      return ("崩溃疑似: " + line.trim()).slice(0, 200);
    }
  }
  return `离线诊断包 ${stamp}`;
}

function fence(text) {
  // 选一个不会与内容冲突的代码围栏,并限长(GitHub Issue body 上限 65536)。
  const capped = (text || "").slice(0, 50000);
  const ticks = (capped.match(/`+/g) || []).reduce((m, s) => Math.max(m, s.length), 0);
  const fenceStr = "`".repeat(Math.max(3, ticks + 1));
  return fenceStr + "\n" + capped + "\n" + fenceStr;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("dotabyss-diag-collector ok (use POST)", { status: 200 });
    }

    // 令牌校验:配了 UPLOAD_TOKEN 才强制;未配则放行(不建议公开裸奔)。
    const expected = env.UPLOAD_TOKEN;
    if (expected) {
      const auth = request.headers.get("Authorization") || "";
      if (auth !== `Bearer ${expected}`) {
        return new Response("forbidden", { status: 401 });
      }
    }

    let form;
    try {
      form = await request.formData();
    } catch (e) {
      return new Response("bad multipart", { status: 400 });
    }

    const file = form.get("file");
    if (!file || typeof file === "string" || !(typeof file.arrayBuffer === "function")) {
      return new Response("missing file field", { status: 400 });
    }
    const summary = typeof form.get("summary") === "string" ? form.get("summary") : "";

    const MAX_BYTES = 64 * 1024 * 1024;
    if (file.size && file.size > MAX_BYTES) {
      return new Response("too large", { status: 413 });
    }

    const safeName = (file.name || "diag.zip").replace(/[^A-Za-z0-9._-]/g, "_");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const key = `diag/${stamp}-${crypto.randomUUID().slice(0, 8)}-${safeName}`;
    const bucket = env.BUCKET_NAME || "dotabyss-diag";

    // 1) 先落 R2(数据源)。
    await env.BUCKET.put(key, file.stream(), {
      httpMetadata: { contentType: file.type || "application/zip" },
    });

    // 2) 再尽力开 GitHub Issue;失败也不影响已存对象(返回 200,body 里带 issue 状态)。
    let issue = null;
    let issueError = "";
    if (env.GITHUB_TOKEN && env.GITHUB_REPO) {
      const title = pickTitle(summary, stamp);
      const body =
        "## ドットアビスX 离线诊断包\n\n" +
        `- 上传时间(UTC):${stamp}\n` +
        `- 文件名:\`${safeName}\`\n` +
        `- 大小:${file.size || "未知"} 字节\n` +
        `- R2 位置:\`${bucket}/${key}\`\n\n` +
        "### 取回原始包\n" +
        fence(`npx wrangler r2 object get ${bucket}/${key} --file got.zip`) + "\n\n" +
        "### 诊断摘要\n" +
        fence(summary) + "\n";
      try {
        const gh = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GITHUB_TOKEN}`,
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "dotabyss-diag-collector",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ title, body }),
        });
        if (gh.ok) {
          const j = await gh.json();
          issue = { number: j.number, url: j.html_url };
        } else {
          issueError = `HTTP ${gh.status}: ${(await gh.text()).slice(0, 300)}`;
        }
      } catch (e) {
        issueError = String(e);
      }
    } else {
      issueError = "未配置 GITHUB_TOKEN/GITHUB_REPO(仅存 R2,未开 Issue)";
    }

    return Response.json({ ok: true, key, size: file.size, issue, issueError });
  },
};
