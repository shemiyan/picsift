import cv2
import numpy as np
import pytest

from picsift import imaging


def make_scene(seed: int = 0, size=(240, 320)) -> np.ndarray:
    """生成一张有渐变和几何图形的测试图，seed 不同图案不同。"""
    rng = np.random.default_rng(seed)
    h, w = size
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = np.linspace(40, 200, w, dtype=np.uint8)[None, :, None]
    for _ in range(6):
        center = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.circle(img, center, int(rng.integers(15, 60)), color, -1)
    cv2.putText(img, f"#{seed}", (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    return img


def jpeg_roundtrip(img: np.ndarray, quality: int) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(imaging.encode_jpeg(img, quality), np.uint8), cv2.IMREAD_COLOR)


def test_dhash_same_image_distance_zero():
    img = make_scene(1)
    assert imaging.hamming(imaging.dhash(img), imaging.dhash(img.copy())) == 0


def test_dhash_survives_resize_and_recompression():
    img = make_scene(2)
    variant = jpeg_roundtrip(cv2.resize(img, (160, 120), interpolation=cv2.INTER_AREA), 60)
    assert imaging.hamming(imaging.dhash(img), imaging.dhash(variant)) <= 6


def test_dhash_different_images_far_apart():
    a, b = imaging.dhash(make_scene(3)), imaging.dhash(make_scene(4))
    assert imaging.hamming(a, b) > 10


def test_dhash_fits_signed_bigint():
    for seed in range(20):
        h = imaging.dhash(make_scene(seed))
        assert -(2**63) <= h < 2**63


@pytest.mark.parametrize("value", [0, 1, 2**63 - 1, 2**63, 2**64 - 1])
def test_to_signed64_roundtrip(value):
    signed = imaging.to_signed64(value)
    assert -(2**63) <= signed < 2**63
    assert signed & ((1 << 64) - 1) == value


def test_blur_score_drops_when_blurred():
    img = make_scene(5)
    blurred = cv2.GaussianBlur(img, (0, 0), 4)
    assert imaging.blur_score(img) > imaging.blur_score(blurred) * 3


def test_brightness_orders_dark_and_light():
    dark = np.full((50, 50, 3), 20, np.uint8)
    light = np.full((50, 50, 3), 230, np.uint8)
    assert imaging.brightness(dark) < 0.1 < 0.9 < imaging.brightness(light)


def test_dominant_colors_two_halves():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :60] = (0, 0, 255)  # BGR 红
    img[:, 60:] = (255, 0, 0)  # BGR 蓝
    colors = imaging.dominant_colors(img, k=3)
    assert colors[0]["hex"] == "#ff0000" and colors[0]["ratio"] == pytest.approx(0.6, abs=0.02)
    assert colors[1]["hex"] == "#0000ff"
    assert len(colors) == 2  # 只有两种颜色时不硬凑第三种


def test_thumbnail_keeps_aspect_and_never_upscales():
    big = np.zeros((1000, 2000, 3), np.uint8)
    assert imaging.thumbnail(big, 480).shape[:2] == (240, 480)
    small = np.zeros((100, 50, 3), np.uint8)
    assert imaging.thumbnail(small, 480).shape[:2] == (100, 50)


def test_sniff_format():
    img = make_scene(6)
    assert imaging.sniff_format(imaging.encode_jpeg(img)) == "jpeg"
    ok, png = cv2.imencode(".png", img)
    assert imaging.sniff_format(png.tobytes()) == "png"
    assert imaging.sniff_format(b"GIF89a....") == "gif"


def test_analyze_rejects_garbage_and_fills_fields():
    assert imaging.analyze(b"not an image") is None
    info = imaging.analyze(imaging.encode_jpeg(make_scene(7)))
    assert (info.width, info.height, info.format) == (320, 240, "jpeg")
    assert info.thumb_jpeg.startswith(b"\xff\xd8") and info.colors


def test_blur_score_comparable_across_resolutions():
    img = make_scene(8, size=(600, 800))
    small = cv2.resize(img, (200, 150), interpolation=cv2.INTER_AREA)
    # 同一张图的大小两个版本：小图在同样显示尺寸下更糊，分数应更低，但不该差出数量级
    big_score, small_score = imaging.blur_score(img), imaging.blur_score(small)
    assert small_score < big_score
    assert small_score > big_score / 20
