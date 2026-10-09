"""Ядро редактора: текстовый виджет, форматирование, отмена/повтор,
проверка орфографии и грамматики, таблицы и картинки."""
import bisect
import queue
import re
import threading
import time
import tkinter as tk

from . import docwalk
from .grammar import GrammarEngine
from .spell import WORD_RE, SpellEngine

CHAR_TAG_EXACT = ("b", "i", "u", "s")
CHAR_TAG_PREFIXES = ("font_", "size_", "color_", "hl_")
ALL_CHAR_TAGS = CHAR_TAG_EXACT + CHAR_TAG_PREFIXES
PARA_TAGS = (
    "al_left", "al_center", "al_right", "al_justify",
    "style_h1", "style_h2", "style_h3", "list_bullet", "list_number", "pb",
)
TAG_TO_KEY = {"b": "bold", "i": "italic", "u": "underline", "s": "strike"}
KEY_TO_TAG = {v: k for k, v in TAG_TO_KEY.items()}
SAFE_KEYSYMS = {
    "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Meta_L", "Meta_R", "Escape", "Caps_Lock", "ISO_Left_Tab",
    "F1", "F2", "F3", "F4", "F6", "F8", "F9", "F10", "F11", "F12",
    "Insert", "Num_Lock", "Scroll_Lock", "Pause", "Print", "Menu",
    "KP_Up", "KP_Down", "KP_Left", "KP_Right", "KP_Home", "KP_End",
    "KP_Page_Up", "KP_Page_Down", "KP_Begin",
}
RE_NUMBER_PREFIX = re.compile(r"^\s*\d+[.)]\s*")
RE_BULLET_PREFIX = re.compile(r"^\s*[•●▪–]\s*")


def offset_to_index(line_starts, off):
    li = bisect.bisect_right(line_starts, off) - 1
    if li < 0:
        return None
    return f"{li + 1}.{off - line_starts[li]}"


def line_starts_of(content):
    starts = [0]
    pos = content.find("\n")
    while pos != -1:
        starts.append(pos + 1)
        pos = content.find("\n", pos + 1)
    return starts


# ============================ Отмена/повтор ============================
class UndoStack:
    """Снимки состояния документа (текст + теги + содержимое таблиц) перед изменением."""

    def __init__(self, editor, max_depth=150):
        self.editor = editor
        self.text = editor.text
        self.past = []
        self.future = []
        self.max_depth = max_depth
        self.suppress = False
        self._last_time = 0.0
        self._last_kind = None
        self._last_end = None

    def snapshot(self):
        t = self.text
        content = t.get("1.0", "end-1c")
        tags = []
        for name in t.tag_names():
            if name in ("sel", "find_cur", "find_hit") or name.startswith("err_"):
                continue
            if (name in ALL_CHAR_TAGS or name in PARA_TAGS or name == "objhide"
                    or name.startswith(("font_", "color_", "hl_", "ind_", "sp_",
                                        "size_", "img_", "tbl_"))):
                ranges = t.tag_ranges(name)
                for i in range(0, len(ranges), 2):
                    tags.append((name, str(ranges[i]), str(ranges[i + 1])))
        cells = self.editor.table_snapshot()
        return (content, tags, cells)

    def restore(self, snap):
        t = self.text
        content, tags, cells = snap
        self.suppress = True
        try:
            cur = t.get("1.0", "end-1c")
            if cur != content:
                # дифф: общий префикс и суффикс — не трогаем участки с таблицами
                p = 0
                m = min(len(cur), len(content))
                while p < m and cur[p] == content[p]:
                    p += 1
                s = 0
                max_s = m - p
                while s < max_s and cur[len(cur) - 1 - s] == content[len(content) - 1 - s]:
                    s += 1
                starts = line_starts_of(cur)
                idx_a = offset_to_index(starts, p) or "1.0"
                idx_b = offset_to_index(starts, len(cur) - s) or "end-1c"
                ins = content[p:len(content) - s]
                if t.compare(idx_a, "<", idx_b):
                    t.delete(idx_a, idx_b)
                if ins:
                    t.insert(idx_a, ins)
            # снять форматные теги и наложить снимка
            for name in list(t.tag_names()):
                if (name in ALL_CHAR_TAGS or name in PARA_TAGS
                        or name.startswith(("font_", "size_", "color_", "hl_", "ind_", "sp_"))):
                    t.tag_remove(name, "1.0", "end")
                elif name.startswith(("err_", "find_")):
                    t.tag_remove(name, "1.0", "end")
            for name, a, b in tags:
                try:
                    t.tag_add(name, a, b)
                except tk.TclError:
                    pass
            self.editor.rebuild_tables(cells)
            self.editor.rebuild_images()
        finally:
            self.suppress = False

    def begin(self, kind, pos=None):
        if self.suppress:
            return
        now = time.time()
        coalesce = (
            kind == self._last_kind
            and kind in ("insert", "delete")
            and pos is not None
            and self._last_end == pos
            and (now - self._last_time) < 0.8
        )
        if coalesce:
            self._last_time = now
            return
        snap = self.snapshot()
        self.past.append(snap)
        if len(self.past) > self.max_depth:
            self.past.pop(0)
        self.future.clear()
        self._last_kind = kind
        self._last_time = now
        self._last_end = None

    def note_end(self, pos):
        self._last_end = pos

    def undo(self):
        if self.suppress or not self.past:
            return False
        self.suppress = True
        try:
            self.future.append(self.snapshot())
        finally:
            self.suppress = False
        self.restore(self.past.pop())
        self._last_kind = None
        return True

    def redo(self):
        if self.suppress or not self.future:
            return False
        self.suppress = True
        try:
            self.past.append(self.snapshot())
        finally:
            self.suppress = False
        self.restore(self.future.pop())
        self._last_kind = None
        return True

    def clear(self):
        self.past.clear()
        self.future.clear()
        self._last_kind = None
        self._last_end = None


# ============================ Редактор ============================
class Editor:
    def __init__(self, app, master):
        self.app = app
        self.frame = tk.Frame(master, bg="#7f8c99")
        self.frame.pack(fill="both", expand=True)

        self.vsb = tk.Scrollbar(self.frame, orient="vertical")
        self.hsb = tk.Scrollbar(self.frame, orient="horizontal")
        self.text = tk.Text(
            self.frame,
            wrap="word",
            undo=False,
            font=("Arial", 11),
            padx=64,
            pady=24,
            spacing1=2,
            spacing3=2,
            bg="white",
            fg="black",
            insertwidth=2,
            insertbackground="black",
            selectbackground="#3399ff",
            selectforeground="white",
            highlightthickness=0,
            relief="flat",
            xscrollcommand=self.hsb.set,
            yscrollcommand=self.vsb.set,
        )
        self.vsb.config(command=self.text.yview)
        self.hsb.config(command=self.text.xview)
        self.vsb.pack(side="right", fill="y")
        self.hsb.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)

        self.undo_stack = UndoStack(self)
        self.spell = SpellEngine()
        self.grammar = GrammarEngine()

        self.dirty = False
        self.ignored_words = set()
        self.ignored_grammar = set()
        self.pending_fmt = {}
        self._pending_key = None
        self._check_seq = 0
        self._check_running = False
        self._check_again = False
        self._check_after_id = None
        self._check_queue = queue.Queue()
        self._state_after_id = None
        self._table_seq = 0
        self._img_seq = 0
        self.images = {}
        self.tables = {}

        self._setup_tags()
        self._bind_keys()
        self._insert_default_content()
        self.text.after(120, self._poll_checks)

    # ------------------------------------------------ теги
    def _setup_tags(self):
        t = self.text
        t.tag_configure("al_center", justify="center")
        t.tag_configure("al_right", justify="right")
        # al_justify: Tk не умеет «по ширине» визуально — тег хранится для docx/pdf
        t.tag_configure("al_left", justify="left")
        t.tag_configure("style_h1", font=("Arial", 20, "bold"),
                        foreground="#2F5496", spacing1=6, spacing3=6)
        t.tag_configure("style_h2", font=("Arial", 16, "bold"),
                        foreground="#2F5496", spacing1=4, spacing3=4)
        t.tag_configure("style_h3", font=("Arial", 13, "bold"),
                        foreground="#1F4E79", spacing1=3, spacing3=3)
        t.tag_configure("list_bullet", lmargin1=24, lmargin2=44)
        t.tag_configure("list_number", lmargin1=24, lmargin2=44)
        t.tag_configure("err_spell", underline=True, underlinefg="#d92b2b")
        t.tag_configure("err_grammar", underline=True, underlinefg="#1f6fd0")
        t.tag_configure("err_grammar_lt", underline=True, underlinefg="#0f9d58")
        # скрыть служебный символ объекта (￼) — окно/картинка размещаются на \n
        t.tag_configure("objhide", elide=True)
        t.tag_configure("find_hit", background="#fff2a8")
        t.tag_configure("find_cur", background="#ffb347")
        for tg in ("err_spell", "err_grammar", "err_grammar_lt"):
            t.tag_lower(tg, "sel")
        t.tag_raise("find_cur", "find_hit")

    def _insert_default_content(self):
        t = self.text
        self.undo_stack.suppress = True
        try:
            t.insert("1.0", "Добро пожаловать в WordFree!\n")
            t.tag_add("style_h1", "1.0", "1.end+1c")
            t.insert("end", "Это бесплатный текстовый редактор с проверкой орфографии и грамматики.\n")
            t.insert("end", "Горячие клавиши: Ctrl+B — жирный, Ctrl+I — курсив, Ctrl+U — подчёркнутый,\n")
            t.insert("end", "Ctrl+F — найти, F7 — проверка орфографии и грамматики, Ctrl+S — сохранить.\n\n")
            t.insert("end", "Начните печатать…")
            t.tag_add("i", "end-14c", "end-1c")
        finally:
            self.undo_stack.suppress = False
            t.edit_modified(False)
            self.dirty = False
            self.undo_stack.clear()

    def _lr(self, ln):
        """Диапазон абзаца: включает символ новой строки (иначе пустые строки не тегируются)."""
        return (f"{ln}.0", f"{ln}.end+1c")

    # ------------------------------------------------ клавиатура
    def _bind_keys(self):
        t = self.text
        t.bind("<Key>", self._on_key, add="+")
        t.bind("<Return>", self._on_return, add="+")
        t.bind("<Button-1>", self._on_click, add="+")
        t.bind("<<Modified>>", self._on_modified, add="+")
        t.bind("<<Selection>>", self._schedule_state_refresh, add="+")
        t.bind("<Button-3>", self._on_context, add="+")
        t.bind("<Control-z>", lambda e: (self.undo(), "break")[1], add="+")
        t.bind("<Control-y>", lambda e: (self.redo(), "break")[1], add="+")
        t.bind("<Control-Z>", lambda e: (self.undo(), "break")[1], add="+")
        t.bind("<Control-v>", lambda e: (self.paste(), "break")[1], add="+")
        t.bind("<Control-x>", lambda e: (self.cut(), "break")[1], add="+")
        t.bind("<Control-BackSpace>",
               lambda e: (self.delete_word_backward(), "break")[1], add="+")
        t.bind("<Button-4>", lambda e: self.text.yview_scroll(-3, "units"))
        t.bind("<Button-5>", lambda e: self.text.yview_scroll(3, "units"))
        t.bind("<Configure>", self._on_text_configure, add="+")

    def _on_key(self, event):
        if event.keysym in SAFE_KEYSYMS:
            self._sync_pending_from_caret()
            self._schedule_state_refresh()
            return None
        t = self.text
        pos = t.index("insert")
        printable = (
            not (event.state & 0x4)
            and not (event.state & 0x8)
            and len(event.char or "") == 1
            and (ord(event.char) >= 32 or event.char == "\t")
        )
        if printable:
            self.undo_stack.begin("insert", pos)
            self._pending_key = ("insert", pos)
        elif event.keysym in ("BackSpace", "Delete"):
            self.undo_stack.begin("delete", pos)
            self._pending_key = ("delete", pos)
        elif event.state & 0x4 and event.keysym.lower() in ("v", "x"):
            self.undo_stack.begin("edit", pos)
            self._pending_key = ("edit", pos)
        return None

    def delete_selection(self):
        t = self.text
        if not t.tag_ranges("sel"):
            return
        self.undo_stack.begin("edit", t.index("sel.first"))
        self._pending_key = None
        t.delete("sel.first", "sel.last")
        self.dirty = True
        self.app.update_title()
        self._schedule_check()
        self.undo_stack.note_end(t.index("insert"))

    def insert_plain(self, s):
        self.undo_stack.begin("insert", self.text.index("insert"))
        self._pending_key = None
        self.text.insert("insert", s)
        self.dirty = True
        self.app.update_title()
        self._schedule_check()

    def _on_modified(self, event=None):
        t = self.text
        if not t.edit_modified():
            return
        t.edit_modified(False)
        self.dirty = True
        self.app.update_title()

        pend = self._pending_key
        self._pending_key = None
        if pend and pend[0] == "insert":
            kind, pos = pend
            try:
                cur = t.index("insert")
                lo, hi = sorted([pos, cur], key=lambda ix: t.index(ix))
                if t.compare(lo, "<", hi):
                    if not self.pending_fmt:
                        # наследовать символный формат от предыдущего символа
                        if t.compare(lo, ">", "1.0"):
                            prev_tags = t.tag_names(f"{lo}-1c")
                            for name in prev_tags:
                                if name in ALL_CHAR_TAGS or name.startswith(
                                    ("font_", "size_", "color_", "hl_")
                                ):
                                    t.tag_add(name, lo, hi)
                    else:
                        # явный формат будущего ввода
                        for key, on in self.pending_fmt.items():
                            tag = self._fmt_tag(key, on)
                            if not tag:
                                continue
                            if on:
                                t.tag_add(tag, lo, hi)
                            else:
                                t.tag_remove(tag, lo, hi)
                self.undo_stack.note_end(cur)
            except tk.TclError:
                pass
        elif pend and pend[0] == "delete":
            if self._has_number_list():
                self.renumber_lists()
            self.undo_stack.note_end(t.index("insert"))

        self._schedule_check()
        self._schedule_state_refresh()

    @staticmethod
    def _fmt_tag(key, value):
        if key in KEY_TO_TAG:
            return KEY_TO_TAG[key]
        if key == "font" and value:
            return "font_" + str(value).replace(" ", "_")
        if key == "size" and value:
            return f"size_{int(value)}"
        if key == "color" and value:
            return "color_" + str(value).lstrip("#").lower()
        if key == "highlight" and value:
            return "hl_" + str(value).lstrip("#").lower()
        return None

    def _on_click(self, event=None):
        self.text.after(1, self._after_click)

    def _after_click(self):
        self._sync_pending_from_caret()
        self.app.refresh_format_state()

    def _schedule_state_refresh(self, event=None):
        if self._state_after_id:
            try:
                self.text.after_cancel(self._state_after_id)
            except Exception:
                pass
        self._state_after_id = self.text.after(80, self._sync_state_from_caret)

    def _sync_state_from_caret(self):
        self._state_after_id = None
        self.app.refresh_format_state()

    def _sync_pending_from_caret(self):
        """При перемещении курсора — синхронизировать «формат будущего ввода»."""
        if self.text.tag_ranges("sel"):
            return
        pos = self.text.index("insert")
        fmt = {}
        for name in self.text.tag_names(pos):
            if name in TAG_TO_KEY:
                fmt[TAG_TO_KEY[name]] = True
            elif name.startswith("font_"):
                fmt["font"] = name[5:].replace("_", " ")
            elif name.startswith("size_"):
                try:
                    fmt["size"] = int(name[5:])
                except ValueError:
                    pass
            elif name.startswith("color_"):
                fmt["color"] = "#" + name[6:]
            elif name.startswith("hl_"):
                fmt["highlight"] = "#" + name[3:]
        self.pending_fmt = fmt

    # ------------------------------------------------ символное форматирование
    def selection_fmt(self):
        t = self.text
        if not t.tag_ranges("sel"):
            return dict(self.pending_fmt)
        s, e = t.index("sel.first"), t.index("sel.last")
        fmt = {}
        for name in t.tag_names(s):
            if name in TAG_TO_KEY and self._tag_covers(name, s, e):
                fmt[TAG_TO_KEY[name]] = True
            elif name.startswith("font_") and self._tag_covers(name, s, e):
                fmt["font"] = name[5:].replace("_", " ")
            elif name.startswith("size_") and self._tag_covers(name, s, e):
                try:
                    fmt["size"] = int(name[5:])
                except ValueError:
                    pass
            elif name.startswith("color_") and self._tag_covers(name, s, e):
                fmt["color"] = "#" + name[6:]
            elif name.startswith("hl_") and self._tag_covers(name, s, e):
                fmt["highlight"] = "#" + name[3:]
        return fmt

    def _tag_covers(self, tag, s, e):
        ranges = self.text.tag_ranges(tag)
        for i in range(0, len(ranges), 2):
            if (self.text.compare(str(ranges[i]), "<=", s)
                    and self.text.compare(str(ranges[i + 1]), ">=", e)):
                return True
        return False

    def toggle_char(self, key):
        t = self.text
        tag = KEY_TO_TAG[key]
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            self.undo_stack.begin("edit", s)
            on = not self._tag_covers(tag, s, e)
            if on:
                t.tag_add(tag, s, e)
            else:
                t.tag_remove(tag, s, e)
            self.pending_fmt[key] = on
            self.dirty = True
            self.app.update_title()
        else:
            self.pending_fmt[key] = not self.pending_fmt.get(key, False)
        self._schedule_check()
        self.app.refresh_format_state()

    def apply_char(self, key, value):
        t = self.text
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            self.undo_stack.begin("edit", s)
            tag = KEY_TO_TAG[key]
            if value:
                t.tag_add(tag, s, e)
            else:
                t.tag_remove(tag, s, e)
            self.dirty = True
            self.app.update_title()
        else:
            self.pending_fmt[key] = value
        self.app.refresh_format_state()

    def set_font_family(self, family):
        tag = "font_" + family.replace(" ", "_")
        t = self.text
        size = self.pending_fmt.get("size")
        try:
            t.tag_configure(tag, font=(family, size or 11))
        except tk.TclError:
            pass
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            self.undo_stack.begin("edit", s)
            for name in list(t.tag_names()):
                if name.startswith("font_"):
                    t.tag_remove(name, s, e)
            t.tag_add(tag, s, e)
            self.dirty = True
            self.app.update_title()
        else:
            self.pending_fmt["font"] = family
        self.app.refresh_format_state()

    def set_font_size(self, size):
        size = int(size)
        tag = f"size_{size}"
        t = self.text
        family = "Arial"
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            for name in t.tag_names(s):
                if name.startswith("font_") and self._tag_covers(name, s, e):
                    family = name[5:].replace("_", " ")
        else:
            family = self.pending_fmt.get("font", "Arial")
        try:
            t.tag_configure(tag, font=(family, size))
        except tk.TclError:
            pass
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            self.undo_stack.begin("edit", s)
            for name in list(t.tag_names()):
                if name.startswith("size_"):
                    t.tag_remove(name, s, e)
            t.tag_add(tag, s, e)
            self.dirty = True
            self.app.update_title()
        else:
            self.pending_fmt["size"] = size
        self.app.refresh_format_state()

    def set_font_color(self, color):
        tag = "color_" + color.lstrip("#").lower()
        t = self.text
        t.tag_configure(tag, foreground=color)
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            self.undo_stack.begin("edit", s)
            for name in list(t.tag_names()):
                if name.startswith("color_"):
                    t.tag_remove(name, s, e)
            t.tag_add(tag, s, e)
            self.dirty = True
            self.app.update_title()
        else:
            self.pending_fmt["color"] = color
        self.app.refresh_format_state()

    def set_highlight(self, color):
        t = self.text
        if color is None:
            if t.tag_ranges("sel"):
                s, e = t.index("sel.first"), t.index("sel.last")
                self.undo_stack.begin("edit", s)
                for name in list(t.tag_names()):
                    if name.startswith("hl_"):
                        t.tag_remove(name, s, e)
                self.dirty = True
                self.app.update_title()
            self.pending_fmt.pop("highlight", None)
            self.app.refresh_format_state()
            return
        tag = "hl_" + color.lstrip("#").lower()
        t.tag_configure(tag, background=color)
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            self.undo_stack.begin("edit", s)
            for name in list(t.tag_names()):
                if name.startswith("hl_"):
                    t.tag_remove(name, s, e)
            t.tag_add(tag, s, e)
            self.dirty = True
            self.app.update_title()
        else:
            self.pending_fmt["highlight"] = color
        self.app.refresh_format_state()

    def grow_font(self, step=1):
        sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]
        cur = self.selection_fmt().get("size") or 11
        idx = min(range(len(sizes)), key=lambda i: abs(sizes[i] - cur))
        idx = max(0, min(len(sizes) - 1, idx + step))
        self.set_font_size(sizes[idx])

    # ------------------------------------------------ абзацное форматирование
    def _sel_line_range(self):
        t = self.text
        if t.tag_ranges("sel"):
            s, e = t.index("sel.first"), t.index("sel.last")
            l1 = int(s.split(".")[0])
            l2 = int(e.split(".")[0])
            if e.endswith(".0") and l2 > l1:
                l2 -= 1
            return l1, l2
        l = int(t.index("insert").split(".")[0])
        return l, l

    def set_align(self, align):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            for al in ("al_left", "al_center", "al_right", "al_justify"):
                t.tag_remove(al, a, b)
            t.tag_add(f"al_{align}", a, b)
        self.dirty = True
        self.app.update_title()
        self.app.refresh_format_state()

    def set_style(self, style):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            for st in ("style_h1", "style_h2", "style_h3"):
                t.tag_remove(st, a, b)
            if style != "normal":
                t.tag_add(f"style_{style}", a, b)
        self.dirty = True
        self.app.update_title()
        self.app.refresh_format_state()

    def set_para_tag(self, tag, on):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            if on:
                t.tag_add(tag, a, b)
            else:
                t.tag_remove(tag, a, b)
        self.dirty = True
        self.app.update_title()

    def current_para_info(self):
        """pfmt текущего абзаца — для панелей."""
        t = self.text
        l = int(t.index("insert").split(".")[0])
        names = t.tag_names(f"{l}.0")
        pfmt = {"align": "left", "style": "normal", "list": None}
        for n in names:
            if n in ("al_left", "al_center", "al_right", "al_justify"):
                pfmt["align"] = n[3:]
            elif n in ("style_h1", "style_h2", "style_h3"):
                pfmt["style"] = n[6:]
            elif n == "list_bullet":
                pfmt["list"] = "bullet"
            elif n == "list_number":
                pfmt["list"] = "number"
        return pfmt

    def toggle_list(self, kind):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        tag = "list_bullet" if kind == "bullet" else "list_number"
        other = "list_number" if kind == "bullet" else "list_bullet"
        any_on = any(tag in t.tag_names(f"{ln}.0") for ln in range(l1, l2 + 1))
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            line_end = f"{ln}.end"
            t.tag_remove(other, a, b)
            if any_on:
                t.tag_remove(tag, a, b)
                txt = t.get(f"{ln}.0", line_end)
                m = RE_BULLET_PREFIX.match(txt) or RE_NUMBER_PREFIX.match(txt)
                if m and m.end() > 0:
                    t.delete(f"{ln}.0", f"{ln}.{m.end()}")
            else:
                # сначала префикс, потом теги — иначе символы окажутся вне диапазона
                txt = t.get(f"{ln}.0", line_end)
                if kind == "bullet" and not RE_BULLET_PREFIX.match(txt):
                    t.insert(f"{ln}.0", "• ")
                elif kind == "number" and not RE_NUMBER_PREFIX.match(txt):
                    t.insert(f"{ln}.0", "1. ")
                t.tag_add(tag, a, b)
        if kind == "number" and not any_on:
            self.renumber_lists()
        self.dirty = True
        self.app.update_title()
        self.app.refresh_format_state()

    def _has_number_list(self):
        return bool(self.text.tag_ranges("list_number"))

    def renumber_lists(self):
        t = self.text
        last_line = int(t.index("end-1c").split(".")[0])
        counter = 0
        in_group = False
        for ln in range(1, last_line + 1):
            if "list_number" in t.tag_names(f"{ln}.0"):
                if not in_group:
                    counter = 0
                    in_group = True
                counter += 1
                txt = t.get(f"{ln}.0", f"{ln}.end")
                m = RE_NUMBER_PREFIX.match(txt)
                if m:
                    if m.group(0) != f"{counter}. ":
                        t.delete(f"{ln}.0", f"{ln}.{m.end()}")
                        t.insert(f"{ln}.0", f"{counter}. ")
                else:
                    t.insert(f"{ln}.0", f"{counter}. ")
            else:
                in_group = False

    def set_indent(self, kind, px):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            for name in list(t.tag_names(a)):
                if name.startswith(f"ind_{kind}_"):
                    t.tag_remove(name, a, b)
            if px > 0:
                tag = f"ind_{kind}_{int(px)}"
                if kind == "left":
                    t.tag_configure(tag, lmargin1=int(px), lmargin2=int(px) + 20)
                t.tag_add(tag, a, b)
        self.dirty = True
        self.app.update_title()

    def set_line_spacing(self, value):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            for name in list(t.tag_names(a)):
                if name.startswith("sp_line_"):
                    t.tag_remove(name, a, b)
            if value:
                tag = f"sp_line_{value}"
                t.tag_configure(tag, spacing1=1, spacing2=max(0, int(11 * (float(value) - 1) * 1.6)))
                t.tag_add(tag, a, b)
        self.dirty = True
        self.app.update_title()

    def set_space_after(self, pt):
        l1, l2 = self._sel_line_range()
        t = self.text
        self.undo_stack.begin("edit", f"{l1}.0")
        for ln in range(l1, l2 + 1):
            a, b = self._lr(ln)
            for name in list(t.tag_names(a)):
                if name.startswith("sp_after_"):
                    t.tag_remove(name, a, b)
            tag = f"sp_after_{int(pt)}"
            t.tag_configure(tag, spacing3=int(pt * 4 / 3))
            t.tag_add(tag, a, b)
        self.dirty = True
        self.app.update_title()

    def set_para_props(self, pfmt):
        if pfmt.get("align"):
            self.set_align(pfmt["align"])
        if "style" in pfmt:
            self.set_style(pfmt["style"])
        if "indent_left" in pfmt:
            self.set_indent("left", pfmt["indent_left"])
        if "line_spacing" in pfmt:
            self.set_line_spacing(pfmt["line_spacing"])
        if "space_after" in pfmt:
            self.set_space_after(pfmt["space_after"])

    # ------------------------------------------------ Enter
    def _handle_return(self):
        t = self.text
        pos = t.index("insert")
        self.undo_stack.begin("insert", pos)
        l = int(pos.split(".")[0])
        line_tags = t.tag_names(f"{l}.0")
        in_list = "list_bullet" in line_tags or "list_number" in line_tags
        is_heading = any(s in line_tags for s in ("style_h1", "style_h2", "style_h3"))
        line_text = t.get(f"{l}.0", f"{l}.end")

        if in_list:
            m = RE_BULLET_PREFIX.match(line_text) or RE_NUMBER_PREFIX.match(line_text)
            content_wo = line_text[m.end():] if m else line_text
            if content_wo.strip() == "":
                if m:
                    t.delete(f"{l}.0", f"{l}.{m.end()}")
                a, b = self._lr(l)
                t.tag_remove("list_bullet", a, b)
                t.tag_remove("list_number", a, b)
                self.undo_stack.note_end(t.index("insert"))
                self.dirty = True
                return "break"

        para_tags = [
            n for n in line_tags
            if (n in PARA_TAGS or n.startswith(("ind_", "sp_line_", "sp_after_")))
        ]
        if is_heading:
            para_tags = [n for n in para_tags
                         if not n.startswith("style_") and n not in ("list_bullet", "list_number")]

        t.insert(pos, "\n")
        new_line = int(t.index("insert").split(".")[0])
        a, b = self._lr(new_line)
        for tag in para_tags:
            t.tag_add(tag, a, b)
        if in_list:
            if "list_number" in line_tags:
                cnt, prev = 1, l - 1
                while prev >= 1 and "list_number" in t.tag_names(f"{prev}.0"):
                    cnt += 1
                    prev -= 1
                t.insert(f"{new_line}.0", f"{cnt}. ")
                na, nb = self._lr(new_line)
                t.tag_add("list_number", na, nb)
                self.renumber_lists()
            else:
                t.insert(f"{new_line}.0", "• ")
                na, nb = self._lr(new_line)
                t.tag_add("list_bullet", na, nb)
        # формат для нового текста — обычный
        self.dirty = True
        self.app.update_title()
        self._schedule_check()
        self._schedule_state_refresh()
        return "break"

    def _on_return(self, event):
        if event.state & 0x4:  # Ctrl+Enter — разрыв страницы
            self.insert_page_break()
            return "break"
        if event.state & 0x1:  # Shift+Enter — мягкий перенос строки
            self.undo_stack.begin("insert", self.text.index("insert"))
            self._pending_key = None
            self.text.insert("insert", "\n")
            self.dirty = True
            self.app.update_title()
            self._schedule_check()
            return "break"
        return self._handle_return()

    def delete_word_backward(self):
        t = self.text
        pos = t.index("insert")
        self.undo_stack.begin("delete", pos)
        s = t.search(r"\S+\s*$", t.index("insert -1c"), stopindex="1.0",
                     backwards=True, regexp=True)
        if not s:
            s = "1.0"
        t.delete(s, "insert")
        self.dirty = True
        self.app.update_title()
        self._schedule_check()
        self.undo_stack.note_end(t.index("insert"))

    # ------------------------------------------------ буфер обмена
    def copy(self):
        if self.text.tag_ranges("sel"):
            self.text.event_generate("<<Copy>>")

    def cut(self):
        if not self.text.tag_ranges("sel"):
            return
        self.undo_stack.begin("edit", self.text.index("sel.first"))
        self.text.event_generate("<<Cut>>")
        self.dirty = True
        self.app.update_title()
        self._schedule_check()
        self.undo_stack.note_end(self.text.index("insert"))

    def paste(self):
        self.undo_stack.begin("edit", self.text.index("insert"))
        try:
            self.text.event_generate("<<Paste>>")
        except tk.TclError:
            pass
        self.dirty = True
        self.app.update_title()
        self._schedule_check()
        self.undo_stack.note_end(self.text.index("insert"))

    def select_all(self):
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")
        self.app.refresh_format_state()

    def insert_date(self):
        import datetime

        now = datetime.datetime.now()
        if self.app.settings.get("date_long", True):
            months = ["января", "февраля", "марта", "апреля", "мая", "июня",
                      "июля", "августа", "сентября", "октября", "ноября", "декабря"]
            s = f"{now.day} {months[now.month - 1]} {now.year} г."
        else:
            s = now.strftime("%d.%m.%Y")
        self.undo_stack.begin("insert", self.text.index("insert"))
        self._pending_key = None
        self.text.insert("insert", s)
        self.dirty = True
        self.app.update_title()
        self._schedule_check()

    def insert_page_break(self):
        t = self.text
        self.undo_stack.begin("insert", t.index("insert"))
        self._pending_key = None
        t.insert("insert", "\n")
        cur = t.index("insert")
        # pb на первый символ новой (возможно пустой) строки — её перевод строки
        try:
            t.tag_add("pb", cur, f"{cur}+1c")
        except tk.TclError:
            pass
        self.dirty = True
        self.app.update_title()

    # ------------------------------------------------ отмена/повтор
    def undo(self):
        if self.undo_stack.undo():
            self.dirty = True
            self.app.update_title()
            self._schedule_check()
            self.app.refresh_format_state()

    def redo(self):
        if self.undo_stack.redo():
            self.dirty = True
            self.app.update_title()
            self._schedule_check()
            self.app.refresh_format_state()

    # ------------------------------------------------ картинки
    def insert_image(self, path, width_in=None):
        from PIL import Image, ImageTk

        self._img_seq += 1
        name = f"img{self._img_seq}"
        im = Image.open(path)
        w_px, _h_px = im.size
        if width_in is None:
            width_in = min(max(w_px / 96.0, 0.5), 6.0)
        disp = im.copy()
        disp.thumbnail((640, 10000))
        photo = ImageTk.PhotoImage(disp)
        info = {"path": path, "width_in": width_in, "photo": photo,
                "label": None, "win": None}
        self.images[name] = info

        t = self.text
        self.undo_stack.begin("insert", t.index("insert"))
        self._pending_key = None
        idx = t.index("insert")
        col = int(idx.split(".")[1])
        if col > 0:
            t.insert(idx, "\n")
            idx = t.index("insert")
        line = int(idx.split(".")[0])
        t.insert(idx, "\ufffc")
        obj = f"{line}.0"
        t.insert(f"{obj}+1c", "\n")
        # картинка: окно-Label на позиции перевода строки, глиф скрыт (elide)
        label = tk.Label(t, image=photo, bg="white", bd=0)
        try:
            win = t.window_create(f"{line}.end", window=label, align="center")
            info["label"] = label
            info["win"] = win
        except tk.TclError:
            pass
        t.tag_add("img_" + name, obj, f"{obj}+1c")
        t.tag_add("objhide", obj, f"{obj}+1c")
        t.mark_set("insert", f"{line + 1}.0")
        self.dirty = True
        self.app.update_title()

    def rebuild_images(self):
        """Восстановить Label-окна картинок после отмены/повтора."""
        t = self.text
        for name, info in list(self.images.items()):
            tag = "img_" + name
            rng = t.tag_ranges(tag)
            alive = False
            try:
                alive = info.get("label") is not None and info["label"].winfo_exists()
            except tk.TclError:
                alive = False
            has_char = False
            if rng:
                has_char = "\ufffc" in t.get(str(rng[0]), str(rng[1]))
            if has_char:
                if not alive:
                    label = tk.Label(t, image=info["photo"], bg="white", bd=0)
                    line = str(rng[0]).split(".")[0]
                    try:
                        win = t.window_create(f"{line}.end", window=label,
                                              align="center")
                        info["label"] = label
                        info["win"] = win
                    except tk.TclError:
                        pass
            elif alive:
                try:
                    info["label"].destroy()
                except tk.TclError:
                    pass
                info["label"] = None
                info["win"] = None

    def delete_image_at_cursor(self):
        t = self.text
        pos = t.index("insert")
        for name in t.tag_names(pos):
            if name.startswith("img_"):
                rng = t.tag_ranges(name)
                if rng:
                    self.undo_stack.begin("delete", pos)
                    info = self.images.get(name[4:])
                    if info and info.get("label"):
                        try:
                            info["label"].destroy()
                        except tk.TclError:
                            pass
                        info["label"] = None
                        info["win"] = None
                    t.delete(str(rng[0]), str(rng[1]))
                    self.dirty = True
                    self.app.update_title()
                    return True
        return False

    # ------------------------------------------------ таблицы
    def _make_table_widget(self, parent, rows, cols, cell_texts=None):
        cells = []
        cw = self._cell_chars(cols)
        for i in range(rows):
            row = []
            for j in range(cols):
                e = tk.Entry(parent, relief="solid", bd=1, font=("Arial", 11),
                             bg="white", fg="black", width=cw)
                if cell_texts and i < len(cell_texts) and j < len(cell_texts[i]):
                    e.insert(0, cell_texts[i][j])
                e.grid(row=i, column=j, sticky="nsew", padx=1, pady=1)
                row.append(e)
            cells.append(row)
        for j in range(cols):
            parent.columnconfigure(j, weight=1, uniform="c")
        for i in range(rows):
            parent.rowconfigure(i, weight=1, minsize=24)
        return cells

    def insert_table(self, rows, cols, cell_texts=None):
        t = self.text
        self._table_seq += 1
        tid = self._table_seq
        self.undo_stack.begin("insert", t.index("insert"))
        self._pending_key = None

        # курсор должен стоять на отдельной строке
        col = int(t.index("insert").split(".")[1])
        if col > 0:
            t.insert("insert", "\n")
        tbl_line = int(t.index("insert").split(".")[0])
        t.insert("insert", "\ufffc")
        t.insert("insert", "\n")
        frame = tk.Frame(t, bg="white", bd=0, highlightthickness=1,
                         highlightbackground="#9aa7b5", width=self._table_width())
        cells = self._make_table_widget(frame, rows, cols, cell_texts)
        # окно — на позиции перевода строки, глиф ￼ скрыт через elide
        win = t.window_create(f"{tbl_line}.end", window=frame, align="center")
        # теги — строго ПОСЛЕ window_create (создание окна смещает старт диапазона)
        a, b = self._lr(tbl_line)
        t.tag_add(f"tbl_{tid}", a, b)
        t.tag_add("objhide", f"{tbl_line}.0", f"{tbl_line}.0+1c")
        self.tables[tid] = {
            "rows": rows, "cols": cols, "cells": cells,
            "frame": frame, "win": win, "saved": None,
        }
        self._bind_table(tid)
        frame.bind("<Configure>", lambda ev, f=frame, c=cols: self._resize_table(f, c))
        # курсор — после таблицы
        t.mark_set("insert", f"{tbl_line + 1}.0")
        self.dirty = True
        self.app.update_title()
        return tid

    def _table_width(self):
        """Желаемая ширина таблицы = ширина области текста."""
        try:
            padx = int(self.text.cget("padx") or 0)
            w = self.text.winfo_width() - 2 * padx - 12
            return max(260, w)
        except (tk.TclError, ValueError):
            return 500

    def _cell_chars(self, cols):
        """Ширина ячейки в символах, чтобы таблица растянулась на ширину текста."""
        return max(8, int((self._table_width() - 12) / (7.2 * max(cols, 1))))

    def _on_text_configure(self, event=None):
        for tid, tb in list(self.tables.items()):
            try:
                if tb["frame"].winfo_exists():
                    self._resize_table(tb["frame"], tb["cols"])
            except tk.TclError:
                pass

    def _bind_table(self, tid):
        tb = self.tables[tid]
        for i in range(tb["rows"]):
            for j in range(tb["cols"]):
                e = tb["cells"][i][j]
                e.bind("<Return>", lambda ev, a=(i, j), k=tid: self._cell_return(k, a))
                e.bind("<Tab>", lambda ev, a=(i, j), k=tid: self._cell_tab(k, a, False))
                e.bind("<Shift-Tab>", lambda ev, a=(i, j), k=tid: self._cell_tab(k, a, True))
                e.bind("<Key>", lambda ev: self._cell_editing(ev), add="+")

    def _cell_editing(self, event):
        if event.keysym in ("BackSpace", "Delete") or (
            not (event.state & 0x4)
            and len(event.char or "") == 1
            and ord(event.char) >= 32
        ):
            self.dirty = True
            self.app.update_title()
        return None

    def _cell_return(self, tid, ij):
        tb = self.tables.get(tid)
        if not tb:
            return None
        i, j = ij
        if i + 1 < tb["rows"]:
            tb["cells"][i + 1][j].focus_set()
        elif j + 1 < tb["cols"]:
            tb["cells"][0][j + 1].focus_set()
        return "break"

    def _cell_tab(self, tid, ij, back):
        tb = self.tables.get(tid)
        if not tb:
            return None
        i, j = ij
        if back:
            if j > 0:
                tb["cells"][i][j - 1].focus_set()
            elif i > 0:
                tb["cells"][i - 1][tb["cols"] - 1].focus_set()
        else:
            if j + 1 < tb["cols"]:
                tb["cells"][i][j + 1].focus_set()
            elif i + 1 < tb["rows"]:
                tb["cells"][i + 1][0].focus_set()
            else:
                tb["cells"][0][0].focus_set()
        return "break"

    def _resize_table(self, frame, cols):
        try:
            cw = self._cell_chars(cols)
            for child in frame.winfo_children():
                if isinstance(child, tk.Entry):
                    child.configure(width=cw)
        except tk.TclError:
            pass

    def table_snapshot(self):
        """Содержимое всех таблиц (для отмены)."""
        out = {}
        for tid, tb in self.tables.items():
            grid = []
            alive = True
            try:
                alive = tb["frame"].winfo_exists()
            except tk.TclError:
                alive = False
            if alive:
                for row in tb["cells"]:
                    try:
                        grid.append([e.get() for e in row])
                    except tk.TclError:
                        grid.append(["" for _ in row])
            else:
                grid = tb.get("saved") or [["" for _ in range(tb["cols"])] for _ in range(tb["rows"])]
            out[tid] = {"rows": tb["rows"], "cols": tb["cols"], "cells": grid}
        return out

    def rebuild_tables(self, cellsnap):
        """Восстановить рамки таблиц после отмены/повтора (Tk уничтожает frame
        при удалении символов). Учитывает id из снимка — запись могла уже выпасть."""
        t = self.text
        cellsnap = cellsnap or {}
        for tid in sorted(set(self.tables.keys()) | set(cellsnap.keys())):
            tb = self.tables.get(tid)
            alive = False
            if tb is not None:
                try:
                    alive = tb["frame"].winfo_exists()
                except tk.TclError:
                    alive = False
            rng = t.tag_ranges(f"tbl_{tid}")
            has_char = False
            if rng:
                has_char = "\ufffc" in t.get(str(rng[0]), str(rng[1]))
            if not rng or not has_char:
                if tb is not None:
                    if alive:
                        try:
                            tb["frame"].destroy()
                        except tk.TclError:
                            pass
                    self.tables.pop(tid, None)
                continue
            if not alive:
                data = cellsnap.get(tid)
                if data is None and tb is not None:
                    data = {"rows": tb["rows"], "cols": tb["cols"],
                            "cells": tb.get("saved")}
                if data is None:
                    continue
                frame = tk.Frame(t, bg="white", bd=0, highlightthickness=1,
                                 highlightbackground="#9aa7b5",
                                 width=self._table_width())
                cells = self._make_table_widget(frame, data["rows"], data["cols"],
                                                data.get("cells"))
                try:
                    line = str(rng[0]).split(".")[0]
                    win = t.window_create(f"{line}.end", window=frame,
                                          align="center")
                    # восстановить теги после встраивания (окно смещает старт диапазона)
                    rs, re_ = str(rng[0]), str(rng[1])
                    t.tag_remove(f"tbl_{tid}", "1.0", "end")
                    t.tag_add(f"tbl_{tid}", rs, re_)
                    t.tag_add("objhide", f"{line}.0", f"{line}.0+1c")
                except tk.TclError:
                    frame.destroy()
                    continue
                self.tables[tid] = {
                    "rows": data["rows"], "cols": data["cols"], "cells": cells,
                    "frame": frame, "win": win, "saved": data.get("cells"),
                }
                self._bind_table(tid)
                frame.bind("<Configure>",
                           lambda ev, f=frame, c=data["cols"]: self._resize_table(f, c))
            elif tb is not None:
                tb["saved"] = self.table_snapshot().get(tid, {}).get("cells")

    def table_at_cursor(self):
        t = self.text
        l = int(t.index("insert").split(".")[0])
        for name in t.tag_names(f"{l}.0"):
            if name.startswith("tbl_"):
                return int(name[4:])
        for name in t.tag_names(t.index("insert")):
            if name.startswith("tbl_"):
                return int(name[4:])
        return None

    def table_add_row(self, tid, above=False):
        tb = self.tables.get(tid)
        if not tb:
            return
        row = [tk.Entry(tb["frame"], relief="solid", bd=1, font=("Arial", 11))
               for _ in range(tb["cols"])]
        insert_at = 0 if above else tb["rows"]
        tb["cells"].insert(insert_at, row)
        tb["rows"] += 1
        for i, r in enumerate(tb["cells"]):
            for j, e in enumerate(r):
                e.grid(row=i, column=j, sticky="nsew", padx=1, pady=1)
        self._bind_table(tid)
        tb["frame"].rowconfigure(tb["rows"] - 1, weight=1, minsize=24)
        self.dirty = True
        self.app.update_title()

    def table_add_col(self, tid, left=False):
        tb = self.tables.get(tid)
        if not tb:
            return
        insert_at = 0 if left else tb["cols"]
        for row in tb["cells"]:
            row.insert(insert_at, tk.Entry(tb["frame"], relief="solid", bd=1,
                                           font=("Arial", 11)))
        tb["cols"] += 1
        for i, r in enumerate(tb["cells"]):
            for j, e in enumerate(r):
                e.grid(row=i, column=j, sticky="nsew", padx=1, pady=1)
        self._bind_table(tid)
        tb["frame"].columnconfigure(tb["cols"] - 1, weight=1, uniform="c")
        self.dirty = True
        self.app.update_title()

    def table_delete_row(self, tid):
        tb = self.tables.get(tid)
        if not tb:
            return
        if tb["rows"] <= 1:
            self.delete_table(tid)
            return
        for e in tb["cells"][-1]:
            e.grid_forget()
            e.destroy()
        tb["cells"].pop()
        tb["rows"] -= 1
        self._bind_table(tid)
        self.dirty = True
        self.app.update_title()

    def table_delete_col(self, tid):
        tb = self.tables.get(tid)
        if not tb:
            return
        if tb["cols"] <= 1:
            self.delete_table(tid)
            return
        for row in tb["cells"]:
            row[-1].grid_forget()
            row[-1].destroy()
            row.pop()
        tb["cols"] -= 1
        self._bind_table(tid)
        self.dirty = True
        self.app.update_title()

    def delete_table(self, tid):
        tb = self.tables.get(tid)
        if not tb:
            return
        t = self.text
        self.undo_stack.begin("delete", t.index("insert"))
        rng = t.tag_ranges(f"tbl_{tid}")
        if rng:
            # символ объекта — первый символ диапазона (позиция L.0)
            first = str(rng[0])
            if "\ufffc" in t.get(first, f"{first}+1c"):
                t.delete(first, f"{first}+1c")
        t.tag_remove(f"tbl_{tid}", "1.0", "end")
        try:
            tb["frame"].destroy()
        except tk.TclError:
            pass
        self.tables.pop(tid, None)
        self.dirty = True
        self.app.update_title()
        self._schedule_check()

    # --------------------------- проверка орфографии/грамматики
    def _schedule_check(self):
        if self._check_after_id:
            try:
                self.text.after_cancel(self._check_after_id)
            except Exception:
                pass
        self._check_after_id = self.text.after(650, self._start_check)

    def _start_check(self):
        self._check_after_id = None
        if self._check_running:
            self._check_again = True
            return
        t = self.text
        content = t.get("1.0", "end-1c")
        self._check_seq += 1
        seq = self._check_seq
        use_spell = self.app.settings.get("check_spelling", True)
        use_grammar = self.app.settings.get("check_grammar", True)
        lang = self.app.settings.get("language", "auto")
        self._check_running = True
        self._check_again = False

        def work():
            results = {}
            try:
                if use_spell:
                    errors = []
                    for s, e, w in self.spell.find_errors(content):
                        if w.lower() in self.ignored_words:
                            continue
                        has_cyr = any("а" <= c.lower() <= "я" or c in "ёЁ" for c in w)
                        if lang == "auto" or (lang == "ru") == has_cyr:
                            errors.append((s, e, w))
                    results["spell"] = errors
                if use_grammar:
                    issues = self.grammar.check(content)
                    # убрать дубли того, что уже помечено как орфография
                    spell_spans = results.get("spell", [])
                    keep = []
                    for it in issues:
                        txt = content[it.start:it.end].strip()
                        if (it.rule, txt) in self.ignored_grammar:
                            continue
                        if any(s < it.end and e > it.start for s, e, _w in spell_spans):
                            continue
                        keep.append(it)
                    results["grammar"] = keep
            except Exception as ex:  # pragma: no cover
                results["error"] = str(ex)
            self._check_queue.put((seq, results))

        threading.Thread(target=work, daemon=True).start()

    def _poll_checks(self):
        """Главный поток: забрать результаты проверки из рабочего потока."""
        try:
            while True:
                seq, results = self._check_queue.get_nowait()
                self._apply_check(seq, results)
        except queue.Empty:
            pass
        except Exception as e:  # pragma: no cover
            print("[check-poll]", e)
        try:
            self.text.after(120, self._poll_checks)
        except tk.TclError:
            pass

    def _apply_check(self, seq, results):
        self._check_running = False
        if seq != self._check_seq:
            if self._check_again:
                self._start_check()
            return
        t = self.text
        content = t.get("1.0", "end-1c")
        for tag in ("err_spell", "err_grammar", "err_grammar_lt"):
            t.tag_remove(tag, "1.0", "end")
        if "error" in results:
            print("[check]", results["error"])
            return
        starts = line_starts_of(content)
        spell_errors = results.get("spell", [])
        for s, e, _w in spell_errors:
            idx = offset_to_index(starts, s)
            end = offset_to_index(starts, e)
            if idx and end:
                t.tag_add("err_spell", idx, end)
        for it in results.get("grammar", []):
            idx = offset_to_index(starts, it.start)
            end = offset_to_index(starts, it.end)
            if idx and end:
                tag = "err_grammar_lt" if it.source == "languagetool" else "err_grammar"
                t.tag_add(tag, idx, end)
        n_err = len(spell_errors) + len(results.get("grammar", []))
        self.app.on_check_finished(n_err, results)
        if self._check_again:
            self._start_check()

    def index_to_offsets(self, content, index):
        line, col = index.split(".")
        starts = line_starts_of(content)
        li = int(line) - 1
        if li >= len(starts):
            return len(content)
        return starts[li] + int(col)

    # --------------------------- контекстное меню ошибок
    def _on_context(self, event):
        t = self.text
        pos = t.index(f"@{event.x},{event.y}")
        t.mark_set("insert", pos)
        over_spell = "err_spell" in t.tag_names(pos)
        over_grammar = ("err_grammar" in t.tag_names(pos)
                        or "err_grammar_lt" in t.tag_names(pos))
        if not (over_spell or over_grammar):
            self._show_std_context(event)
            return "break"
        menu = tk.Menu(t, tearoff=0)
        content = t.get("1.0", "end-1c")
        off = self.index_to_offsets(content, pos)
        if over_spell:
            m = None
            for mm in WORD_RE.finditer(content):
                if mm.start() <= off < mm.end():
                    m = mm
                    break
            if m:
                word = m.group(0)
                cands = self.spell.candidates(word, limit=6)
                if cands:
                    for c in cands:
                        menu.add_command(
                            label=c,
                            command=lambda c=c, m=m: self._replace_span(m.start(), m.end(), c))
                else:
                    menu.add_command(label=f"«{word}» — вариантов нет", command=lambda: None)
                menu.add_separator()
                menu.add_command(label="Игнорировать",
                                 command=lambda m=m: self._ignore_word(m.group(0)))
                menu.add_command(label="Добавить в словарь",
                                 command=lambda m=m: self._add_to_dict(m.group(0)))
        else:
            issues = list(self.grammar.check(content, use_lt=False))
            if self.grammar.lt.tool is not None:
                try:
                    issues += self.grammar.lt.check(content)
                except Exception:
                    pass
            hit = None
            for it in issues:
                if it.start <= off <= it.end:
                    hit = it
                    break
            if hit:
                if hit.suggestion:
                    menu.add_command(
                        label=f"Заменить на: {hit.suggestion}",
                        command=lambda: self._replace_span(hit.start, hit.end, hit.suggestion))
                    menu.add_separator()
                menu.add_command(label="Игнорировать правило",
                                 command=lambda: self._ignore_grammar(hit, content))
                msg = hit.message if len(hit.message) < 70 else hit.message[:70] + "…"
                menu.add_command(label=msg, command=lambda: None)
        if menu.index("end") is not None:
            menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _show_std_context(self, event):
        menu = tk.Menu(self.text, tearoff=0)
        menu.add_command(label="Вырезать", command=self.cut, accelerator="Ctrl+X")
        menu.add_command(label="Копировать", command=self.copy, accelerator="Ctrl+C")
        menu.add_command(label="Вставить", command=self.paste, accelerator="Ctrl+V")
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=self.select_all, accelerator="Ctrl+A")
        menu.tk_popup(event.x_root, event.y_root)

    def _replace_span(self, s, e, new):
        content = self.text.get("1.0", "end-1c")
        starts = line_starts_of(content)
        a, b = offset_to_index(starts, s), offset_to_index(starts, e)
        if not a or not b:
            return
        self.undo_stack.begin("edit", a)
        self.text.delete(a, b)
        self.text.insert(a, new)
        self.dirty = True
        self.app.update_title()
        self._schedule_check()

    def _ignore_word(self, word):
        self.ignored_words.add(word.lower())
        self._schedule_check()

    def _add_to_dict(self, word):
        self.spell.add_user_word(word)
        self._schedule_check()
        self.app.set_status(f"«{word}» добавлено в словарь")

    def _ignore_grammar(self, issue, content):
        txt = content[issue.start:issue.end].strip()
        self.ignored_grammar.add((issue.rule, txt))
        self._schedule_check()

    # --------------------------- F7
    def run_check_dialog(self):
        from .dialogs import CheckDialog

        CheckDialog(self.app)

    # --------------------------- поиск
    def find_next(self, needle, match_case=False, whole_word=False):
        t = self.text
        if not needle:
            return False
        start = t.index("insert")
        idx = self._search(needle, start, "end", match_case, whole_word)
        wrapped = False
        if idx is None:
            idx = self._search(needle, "1.0", start, match_case, whole_word)
            if idx is None:
                return False
            wrapped = True
        t.tag_remove("find_cur", "1.0", "end")
        t.tag_add("find_cur", idx[0], idx[1])
        t.mark_set("insert", idx[1])
        t.see(idx[0])
        if wrapped:
            self.app.set_status("Поиск: возвращён к началу документа")
        return True

    def find_prev(self, needle, match_case=False, whole_word=False):
        t = self.text
        if not needle:
            return False
        start = t.index("insert")
        idx = self._search_back(needle, start, "1.0", match_case, whole_word)
        if idx is None:
            idx = self._search_back(needle, "end-1c", start, match_case, whole_word)
            if idx is None:
                return False
        t.tag_remove("find_cur", "1.0", "end")
        t.tag_add("find_cur", idx[0], idx[1])
        t.mark_set("insert", idx[1])
        t.see(idx[0])
        return True

    def _search(self, needle, start, stop, match_case, whole_word):
        t = self.text
        idx = t.search(needle, start, stopindex=stop, nocase=not match_case, regexp=False)
        while idx:
            end = f"{idx}+{len(needle)}c"
            if not whole_word or self._is_whole_word(idx, end):
                return (idx, end)
            idx = t.search(needle, end, stopindex=stop, nocase=not match_case, regexp=False)
        return None

    def _search_back(self, needle, start, stop, match_case, whole_word):
        t = self.text
        idx = t.search(needle, start, stopindex=stop, backwards=True,
                       nocase=not match_case, regexp=False)
        while idx:
            end = f"{idx}+{len(needle)}c"
            if not whole_word or self._is_whole_word(idx, end):
                return (idx, end)
            idx = t.search(needle, idx, stopindex=stop, backwards=True,
                           nocase=not match_case, regexp=False)
        return None

    def _is_whole_word(self, s, e):
        t = self.text
        before = t.get(f"{s}-1c", s) if t.compare(s, ">", "1.0") else " "
        after = t.get(e, f"{e}+1c")

        def is_w(c):
            return bool(c) and (c.isalnum() or c in "_'’")
        return not is_w(before) and not is_w(after)

    def replace_all(self, needle, repl, match_case=False, whole_word=False):
        t = self.text
        if not needle:
            return 0
        self.undo_stack.begin("edit", "1.0")
        cnt = 0
        start = "1.0"
        while True:
            idx = self._search(needle, start, "end", match_case, whole_word)
            if not idx:
                break
            t.delete(idx[0], idx[1])
            t.insert(idx[0], repl)
            start = f"{idx[0]}+{len(repl)}c"
            cnt += 1
            if cnt > 10000:
                break
        self.dirty = True
        self.app.update_title()
        self._schedule_check()
        return cnt

    def clear_find_tags(self):
        self.text.tag_remove("find_hit", "1.0", "end")
        self.text.tag_remove("find_cur", "1.0", "end")

    # --------------------------- содержимое
    def blocks(self):
        return list(docwalk.iter_blocks(self.text))

    def clear(self):
        t = self.text
        self.undo_stack.suppress = True
        try:
            for tid in list(self.tables.keys()):
                try:
                    self.tables[tid]["frame"].destroy()
                except tk.TclError:
                    pass
            self.tables.clear()
            self.images.clear()
            t.delete("1.0", "end")
            for name in list(t.tag_names()):
                if name == "sel":
                    continue
                try:
                    t.tag_remove(name, "1.0", "end")
                except tk.TclError:
                    pass
        finally:
            self.undo_stack.suppress = False
        self.undo_stack.clear()
        self.ignored_words.clear()
        self.ignored_grammar.clear()
        self.pending_fmt = {}
        self.dirty = False

    def stats(self):
        content = self.text.get("1.0", "end-1c")
        return {
            "words": len(re.findall(r"\S+", content)),
            "chars": len(content),
            "chars_nospace": len(re.sub(r"\s", "", content)),
            "lines": int(self.text.index("end-1c").split(".")[0]),
        }
