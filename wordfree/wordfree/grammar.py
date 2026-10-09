"""Движок проверки грамматики: правила (всегда) + LanguageTool (если есть Java)."""
import re
import shutil
import threading

from . import resources  # noqa: F401  (setup_languagetool_cache вызывается из main до импорта LT)


class GrammarIssue:
    __slots__ = ("start", "end", "message", "rule", "suggestion", "source")

    def __init__(self, start, end, message, rule, suggestion=None, source="rules"):
        self.start = start
        self.end = end
        self.message = message
        self.rule = rule
        self.suggestion = suggestion
        self.source = source

    def __repr__(self):
        return f"<GrammarIssue {self.rule} [{self.start}:{self.end}] {self.message!r}>"


# ---------------- Правила (работают всегда, без Java и интернета) ----------------
# Каждое правило: (id, regex, сообщение, замена) — замена: строка или callable(match)->str
_RULES = [
    (
        "REPEATED_WORD",
        re.compile(r"\b([А-Яа-яЁёA-Za-z]{2,})[ \t]+\1\b", re.IGNORECASE),
        "Повтор слова «{w}»",
        lambda m: m.group(1),
    ),
    (
        "DOUBLE_SPACE",
        re.compile(r"[^\S\n]{2,}"),
        "Несколько пробелов подряд",
        " ",
    ),
    (
        "SPACE_BEFORE_PUNCT",
        re.compile(r"[ \t]+([,.!?…:;»])"),
        "Лишний пробел перед знаком препинания",
        lambda m: m.group(1),
    ),
    (
        "SPACE_BEFORE_OPEN_QUOTE",
        re.compile(r"[ \t]+(«)"),
        "Лишний пробел перед открывающей кавычкой",
        lambda m: m.group(1),
    ),
    (
        "NO_SPACE_AFTER_PUNCT",
        re.compile(r"([,.!?…:;»„])([А-Яа-яЁёA-Za-z0-9])"),
        "Нет пробела после знака препинания",
        lambda m: m.group(1) + " " + m.group(2),
    ),
    (
        "LOWERCASE_SENTENCE_START",
        re.compile(r"(?:^|(?<=[.!?…])\s+)([а-яёa-z])"),
        "Предложение начинается с маленькой буквы",
        lambda m: m.group(1).upper(),
    ),
    (
        "REPEATED_PUNCT",
        re.compile(r"([,.!?])(?:\s*\1)+"),
        "Повтор знака препинания",
        lambda m: m.group(1),
    ),
    (
        "HYPHEN_AS_DASH",
        re.compile(r"(?<=\s)--(?=\s|$)"),
        "Два дефиса вместо тире",
        "—",
    ),
    (
        "TAB_AT_LINE_START",
        re.compile(r"(?m)^\t+"),
        "Tab в начале строки (лучше отступ)",
        "",
    ),
    (
        "TRAILING_SPACES",
        re.compile(r"(?m)[ \t]+$"),
        "Пробелы в конце строки",
        "",
    ),
]


def check_rules(text):
    issues = []
    for rule_id, rx, msg, repl in _RULES:
        for m in rx.finditer(text):
            suggestion = repl(m) if callable(repl) else repl
            if rule_id == "REPEATED_WORD":
                msg_t = msg.format(w=m.group(1))
            else:
                msg_t = msg
            issues.append(GrammarIssue(m.start(), m.end(), msg_t, rule_id, suggestion, "rules"))
    issues.sort(key=lambda i: (i.start, i.end))
    return issues


# ---------------- LanguageTool (нужна Java; скачивается один раз) ----------------

class LTBackend:
    def __init__(self):
        self.tool = None
        self.error = None
        self.lock = threading.Lock()

    @staticmethod
    def java_available():
        return shutil.which("java") is not None

    def start(self):
        """Запуск сервера LanguageTool. Блокирующий — вызывать из потока."""
        with self.lock:
            if self.tool is not None:
                return True
            try:
                import language_tool_python

                try:
                    self.tool = language_tool_python.LanguageTool("ru")
                except SystemError as e:
                    # свежий LanguageTool требует Java >= 17; пробуем версию под Java 8+
                    if "Java" in str(e):
                        self.tool = language_tool_python.LanguageTool(
                            "ru", language_tool_download_version="6.5"
                        )
                    else:
                        raise
                return True
            except Exception as e:
                self.error = str(e)
                self.tool = None
                return False

    def check(self, text):
        with self.lock:
            tool = self.tool
        if tool is None:
            return []
        matches = tool.check(text)
        issues = []
        for m in matches:
            try:
                start = m.offset
                length = m.error_length
            except AttributeError:
                start = m.context.offset
                length = m.context.length
            suggestions = []
            for r in (m.replacements or [])[:3]:
                if isinstance(r, str):
                    suggestions.append(r)
                else:
                    suggestions.append(getattr(r, "value", str(r)))
            issues.append(
                GrammarIssue(
                    start,
                    start + max(length, 1),
                    m.message,
                    getattr(m, "rule_id", "LT"),
                    suggestions[0] if suggestions else None,
                    "languagetool",
                )
            )
        return issues

    def close(self):
        with self.lock:
            if self.tool is not None:
                try:
                    self.tool.close()
                except Exception:
                    pass
                self.tool = None


class GrammarEngine:
    def __init__(self):
        self.lt = LTBackend()
        self.use_lt = True
        self.lt_started = False

    def ensure_lt(self):
        """Запустить LanguageTool (если есть Java). Блокирующий — вызывать из потока."""
        if not self.lt_started and self.use_lt and self.lt.java_available():
            self.lt_started = self.lt.start()
        return self.lt_started

    def check(self, text, use_lt=True):
        """Все проверки: правила + LanguageTool (если запущен)."""
        issues = check_rules(text)
        if use_lt and self.use_lt and self.lt_started and self.lt.tool is not None:
            try:
                issues += self.lt.check(text)
            except Exception as e:
                print(f"[grammar] LanguageTool: {e}")
        issues.sort(key=lambda i: (i.start, i.end))
        return issues

    def close(self):
        self.lt.close()
