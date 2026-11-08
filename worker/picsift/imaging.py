"""图像分析：缩略图、感知哈希（dHash）、清晰度、亮度、主色。

所有函数只依赖 OpenCV 和 numpy，输入是 OpenCV 的 BGR 数组。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

_MASK64 = (1 << 64) - 1


@dataclass
class ImageInfo:
    width: int
    height: int
    format: str
    dhash: int  # 有符号 64 位，方便直接存 Postgres bigint
    blur_score: float
    brightness: float
    colors: list[dict] = field(default_factory=list)
    thumb_jpeg: bytes = b""


def sniff_format(data: bytes) -> str:
    """按文件头判断格式，不信任服务器给的 Content-Type。"""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:2] == b"BM":
        return "bmp"
    return "unknown"


def decode(data: bytes) -> np.ndarray | None:
    """解码成 BGR 数组；OpenCV 不支持的格式（如 GIF）返回 None。"""
    arr = np.frombuffer(data, dtype=np.uint8)
    if arr.size == 0:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def thumbnail(img: np.ndarray, max_side: int = 480) -> np.ndarray:
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale >= 1:
        return img
    # 缩小用 INTER_AREA，摩尔纹和锯齿最少
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)


def encode_jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG 编码失败")
    return buf.tobytes()


def to_signed64(value: int) -> int:
    value &= _MASK64
    return value - (1 << 64) if value >= 1 << 63 else value


def dhash(img: np.ndarray, hash_size: int = 8) -> int:
    """差值哈希：缩成 (hash_size+1) x hash_size 的灰度图，逐行比较相邻像素明暗。

    缩放、重新压缩、轻微调色后哈希基本不变，所以两张图哈希的汉明距离
    可以当作"像不像"的度量。返回有符号 64 位整数。
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return to_signed64(value)


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & _MASK64).bit_count()


def _normalized_gray(img: np.ndarray, side: int = 512) -> np.ndarray:
    """长边统一缩放到 side（大图缩小、小图放大）再算指标，不同分辨率的图分数才可比。

    小图放大后会变"软"，清晰度分数随之降低，这正符合它在同样显示尺寸下看起来更糊的事实。
    """
    h, w = img.shape[:2]
    scale = side / max(h, w)
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    resized = cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=interp)
    return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)


def blur_score(img: np.ndarray) -> float:
    """拉普拉斯方差：边缘越锐利方差越大，越模糊越接近 0。"""
    return float(cv2.Laplacian(_normalized_gray(img), cv2.CV_64F).var())


def brightness(img: np.ndarray) -> float:
    """平均亮度，0（全黑）~ 1（全白）。"""
    return float(_normalized_gray(img).mean() / 255.0)


def dominant_colors(img: np.ndarray, k: int = 3, min_ratio: float = 0.03) -> list[dict]:
    """k-means 聚类取主色，按占比从高到低返回 [{"hex": "#rrggbb", "ratio": 0.42}, ...]。

    缩小时色块交界会混出过渡色（红蓝交界出紫色），占比低于 min_ratio 的不算主色。
    """
    small = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    k = min(k, len(np.unique(pixels, axis=0)))
    cv2.setRNGSeed(0)  # 固定随机种子，同一张图每次结果一样
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    result = []
    for idx in np.argsort(-counts):
        ratio = float(counts[idx] / counts.sum())
        if ratio < min_ratio:
            continue
        b, g, r = (int(round(c)) for c in centers[idx])
        result.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "ratio": round(ratio, 3)})
    return result


def analyze(data: bytes, thumb_side: int = 480) -> ImageInfo | None:
    img = decode(data)
    if img is None:
        return None
    h, w = img.shape[:2]
    return ImageInfo(
        width=w,
        height=h,
        format=sniff_format(data),
        dhash=dhash(img),
        blur_score=round(blur_score(img), 2),
        brightness=round(brightness(img), 3),
        colors=dominant_colors(img),
        thumb_jpeg=encode_jpeg(thumbnail(img, thumb_side)),
    )
