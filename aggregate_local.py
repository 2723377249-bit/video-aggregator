#!/usr/bin/env python3
"""
本地汇总脚本（Cloudflare Pages + Backblaze B2 方案）

功能：
  seeds      把 deploy-render/media/ 下的种子视频+封面 上传到 B2，并上传 videos.json
  add URL...  下载指定 B站/抖音链接 → 上传 B2 → 追加到 videos.json（云端永久保存，所有人可见）

配置（环境变量，切勿写进文件/仓库）：
  B2_ENDPOINT   例如 https://s3.us-west-004.backblazeb2.com
  B2_REGION     例如 us-west-004
  B2_BUCKET     桶名
  B2_KEY_ID     applicationKeyId
  B2_APP_KEY    applicationKey
  B2_ACCOUNT_ID B2 账号 ID（用于公开 URL 前缀 f<accountId>）

用法：
  set B2_ENDPOINT=...   (Windows)  /  export B2_ENDPOINT=... (Linux/Mac)
  python aggregate_local.py seeds
  python aggregate_local.py add https://www.bilibili.com/video/BVxxxx https://v.douyin.com/xxxx/
"""
import os, sys, json, time, glob, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import downloader  # 复用现成的 B站/抖音下载逻辑

try:
    import boto3
except ImportError:
    sys.exit("缺少 boto3，请先安装：pip install boto3")

ROOT = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(ROOT, "media")
SEED_JSON = os.path.join(ROOT, "videos.json")


def cfg():
    need = ["B2_ENDPOINT", "B2_REGION", "B2_BUCKET", "B2_KEY_ID", "B2_APP_KEY", "B2_ACCOUNT_ID"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        sys.exit("缺少环境变量：" + ", ".join(miss))
    return {k: os.environ[k] for k in need}


def client(c):
    return boto3.client(
        "s3",
        endpoint_url=c["B2_ENDPOINT"],
        region_name=c["B2_REGION"],
        aws_access_key_id=c["B2_KEY_ID"],
        aws_secret_access_key=c["B2_APP_KEY"],
    )


def b2_base(c):
    return f"https://f{c['B2_ACCOUNT_ID']}.backblazeb2.com/file/{c['B2_BUCKET']}"


def upload_file(cli, bucket, local_path, key):
    cli.upload_file(local_path, bucket, key)
    print(f"  上传完成 -> {key}")


def load_remote_list(cli, bucket):
    try:
        obj = cli.get_object(Bucket=bucket, Key="videos.json")
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        # 远端还没有清单，用本地种子清单兜底
        if os.path.exists(SEED_JSON):
            with open(SEED_JSON, encoding="utf-8") as f:
                return json.load(f)
        return []


def save_remote_list(cli, bucket, lst):
    cli.put_object(
        Bucket=bucket,
        Key="videos.json",
        Body=json.dumps(lst, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def cmd_seeds(c):
    cli = client(c)
    print("上传种子视频 + 封面到 B2 ...")
    files = sorted(glob.glob(os.path.join(MEDIA, "*")))
    for fp in files:
        if os.path.isfile(fp):
            upload_file(cli, c["B2_BUCKET"], fp, os.path.basename(fp))
    # 上传 videos.json（若存在本地种子清单，用它；否则保持远端原样）
    if os.path.exists(SEED_JSON):
        save_remote_list(cli, c["B2_BUCKET"], json.load(open(SEED_JSON, encoding="utf-8")))
        print("  已上传 videos.json")
    print("种子数据上传完成。前端地址：", b2_base(c) + "/videos.json")


def cmd_add(c, urls):
    cli = client(c)
    lst = load_remote_list(cli, c["B2_BUCKET"])
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
        # 上传视频 + 封面
        upload_file(cli, c["B2_BUCKET"], out_mp4, base + ".mp4")
        poster_key = None
        if poster and os.path.exists(poster):
            upload_file(cli, c["B2_BUCKET"], poster, base + ".jpg")
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
        save_remote_list(cli, c["B2_BUCKET"], lst)
        # 本地清理临时文件
        try:
            os.remove(out_mp4)
            if poster and os.path.exists(poster):
                os.remove(poster)
        except Exception:
            pass
        added += 1
        print(f"已汇总并发布：{label}")
    print(f"完成：新增 {added} 个。前端稍后刷新即可看到。")


def main():
    c = cfg()
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "seeds":
        cmd_seeds(c)
    elif cmd == "add":
        if len(sys.argv) < 3:
            sys.exit("用法：python aggregate_local.py add <url1> [url2 ...]")
        cmd_add(c, sys.argv[2:])
    else:
        sys.exit("未知命令：" + cmd + "\n" + __doc__)


if __name__ == "__main__":
    main()
