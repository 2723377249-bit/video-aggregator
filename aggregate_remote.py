#!/usr/bin/env python3
"""
远程（GitHub Actions）自动汇总脚本。

由 Cloudflare Worker 调用 GitHub repository_dispatch 触发，
自动下载 B站/抖音 视频 → 上传 Backblaze B2 → 追加 videos.json。

环境变量（在仓库 Settings → Secrets and variables → Actions 中配置）：
  B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_BUCKET_ID
"""
import os, sys, json, time, glob

ROOT = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(ROOT, "media")
os.makedirs(MEDIA, exist_ok=True)

sys.path.insert(0, ROOT)
import downloader
import b2_native


def load_event_urls():
    """从 GitHub Actions event payload 读取 urls 列表。"""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        sys.exit("GITHUB_EVENT_PATH 不存在，无法读取触发事件")
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    payload = event.get("client_payload", {})
    urls = payload.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]
    if not urls:
        sys.exit("client_payload.urls 为空，无需处理")
    print("收到汇总请求：", urls)
    return urls


def load_remote_list(api, token):
    try:
        return b2_native.read_json(api, "videos.json", token)
    except Exception as e:
        print("从 B2 读取 videos.json 失败，使用空列表：", e)
        return []


def save_remote_list(api, lst):
    b2_native.upload_bytes(
        json.dumps(lst, ensure_ascii=False, indent=2).encode("utf-8"),
        "videos.json",
        api=api,
        content_type="application/json",
    )
    print("已更新 videos.json（共 %d 条）" % len(lst))


def main():
    urls = load_event_urls()
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
        save_remote_list(api, lst)

        try:
            os.remove(out_mp4)
            if poster and os.path.exists(poster):
                os.remove(poster)
        except Exception:
            pass
        added += 1
        print(f"已汇总并发布：{label}")

    print(f"完成：新增 {added} 个视频。")


if __name__ == "__main__":
    main()
