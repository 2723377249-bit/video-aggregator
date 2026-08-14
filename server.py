"""一键汇总 Web 服务（公网版）：页面 + 媒体(Range) + 视频清单 + 聚合下载(SSE)。"""
import os, json, uuid, mimetypes, asyncio
from aiohttp import web
import downloader
import s3_store

HERE = os.path.dirname(os.path.abspath(__file__))
# 种子视频在构建时烤进镜像（./media），运行期新增的视频优先存到持久卷 /data
DATA_VOL = "/data" if os.path.isdir("/data") else None
SEED_MEDIA = os.path.join(HERE, "media")          # 烤进镜像的种子（重启不丢）
RUNTIME_MEDIA = os.path.join(DATA_VOL, "media") if DATA_VOL else SEED_MEDIA
MEDIA = RUNTIME_MEDIA
INDEX = os.path.join(HERE, "index.html")
SEED_JSON = os.path.join(HERE, "videos.json")
RUNTIME_JSON = os.path.join(DATA_VOL, "videos.json") if DATA_VOL else SEED_JSON
VIDEOS_JSON = RUNTIME_JSON
PORT = int(os.environ.get("PORT", "7860"))

os.makedirs(SEED_MEDIA, exist_ok=True)
os.makedirs(RUNTIME_MEDIA, exist_ok=True)
# 首次运行：把种子清单复制到持久卷（运行期新增会追加到这里）
if RUNTIME_JSON != SEED_JSON and not os.path.exists(RUNTIME_JSON):
    try:
        import shutil
        shutil.copyfile(SEED_JSON, RUNTIME_JSON)
    except Exception as e:
        print("init runtime videos.json failed:", e)


def load_seed():
    """烤进镜像的 12 个种子（重启永丢不了）。"""
    try:
        return json.load(open(SEED_JSON, encoding="utf-8"))
    except Exception:
        return []


def load_aggregated():
    """运行期新增的视频：优先从 S3 持久化读取，否则读本地文件（Render 免费版重启会丢）。"""
    if s3_store.enabled():
        return s3_store.load_aggregated()
    agg_path = os.path.join(SEED_MEDIA, "aggregated.json")
    if os.path.exists(agg_path):
        try:
            return json.load(open(agg_path, encoding="utf-8"))
        except Exception:
            return []
    return []


def save_aggregated(entries):
    if s3_store.enabled():
        try:
            s3_store.save_aggregated(entries)
            return
        except Exception as e:
            print("s3 save aggregated failed, fallback local:", e)
    agg_path = os.path.join(SEED_MEDIA, "aggregated.json")
    json.dump(entries, open(agg_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def load_videos():
    """种子 + 聚合（去重）合并成完整清单。"""
    seed = load_seed()
    agg = load_aggregated()
    seed_keys = {e.get("id") or e.get("file") for e in seed}
    merged = list(seed)
    for e in agg:
        k = e.get("id") or e.get("file")
        if k not in seed_keys:
            merged.append(e)
    return merged


def save_videos(videos):
    """只持久化「非种子」的聚合部分（种子烤在镜像里，无需存）。"""
    save_aggregated([e for e in videos if not e.get("seed")])


def _mime(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


async def index_handler(request):
    try:
        text = open(INDEX, encoding="utf-8").read()
    except Exception:
        return web.Response(text="index.html missing", status=500)
    return web.Response(text=text, content_type="text/html", charset="utf-8")


async def videos_json_handler(request):
    # 让前端优先读取 /videos.json（含 12 个种子）后，再探测 /api/videos 进入实时聚合模式
    return web.json_response(load_videos())


async def media_handler(request):
    name = request.match_info["filename"]
    base = os.path.basename(name)  # 防目录穿越
    # 优先持久卷（运行期新增），回退镜像内种子
    path = os.path.join(RUNTIME_MEDIA, base)
    if not os.path.isfile(path):
        path = os.path.join(SEED_MEDIA, base)
    if not os.path.isfile(path):
        return web.Response(status=404, text="not found")
    total = os.path.getsize(path)
    mime = _mime(name)
    rng = request.headers.get("Range")
    if rng and rng.startswith("bytes="):
        spec = rng[6:].split(",")[0].strip()
        start_s, end_s = spec.split("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else total - 1
        end = min(end, total - 1)
        length = end - start + 1
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(length)
        return web.Response(
            body=data, status=206,
            headers={
                "Content-Type": mime,
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )
    with open(path, "rb") as f:
        data = f.read()
    return web.Response(
        body=data,
        headers={
            "Content-Type": mime,
            "Accept-Ranges": "bytes",
            "Content-Length": str(total),
        },
    )


async def videos_handler(request):
    return web.json_response(load_videos())


async def aggregate_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    urls_raw = body.get("urls") or []
    if isinstance(urls_raw, str):
        urls_raw = [urls_raw]
    norm = []
    for raw in urls_raw:
        for part in str(raw).replace("\n", ",").replace("，", ",").split(","):
            part = part.strip()
            if part:
                norm.append(part)
    norm = list(dict.fromkeys(norm))
    if not norm:
        return web.json_response({"error": "没有有效链接"}, status=400)

    resp = web.StreamResponse()
    resp.content_type = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    await resp.prepare(request)

    def send(obj):
        return resp.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))

    loop = asyncio.get_event_loop()
    added, failed = 0, 0
    total = len(norm)
    for i, url in enumerate(norm):
        await send({"stage": "start", "url": url, "index": i, "total": total})
        try:
            kind = downloader.classify(url)
            if kind == "unknown":
                raise RuntimeError("不支持的链接（仅支持 B站 / 抖音）")
            base = uuid.uuid4().hex[:12]
            fn = f"{'bili' if kind == 'bilibili' else 'dy'}_{base}.mp4"
            out = os.path.join(MEDIA, fn)
            label, desc, poster = await loop.run_in_executor(
                None, downloader.download, url, out)
            entry = {
                "id": os.path.splitext(fn)[0],
                "file": fn,
                "poster": os.path.basename(poster) if poster else None,
                "label": label,
                "desc": desc,
                "source": kind,
                "seed": False,
            }
            # 聚合视频持久化到 S3（避免 Render 免费版重启/重新部署丢数据）
            try:
                if s3_store.enabled():
                    entry["file"] = s3_store.upload_file(
                        out, s3_store.media_key(fn), "video/mp4")
                    if poster and os.path.isfile(poster):
                        entry["poster"] = s3_store.upload_file(
                            poster, s3_store.media_key(os.path.basename(poster)),
                            "image/jpeg")
                    # 上传成功后再删除本地临时文件
                    for p in (out, poster):
                        if p and os.path.isfile(p):
                            try:
                                os.remove(p)
                            except OSError:
                                pass
            except Exception as e:
                # 上传失败：保留本地文件，entry.file 仍是文件名，由本服务 /media 提供
                print("s3 upload failed, keep local media:", e)
            videos = load_videos()
            videos.append(entry)
            save_videos(videos)
            added += 1
            await send({"stage": "done", "entry": entry, "index": i, "total": total})
        except Exception as e:
            failed += 1
            await send({"stage": "error", "url": url, "msg": str(e),
                        "index": i, "total": total})

    await send({"stage": "complete", "added": added, "failed": failed, "total": total})
    await resp.write_eof()
    return resp


def make_app():
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/videos.json", videos_json_handler)
    app.router.add_get("/media/{filename}", media_handler)
    app.router.add_get("/api/videos", videos_handler)
    app.router.add_post("/api/aggregate", aggregate_handler)
    return app


if __name__ == "__main__":
    app = make_app()
    print(f"Serving on http://0.0.0.0:{PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)
