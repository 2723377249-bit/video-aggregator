#!/usr/bin/env python3
# 通过 Render API 自动创建并部署 web service(使用仓库内的 Dockerfile)。
# 密钥从环境变量 RENDER_API_KEY 读取,不写进文件。
import os, json, sys, time
import urllib.request
import urllib.error

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY")
if not KEY:
    sys.exit("缺少环境变量 RENDER_API_KEY")

REPO = "https://github.com/2723377249-bit/video-aggregator"
BRANCH = "main"


def req(method, path, body=None):
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + KEY)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode())
        raise


def main():
    # 1) 取 owner(个人账号)
    owners = req("GET", "/owners")
    if not owners:
        sys.exit("无法获取 owner,请确认 API Key 有效")
    owner_id = owners[0]["owner"]["id"]
    print("ownerId:", owner_id)

    # 2) 创建 web service(docker + free + 自动部署)
    svc = req("POST", "/services", {
        "type": "web_service",
        "name": "video-aggregator",
        "ownerId": owner_id,
        "repo": REPO,
        "branch": BRANCH,
        "serviceDetails": {
            "runtime": "docker",
            "plan": "free",
            "healthCheckPath": "/",
            "autoDeploy": "yes",
        },
    })
    service = svc.get("service", svc)
    service_id = service.get("id")
    print("serviceId:", service_id)
    print("dashboard:", service.get("dashboardUrl", "(见 Render 后台)"))

    # 3) 轮询部署状态
    print("等待部署完成(构建含 Playwright Chromium + 442MB 视频,约 10-20 分钟)...")
    deadline = time.time() + 30 * 60
    last = None
    while time.time() < deadline:
        try:
            d = req("GET", f"/services/{service_id}/deploys?limit=1")
            deploys = d.get("deploys", d if isinstance(d, list) else [])
            if deploys:
                st = deploys[0].get("status")
                if st != last:
                    print("  deploy status:", st)
                    last = st
                if st in ("live", "build_failed", "deploy_failed", "canceled"):
                    break
        except Exception as e:
            print("  poll error:", e)
        time.sleep(30)

    # 4) 取服务域名
    info = req("GET", f"/services/{service_id}")
    svc_info = info.get("service", info)
    url = svc_info.get("url") or svc_info.get("serviceDetails", {}).get("url")
    print("服务地址:", url or "(部署完成后在 Render 后台查看)")
    if last == "live":
        print("部署成功!打开上面的地址即可访问。")


if __name__ == "__main__":
    main()
