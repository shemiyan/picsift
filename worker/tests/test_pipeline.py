import json

import cv2
import httpx

from picsift import imaging
from picsift.crawl import PoliteClient
from picsift.pipeline import JobStats, LocalSink, run_job

from .test_imaging import make_scene


def jpeg(img) -> bytes:
    return imaging.encode_jpeg(img, 90)


def test_run_job_end_to_end(tmp_path):
    original = make_scene(10)
    near_copy = cv2.resize(original, (200, 150), interpolation=cv2.INTER_AREA)  # 缩小版，应判为重复
    other = make_scene(11)
    page = """<html><body>
      <img src="/img/1.jpg"><img src="/img/2.jpg"><img src="/img/3.jpg">
      <img src="/img/gif.gif"><img src="/img/missing.jpg"><img src="/blocked/4.jpg">
    </body></html>"""
    img = {"status_code": 200, "headers": {"Content-Type": "image/jpeg"}}
    routes = {
        "/robots.txt": {"status_code": 200, "text": "User-agent: *\nDisallow: /blocked/\n"},
        "/": {"status_code": 200, "text": page},
        "/img/1.jpg": {**img, "content": jpeg(original)},
        "/img/2.jpg": {**img, "content": jpeg(near_copy)},
        "/img/3.jpg": {**img, "content": jpeg(other)},
        "/img/gif.gif": {
            "status_code": 200, "headers": {"Content-Type": "image/gif"}, "content": b"GIF89a\x00",
        },
    }

    def handler(request):
        args = routes.get(request.url.path)
        return httpx.Response(**args) if args else httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = PoliteClient(transport=transport, min_interval=0, sleep=lambda s: None)
    sink = LocalSink(tmp_path)

    stats = run_job("https://example.test/", client, sink, max_images=10)

    assert stats.found == 6
    assert stats.saved == 3
    assert stats.duplicates == 1
    assert stats.skipped_robots == 1
    assert stats.skipped_undecodable == 1  # GIF OpenCV 解不了
    assert stats.skipped_not_image == 1  # 404

    records = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    by_url = {r["source_url"].rsplit("/", 1)[-1]: r for r in records}
    assert by_url["2.jpg"]["dup_of"] == by_url["1.jpg"]["id"]
    assert by_url["1.jpg"]["dup_of"] is None and by_url["3.jpg"]["dup_of"] is None
    assert all((tmp_path / r["thumb"]).exists() for r in records)

    # 同一页面再跑一次：已有的图跳过，不重复保存
    again = run_job("https://example.test/", client, sink, max_images=10)
    assert again.saved == 0 and again.skipped_existing == 3


def test_summary_explains_why_nothing_was_saved():
    assert JobStats(found=20, skipped_existing=20).summary() == "找到 20，保存 0，已存在 20"
    stats = JobStats(found=6, saved=3, duplicates=1, skipped_robots=1,
                     skipped_undecodable=1, skipped_not_image=1)
    assert stats.summary() == "找到 6，保存 3，重复 1，robots 禁止 1，非图片 1，无法解码 1"
