"""云存储适配层（腾讯云 COS / CloudBase 云存储底层）。

环境变量包含 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION 时启用；
否则 enabled() 返回 False，调用方自动降级为本地 media 模式，不影响本地运行。
"""
import os
import json

try:
    from qcloud_cos import CosConfig, CosS3Client
    _ENV_OK = all(os.environ.get(k) for k in (
        "COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION"))
except Exception:
    _ENV_OK = False

_client = None
if _ENV_OK:
    try:
        _client = CosS3Client(CosConfig(
            Region=os.environ["COS_REGION"],
            SecretId=os.environ["COS_SECRET_ID"],
            SecretKey=os.environ["COS_SECRET_KEY"],
        ))
    except Exception:
        _client = None

_BUCKET = os.environ.get("COS_BUCKET")
_REGION = os.environ.get("COS_REGION")


def enabled() -> bool:
    return _ENV_OK and _client is not None


def public_url(key: str) -> str:
    """假设桶已开启公开读，返回可直接用于 <video src> 的 URL。"""
    return f"https://{_BUCKET}.cos.{_REGION}.myqcloud.com/{key}"


def upload_file(local_path: str, key: str) -> str:
    """上传本地文件到 COS，返回公开访问 URL。"""
    _client.upload_file(Bucket=_BUCKET, Key=key, LocalFilePath=local_path)
    return public_url(key)


def get_text(key: str):
    """读取 COS 上的文本对象，不存在返回 None。"""
    try:
        resp = _client.get_object(Bucket=_BUCKET, Key=key)
        return resp["Body"].get_raw_stream().read().decode("utf-8")
    except Exception:
        return None


def put_text(key: str, text: str):
    """写入文本对象到 COS。"""
    _client.put_object(Bucket=_BUCKET, Key=key, Body=text.encode("utf-8"))


def put_json(key: str, obj):
    put_text(key, json.dumps(obj, ensure_ascii=False, indent=2))
