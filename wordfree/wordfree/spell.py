"""Движок проверки орфографии: hunspell-словари (spylls) с откатом на pyspellchecker.

Основа: полные словари ru_RU и en_US (LibreOffice dictionaries, лицензия см. README).
spylls — чистый Python, полностью работает офлайн и включается в .exe.
"""
import json
import os
import re
import threading

from . import resources

# слово: русские/английские буквы, возможны дефис/апостроф внутри
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:['’\-][A-Za-zА-Яа-яЁё]+)*")
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def word_language(word):
    return "ru" if CYRILLIC_RE.search(word) else "en"


def _hunspell_base(lang):
    """Путь-основа hunspell-словаря в комплекте или в пользовательской папке."""
    candidates = [
        os.path.join(resources.dicts_dir(), "hunspell", f"{'ru_RU' if lang=='ru' else 'en_US'}"),
        os.path.join(resources.user_dir(), "dictionaries", f"{'ru_RU' if lang=='ru' else 'en_US'}"),
    ]
    for base in candidates:
        if os.path.exists(base + ".aff") and os.path.exists(base + ".dic"):
            return base
    return None


class SpellEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._hun = {}          # lang -> spylls Dictionary
        self._fallback = {}     # lang -> pyspellchecker.SpellChecker
        self.user_dict_path = os.path.join(resources.user_dir(), "userdict.json")
        self._user_words = set()
        self._load_user_dict()
        self._load_checkers()

    # ------------------------------------------------ загрузка словарей
    def _load_checkers(self):
        hun_ok = False
        try:
            from spylls.hunspell import Dictionary
        except ImportError:
            Dictionary = None
        for lang in ("ru", "en"):
            if Dictionary is not None:
                base = _hunspell_base(lang)
                if base:
                    try:
                        self._hun[lang] = Dictionary.from_files(base)
                        hun_ok = True
                        continue
                    except Exception as e:  # pragma: no cover
                        print(f"[spell] hunspell {lang}: {e}")
            # fallback: pyspellchecker (крошечный словарь, при необходимости скачается)
            try:
                path = os.path.join(resources.dicts_dir(), f"{lang}.json.gz")
                from spellchecker import SpellChecker

                if os.path.exists(path):
                    self._fallback[lang] = SpellChecker(
                        language=None, local_dictionary=path)
                else:
                    self._fallback[lang] = SpellChecker(language=lang)
            except Exception as e:  # pragma: no cover
                print(f"[spell] словарь {lang}: {e}")
        self.engine_name = "hunspell" if hun_ok else "pyspellchecker"

    def _load_user_dict(self):
        try:
            with open(self.user_dict_path, "r", encoding="utf-8") as f:
                self._user_words = set(json.load(f))
        except Exception:
            # первый запуск: засеять словами, встречающимися в подсказках программы
            self._user_words = {"wordfree", "ctrl", "f7", "pdf", "docx"}
            self._save_user_dict()

    def _save_user_dict(self):
        try:
            with open(self.user_dict_path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._user_words), f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ------------------------------------------------ проверка
    def has_language(self, lang):
        return lang in self._hun or lang in self._fallback

    def _hun_lookup(self, lang, word):
        d = self._hun.get(lang)
        if d is None:
            return None
        try:
            return d.lookup(word)
        except Exception:
            return None

    def is_correct(self, word):
        if len(word) < 2:
            return True
        w = word.lower()
        if w in self._user_words:
            return True
        lang = word_language(word)
        if lang in self._hun:
            entry = self._hun_lookup(lang, word)
            if entry:
                return True
            # попытка в нижнем регистре (spylls/hunspell сам обрабатывает регистр,
            # но на всякий случай)
            if word != w and self._hun_lookup(lang, w):
                return True
            return False
        checker = self._fallback.get(lang)
        if checker is None:
            return True
        with self._lock:
            return w in checker

    def candidates(self, word, limit=8):
        lang = word_language(word)
        out = []
        if lang in self._hun:
            d = self._hun[lang]
            try:
                for c in d.suggest(word):
                    if c and c.lower() != word.lower():
                        if word[:1].isupper():
                            c = c[:1].upper() + c[1:]
                        if c not in out:
                            out.append(c)
                    if len(out) >= limit:
                        break
            except Exception:
                pass
        if not out and lang in self._fallback:
            checker = self._fallback[lang]
            with self._lock:
                cands = checker.candidates(word.lower())
            for c in sorted(cands)[: limit * 2]:
                if c.lower() == word.lower():
                    continue
                if word[:1].isupper():
                    c = c[:1].upper() + c[1:]
                if c not in out:
                    out.append(c)
                if len(out) >= limit:
                    break
        return out

    # ------------------------------------------------ словарь пользователя
    def add_user_word(self, word):
        w = word.lower()
        if w and w not in self._user_words:
            self._user_words.add(w)
            self._save_user_dict()

    def remove_user_word(self, word):
        w = word.lower()
        if w in self._user_words:
            self._user_words.discard(w)
            self._save_user_dict()

    def user_words(self):
        return sorted(self._user_words)

    # ------------------------------------------------ поиск ошибок
    def find_errors(self, text):
        """Вернуть список (start, end, word) для ошибочных слов в тексте."""
        errors = []
        for m in WORD_RE.finditer(text):
            word = m.group(0)
            if not self.is_correct(word):
                errors.append((m.start(), m.end(), word))
        return errors
