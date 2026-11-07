"""礼貌爬取：遵守 robots.txt、同站限速、遇 429/503 按 Retry-After 退避、限制单图大小。"""

from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

DEFAULT_UA = "PicSiftBot/0.1 (+https://github.com/shemiyan/picsift)"


def _best_from_srcset(srcset: str) -> str | None:
    """srcset 里挑最大的一张：按 "url 640w" 的宽度或 "url 2x" 的倍率比较。"""
    best, best_score = None, -1.0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        score = 1.0
        if len(bits) > 1:
            desc = bits[1]
            try:
                score = float(desc[:-1]) if desc[-1] in "wx" else 1.0
            except ValueError:
                score = 1.0
        if score > best_score:
            best, best_score = bits[0], score
    return best


def extract_image_urls(html: str, base_url: str) -> list[str]:
    """从页面里找图片地址：img 的 src/data-src/srcset、picture 的 source、og:image。

    返回绝对地址，去重并保持页面顺序，跳过 data: 内联图。
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for tag in soup.find_all("meta", attrs={"property": "og:image"}):
        if tag.get("content"):
            candidates.append(tag["content"])
    for tag in soup.find_all("source"):
        if tag.get("srcset"):
            candidates.append(_best_from_srcset(tag["srcset"]) or "")
    for tag in soup.find_all("img"):
        if tag.get("srcset"):
            candidates.append(_best_from_srcset(tag["srcset"]) or "")
        for attr in ("src", "data-src", "data-original"):
            if tag.get(attr):
                candidates.append(tag[attr])

    seen: set[str] = set()
    result: list[str] = []
    for raw in candidates:
        raw = raw.strip()
        if not raw or raw.startswith("data:"):
            continue
        url = urljoin(base_url, raw)
        if urlsplit(url).scheme not in ("http", "https") or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


class PoliteClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        min_interval: float = 1.0,
        max_bytes: int = 8 * 1024 * 1024,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self.max_retries = max_retries
        self._sleep = sleep
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_error: dict[str, str] = {}  # 取不到 robots.txt 的原因，报错时区分"连不上"和"被禁止"
        self._last_hit: dict[str, float] = {}
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- robots.txt ----
    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(origin)
        if rp is None:
            rp = RobotFileParser()
            try:
                resp = self._request("GET", origin + "/robots.txt", check_robots=False)
                # 4xx 视为没有限制；5xx 或网络错误时保守起见全部不抓
                if resp.status_code >= 500:
                    rp.disallow_all = True
                    self._robots_error[origin] = f"robots.txt 返回 {resp.status_code}"
                else:
                    rp.parse(resp.text.splitlines() if resp.status_code < 400 else [])
            except httpx.HTTPError as exc:
                rp.disallow_all = True
                self._robots_error[origin] = f"取不到 robots.txt（{type(exc).__name__}）"
            self._robots[origin] = rp
        return rp.can_fetch(self.user_agent, url)

    def _deny(self, url: str) -> PermissionError:
        parts = urlsplit(url)
        reason = self._robots_error.get(f"{parts.scheme}://{parts.netloc}")
        if reason:
            return PermissionError(f"{reason}，保守起见不抓取：{url}")
        return PermissionError(f"robots.txt 不允许抓取：{url}")

    # ---- 限速与重试 ----
    def _throttle(self, host: str) -> None:
        wait = self._last_hit.get(host, 0.0) + self.min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_hit[host] = time.monotonic()

    def _request(self, method: str, url: str, check_robots: bool = True, **kw) -> httpx.Response:
        if check_robots and not self.allowed(url):
            raise self._deny(url)
        for attempt in range(self.max_retries + 1):
            self._throttle(urlsplit(url).netloc)
            resp = self._http.request(method, url, **kw)
            if resp.status_code not in (429, 503) or attempt == self.max_retries:
                return resp
            retry_after = resp.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2.0**attempt
            self._sleep(min(delay, 60.0))
        return resp  # pragma: no cover

    def fetch_page(self, url: str) -> str:
        resp = self._request("GET", url)
        resp.raise_for_status()
        return resp.text

    def download_image(self, url: str) -> bytes | None:
        """下载图片；不是图片或超过大小上限就返回 None。"""
        if not self.allowed(url):
            raise self._deny(url)
        self._throttle(urlsplit(url).netloc)
        with self._http.stream("GET", url) as resp:
            if resp.status_code != 200:
                return None
            ctype = resp.headers.get("Content-Type", "")
            if not ctype.startswith("image/"):
                return None
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                return None
            chunks, total = [], 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > self.max_bytes:
                    return None
                chunks.append(chunk)
        return b"".join(chunks)
