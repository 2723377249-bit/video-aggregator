// Cloudflare Worker：同源代理 Backblaze B2 私有桶 + 公开聚合（GitHub Actions）+ 视频上传
//
// 路由：
//   GET  /*             代理 B2（index.html / videos.json / media/*）
//   POST /api/aggregate 提交 B站/抖音链接 → 触发 GitHub Actions 自动汇总
//   POST /api/upload    上传本地 mp4 → 存入 B2 并更新 videos.json（所有��可见可播）
//
// 凭证（通过 dashboard 环境变量 / 部署脚本注入，勿提交仓库）：
//   B2_KEY_ID / B2_APP_KEY / B2_BUCKET / B2_BUCKET_ID
//   GITHUB_TOKEN / GITHUB_REPO

const API_HOST = "https://api.backblazeb2.com";
const GITHUB_API = "https://api.github.com";
const MAX_UPLOAD = 80 * 1024 * 1024; // 80MB

let _dlCache = { token: null, dl: null, exp: 0 };
let _apiCache = { url: null, token: null, exp: 0 };

// ---- B2 下载授权（代理播放用） ----
async function authorize(env) {
  const now = Date.now();
  if (_dlCache.token && _dlCache.exp > now + 120000) return _dlCache;
  const basic = "Basic " + btoa(env.B2_KEY_ID + ":" + env.B2_APP_KEY);
  const a = await fetch(API_HOST + "/b2api/v2/b2_authorize_account", {
    headers: { Authorization: basic },
  });
  if (!a.ok) throw new Error("b2_authorize_account failed: " + a.status);
  const ad = await a.json();
  const d = await fetch(ad.apiUrl + "/b2api/v2/b2_get_download_authorization", {
    method: "POST",
    headers: { Authorization: ad.authorizationToken, "Content-Type": "application/json" },
    body: JSON.stringify({
      bucketId: env.B2_BUCKET_ID,
      fileNamePrefix: "",
      validDurationInSeconds: 604800,
    }),
  });
  if (!d.ok) throw new Error("b2_get_download_authorization failed: " + d.status);
  const dd = await d.json();
  _dlCache = {
    token: dd.authorizationToken,
    dl: ad.downloadUrl,
    exp: now + (dd.validDurationInSeconds - 120) * 1000,
  };
  return _dlCache;
}

// ---- B2 账户授权（上传用） ----
async function authorizeApi(env) {
  const now = Date.now();
  if (_apiCache.token && _apiCache.exp > now + 60000) return _apiCache;
  const basic = "Basic " + btoa(env.B2_KEY_ID + ":" + env.B2_APP_KEY);
  const a = await fetch(API_HOST + "/b2api/v2/b2_authorize_account", {
    headers: { Authorization: basic },
  });
  if (!a.ok) throw new Error("b2_authorize_account failed: " + a.status);
  const ad = await a.json();
  _apiCache = { url: ad.apiUrl, token: ad.authorizationToken, exp: now + 60 * 60 * 1000 };
  return _apiCache;
}

async function sha1Hex(data) {
  const digest = await crypto.subtle.digest("SHA-1", data);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function getUploadUrl(api, bucketId) {
  const r = await fetch(api.url + "/b2api/v2/b2_get_upload_url", {
    method: "POST",
    headers: { Authorization: api.token, "Content-Type": "application/json" },
    body: JSON.stringify({ bucketId }),
  });
  if (!r.ok) throw new Error("b2_get_upload_url failed: " + r.status);
  return r.json();
}

async function uploadB2Bytes(env, fileName, contentType, data) {
  const api = await authorizeApi(env);
  const up = await getUploadUrl(api, env.B2_BUCKET_ID);
  const sha1 = await sha1Hex(data);
  const resp = await fetch(up.uploadUrl, {
    method: "POST",
    headers: {
      Authorization: up.authorizationToken,
      "X-Bz-File-Name": encodeURIComponent(fileName),
      "Content-Type": contentType,
      "X-Bz-Content-Sha1": sha1,
    },
    body: data,
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error("B2 upload failed: " + resp.status + " " + txt.slice(0, 200));
  }
  return resp.json();
}

async function readVideosJson(env) {
  const dl = await authorize(env);
  const url = dl.dl + "/file/" + env.B2_BUCKET + "/videos.json?Authorization=" + dl.token;
  const r = await fetch(url);
  if (!r.ok) return [];
  return r.json();
}

// ---- 上传处理器 ----
async function handleUpload(request, env, origin) {
  if (request.method !== "POST") {
    return jsonResponse({ message: "Method Not Allowed" }, 405, origin);
  }
  const url = new URL(request.url);
  const title = (url.searchParams.get("name") || url.searchParams.get("title") || "").trim();
  const ctype = request.headers.get("Content-Type") || "";
  if (!/mp4|octet-stream/i.test(ctype)) {
    return jsonResponse({ message: "仅支持 mp4 视频" }, 415, origin);
  }
  let buf;
  try {
    buf = await request.arrayBuffer();
  } catch (e) {
    return jsonResponse({ message: "读取上传内容失败" }, 400, origin);
  }
  if (buf.byteLength === 0) {
    return jsonResponse({ message: "文件为空" }, 400, origin);
  }
  if (buf.byteLength > MAX_UPLOAD) {
    return jsonResponse({ message: "文件超过 80MB 上限" }, 413, origin);
  }

  const ts = Date.now();
  const rand = Math.random().toString(36).slice(2, 8);
  const base = `upload_${ts}_${rand}`;
  const key = `media/${base}.mp4`;

  try {
    await uploadB2Bytes(env, key, "video/mp4", buf);
  } catch (e) {
    return jsonResponse({ message: "上传 B2 失败：" + e.message }, 502, origin);
  }

  // 更新 videos.json
  const label = title || `上传视频_${base.slice(7)}`;
  const entry = {
    id: base,
    file: base + ".mp4",
    poster: "",
    label: label,
    desc: "用户上传",
    source: "upload",
    seed: false,
  };
  try {
    let lst = await readVideosJson(env);
    if (!Array.isArray(lst)) lst = [];
    lst.push(entry);
    await uploadB2Bytes(env, "videos.json", "application/json",
      new TextEncoder().encode(JSON.stringify(lst, null, 2)));
  } catch (e) {
    return jsonResponse({ message: "更新清单失败：" + e.message }, 502, origin);
  }

  return jsonResponse({ ok: true, entry, message: "上传成功，已出现在下方列表" }, 200, origin);
}

// ---- 聚合处理器 ----
async function handleAggregate(request, env, origin) {
  if (request.method !== "POST") {
    return jsonResponse({ message: "Method Not Allowed" }, 405, origin);
  }

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const now = Date.now();
  const windowKey = `rate:${ip}`;
  try {
    if (env.AGGREGATE_KV) {
      const rec = await env.AGGREGATE_KV.get(windowKey);
      const calls = rec ? JSON.parse(rec) : [];
      const recent = calls.filter((t) => now - t < 60000);
      if (recent.length >= 3) {
        return jsonResponse({ message: "提交太频繁，请 1 分钟后再试" }, 429, origin);
      }
      recent.push(now);
      await env.AGGREGATE_KV.put(windowKey, JSON.stringify(recent), { expirationTtl: 120 });
    }
  } catch (e) {
    // ignore
  }

  let body;
  try {
    body = await request.json();
  } catch (e) {
    return jsonResponse({ message: "JSON 解析失败" }, 400, origin);
  }

  const rawUrls = Array.isArray(body.urls)
    ? body.urls
    : typeof body.url === "string"
    ? [body.url]
    : [];
  if (rawUrls.length === 0) {
    return jsonResponse({ message: "缺少 url / urls 参数" }, 400, origin);
  }
  if (rawUrls.length > 5) {
    return jsonResponse({ message: "一次最多提交 5 个链接" }, 400, origin);
  }

  const urls = validateUrls(extractUrls(rawUrls.join("\n")));
  if (urls.length === 0) {
    return jsonResponse({ message: "未识别到 B站/抖音 链接" }, 400, origin);
  }

  if (!env.GITHUB_TOKEN) {
    return jsonResponse({ message: "服务端未配置 GITHUB_TOKEN，无法触发自动汇总" }, 503, origin);
  }

  const repo = env.GITHUB_REPO || "2723377249-bit/video-aggregator";
  const dispatch = await fetch(`${GITHUB_API}/repos/${repo}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: "token " + env.GITHUB_TOKEN,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      "User-Agent": "video-aggregator-worker",
    },
    body: JSON.stringify({
      event_type: "aggregate",
      client_payload: { urls, submitted_at: new Date().toISOString() },
    }),
  });

  if (!dispatch.ok) {
    const txt = await dispatch.text();
    return jsonResponse(
      { message: "触发 GitHub Actions 失败：" + dispatch.status + " " + txt.slice(0, 200) },
      502,
      origin
    );
  }

  return jsonResponse({ ok: true, urls, message: "已提交，后台正在处理" }, 200, origin);
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-File-Name",
  };
}

function jsonResponse(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: { "Content-Type": "application/json; charset=utf-8", ...corsHeaders(origin) },
  });
}

function extractUrls(raw) {
  return raw
    .split(/[\n,，]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((u) => (/^https?:\/\//i.test(u) ? u : "https://" + u));
}

function validateUrls(urls) {
  return urls.filter((u) => /bilibili\.com|b23\.tv|bv|douyin\.com|iesdouyin\.com/i.test(u));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "*";

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const path = decodeURIComponent(url.pathname);

    if (path === "/api/upload") {
      return handleUpload(request, env, origin);
    }
    if (path === "/api/aggregate") {
      return handleAggregate(request, env, origin);
    }

    let target = path;
    if (target === "/") target = "/index.html";

    let auth;
    try {
      auth = await authorize(env);
    } catch (e) {
      return new Response("B2 auth error: " + e.message, { status: 502 });
    }

    const upstream =
      auth.dl + "/file/" + env.B2_BUCKET + target + "?Authorization=" + auth.token;

    const headers = {};
    const range = request.headers.get("Range");
    if (range) headers.Range = range;

    let up;
    try {
      up = await fetch(upstream, { headers });
    } catch (e) {
      return new Response("B2 fetch error: " + e.message, { status: 502 });
    }

    const out = new Headers(up.headers);
    out.set("Access-Control-Allow-Origin", origin);
    out.set("Cache-Control", "public, max-age=300");
    return new Response(up.body, {
      status: up.status,
      statusText: up.statusText,
      headers: out,
    });
  },
};
