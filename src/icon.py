"""水滴图标绘制(托盘与桌面快捷方式共用)。仅依赖 Pillow。"""
from __future__ import annotations


def drop_image(size: int = 64):
    """返回一张指定尺寸的水滴图标(PIL.Image, RGBA)。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64.0
    draw.polygon([(32 * s, 8 * s), (16 * s, 36 * s), (48 * s, 36 * s)], fill=(30, 144, 255, 255))
    draw.ellipse([14 * s, 26 * s, 50 * s, 56 * s], fill=(30, 144, 255, 255))
    draw.ellipse([26 * s, 38 * s, 34 * s, 48 * s], fill=(180, 220, 255, 255))
    return img
