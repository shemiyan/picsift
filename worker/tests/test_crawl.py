import httpx
import pytest

from picsift.crawl import NotAllowedError, PoliteClient, extract_image_urls, host_allowed

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


def test_host_allowed_matching():
    allowed = ("example.test",)
    assert host_allowed("https://example.test/a.jpg", allowed)
    assert host_allowed("https://cdn.example.test/a.jpg", allowed)  # 子域名也算
    assert not host_allowed("https://example.test.evil.com/a.jpg", allowed)
    assert not host_allowed("https://notexample.test/", allowed)
    assert not host_allowed("http://10.0.0.8/", allowed)
    assert host_allowed("http://10.0.0.8/", ())  # 名单为空表示不限制


JPEG = {"status_code": 200, "headers": {"Content-Type": "image/jpeg"}}


def host_recording_client(routes: dict, seen: list, **kw) -> PoliteClient:
    """按 "主机+路径" 路由，并记录每个被请求过的地址。"""
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}{request.url.path}"
        seen.append(key)
        args = routes.get(key)
        return httpx.Response(**args) if args is not None else httpx.Response(404)

    return PoliteClient(transport=httpx.MockTransport(handler), min_interval=0, sleep=lambda s: None, **kw)


def test_allowlist_blocks_before_any_request():
    seen: list[str] = []
    client = host_recording_client({}, seen, allowed_hosts=("example.test",))
    with pytest.raises(NotAllowedError):
        client.fetch_page("http://intranet.local/admin")
    with pytest.raises(NotAllowedError):
        client.download_image("http://10.0.0.8/secret.jpg")
    assert seen == []  # 名单外的地址连 robots.txt 都不会去请求


def test_redirect_out_of_allowlist_is_never_requested():
    seen: list[str] = []
    client = host_recording_client({
        "example.test/go.jpg": {"status_code": 302, "headers": {"Location": "http://10.0.0.8/secret.jpg"}},
        "10.0.0.8/secret.jpg": {**JPEG, "content": b"x"},
    }, seen, allowed_hosts=("example.test",))
    with pytest.raises(NotAllowedError):
        client.download_image("https://example.test/go.jpg")
    assert not any(k.startswith("10.0.0.8") for k in seen)


def test_redirect_inside_allowlist_is_followed():
    seen: list[str] = []
    client = host_recording_client({
        "example.test/old.jpg": {"status_code": 301, "headers": {"Location": "https://cdn.example.test/new.jpg"}},
        "cdn.example.test/new.jpg": {**JPEG, "content": b"ok"},
    }, seen, allowed_hosts=("example.test",))
    assert client.download_image("https://example.test/old.jpg") == b"ok"
    assert "cdn.example.test/robots.txt" in seen  # 跳到新主机后也先读它的 robots.txt


def test_too_many_redirects():
    seen: list[str] = []
    client = host_recording_client({
        "example.test/loop": {"status_code": 302, "headers": {"Location": "/loop"}},
    }, seen)
    with pytest.raises(httpx.TooManyRedirects):
        client.fetch_page("https://example.test/loop")
