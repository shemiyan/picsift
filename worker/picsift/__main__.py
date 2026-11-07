"""命令行入口。

  python -m picsift local <网址> [--out out] [--limit 20]   不连数据库，结果写本地目录
  python -m picsift worker [--once]                         从 Supabase 领任务处理
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .crawl import PoliteClient
from .pipeline import LocalSink, run_job

log = logging.getLogger("picsift")


def cmd_local(args) -> None:
    sink = LocalSink(Path(args.out))
    with PoliteClient(min_interval=args.interval) as client:
        stats = run_job(args.url, client, sink, max_images=args.limit)
    for key, value in stats.as_dict().items():
        if key != "errors":
            print(f"{key:>20}: {value}")
    for err in stats.errors[:5]:
        print("  error:", err)
    print(f"缩略图和 index.json 在 {Path(args.out).resolve()}")


def cmd_worker(args) -> None:
    from . import config, store

    settings = config.load()
    client = store.make_client(settings)
    log.info("worker started, polling every %.0fs", settings.poll_seconds)
    while True:
        job = store.claim_job(client)
        if job is None:
            if args.once:
                return
            time.sleep(settings.poll_seconds)
            continue
        log.info("job %s: %s", job["id"], job["seed_url"])
        sink = store.SupabaseSink(client, settings.bucket, job["user_id"], job["id"])
        try:
            with PoliteClient(min_interval=settings.request_interval,
                              max_bytes=settings.max_image_bytes) as http:
                stats = run_job(job["seed_url"], http, sink, max_images=job["max_images"],
                                dup_distance=settings.dup_distance)
            store.finish_job(client, job["id"], "done", stats.as_dict())
        except Exception as exc:
            log.exception("job %s failed", job["id"])
            store.finish_job(client, job["id"], "failed", {}, str(exc)[:500])
        if args.once:
            return


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # 每 3 秒轮询一次，httpx 的逐条请求日志会刷屏，只保留警告以上
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="picsift")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_local = sub.add_parser("local", help="不连数据库，抓一个页面写到本地目录")
    p_local.add_argument("url")
    p_local.add_argument("--out", default="out")
    p_local.add_argument("--limit", type=int, default=20)
    p_local.add_argument("--interval", type=float, default=1.0)
    p_local.set_defaults(func=cmd_local)

    p_worker = sub.add_parser("worker", help="从 Supabase 领取任务并处理")
    p_worker.add_argument("--once", action="store_true", help="处理一个任务就退出")
    p_worker.set_defaults(func=cmd_worker)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
