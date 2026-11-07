import httpx
import pytest

from picsift.crawl import PoliteClient, extract_image_urls

BASE = "https://example.test/gallery/index.html"


def test_extract_handles_common_markup():
    html = """
    <html><head><meta property="og:image" content="/og.jpg"></head><body>
      <img src="a.jpg">
      <img data-src="//cdn.example.test/lazy.png" src="data:image/gif;base64,R0lGOD">
      <img srcset="s.jpg 320w, l.jpg 1280w, m.jpg 640w" src="fallback.jpg">
      <picture><source srcset="p1.webp 1x, p2.webp 2x"><img src="p.jpg"></picture>
      <img src="a.jpg">
      <img src="javascript:alert(1)">
    </body></html>
    """
    assert extract_image_urls(html, BASE) == [
        "https://example.test/og.jpg",
        "https://example.test/gallery/p2.webp",
        "https://example.test/gallery/a.jpg",
        "https://cdn.example.test/lazy.png",
        "https://example.test/gallery/l.jpg",
        "https://example.test/gallery/fallback.jpg",
        "https://example.test/gallery/p.jpg",
    ]


def make_client(routes: dict, calls: list | None = None, **kw) -> PoliteClient:
    """routes: 路径 → httpx.Response 的构造参数（每次请求新建一个 Response）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request.url.path)
        args = routes.get(request.url.path)
        return httpx.Response(**args) if args is not None else httpx.Response(404)

    return PoliteClient(transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda s: None, **kw)


ROBOTS = {"status_code": 200, "text": "User-agent: *\nDisallow: /private/\n"}


def test_robots_disallow_is_respected():
    client = make_client({"/robots.txt": ROBOTS, "/private/x.jpg": {"status_code": 200}})
    assert client.allowed("https://example.test/public/x.jpg")
    assert not client.allowed("https://example.test/private/x.jpg")
    with pytest.raises(PermissionError):
        client.download_image("https://example.test/private/x.jpg")


def test_robots_server_error_means_disallow_all():
    client = make_client({"/robots.txt": {"status_code": 503}}, max_retries=0)
    assert not client.allowed("https://example.test/anything.jpg")
    with pytest.raises(PermissionError, match="robots.txt 返回 503"):
        client.fetch_page("https://example.test/")


def test_unreachable_site_reports_connection_not_robots_rule():
    def handler(request):
        raise httpx.ConnectTimeout("handshake timed out", request=request)

    client = PoliteClient(transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda s: None)
    with pytest.raises(PermissionError, match="取不到 robots.txt"):
        client.fetch_page("https://unreachable.test/")


def test_download_rejects_non_image_and_oversize():
    client = make_client({
        "/robots.txt": {"status_code": 404},
        "/page.jpg": {"status_code": 200, "headers": {"Content-Type": "text/html"}, "content": b"<html>"},
        "/big.jpg": {"status_code": 200, "headers": {"Content-Type": "image/jpeg"}, "content": b"x" * 2048},
        "/ok.jpg": {"status_code": 200, "headers": {"Content-Type": "image/jpeg"}, "content": b"x" * 100},
    }, max_bytes=1024)
    assert client.download_image("https://example.test/page.jpg") is None
    assert client.download_image("https://example.test/big.jpg") is None
    assert client.download_image("https://example.test/ok.jpg") == b"x" * 100


def test_retry_after_on_429():
    hits = {"n": 0}
    sleeps: list[float] = []

    def flaky(request):
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, text="<html></html>")

    def handler(request):
        return httpx.Response(**ROBOTS) if request.url.path == "/robots.txt" else flaky(request)

    client = PoliteClient(transport=httpx.MockTransport(handler), min_interval=0, sleep=sleeps.append)
    assert client.fetch_page("https://example.test/") == "<html></html>"
    assert 7.0 in sleeps and hits["n"] == 2


def test_robots_fetched_once_per_origin():
    calls: list[str] = []
    client = make_client({"/robots.txt": ROBOTS}, calls)
    for path in ("/a.jpg", "/b.jpg", "/c.jpg"):
        client.allowed("https://example.test" + path)
    assert calls.count("/robots.txt") == 1
