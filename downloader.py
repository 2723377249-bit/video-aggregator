"""视频下载模块：B站(yt-dlp) + 抖音(Playwright 抓 play_addr)。"""
import json, os, shutil, subprocess, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_ffmpeg():
    """优先环境变量 FFMPEG_PATH，其次系统 PATH，最后回退本地 Windows 工具。"""
    env = os.environ.get("FFMPEG_PATH")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.path.join(ROOT, "tools", "ffmpeg", "ffmpeg-master-latest-win64-gpl", "bin", "ffmpeg.exe")
    if os.path.isfile(local):
        return local
    return "ffmpeg"


FFMPEG = _find_ffmpeg()
PY = sys.executable  # 服务进程本身即 venv 的 python，直接复用
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _extract_poster(video_path, poster_path):
    try:
        subprocess.run([FFMPEG, "-y", "-ss", "1", "-i", video_path, "-frames:v", "1",
                        "-q:v", "4", poster_path], capture_output=True, timeout=90)
        return os.path.exists(poster_path)
    except Exception as e:
        print("poster err", e)
        return False


def _bvid_from_url(url):
    import re
    m = re.search(r"BV\w+", url)
    return m.group(0) if m else None


def _download_bilibili_api(bvid, out_path):
    """用 Bilibili 公开 API 下载（绕开 yt-dlp 在美国 runner 上的 412）。"""
    import requests
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com",
    }
    view = requests.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                        headers=headers, timeout=30).json()
    if view.get("code") != 0:
        raise RuntimeError(f"B站 view API 错误：{view}")
    data = view["data"]
    cid = data["cid"]
    title = data.get("title") or bvid
    pu = requests.get(
        f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&qn=80&fnval=0&fourk=1",
        headers=headers, timeout=30).json()
    if pu.get("code") != 0:
        raise RuntimeError(f"B站 playurl API 错误：{pu}")
    durl = pu["data"]["durl"][0]
    video_url = durl["url"]
    r = requests.get(video_url, headers=headers, timeout=300)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    return title, ""


def download_bilibili(url, out_path):
    """返回 (title, desc)。优先用 B站 API，失败再回退 yt-dlp。"""
    bvid = _bvid_from_url(url)
    if bvid:
        try:
            title, desc = _download_bilibili_api(bvid, out_path)
            poster = os.path.splitext(out_path)[0] + ".jpg"
            _extract_poster(out_path, poster)
            return title, desc
        except Exception as e:
            print("B站 API 下载失败，回退 yt-dlp：", e)
    # 回退 yt-dlp
    title = ""
    try:
        r = subprocess.run([PY, "-m", "yt_dlp", "-e", url],
                           capture_output=True, text=True, timeout=120)
        title = (r.stdout or "").strip()
    except Exception as e:
        print("bili title err", e)
    if not title:
        title = os.path.splitext(os.path.basename(out_path))[0]
    r = subprocess.run([PY, "-m", "yt_dlp", "--ffmpeg-location", FFMPEG,
                    "-f", "bv+ba/b", "--merge-output-format", "mp4",
                    "-o", out_path, url], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("yt-dlp stderr:", r.stderr[-2000:] if r.stderr else "(empty)")
        print("yt-dlp stdout:", r.stdout[-1000:] if r.stdout else "(empty)")
        raise RuntimeError("yt-dlp 下载失败：" + (r.stderr or "unknown")[-500:])
    poster = os.path.splitext(out_path)[0] + ".jpg"
    _extract_poster(out_path, poster)
    return title, ""


def _ytdlp_cmd(url, out_path=None):
    cmd = [PY, "-m", "yt_dlp", "--ffmpeg-location", FFMPEG]
    cookie = os.environ.get("DOUYIN_COOKIE")
    if cookie:
        cmd += ["--add-header", "Cookie: " + cookie]
    if out_path:
        cmd += ["-o", out_path]
    cmd += [url]
    return cmd


def _download_douyin_ytdlp(url, out_path):
    """用 yt-dlp 下载抖音（带 DOUYIN_COOKIE，若配置）。"""
    r = subprocess.run(_ytdlp_cmd(url, out_path),
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("yt-dlp (douyin) stderr:", r.stderr[-2000:] if r.stderr else "(empty)")
        raise RuntimeError("yt-dlp 抖音下载失败：" + (r.stderr or "unknown")[-500:])
    # yt-dlp 可能不会写描述，尝试获取标题（带 cookie）
    title = ""
    try:
        tcmd = [PY, "-m", "yt_dlp", "--ffmpeg-location", FFMPEG]
        cookie = os.environ.get("DOUYIN_COOKIE")
        if cookie:
            tcmd += ["--add-header", "Cookie: " + cookie]
        tcmd += ["-e", url]
        r2 = subprocess.run(tcmd, capture_output=True, text=True, timeout=60)
        title = (r2.stdout or "").strip()
    except Exception:
        pass
    return title or "抖音视频", ""


def _download_douyin_playwright(url, out_path):
    """返回 (title, desc)。Playwright 抓 aweme detail 的 play_addr 下载。"""
    detail = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, locale="zh-CN")
        pg = ctx.new_page()

        def on_resp(r):
            if "aweme/v1/web/aweme/detail" in r.url and "d" not in detail:
                try:
                    detail["d"] = r.json()
                except Exception:
                    pass

        pg.on("response", on_resp)
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(8000)
        d = detail.get("d")
        if not d:
            # 最后尝试解析页面内嵌的 RENDER_DATA
            try:
                render = pg.evaluate('''() => {
                    const el = document.querySelector('script[id="RENDER_DATA"]');
                    return el ? el.textContent : "";
                }''')
                if render:
                    rd = json.loads(render)
                    # 常见路径
                    app = rd.get("app", {})
                    for k in ["videoInfo", "video", "aweme_detail", "awemeDetail"]:
                        if k in app:
                            detail["d"] = {"aweme_detail": app[k]}
                            break
            except Exception as e:
                print("RENDER_DATA parse err", e)
        d = detail.get("d")
        if not d:
            b.close()
            raise RuntimeError("抖音：未捕获到视频详情接口")
        aweme = (d.get("aweme_detail") or d.get("awemeDetail")
                 or (d.get("data") or {}).get("aweme_detail"))
        if not aweme:
            b.close()
            raise RuntimeError("抖音：详情中无 aweme 数据")
        video = aweme.get("video", {})
        play_urls = (video.get("play_addr") or {}).get("url_list", [])
        if not play_urls:
            b.close()
            raise RuntimeError("抖音：无 play_addr 直链")
        play_url = play_urls[0]
        desc = aweme.get("desc") or "抖音视频"
        req = ctx.request.get(play_url, headers={"Referer": "https://www.douyin.com/"},
                              timeout=120000)
        open(out_path, "wb").write(req.body())
        b.close()

    label = desc.strip().split("\n")[0][:30] or "抖音视频"
    return label, desc.strip()


def download_douyin(url, out_path):
    """返回 (title, desc)。优先 yt-dlp，失败再回退 Playwright。"""
    errs = []
    try:
        title, desc = _download_douyin_ytdlp(url, out_path)
        poster = os.path.splitext(out_path)[0] + ".jpg"
        _extract_poster(out_path, poster)
        return title, desc
    except Exception as e:
        errs.append(str(e))
        print("yt-dlp 抖音失败：", e)
    try:
        title, desc = _download_douyin_playwright(url, out_path)
        poster = os.path.splitext(out_path)[0] + ".jpg"
        _extract_poster(out_path, poster)
        return title, desc
    except Exception as e:
        errs.append(str(e))
        print("Playwright 抖音失败：", e)
    raise RuntimeError("抖音下载失败：" + "; ".join(errs[-2:]))


def classify(url):
    u = url.lower()
    if "bilibili.com" in u or "b23.tv" in u:
        return "bilibili"
    if "douyin.com" in u or "v.douyin.com" in u:
        return "douyin"
    return "unknown"


def download(url, out_path):
    """统一入口：按平台分发，返回 (label, desc, poster_or_None)。"""
    kind = classify(url)
    if kind == "bilibili":
        label, desc = download_bilibili(url, out_path)
    elif kind == "douyin":
        label, desc = download_douyin(url, out_path)
    else:
        raise RuntimeError("不支持的链接：仅支持 B站 / 抖音")
    poster = os.path.splitext(out_path)[0] + ".jpg"
    return label, desc, poster if os.path.exists(poster) else None
