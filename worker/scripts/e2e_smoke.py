"""端到端冒烟测试：连真实 Supabase 项目跑一遍完整链路，跑完清理。

  python scripts/e2e_smoke.py [--url https://books.toscrape.com/] [--images 3]

会临时创建两个测试账号（A、B），验证：
  1. A 能新建任务，user_id 由数据库默认值填成 A；不能新建非 pending 任务，不能改任务状态
  2. worker 通过 claim_job() 领到任务，抓图、分析、上传缩略图、写 images、回写 done
  3. A 能读到自己的图片，能给缩略图签名并下载到 JPEG
  4. B 看不到 A 的任务和图片，也签不了 A 的缩略图
  5. 前端角色调不了 worker 专用的 similar_images()
最后删除测试账号（级联删除任务和图片）和它们的缩略图。

需要根目录 .env（SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY）和 web/.env.local（VITE_SUPABASE_ANON_KEY）。
"""

from __future__ import annotations

import argparse
import secrets
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import dotenv_values
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from picsift import config, store  # noqa: E402
from picsift.crawl import PoliteClient  # noqa: E402
from picsift.pipeline import run_job  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> bool:
    results.append((ok, label))
    print(("  ✓ " if ok else "  ✗ ") + label)
    return ok


def expect_error(fn, label: str) -> None:
    try:
        fn()
    except Exception:
        check(True, label)
        return
    check(False, label + "（本应失败却成功了）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://books.toscrape.com/")
    parser.add_argument("--images", type=int, default=3)
    args = parser.parse_args()

    settings = config.load()
    anon_key = dotenv_values(Path(__file__).resolve().parents[2] / "web" / ".env.local").get(
        "VITE_SUPABASE_ANON_KEY")
    if not anon_key:
        print("缺少 web/.env.local 里的 VITE_SUPABASE_ANON_KEY")
        return 2

    admin = create_client(settings.supabase_url, settings.supabase_service_key)
    users: list[str] = []
    try:
        print("准备测试账号")
        creds = []
        for name in ("a", "b"):
            email = f"picsift-smoke-{name}-{uuid.uuid4().hex[:8]}@example.com"
            password = secrets.token_urlsafe(16)
            u = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
            users.append(u.user.id)
            creds.append({"email": email, "password": password})
        user_a, user_b = users
        a = create_client(settings.supabase_url, anon_key)
        a.auth.sign_in_with_password(creds[0])
        b = create_client(settings.supabase_url, anon_key)
        b.auth.sign_in_with_password(creds[1])

        print("1. 新建任务与 RLS")
        new_job = {"seed_url": args.url, "max_images": args.images}
        job = a.table("crawl_jobs").insert(new_job).execute().data[0]
        check(job["user_id"] == user_a and job["status"] == "pending",
              "A 新建任务，user_id 自动填成 A，状态 pending")
        expect_error(lambda: a.table("crawl_jobs").insert({"seed_url": args.url, "status": "done"}).execute(),
                     "A 不能直接新建 done 状态的任务")
        upd = a.table("crawl_jobs").update({"status": "done"}).eq("id", job["id"]).execute()
        check(upd.data == [], "A 改不了任务状态（没有 update 策略，影响 0 行）")

        print("2. worker 领取并处理")
        claimed = store.claim_job(admin)
        if not check(claimed is not None and claimed["id"] == job["id"], "claim_job() 领到刚才的任务"):
            return 1
        check(claimed["status"] == "running", "领取后状态变为 running")
        sink = store.SupabaseSink(admin, settings.bucket, claimed["user_id"], claimed["id"])
        with PoliteClient(min_interval=settings.request_interval) as http:
            stats = run_job(claimed["seed_url"], http, sink, max_images=claimed["max_images"],
                            dup_distance=settings.dup_distance)
        store.finish_job(admin, claimed["id"], "done", stats.as_dict())
        check(stats.saved == args.images,
              f"保存 {stats.saved} 张（目标 {args.images}），找到 {stats.found} 张")

        print("3. A 读取自己的数据")
        job_a = a.table("crawl_jobs").select("*").eq("id", job["id"]).single().execute().data
        check(job_a["status"] == "done" and job_a["stats"].get("saved") == stats.saved,
              "A 看到任务已完成及统计")
        imgs = a.table("images").select("*").eq("job_id", job["id"]).execute().data
        check(len(imgs) == stats.saved, f"A 读到 {len(imgs)} 条图片记录")
        if imgs:
            signed = a.storage.from_(settings.bucket).create_signed_url(imgs[0]["thumb_path"], 60)
            url = signed.get("signedURL") or signed.get("signedUrl")
            resp = httpx.get(url, timeout=30)
            check(resp.status_code == 200 and resp.content[:3] == b"\xff\xd8\xff",
                  "A 签名下载缩略图，拿到 JPEG")

        print("4. B 看不到 A 的数据")
        check(b.table("crawl_jobs").select("id").execute().data == [], "B 读任务表得到 0 行")
        check(b.table("images").select("id").execute().data == [], "B 读图片表得到 0 行")
        if imgs:
            path_a = imgs[0]["thumb_path"]
            expect_error(lambda: b.storage.from_(settings.bucket).create_signed_url(path_a, 60),
                         "B 签不了 A 的缩略图")

        print("5. 函数权限")
        rpc_args = {"p_user": user_a, "p_hash": 0, "p_max_dist": 6}
        expect_error(lambda: a.rpc("similar_images", rpc_args).execute(), "前端角色调不了 similar_images()")
        expect_error(lambda: a.rpc("claim_job", {}).execute(), "前端角色调不了 claim_job()")
    finally:
        print("清理")
        for uid in users:
            try:
                folders = admin.storage.from_(settings.bucket).list(uid)
                paths = []
                for folder in folders:
                    for obj in admin.storage.from_(settings.bucket).list(f"{uid}/{folder['name']}"):
                        paths.append(f"{uid}/{folder['name']}/{obj['name']}")
                if paths:
                    admin.storage.from_(settings.bucket).remove(paths)
                admin.auth.admin.delete_user(uid)
                print(f"  已删除测试账号及 {len(paths)} 个缩略图")
            except Exception as exc:
                print(f"  清理失败，请到后台手动删除用户 {uid}：{type(exc).__name__}")

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
