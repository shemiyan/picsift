"""命令行入口。

  python -m picsift local <网址> [--out out] [--limit 20]   不连数据库，结果写本地目录
"""

from __future__ import annotations

import argparse
import logging
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="picsift")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_local = sub.add_parser("local", help="不连数据库，抓一个页面写到本地目录")
    p_local.add_argument("url")
    p_local.add_argument("--out", default="out")
    p_local.add_argument("--limit", type=int, default=20)
    p_local.add_argument("--interval", type=float, default=1.0)
    p_local.set_defaults(func=cmd_local)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
