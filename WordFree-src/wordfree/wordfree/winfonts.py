"""Регистрация шрифтов из комплекта во временную (сессионную) область Windows,
чтобы интерфейс и PDF корректно показывали кириллицу даже без установленных шрифтов."""
import os
import sys


def register_bundled_fonts():
    """AddFontResourceW для каждого .ttf из fonts/. Возвращает True, если хоть один зарегистрирован."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        from . import resources

        gdi = ctypes.windll.gdi32  # type: ignore[attr-defined]
        ok = 0
        fd = resources.fonts_dir()
        if os.path.isdir(fd):
            for f in sorted(os.listdir(fd)):
                if f.lower().endswith(".ttf"):
                    try:
                        r = gdi.AddFontResourceW(ctypes.c_wchar_p(os.path.join(fd, f)))
                        if r:
                            ok += r
                    except Exception:
                        pass
        return ok > 0
    except Exception:
        return False
