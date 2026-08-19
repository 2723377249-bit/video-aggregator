#!/usr/bin/env python3
"""
把种子数据上传到 B2 私有桶（供 Cloudflare Worker 代理）：
  - media/*         ->  media/<文件名>
  - videos.json     ->  videos.json
  - cloudflare/index.html -> index.html

用法：
  set B2_KEY_ID=... & set B2_APP_KEY=... & set B2_BUCKET_ID=... & set B2_BUCKET=jinghe001
  python upload_b2.py
"""
import os, glob, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b2_native

ROOT = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(ROOT, "media")
CLOUDFLARE = os.path.join(ROOT, "..", "cloudflare")


def main():
    api = b2_native.authorize()
    print("已授权 B2，开始上传种子数据 ...")

    # 1) 媒体文件（视频 + 封面）
    files = sorted(glob.glob(os.path.join(MEDIA, "*")))
    for fp in files:
        if os.path.isfile(fp):
            key = "media/" + os.path.basename(fp)
            b2_native.upload_file(fp, key, api=api, content_type=b2_native.content_type_for(fp))
            print("  ✔", key)

    # 2) 视频清单
    vj = os.path.join(ROOT, "videos.json")
    if os.path.exists(vj):
        b2_native.upload_file(vj, "videos.json", api=api, content_type="application/json")
        print("  ✔ videos.json")

    # 3) 前端页面
    idx = os.path.join(CLOUDFLARE, "index.html")
    if os.path.exists(idx):
        b2_native.upload_file(idx, "index.html", api=api, content_type="text/html; charset=utf-8")
        print("  ✔ index.html")

    # 4) 验证：用下载令牌取一个文件，确认 Worker 代理链路可通
    da = b2_native.get_download_auth(api, prefix="", duration=604800)
    sample = "media/" + os.path.basename(sorted(glob.glob(os.path.join(MEDIA, "*.mp4")))[0])
    url = b2_native.download_url(api, sample, da["authorizationToken"])
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as r:
        print(f"验证下载令牌：{r.status} {r.headers.get('Content-Type')} length={r.headers.get('Content-Length')}")
    print("全部完成。等待 Worker 部署后，访问其地址即可看到 12 个视频。")


if __name__ == "__main__":
    main()
