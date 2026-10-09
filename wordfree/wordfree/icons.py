"""Рисует простые иконки панели инструментов через PIL (не зависят от системы)."""
import base64
import io
import os

from PIL import Image, ImageDraw, ImageFont

from . import resources

_FONT_PATH = os.path.join(resources.fonts_dir(), "DejaVuSans-Bold.ttf")
_cache = {}


def _pil_font(size):
    try:
        return ImageFont.truetype(_FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _make(draw_fn, size=18):
    key = (getattr(draw_fn, "__qualname__", None) or draw_fn.__name__, size)
    if key in _cache:
        return _cache[key]
    import tkinter as tk

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_fn(d, size)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    photo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
    _cache[key] = photo
    return photo


def icon_align_left():
    def draw(d, s):
        for i, (x0, x1) in enumerate([(2, 13), (2, 16), (2, 10), (2, 16)]):
            d.line([(x0, 3 + i * 4), (x1, 3 + i * 4)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_align_center():
    def draw(d, s):
        c = s // 2
        for i, (x0, x1) in enumerate([(4, 14), (2, 16), (6, 12), (2, 16)]):
            d.line([(x0, 3 + i * 4), (x1, 3 + i * 4)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_align_right():
    def draw(d, s):
        for i, (x0, x1) in enumerate([(5, 16), (2, 16), (8, 16), (2, 16)]):
            d.line([(x0, 3 + i * 4), (x1, 3 + i * 4)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_align_justify():
    def draw(d, s):
        for i in range(4):
            d.line([(2, 3 + i * 4), (16, 3 + i * 4)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_bullet_list():
    def draw(d, s):
        f = _pil_font(7)
        for i, y in enumerate([4, 9, 14]):
            d.ellipse([2, y, 4, y + 2], fill=(60, 60, 60))
            d.line([(7, y + 1), (16, y + 1)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_number_list():
    def draw(d, s):
        f = _pil_font(6)
        for i, y in enumerate([3, 8, 13]):
            d.text((1, y - 1), str(i + 1), fill=(60, 60, 60), font=f)
            d.line([(7, y + 1), (16, y + 1)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_text_color():
    def draw(d, s):
        f = _pil_font(12)
        d.text((4, 1), "A", fill=(40, 40, 40), font=f)
        d.rectangle([2, 14, 15, 16], fill=(200, 30, 30))
    return _make(draw)


def icon_highlight():
    def draw(d, s):
        d.rounded_rectangle([1, 2, 17, 13], radius=2, fill=(255, 235, 120))
        f = _pil_font(11)
        d.text((5, 2), "A", fill=(40, 40, 40), font=f)
    return _make(draw)


def icon_spellcheck():
    def draw(d, s):
        f = _pil_font(9)
        d.text((1, 2), "AB", fill=(40, 40, 40), font=f)
        d.line([(1, 14), (16, 14)], fill=(200, 30, 30), width=2)
        d.line([(10, 6), (13, 10)], fill=(30, 140, 60), width=2)
        d.line([(13, 10), (17, 3)], fill=(30, 140, 60), width=2)
    return _make(draw)


def icon_grammar():
    def draw(d, s):
        f = _pil_font(11)
        d.text((1, 2), "A", fill=(40, 40, 40), font=f)
        # лупа
        d.ellipse([8, 5, 16, 13], outline=(30, 100, 180), width=2)
        d.line([(14, 12), (18, 17)], fill=(30, 100, 180), width=2)
    return _make(draw)


def icon_image():
    def draw(d, s):
        d.rectangle([1, 3, 17, 15], outline=(60, 60, 60), width=2)
        d.ellipse([4, 6, 8, 10], fill=(240, 200, 60))
        d.polygon([(1, 15), (7, 9), (11, 13), (14, 10), (17, 13), (17, 15), (1, 15)], fill=(90, 160, 90))
    return _make(draw)


def icon_table():
    def draw(d, s):
        d.rectangle([1, 3, 17, 15], outline=(60, 60, 60), width=2)
        d.line([(1, 9), (17, 9)], fill=(60, 60, 60), width=2)
        d.line([(9, 3), (9, 15)], fill=(60, 60, 60), width=2)
    return _make(draw)


def icon_print():
    def draw(d, s):
        d.rectangle([4, 2, 14, 8], outline=(60, 60, 60), width=2)
        d.rectangle([2, 7, 16, 13], fill=(120, 140, 165), outline=(60, 60, 60), width=1)
        d.rectangle([4, 11, 14, 17], fill=(255, 255, 255), outline=(60, 60, 60), width=1)
        d.ellipse([12, 9, 14, 11], fill=(40, 180, 80))
    return _make(draw)


def icon_save():
    def draw(d, s):
        d.rectangle([2, 2, 16, 16], fill=(70, 110, 180), outline=(40, 70, 130), width=1)
        d.rectangle([5, 3, 13, 8], fill=(255, 255, 255))
        d.rectangle([5, 10, 13, 15], fill=(220, 230, 245))
        d.rectangle([9, 11, 11, 14], fill=(70, 110, 180))
    return _make(draw)
