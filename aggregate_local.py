#!/usr/bin/env python3
"""
本地汇总脚本（Cloudflare Worker + Backblaze B2 私有桶方案）

功能：
  seeds      把 deploy-render/media/ 下的种子视频+封面 上传到 B2（media/ 前缀），并上传 videos.json、index.html
  add URL...  下载指定 B站/抖音链接 → 上传 B2 → 追加到 videos.json（所有人永久可见，无需重新部署）

凭证（环境变量，切勿写进文件/仓库）：
  B2_KEY_ID       applicationKeyId
  B2_APP_KEY      applicationKey
  B2_BUCKET_ID    桶 ID
  B2_BUCKET       桶名（jinghe001）

用法：
  set B2_KEY_ID=... & set B2_APP_KEY=... & set B2_BUCKET_ID=... & set B2_BUCKET=jinghe001
  python aggregate_local.py seeds
  python aggregate_local.py add https://www.bilibili.com/video/BVxxxx https://v.douyin.com/xxxx/
"""
import os, sys, json, time, glob, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import downloader          # 复用现成的 B站/抖音下载逻辑
import b2_native           # 原生 B2 API（绕开 S3 锁）

ROOT = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(ROOT, "media")
SEED_JSON = os.path.join(ROOT, "videos.json")
CLOUDFLARE = os.path.join(ROOT, "..", "cloudflare")


def load_remote_list(api, token):
    try:
        return b2_native.read_json(api, "videos.json", token)
    except Exception:
        if os.path.exists(SEED_JSON):
            with open(SEED_JSON, encoding="utf-8") as f:
                return json.load(f)
        return []


def save_remote_list(api, token, lst):
    b2_native.upload_bytes(
        json.dumps(lst, ensure_ascii=False, indent=2).encode("utf-8"),
        "videos.json", api=api, content_type="application/json",
    )


def cmd_seeds():
    api = b2_native.authorize()
    print("上传种子视频 + 封面到 B2 ...")
    for fp in sorted(glob.glob(os.path.join(MEDIA, "*"))):
        if os.path.isfile(fp):
            key = "media/" + os.path.basename(fp)
            b2_native.upload_file(fp, key, api=api, content_type=b2_native.content_type_for(fp))
            print("  ✔", key)
    if os.path.exists(SEED_JSON):
        save_remote_list(api, b2_native.get_download_auth(api)["authorizationToken"], json.load(open(SEED_JSON, encoding="utf-8")))
        print("  ✔ videos.json")
    idx = os.path.join(CLOUDFLARE, "index.html")
    if os.path.exists(idx):
        b2_native.upload_file(idx, "index.html", api=api, content_type="text/html; charset=utf-8")
        print("  ✔ index.html")
    print("种子数据上传完成。")


def cmd_add(urls):
    api = b2_native.authorize()
    token = b2_native.get_download_auth(api)["authorizationToken"]
    lst = load_remote_list(api, token)
    added = 0
    for url in urls:
        url = url.strip()
        if not url:
            continue
        kind = downloader.classify(url)
        if kind == "unknown":
            print(f"跳过（不支持）：{url}")
            continue
        ts = str(int(time.time()))[-8:]
        base = f"{kind}_{ts}"
        out_mp4 = os.path.join(MEDIA, base + ".mp4")
        try:
            label, desc, poster = downloader.download(url, out_mp4)
        except Exception as e:
            print(f"下载失败：{url} -> {e}")
            continue
        b2_native.upload_file(out_mp4, "media/" + base + ".mp4", api=api, content_type="video/mp4")
        poster_key = None
        if poster and os.path.exists(poster):
            b2_native.upload_file(poster, "media/" + base + ".jpg", api=api, content_type="image/jpeg")
            poster_key = base + ".jpg"
        entry = {
            "id": base,
            "file": base + ".mp4",
            "poster": poster_key or "",
            "label": label or base,
            "desc": desc or "",
            "source": kind,
            "seed": False,
        }
        lst.append(entry)
        save_remote_list(api, token, lst)
        try:
            os.remove(out_mp4)
            if poster and os.path.exists(poster):
                os.remove(poster)
        except Exception:
            pass
        added += 1
        print(f"已汇总并发布：{label}")
    print(f"完成：新增 {added} 个。前端刷新即可看到。")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "seeds":
        cmd_seeds()
    elif cmd == "add":
        if len(sys.argv) < 3:
            sys.exit("用法：python aggregate_local.py add <url1> [url2 ...]")
        cmd_add(sys.argv[2:])
    else:
        sys.exit("未知命令：" + cmd + "\n" + __doc__)


if __name__ == "__main__":
    main()
