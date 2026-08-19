#!/usr/bin/env python3
"""
用 Cloudflare 原生 API 部署 video-aggregator Worker（同源代理 B2 私有桶 + 公开聚合接口）。

需要一个带 Workers 编辑权限的 API Token（环境变量 CLOUDFLARE_API_TOKEN），
以及一个用于触发 GitHub Actions 的 GITHUB_TOKEN（classic token，需 repo 权限）。

脚本会：
  1) 读取账户 ID
  2) 确保账户有 workers.dev 子域（没有则设置一个）
  3) 上传 worker.js（module 格式）
  4) 注入密钥 B2_KEY_ID / B2_APP_KEY / GITHUB_TOKEN
  5) 开启 workers.dev 路由并输出最终地址

用法（Git Bash）：
  export CLOUDFLARE_API_TOKEN="你的token"
  export B2_KEY_ID="c5a4e135718d"
  export B2_APP_KEY="005ecf939fd62bcd79b42651a6245bfb2cd5f1dfdb"
  export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  python deploy_cloudflare.py
"""

import os, sys, json, urllib.request, urllib.error, uuid

BASE = "https://api.cloudflare.com/client/v4"
SCRIPT_NAME = "video-aggregator-proxy"
COMPAT_DATE = "2024-09-23"
WORKER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.js")

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
B2_KEY_ID = os.environ.get("B2_KEY_ID")
B2_APP_KEY = os.environ.get("B2_APP_KEY")
B2_BUCKET = os.environ.get("B2_BUCKET", "jinghe001")
B2_BUCKET_ID = os.environ.get("B2_BUCKET_ID", "2c859aa45ea11345a701081d")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "2723377249-bit/video-aggregator")

for k, v in [("CLOUDFLARE_API_TOKEN", TOKEN), ("B2_KEY_ID", B2_KEY_ID), ("B2_APP_KEY", B2_APP_KEY), ("GITHUB_TOKEN", GITHUB_TOKEN)]:
    if not v:
        sys.exit(f"缺少环境变量：{k}")


def req(method, path, data=None, raw=None, ctype=None):
    url = BASE + path
    headers = {"Authorization": "Bearer " + TOKEN}
    body = None
    if raw is not None:
        body = raw
        headers["Content-Type"] = ctype
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            txt = resp.read().decode()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode(errors="replace")}


def multipart(fields, files):
    boundary = "----wb" + uuid.uuid4().hex
    CRLF = b"\r\n"
    out = b""
    for name, value in fields.items():
        out += b"--" + boundary.encode() + CRLF
        out += f'Content-Disposition: form-data; name="{name}"'.encode() + CRLF + CRLF
        out += value.encode() + CRLF
    for name, (filename, ctype, content) in files.items():
        out += b"--" + boundary.encode() + CRLF
        out += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'.encode() + CRLF
        out += f"Content-Type: {ctype}".encode() + CRLF + CRLF
        out += content + CRLF
    out += b"--" + boundary.encode() + b"--" + CRLF
    return out, "multipart/form-data; boundary=" + boundary


def main():
    # 1) 账户 ID（优先用环境变量；否则尝试列出）
    acct_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if acct_id:
        print("账户 ID：", acct_id)
    else:
        acc = req("GET", "/accounts")
        if "_error" in acc or not acc.get("result"):
            sys.exit("读取账户失败（token 无列账户权限），请用 CLOUDFLARE_ACCOUNT_ID 传入账户 ID："
                     + json.dumps(acc, ensure_ascii=False)[:300])
        account = acc["result"][0]
        acct_id = account["id"]
        print("账户：", account.get("name"), acct_id)

    # 2) workers.dev 子域
    sub = req("GET", f"/accounts/{acct_id}/workers/subdomain")
    if "_error" in sub or not sub.get("result", {}).get("subdomain"):
        cand = "wbvideo-" + uuid.uuid4().hex[:8]
        r = req("PUT", f"/accounts/{acct_id}/workers/subdomain", {"subdomain": cand})
        if "_error" in r:
            sys.exit("设置 workers.dev 子域失败：" + json.dumps(r, ensure_ascii=False)[:300])
        sub = r
    subdomain = sub["result"]["subdomain"]
    print("workers.dev 子域：", subdomain)

    # 3) 上传 Worker（module 格式 + 明文绑定）
    with open(WORKER_PATH, "rb") as f:
        code = f.read()
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": COMPAT_DATE,
        "bindings": [
            {"name": "B2_BUCKET", "type": "plain_text", "text": B2_BUCKET},
            {"name": "B2_BUCKET_ID", "type": "plain_text", "text": B2_BUCKET_ID},
            {"name": "B2_KEY_ID", "type": "secret_text", "text": B2_KEY_ID},
            {"name": "B2_APP_KEY", "type": "secret_text", "text": B2_APP_KEY},
            {"name": "GITHUB_TOKEN", "type": "secret_text", "text": GITHUB_TOKEN},
            {"name": "GITHUB_REPO", "type": "plain_text", "text": GITHUB_REPO},
        ],
    }
    body, ctype = multipart(
        {"metadata": json.dumps(metadata)},
        {"worker.js": ("worker.js", "application/javascript+module", code)},
    )
    up = req("PUT", f"/accounts/{acct_id}/workers/scripts/{SCRIPT_NAME}", raw=body, ctype=ctype)
    if "_error" in up or not up.get("success", True):
        sys.exit("上传 Worker 失败：" + json.dumps(up, ensure_ascii=False)[:500])
    print("Worker 已上传（含密钥绑定）：", SCRIPT_NAME)

    # 5) 开启 workers.dev 路由
    r = req("POST", f"/accounts/{acct_id}/workers/scripts/{SCRIPT_NAME}/subdomain", {"enabled": True})
    if "_error" in r:
        print("（开启 workers.dev 返回非致命错误，可忽略）", json.dumps(r, ensure_ascii=False)[:200])

    url = f"https://{SCRIPT_NAME}.{subdomain}.workers.dev"
    print("\n=== 部署完成 ===")
    print("访问地址：", url)


if __name__ == "__main__":
    main()
