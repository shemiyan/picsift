"""Supabase 存储：缩略图进 Storage，元数据进 Postgres，任务通过 RPC 领取。

worker 用 service_role 密钥（绕过 RLS），所以只能跑在自己的机器或服务器上，
密钥只放 .env，绝不能出现在前端。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from supabase import Client, create_client

from . import imaging
from .config import Settings
from .pipeline import SavedImage


def make_client(settings: Settings) -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)


class SupabaseSink:
    def __init__(self, client: Client, bucket: str, user_id: str, job_id: int):
        self.client = client
        self.bucket = bucket
        self.user_id = user_id
        self.job_id = job_id

    def exists(self, source_url: str) -> bool:
        res = (self.client.table("images").select("id")
               .eq("user_id", self.user_id).eq("source_url", source_url).limit(1).execute())
        return bool(res.data)

    def find_duplicate(self, dhash: int, max_distance: int) -> SavedImage | None:
        # 汉明距离在数据库里算：bit_count((a # b)::bit(64))，见 supabase/migrations
        res = self.client.rpc("similar_images", {
            "p_user": self.user_id, "p_hash": dhash, "p_max_dist": max_distance,
        }).execute()
        if not res.data:
            return None
        top = res.data[0]
        return SavedImage(top["id"], dhash)

    def save(self, *, source_url, page_url, info: imaging.ImageInfo, size, dup_of):
        # 路径第一段是用户 id，Storage 的 RLS 策略按它判断归属
        name = hashlib.sha1(source_url.encode()).hexdigest()[:16]
        thumb_path = f"{self.user_id}/{self.job_id}/{name}.jpg"
        self.client.storage.from_(self.bucket).upload(
            path=thumb_path, file=info.thumb_jpeg,
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )
        row = {
            "job_id": self.job_id, "user_id": self.user_id, "source_url": source_url,
            "page_url": page_url, "thumb_path": thumb_path, "width": info.width,
            "height": info.height, "bytes": size, "format": info.format, "dhash": info.dhash,
            "blur_score": info.blur_score, "brightness": info.brightness, "colors": info.colors,
            "dup_of": dup_of,
        }
        res = self.client.table("images").insert(row).execute()
        return SavedImage(res.data[0]["id"], info.dhash)


def claim_job(client: Client) -> dict | None:
    """领取一个待处理任务。数据库里用 FOR UPDATE SKIP LOCKED，多个 worker 同时跑也不会抢到同一个。"""
    res = client.rpc("claim_job", {}).execute()
    return res.data[0] if res.data else None


def finish_job(client: Client, job_id: int, status: str, stats: dict, error: str | None = None) -> None:
    client.table("crawl_jobs").update({
        "status": status, "stats": stats, "error": error,
        "finished_at": datetime.now(UTC).isoformat(),
    }).eq("id", job_id).execute()
