"""一次采集任务的完整流程：抓页面 → 找图 → 下载 → 分析 → 查重 → 保存。

保存目标（Sink）可替换：本地目录用于调试和测试，Supabase 用于线上。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from . import imaging
from .crawl import NotAllowedError, PoliteClient, extract_image_urls

log = logging.getLogger(__name__)


@dataclass
class JobStats:
    found: int = 0
    downloaded: int = 0
    saved: int = 0
    duplicates: int = 0
    skipped_robots: int = 0
    skipped_not_allowed: int = 0
    skipped_not_image: int = 0
    skipped_undecodable: int = 0
    skipped_existing: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """一行汇总，给 worker 日志用。全部被跳过时也能看出原因；为 0 的项不显示。"""
        parts = [f"找到 {self.found}", f"保存 {self.saved}"]
        for label, value in (("重复", self.duplicates), ("已存在", self.skipped_existing),
                             ("robots 禁止", self.skipped_robots), ("不在允许范围", self.skipped_not_allowed),
                             ("非图片", self.skipped_not_image),
                             ("无法解码", self.skipped_undecodable), ("失败", self.failed)):
            if value:
                parts.append(f"{label} {value}")
        return "，".join(parts)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["errors"] = d["errors"][:10]  # 只留前 10 条，避免把任务表撑大
        return d


@dataclass
class SavedImage:
    id: int | str
    dhash: int


class Sink(Protocol):
    def exists(self, source_url: str) -> bool: ...

    def find_duplicate(self, dhash: int, max_distance: int) -> SavedImage | None: ...

    def save(self, *, source_url: str, page_url: str, info: imaging.ImageInfo, size: int,
             dup_of: int | str | None) -> SavedImage: ...


def run_job(seed_url: str, client: PoliteClient, sink: Sink, max_images: int = 30,
            dup_distance: int = 6) -> JobStats:
    stats = JobStats()
    html = client.fetch_page(seed_url)
    urls = extract_image_urls(html, seed_url)
    stats.found = len(urls)

    for url in urls:
        if stats.saved >= max_images:
            break
        if sink.exists(url):
            stats.skipped_existing += 1
            continue
        try:
            data = client.download_image(url)
        except NotAllowedError:  # 必须排在 PermissionError 前面：它是 PermissionError 的子类
            stats.skipped_not_allowed += 1
            continue
        except PermissionError:
            stats.skipped_robots += 1
            continue
        except Exception as exc:  # 单张失败不影响整个任务
            stats.failed += 1
            stats.errors.append(f"{url}: {exc}")
            continue
        if data is None:
            stats.skipped_not_image += 1
            continue
        stats.downloaded += 1

        info = imaging.analyze(data)
        if info is None:
            stats.skipped_undecodable += 1
            continue

        dup = sink.find_duplicate(info.dhash, dup_distance)
        if dup is not None:
            stats.duplicates += 1
        sink.save(source_url=url, page_url=seed_url, info=info, size=len(data),
                  dup_of=dup.id if dup else None)
        stats.saved += 1
        log.info("saved %s (%dx%d, blur=%.1f%s)", url, info.width, info.height, info.blur_score,
                 f", dup_of={dup.id}" if dup else "")
    return stats


class LocalSink:
    """把缩略图和元数据写到本地目录，查重在内存里做。用于本地调试和测试。"""

    def __init__(self, out_dir: Path):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[dict] = []

    def exists(self, source_url: str) -> bool:
        return any(r["source_url"] == source_url for r in self.records)

    def find_duplicate(self, dhash: int, max_distance: int) -> SavedImage | None:
        best = None
        for r in self.records:
            if r["dup_of"] is not None:
                continue  # 只和每组的第一张比，组内其他图不当基准
            d = imaging.hamming(dhash, r["dhash"])
            if d <= max_distance and (best is None or d < best[0]):
                best = (d, r)
        return SavedImage(best[1]["id"], best[1]["dhash"]) if best else None

    def save(self, *, source_url, page_url, info, size, dup_of):
        image_id = len(self.records) + 1
        name = hashlib.sha1(source_url.encode()).hexdigest()[:16] + ".jpg"
        (self.out_dir / name).write_bytes(info.thumb_jpeg)
        record = {
            "id": image_id, "source_url": source_url, "page_url": page_url, "thumb": name,
            "width": info.width, "height": info.height, "bytes": size, "format": info.format,
            "dhash": info.dhash, "blur_score": info.blur_score, "brightness": info.brightness,
            "colors": info.colors, "dup_of": dup_of,
        }
        self.records.append(record)
        (self.out_dir / "index.json").write_text(json.dumps(self.records, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        return SavedImage(image_id, info.dhash)
