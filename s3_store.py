"""S3 兼容对象存储（用于持久化运行期聚合的视频，避免 Render 免费版重启/重新部署丢数据）。

支持任意 S3 兼容服务：Backblaze B2（免费 10GB、免信用卡）、Cloudflare R2、AWS S3、阿里云 OSS、腾讯云 COS 等。
通过环境变量配置（在 Render 的 Environment 里设置）：
  S3_ENDPOINT   例如 https://s3.us-west-004.backblazeb2.com
  S3_BUCKET     桶名
  S3_REGION     区域（B2 可填 auto）
  S3_ACCESS_KEY 密钥 ID
  S3_SECRET_KEY 密钥
  S3_PUBLIC_URL 可选：桶的公开访问基址（如 https://<bucket>.s3.us-west-004.backblazeb2.com）；
                不填则直接用 ENDPOINT 拼路径（需桶/对象允许公开读）
  S3_PRESIGNED  可选：设为 1 则用临时签名 URL（适合私有桶）
未配置或 boto3 缺失时 enabled() 返回 False，调用方自动降级到本地存储。
"""
import os
import json

try:
    import boto3
    from botocore.client import Config
except Exception:  # pragma: no cover
    boto3 = None

ENDPOINT = os.environ.get("S3_ENDPOINT")
BUCKET = os.environ.get("S3_BUCKET")
REGION = os.environ.get("S3_REGION", "auto")
ACCESS = os.environ.get("S3_ACCESS_KEY")
SECRET = os.environ.get("S3_SECRET_KEY")
PUBLIC_URL = (os.environ.get("S3_PUBLIC_URL") or "").rstrip("/")
USE_PRESIGNED = os.environ.get("S3_PRESIGNED", "0") == "1"

MEDIA_PREFIX = "videoagg/media/"
AGG_KEY = "videoagg/aggregated.json"


def enabled():
    return bool(boto3 and ENDPOINT and BUCKET and ACCESS and SECRET)


_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            aws_access_key_id=ACCESS,
            aws_secret_access_key=SECRET,
            region_name=None if (not REGION or REGION == "auto") else REGION,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
    return _client


def public_url(key):
    if PUBLIC_URL:
        return f"{PUBLIC_URL}/{key}"
    return f"{ENDPOINT}/{BUCKET}/{key}"


def upload_file(local_path, key, content_type=None):
    extra = {"ContentType": content_type} if content_type else {}
    client().upload_file(local_path, BUCKET, key, ExtraArgs=extra)
    if USE_PRESIGNED:
        from botocore.exceptions import ClientError

        try:
            return client().generate_presigned_url(
                "get_object",
                Params={"Bucket": BUCKET, "Key": key},
                ExpiresIn=3600 * 24 * 7,
            )
        except ClientError as e:
            print("presign failed:", e)
    return public_url(key)


def get_bytes(key):
    try:
        o = client().get_object(Bucket=BUCKET, Key=key)
        return o["Body"].read()
    except Exception as e:  # noqa
        print("s3 get failed:", e)
        return None


def put_bytes(data, key, content_type="application/json"):
    client().put_object(Bucket=BUCKET, Key=key, Body=data, ContentType=content_type)


def load_aggregated():
    if not enabled():
        return []
    raw = get_bytes(AGG_KEY)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def save_aggregated(entries):
    put_bytes(
        json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8"), AGG_KEY
    )


def media_key(filename):
    return MEDIA_PREFIX + os.path.basename(filename)


def media_url(filename):
    return public_url(media_key(filename))
