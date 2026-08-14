"""构建/首次运行时，从公有源拉取 12 个种子视频 + 封面 + videos.json。

用法：
  python fetch_seeds.py            # 拉到 ./media 与 ./videos.json
环境变量：
  SEED_SRC  主源站根地址（可覆盖默认候选列表）
说明：
  - 仅在目标文件缺失时下载，可断点重跑
  - 多源兜底：主源 403/失效时自动切换备源，避免构建失败
  - 若所有源都失效，可本地把视频放进 ./media、用 rebuild/videos.json 覆盖后重构建
"""
import os, json, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")
# 多源兜底：主源挂了自动换备源（部署时可用 SEED_SRC 覆盖）
_override = os.environ.get("SEED_SRC")
SRC_CANDIDATES = [_override.rstrip("/")] if _override else [
    "https://4c804e7dda9346718b1a91b0b5a456e3.app.workbuddy.link",
    "https://joel-xbox-warning-plastics.trycloudflare.com",
]
SRC_CANDIDATES = [s for s in SRC_CANDIDATES if s]

os.makedirs(MEDIA, exist_ok=True)
TIMEOUT = 60


def get_json(url):
    for _ in range(3):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.ok:
                return r.json()
        except Exception as e:
            print("  fetch json retry:", e)
            time.sleep(2)
    return None


def dl(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return True
    for _ in range(3):
        try:
            with requests.get(url, timeout=120, stream=True) as r:
                if not r.ok:
                    print("  HTTP", r.status_code, url)
                    return False
                with open(dest + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
                os.replace(dest + ".part", dest)
                return True
        except Exception as e:
            print("  retry:", e)
            time.sleep(2)
    return False


def main():
    last_err = None
    for SRC in SRC_CANDIDATES:
        print("尝试源:", SRC)
        meta = get_json(f"{SRC}/videos.json")
        if not meta:
            last_err = f"{SRC} 获取 videos.json 失败"
            print("  ", last_err, "-> 换下一源")
            continue
        ok = 0
        for e in meta:
            fn = e.get("file")
            poster = e.get("poster")
            if fn:
                if dl(f"{SRC}/media/{fn}", os.path.join(MEDIA, fn)):
                    ok += 1
                else:
                    print("  失败:", fn)
            if poster:
                dl(f"{SRC}/media/{poster}", os.path.join(MEDIA, poster))
        present = [e for e in meta
                   if os.path.exists(os.path.join(MEDIA, e.get("file", "")))]
        with open(os.path.join(HERE, "videos.json"), "w", encoding="utf-8") as f:
            json.dump(present, f, ensure_ascii=False, indent=2)
        print(f"种子就绪：{ok}/{len(meta)} 个视频已写入 ./media，清单 {len(present)} 条（源 {SRC}）")
        return
    print("所有源均不可用：", last_err)
    print("将使用本地自带 ./videos.json（若为空需手动放入视频）")


if __name__ == "__main__":
    main()
