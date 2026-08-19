// Cloudflare Worker：同源代理 Backblaze B2 私有桶
// 解决 B2「公开桶需绑卡 / S3 兼容层拒绝 key」的限制——
// Worker 用原生 API 给私有文件签发下载令牌并流式回传，前端无需任何公网直链。
//
// 凭证通过 wrangler secret 注入（勿提交到仓库）：
//   B2_KEY_ID      applicationKeyId
//   B2_APP_KEY     applicationKey
//   B2_BUCKET      jinghe001
//   B2_BUCKET_ID   2c859aa45ea11345a701081d

const API_HOST = "https://api.backblazeb2.com";

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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let path = decodeURIComponent(url.pathname);
    if (path === "/") path = "/index.html";

    let auth;
    try {
      auth = await authorize(env);
    } catch (e) {
      return new Response("B2 auth error: " + e.message, { status: 502 });
    }

    const upstream =
      auth.dl + "/file/" + env.B2_BUCKET + path + "?Authorization=" + auth.token;

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
    out.set("Access-Control-Allow-Origin", "*");
    out.set("Cache-Control", "public, max-age=300");
    return new Response(up.body, {
      status: up.status,
      statusText: up.statusText,
      headers: out,
    });
  },
};
