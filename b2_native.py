#!/usr/bin/env python3
"""
Backblaze B2 原生 API 工具（不依赖 boto3 / S3 兼容层）。

原因：该 B2 账户的 S3 兼容网关拒绝所有 application key（"The key ... is not valid"），
且公开桶需要绑卡。改用原生 API：能正常上传/下载，并通过 b2_get_download_authorization
给私有文件签发有时效的下载令牌，由 Cloudflare Worker 代理播放（无需公开桶、无需绑卡）。

凭证从环境变量读取（切勿写死进文件/仓库）：
  B2_KEY_ID       applicationKeyId（主密钥即账号 ID）
  B2_APP_KEY      applicationKey
  B2_BUCKET_ID    桶 ID
  B2_BUCKET       桶名
"""
import os, json, base64, hashlib, urllib.request, urllib.error, urllib.parse


def _env():
    need = ["B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET_ID", "B2_BUCKET"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        raise SystemExit("缺少环境变量：" + ", ".join(miss))
    return {k: os.environ[k] for k in need}


def authorize():
    c = _env()
    auth = base64.b64encode(f"{c['B2_KEY_ID']}:{c['B2_APP_KEY']}".encode()).decode()
    req = urllib.request.Request(
        "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
        headers={"Authorization": "Basic " + auth},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get_upload_url(api):
    req = urllib.request.Request(
        api["apiUrl"] + "/b2api/v2/b2_get_upload_url",
        data=json.dumps({"bucketId": _env()["B2_BUCKET_ID"]}).encode(),
        headers={"Authorization": api["authorizationToken"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def upload_file(local_path, key, api=None, content_type="application/octet-stream"):
    with open(local_path, "rb") as f:
        data = f.read()
    return upload_bytes(data, key, api=api, content_type=content_type)


def upload_bytes(data, key, api=None, content_type="application/octet-stream"):
    api = api or authorize()
    up = get_upload_url(api)
    headers = {
        "Authorization": up["authorizationToken"],
        "X-Bz-File-Name": urllib.parse.quote(key, safe=""),
        "Content-Type": content_type,
        "X-Bz-Content-Sha1": hashlib.sha1(data).hexdigest(),
    }
    req = urllib.request.Request(up["uploadUrl"], data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError:
        # 上传 URL 过期，重新取一次再试
        up = get_upload_url(api)
        headers["Authorization"] = up["authorizationToken"]
        req = urllib.request.Request(up["uploadUrl"], data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read().decode())


def read_json(api, key, token):
    url = download_url(api, key, token)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode())


def get_download_auth(api, prefix="", duration=604800):
    req = urllib.request.Request(
        api["apiUrl"] + "/b2api/v2/b2_get_download_authorization",
        data=json.dumps({
            "bucketId": _env()["B2_BUCKET_ID"],
            "fileNamePrefix": prefix,
            "validDurationInSeconds": duration,
        }).encode(),
        headers={"Authorization": api["authorizationToken"], "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def download_url(api, key, token):
    return f"{api['downloadUrl']}/file/{_env()['B2_BUCKET']}/{urllib.parse.quote(key, safe='')}?Authorization={token}"


def content_type_for(name):
    if name.endswith(".mp4"):
        return "video/mp4"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".json"):
        return "application/json"
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    return "application/octet-stream"
