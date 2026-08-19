// Cloudflare Worker：同源代理 Backblaze B2 私有桶 + 接收公开聚合请求并触发 GitHub Actions
//
// 解决 B2「公开桶需绑卡 / S3 兼容层拒绝 key」的限制——
// Worker 用原生 API 给私有文件签发下载令牌并流式回传，前端无需任何公网直链。
//
// 凭证通过 wrangler secret / dashboard 环境变量注入（勿提交到仓库）：
//   B2_KEY_ID       applicationKeyId
//   B2_APP_KEY      applicationKey
//   B2_BUCKET       jinghe001
//   B2_BUCKET_ID    2c859aa45ea11345a701081d
//   GITHUB_TOKEN    用于触发 GitHub Actions 工作流（需要 repo 权限）
//   GITHUB_REPO     2723377249-bit/video-aggregator

const API_HOST = "https://api.backblazeb2.com";
const GITHUB_API = "https://api.github.com";

let _cache = { token: null, dl: null, exp: 0 };

async function authorize(env) {
  const now = Date.now();
  if (_cache.token && _cache.exp > now + 120000) return _cache;
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
  _cache = {
    token: dd.authorizationToken,
    dl: ad.downloadUrl,
    exp: now + (dd.validDurationInSeconds - 120) * 1000,
  };
  return _cache;
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
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

async function handleAggregate(request, env, origin) {
  // 仅接受 POST
  if (request.method !== "POST") {
    return jsonResponse({ message: "Method Not Allowed" }, 405, origin);
  }

  // 简单限流：每个 IP 最近 1 分钟最多 3 次提交
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const now = Date.now();
  const windowKey = `rate:${ip}`;
  // 读取 KV 进行限流（如果配了 AGGREGATE_KV）否则放行
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
    // 限流失败不影响主流程
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

  return jsonResponse(
    { ok: true, urls, message: "已提交，后台正在处理" },
    200,
    origin
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "*";

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const path = decodeURIComponent(url.pathname);

    // 聚合接口
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
