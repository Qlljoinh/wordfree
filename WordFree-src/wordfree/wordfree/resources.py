"""Пути к ресурсам (внутри exe/сборки) и пользовательским данным."""
import os
import sys

APP_NAME = "WordFree"


def bundle_dir():
    """Корень, где лежат fonts/ и dictionaries/ (внутри PyInstaller-сборки — временная папка распаковки)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    # при запуске из исходников: пакет wordfree/ лежит в корне проекта
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_dir():
    """Папка пользовательских данных (словарь, настройки, кэш LanguageTool)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def fonts_dir():
    return os.path.join(bundle_dir(), "fonts")


def dicts_dir():
    return os.path.join(bundle_dir(), "dictionaries")


def setup_languagetool_cache():
    """Говорим language_tool_python, куда складывать скачанный LanguageTool (~400 МБ, один раз)."""
    os.environ["LTP_PATH"] = os.path.join(user_dir(), "LanguageTool")
