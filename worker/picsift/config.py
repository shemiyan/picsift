"""配置从环境变量读取，本地开发时从仓库根目录的 .env 加载。密钥只放 .env，不进代码。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_key: str
    bucket: str = "thumbs"
    request_interval: float = 1.0  # 同一站点两次请求的最小间隔（秒）
    max_image_bytes: int = 8 * 1024 * 1024
    dup_distance: int = 6  # dHash 汉明距离 ≤ 6 视为近似重复
    poll_seconds: float = 3.0


def load() -> Settings:
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"缺少环境变量：{', '.join(missing)}（见仓库根目录 .env.example）")
    return Settings(
        supabase_url=os.environ["SUPABASE_URL"],
        supabase_service_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        request_interval=float(os.getenv("PICSIFT_REQUEST_INTERVAL", "1.0")),
        dup_distance=int(os.getenv("PICSIFT_DUP_DISTANCE", "6")),
    )
