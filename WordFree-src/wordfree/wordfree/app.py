"""Главное окно WordFree: меню, панели инструментов, линейка, панель грамматики,
файловые операции (.docx/.txt/PDF/печать), запуск LanguageTool."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import APP_NAME, APP_VERSION, icons, resources, winfonts
from .dialogs import (
    AboutDialog,
    FindReplaceDialog,
    FontDialog,
    PageDialog,
    ParagraphDialog,
    TableDialog,
)
from .editor import Editor
from .grammar import LTBackend

FONTS_COMMON = ["Arial", "Calibri", "Cambria", "Times New Roman", "Courier New",
                "Verdana", "Tahoma", "Georgia", "Segoe UI", "DejaVu Sans"]
SIZES = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26",
         "28", "36", "48", "72"]


class WordFreeApp:
    def __init__(self):
        winfonts.register_bundled_fonts()
        self.root = tk.Tk()
        self.root.title(f"Безымянный — {APP_NAME}")
        self.root.geometry("1200x800")
        self.root.minsize(760, 500)
        try:
            self.root.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass

        self.settings = self.load_settings()
        self.current_path = None
        self.last_find = ""
        self.lt_status = "загрузка…" if LTBackend.java_available() else "нет Java"
        self._find_dialog = None

        self._build_menu()
        self._build_toolbar()
        self._build_ruler()
        self._build_main_area()
        self._build_grammar_panel()
        self._build_statusbar()
        self._bind_global_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self._start_languagetool)
        self.root.after(400, self.editor._schedule_check)
        self.root.after(500, self.refresh_format_state)
        self.update_title()

    # ================================ настройки ================================
    def load_settings(self):
        path = os.path.join(resources.user_dir(), "settings.json")
        defaults = {
            "check_spelling": True,
            "check_grammar": True,
            "language": "auto",
            "margins_cm": [2.0, 2.0, 2.0, 2.0],
            "ruler": True,
            "grammar_panel": True,
            "statusbar": True,
            "date_long": True,
        }
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
        except Exception:
            pass
        return defaults

    def save_settings(self):
        path = os.path.join(resources.user_dir(), "settings.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ================================ построение UI ================================
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        # --- Файл
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Новый", accelerator="Ctrl+N", command=self.file_new)
        m_file.add_command(label="Открыть…", accelerator="Ctrl+O", command=self.file_open)
        m_file.add_separator()
        m_file.add_command(label="Сохранить", accelerator="Ctrl+S", command=self.file_save)
        m_file.add_command(label="Сохранить как…", accelerator="Ctrl+Shift+S",
                           command=self.file_save_as)
        m_file.add_separator()
        m_file.add_command(label="Экспорт в PDF…", command=self.export_pdf)
        m_file.add_command(label="Печать…", accelerator="Ctrl+P", command=self.print_doc)
        m_file.add_command(label="Параметры страницы…", command=lambda: PageDialog(self))
        m_file.add_separator()
        m_file.add_command(label="Выход", command=self.on_close)
        menubar.add_cascade(label="Файл", menu=m_file)

        # --- Правка
        m_edit = tk.Menu(menubar, tearoff=0)
        m_edit.add_command(label="Отменить", accelerator="Ctrl+Z",
                           command=lambda: self.editor.undo())
        m_edit.add_command(label="Повторить", accelerator="Ctrl+Y",
                           command=lambda: self.editor.redo())
        m_edit.add_separator()
        m_edit.add_command(label="Вырезать", accelerator="Ctrl+X",
                           command=lambda: self.editor.cut())
        m_edit.add_command(label="Копировать", accelerator="Ctrl+C",
                           command=lambda: self.editor.copy())
        m_edit.add_command(label="Вставить", accelerator="Ctrl+V",
                           command=lambda: self.editor.paste())
        m_edit.add_command(label="Удалить", accelerator="Del",
                           command=lambda: self.editor.delete_selection())
        m_edit.add_separator()
        m_edit.add_command(label="Найти…", accelerator="Ctrl+F",
                           command=lambda: self.open_find(False))
        m_edit.add_command(label="Заменить…", accelerator="Ctrl+H",
                           command=lambda: self.open_find(True))
        m_edit.add_separator()
        m_edit.add_command(label="Выделить всё", accelerator="Ctrl+A",
                           command=lambda: self.editor.select_all())
        m_edit.add_command(label="Дата и время", accelerator="F5",
                           command=lambda: self.editor.insert_date())
        menubar.add_cascade(label="Правка", menu=m_edit)

        # --- Вставка
        m_ins = tk.Menu(menubar, tearoff=0)
        m_ins.add_command(label="Картинка…", command=self.insert_image_dialog)
        m_ins.add_command(label="Таблица…", command=lambda: TableDialog(self))
        m_ins.add_command(label="Разрыв страницы", accelerator="Ctrl+Enter",
                          command=lambda: self.editor.insert_page_break())
        m_ins.add_command(label="Дата", accelerator="F5",
                          command=lambda: self.editor.insert_date())
        m_sym = tk.Menu(m_ins, tearoff=0)
        for sym in ["©", "®", "™", "№", "€", "$", "¥", "§", "±", "×",
                    "÷", "…", "–", "—", "«", "»", "“", "”", "°", "µ"]:
            m_sym.add_command(label=sym,
                              command=lambda s=sym: self.editor.insert_plain(s))
        m_ins.add_cascade(label="Специальный символ", menu=m_sym)
        menubar.add_cascade(label="Вставка", menu=m_ins)

        # --- Формат
        m_fmt = tk.Menu(menubar, tearoff=0)
        m_fmt.add_command(label="Шрифт…", accelerator="Ctrl+D",
                          command=lambda: FontDialog(self))
        m_fmt.add_command(label="Абзац…", command=lambda: ParagraphDialog(self))
        m_fmt.add_separator()
        m_fmt.add_command(label="Обычный", command=lambda: self._set_style("normal"))
        m_fmt.add_command(label="Заголовок 1", command=lambda: self._set_style("h1"))
        m_fmt.add_command(label="Заголовок 2", command=lambda: self._set_style("h2"))
        m_fmt.add_command(label="Заголовок 3", command=lambda: self._set_style("h3"))
        m_fmt.add_separator()
        m_fmt.add_command(label="Маркированный список",
                          command=lambda: self.editor.toggle_list("bullet"))
        m_fmt.add_command(label="Нумерованный список",
                          command=lambda: self.editor.toggle_list("number"))
        menubar.add_cascade(label="Формат", menu=m_fmt)

        # --- Сервис
        m_tools = tk.Menu(menubar, tearoff=0)
        m_tools.add_command(label="Проверка орфографии и грамматики…",
                            accelerator="F7", command=self.run_check)
        m_tools.add_separator()
        self._var_spell = tk.BooleanVar(value=self.settings["check_spelling"])
        self._var_gram = tk.BooleanVar(value=self.settings["check_grammar"])
        m_tools.add_checkbutton(label="Проверять орфографию", variable=self._var_spell,
                                command=self.toggle_spell)
        m_tools.add_checkbutton(label="Проверять грамматику", variable=self._var_gram,
                                command=self.toggle_grammar)
        m_tools.add_separator()
        self._var_lang = tk.StringVar(value=self.settings["language"])
        m_lang = tk.Menu(m_tools, tearoff=0)
        for val, lab in [("auto", "Автоопределение"), ("ru", "Русский"),
                         ("en", "Английский")]:
            m_lang.add_radiobutton(label=lab, value=val, variable=self._var_lang,
                                   command=lambda v=val: self.set_lang(v))
        m_tools.add_cascade(label="Язык проверки", menu=m_lang)
        menubar.add_cascade(label="Сервис", menu=m_tools)

        # --- Вид
        m_view = tk.Menu(menubar, tearoff=0)
        self._var_ruler = tk.BooleanVar(value=self.settings["ruler"])
        self._var_gpanel = tk.BooleanVar(value=self.settings["grammar_panel"])
        self._var_sbar = tk.BooleanVar(value=self.settings["statusbar"])
        m_view.add_checkbutton(label="Линейка", variable=self._var_ruler,
                               command=self.toggle_ruler)
        m_view.add_checkbutton(label="Панель проверки", variable=self._var_gpanel,
                               command=self.toggle_grammar_panel)
        m_view.add_checkbutton(label="Строка состояния", variable=self._var_sbar,
                               command=self.toggle_statusbar)
        menubar.add_cascade(label="Вид", menu=m_view)

        # --- Справка
        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="Горячие клавиши", command=self.show_hotkeys)
        m_help.add_command(label="О программе", command=lambda: AboutDialog(self))
        menubar.add_cascade(label="Справка", menu=m_help)

        self.root.config(menu=menubar)
        self.menubar = menubar
        self.m_file, self.m_edit_full = m_file, m_edit

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(4, 3))
        bar.pack(side="top", fill="x")

        def sep():
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y",
                                                       padx=4, pady=2)

        # отмена/повтор
        self.btn_undo = ttk.Button(bar, text="↶", width=2, command=self.editor_undo)
        self.btn_undo.pack(side="left")
        self.btn_redo = ttk.Button(bar, text="↷", width=2, command=self.editor_redo)
        self.btn_redo.pack(side="left", padx=(2, 4))
        sep()

        # стиль абзаца
        self.style_combo = ttk.Combobox(
            bar, width=15, state="readonly",
            values=["Обычный", "Заголовок 1", "Заголовок 2", "Заголовок 3"])
        self.style_combo.set("Обычный")
        self.style_combo.bind("<<ComboboxSelected>>", self._on_style)
        self.style_combo.pack(side="left")
        sep()

        # шрифт
        from tkinter import font as tkfont
        fams = sorted({f for f in tkfont.families() if not f.startswith("@")})
        ordered = [f for f in FONTS_COMMON if f in fams] + \
                  [f for f in fams if f not in FONTS_COMMON]
        self.font_combo = ttk.Combobox(bar, width=17, values=ordered)
        self.font_combo.set(ordered[0] if ordered else "Arial")
        self.font_combo.bind("<<ComboboxSelected>>",
                             lambda e: self.editor.set_font_family(self.font_combo.get()))
        self.font_combo.pack(side="left")
        self.size_combo = ttk.Combobox(bar, width=5, values=SIZES)
        self.size_combo.set("11")
        self.size_combo.bind("<<ComboboxSelected>>",
                             lambda e: self._on_size())
        self.size_combo.pack(side="left", padx=(3, 4))

        # B I U S
        def tbtn(text, cmd, w=2):
            b = ttk.Button(bar, text=text, width=w, command=cmd)
            b.pack(side="left", padx=1)
            return b

        def fmtbtn(text, cmd, w=2, font=("Arial", 10, "bold")):
            b = tk.Button(bar, text=text, width=w, command=cmd,
                          relief="raised", bd=1, font=font, padx=1)
            b.pack(side="left", padx=1)
            return b
        self.btn_b = fmtbtn("B", lambda: self.editor.toggle_char("bold"))
        self.btn_i = fmtbtn("I", lambda: self.editor.toggle_char("italic"),
                            font=("Arial", 10, "italic"))
        self.btn_u = fmtbtn("U", lambda: self.editor.toggle_char("underline"),
                            font=("Arial", 10, "underline"))
        self.btn_s = fmtbtn("S", lambda: self.editor.toggle_char("strike"),
                            font=("Arial", 10, "overstrike"))
        sep()

        # цвет и выделение
        self.btn_color = tk.Button(bar, image=icons.icon_text_color(),
                                   relief="raised", bd=1, command=self.pick_color)
        self.btn_color.pack(side="left", padx=1)
        self.btn_hl = tk.Button(bar, image=icons.icon_highlight(),
                                relief="raised", bd=1, command=self.pick_highlight)
        self.btn_hl.pack(side="left", padx=1)
        sep()

        # выравнивание
        self.btn_al = {}
        for key, icon_fn, cmd in [
            ("left", icons.icon_align_left, lambda: self.editor.set_align("left")),
            ("center", icons.icon_align_center, lambda: self.editor.set_align("center")),
            ("right", icons.icon_align_right, lambda: self.editor.set_align("right")),
            ("justify", icons.icon_align_justify, lambda: self.editor.set_align("justify")),
        ]:
            b = tk.Button(bar, image=icon_fn(), command=cmd,
                          relief="raised", bd=1)
            b.pack(side="left", padx=1)
            self.btn_al[key] = b
        sep()

        # списки
        tk.Button(bar, image=icons.icon_bullet_list(), relief="raised", bd=1,
                  command=lambda: self.editor.toggle_list("bullet")).pack(side="left", padx=1)
        tk.Button(bar, image=icons.icon_number_list(), relief="raised", bd=1,
                  command=lambda: self.editor.toggle_list("number")).pack(side="left", padx=1)
        sep()

        # вставка
        tk.Button(bar, image=icons.icon_image(), relief="raised", bd=1,
                  command=self.insert_image_dialog).pack(side="left", padx=1)
        tk.Button(bar, image=icons.icon_table(), relief="raised", bd=1,
                  command=lambda: TableDialog(self)).pack(side="left", padx=1)
        sep()

        # проверка
        self.btn_spell = tk.Button(bar, image=icons.icon_spellcheck(),
                                   relief="raised", bd=1, command=self.run_check)
        self.btn_spell.pack(side="left", padx=1)
        sep()

        # экспорт/печать
        tbtn("PDF", self.export_pdf, w=3)
        tk.Button(bar, image=icons.icon_print(), relief="raised", bd=1,
                  command=self.print_doc).pack(side="left", padx=1)

        self.toolbar = bar

    def _build_ruler(self):
        self.ruler_frame = tk.Frame(self.root, bg="#e9edf1", height=26)
        self.ruler = tk.Canvas(self.ruler_frame, bg="#e9edf1",
                               highlightthickness=0, height=24)
        self.ruler.pack(fill="x", expand=True)
        if self.settings.get("ruler", True):
            self.ruler_frame.pack(side="top", fill="x")
        self.ruler_frame.pack_propagate(False)
        self.ruler_frame.bind("<Configure>", lambda e: self.draw_ruler())
        self.ruler.bind("<Configure>", lambda e: self.draw_ruler())
        self.root.after(300, self.draw_ruler)

    def draw_ruler(self, retries=20):
        c = self.ruler
        try:
            c.update_idletasks()
            w = c.winfo_width()
        except tk.TclError:
            return
        if w <= 10:
            # раскладка ещё не выполнена — повторить
            if retries > 0:
                self.root.after(200, lambda: self.draw_ruler(retries - 1))
            return
        c.delete("all")
        c.create_rectangle(0, 0, w, 24, fill="#e9edf1", outline="")
        pad = 64  # внутренний отступ текста (padx)
        # деления: 1 см ≈ 37.8 px при 96dpi; возьмём масштаб из ширины окна
        px_cm = 37.8
        x = pad
        cm = 0
        while x < w - 6:
            major = (cm % 5 == 0)
            h = 12 if major else 6
            c.create_line(x, 24, x, 24 - h, fill="#7a8694")
            if major and cm > 0:
                c.create_text(x, 6, text=str(cm), fill="#5a6673",
                              font=("Arial", 7))
            x += px_cm
            cm += 1
        c.create_rectangle(pad, 4, w - 6, 20, outline="#aab4bf")

    def _build_main_area(self):
        self.main_pane = tk.PanedWindow(self.root, orient="horizontal", sashwidth=4)
        self.main_pane.pack(fill="both", expand=True)
        self.editor = Editor(self, self.main_pane)
        self.main_pane.add(self.editor.frame, minsize=400, stretch="always")

    def _build_grammar_panel(self):
        self.gpanel = tk.Frame(self.main_pane, width=280, bg="#f4f6f8")
        head = ttk.Label(self.gpanel, text="  Проверка", font=("Arial", 10, "bold"))
        head.pack(anchor="w", pady=(6, 2), padx=6)
        self.gstatus = ttk.Label(self.gpanel, text="Запуск проверки…",
                                 foreground="#555", wraplength=250, justify="left")
        self.gstatus.pack(anchor="w", padx=8, pady=(0, 4))
        lb_frame = ttk.Frame(self.gpanel)
        lb_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.glist = tk.Listbox(lb_frame, font=("Arial", 9), activestyle="dotbox",
                                exportselection=False)
        gsb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.glist.yview)
        self.glist.configure(yscrollcommand=gsb.set)
        self.glist.pack(side="left", fill="both", expand=True)
        gsb.pack(side="right", fill="y")
        self.glist.bind("<<ListboxSelect>>", self._on_glist)
        self._gissues = []
        if self.settings.get("grammar_panel", True):
            self.main_pane.add(self.gpanel, width=280, minsize=200)

    def _build_statusbar(self):
        self.sbar = tk.Frame(self.root, bg="#dde3e9", height=24)
        self.sbar_prop = tk.Frame(self.sbar, bg="#dde3e9")
        self.sbar_prop.pack(fill="x")
        self.lbl_left = tk.Label(self.sbar_prop, bg="#dde3e9", anchor="w",
                                 font=("Arial", 9), padx=8)
        self.lbl_left.pack(side="left")
        self.lbl_mid = tk.Label(self.sbar_prop, bg="#dde3e9", anchor="center",
                                font=("Arial", 9))
        self.lbl_mid.pack(side="left", expand=True)
        self.lbl_right = tk.Label(self.sbar_prop, bg="#dde3e9", anchor="e",
                                  font=("Arial", 9), padx=8)
        self.lbl_right.pack(side="right")
        if self.settings.get("statusbar", True):
            self.sbar.pack(side="bottom", fill="x")
        self.set_status("Готово")

    def _bind_global_keys(self):
        r = self.root
        r.bind("<Control-n>", lambda e: self.file_new())
        r.bind("<Control-N>", lambda e: self.file_new())
        r.bind("<Control-o>", lambda e: self.file_open())
        r.bind("<Control-O>", lambda e: self.file_open())
        r.bind("<Control-s>", lambda e: self.file_save())
        r.bind("<Control-S>", lambda e: self.file_save())
        r.bind("<Control-p>", lambda e: self.print_doc())
        r.bind("<Control-P>", lambda e: self.print_doc())
        r.bind("<Control-f>", lambda e: self.open_find(False))
        r.bind("<Control-F>", lambda e: self.open_find(False))
        r.bind("<Control-h>", lambda e: self.open_find(True))
        r.bind("<Control-H>", lambda e: self.open_find(True))
        r.bind("<Control-d>", lambda e: FontDialog(self))
        r.bind("<Control-D>", lambda e: FontDialog(self))
        r.bind("<F7>", lambda e: self.run_check())
        r.bind("<F5>", lambda e: self.editor.insert_date())
        r.bind("<Control-a>", lambda e: self.editor.select_all())
        r.bind("<Control-A>", lambda e: self.editor.select_all())
        # форматирование
        r.bind("<Control-b>", lambda e: self.editor.toggle_char("bold"))
        r.bind("<Control-B>", lambda e: self.editor.toggle_char("bold"))
        r.bind("<Control-i>", lambda e: self.editor.toggle_char("italic"))
        r.bind("<Control-I>", lambda e: self.editor.toggle_char("italic"))
        r.bind("<Control-u>", lambda e: self.editor.toggle_char("underline"))
        r.bind("<Control-U>", lambda e: self.editor.toggle_char("underline"))
        r.bind("<Control-e>", lambda e: self.editor.set_align("center"))
        r.bind("<Control-E>", lambda e: self.editor.set_align("center"))
        r.bind("<Control-l>", lambda e: self.editor.set_align("left"))
        r.bind("<Control-L>", lambda e: self.editor.set_align("left"))
        r.bind("<Control-r>", lambda e: self.editor.set_align("right"))
        r.bind("<Control-R>", lambda e: self.editor.set_align("right"))
        r.bind("<Control-j>", lambda e: self.editor.set_align("justify"))
        r.bind("<Control-J>", lambda e: self.editor.set_align("justify"))
        r.bind("<Control-bracketright>",
               lambda e: self.editor.grow_font(1))
        r.bind("<Control-bracketleft>",
               lambda e: self.editor.grow_font(-1))
        r.bind("<Control-Return>", lambda e: self.editor.insert_page_break())

    # ================================ действия меню ================================
    def editor_undo(self):
        self.editor.undo()

    def editor_redo(self):
        self.editor.redo()

    def _on_style(self, event=None):
        mapping = {
            "Обычный": "normal",
            "Заголовок 1": "h1",
            "Заголовок 2": "h2",
            "Заголовок 3": "h3",
        }
        self.editor.set_style(mapping.get(self.style_combo.get(), "normal"))

    def _on_size(self):
        try:
            self.editor.set_font_size(int(self.size_combo.get()))
        except ValueError:
            pass

    def pick_color(self):
        c = colorchooser.askcolor(color="#000000", parent=self.root, title="Цвет шрифта")
        if c and c[1]:
            self.editor.set_font_color(c[1])

    def pick_highlight(self):
        c = colorchooser.askcolor(color="#ffff00", parent=self.root, title="Цвет выделения")
        if c and c[1]:
            self.editor.set_highlight(c[1])

    def insert_image_dialog(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Вставить картинку",
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("Все файлы", "*.*"),
            ])
        if not path:
            return
        self.editor.insert_image(path)

    def open_find(self, replace_mode):
        if self._find_dialog is not None:
            try:
                self._find_dialog.win.lift()
                return
            except tk.TclError:
                self._find_dialog = None
        self._find_dialog = FindReplaceDialog(self, replace_mode)

    def run_check(self):
        self.editor.run_check_dialog()

    def toggle_spell(self):
        self.settings["check_spelling"] = bool(self._var_spell.get())
        self.save_settings()
        self.editor._schedule_check()

    def toggle_grammar(self):
        self.settings["check_grammar"] = bool(self._var_gram.get())
        self.save_settings()
        self.editor._schedule_check()

    def set_lang(self, lang):
        self.settings["language"] = lang
        self.save_settings()
        self.editor._schedule_check()

    def toggle_ruler(self):
        self.settings["ruler"] = bool(self._var_ruler.get())
        self.save_settings()
        if self.settings["ruler"]:
            self.ruler_frame.pack(side="top", fill="x", before=self.main_pane)
            self.draw_ruler()
        else:
            self.ruler_frame.pack_forget()

    def toggle_grammar_panel(self):
        self.settings["grammar_panel"] = bool(self._var_gpanel.get())
        self.save_settings()
        if self.settings["grammar_panel"]:
            self.main_pane.add(self.gpanel, width=280, minsize=200)
        else:
            try:
                self.main_pane.forget(self.gpanel)
            except tk.TclError:
                pass

    def toggle_statusbar(self):
        self.settings["statusbar"] = bool(self._var_sbar.get())
        self.save_settings()
        if self.settings["statusbar"]:
            self.sbar.pack(side="bottom", fill="x")
        else:
            self.sbar.pack_forget()

    def show_hotkeys(self):
        messagebox.showinfo(
            "Горячие клавиши",
            "Ctrl+B / I / U — жирный, курсив, подчёркнутый\n"
            "Ctrl+E / L / R / J — выравнивание\n"
            "Ctrl+F — найти, Ctrl+H — заменить\n"
            "Ctrl+S — сохранить, Ctrl+O — открыть\n"
            "Ctrl+P — печать, Ctrl+N — новый\n"
            "Ctrl+D — диалог шрифта\n"
            "F7 — проверка орфографии/грамматики\n"
            "F5 — вставить дату\n"
            "Ctrl+Enter — разрыв страницы\n"
            "Ctrl+Z / Ctrl+Y — отмена / повтор\n"
            "Ctrl+] / Ctrl+[ — увеличить/уменьшить кегль",
            parent=self.root)

    # ================================ файловые операции ================================
    def _confirm_discard(self):
        if not self.editor.dirty:
            return True
        name = os.path.basename(self.current_path) if self.current_path else "Безымянный"
        res = messagebox.askyesnocancel(
            "WordFree",
            f"Сохранить изменения в документе «{name}»?",
            parent=self.root)
        if res is None:
            return False
        if res:
            return self.file_save()
        return True

    def file_new(self):
        if not self._confirm_discard():
            return
        self.editor.clear()
        self.current_path = None
        self._insert_welcome()
        self.update_title()
        self.set_status("Создан новый документ")
        self.editor._schedule_check()

    def _insert_welcome(self):
        t = self.editor.text
        self.editor.undo_stack.suppress = True
        try:
            t.insert("1.0", "Новый документ")
            t.tag_add("style_h1", "1.0", "1.end+1c")
        finally:
            self.editor.undo_stack.suppress = False
            self.editor.undo_stack.clear()
            t.edit_modified(False)
        self.editor.dirty = False

    def file_open(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Открыть документ",
            filetypes=[
                ("Документы Word", "*.docx"),
                ("Текстовые файлы", "*.txt"),
                ("Все файлы", "*.*"),
            ])
        if not path:
            return
        self.open_path(path)

    def open_path(self, path):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".docx":
                self._open_docx(path)
            else:
                self._open_txt(path)
        except Exception as e:
            messagebox.showerror("Ошибка открытия", str(e), parent=self.root)
            return
        self.current_path = path
        self.editor.dirty = False
        self.editor.undo_stack.clear()
        self.update_title()
        self.set_status(f"Открыто: {os.path.basename(path)}")
        self.editor._schedule_check()
        self.editor.text.mark_set("insert", "1.0")
        self.editor.text.see("1.0")

    def _open_docx(self, path):
        from . import docx_io

        ed = self.editor
        ed.clear()
        ed.undo_stack.suppress = True
        try:
            tmp = tempfile.mkdtemp(prefix="wordfree_img_")

            def img_cb(p, w):
                ed.text.mark_set("insert", "end-1c")
                ed.insert_image(p, w)

            def tbl_cb(rows, cols, cell_texts):
                ed.text.mark_set("insert", "end-1c")
                ed.insert_table(rows, cols, cell_texts)

            docx_io.open_docx(
                ed.text, ed.tables, ed.images, path,
                insert_image_cb=img_cb,
                create_table_cb=tbl_cb,
                temp_dir=tmp,
            )
        finally:
            ed.undo_stack.suppress = False
            ed.undo_stack.clear()
            ed.text.mark_set("insert", "end-1c")

    def _open_txt(self, path):
        ed = self.editor
        ed.clear()
        content = None
        for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if content is None:
            raise RuntimeError("Не удалось прочитать файл")
        ed.undo_stack.suppress = True
        try:
            ed.text.insert("1.0", content)
        finally:
            ed.undo_stack.suppress = False
            ed.undo_stack.clear()

    def file_save(self):
        if self.current_path:
            return self._save_to(self.current_path)
        return self.file_save_as()

    def file_save_as(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Сохранить как",
            defaultextension=".docx",
            filetypes=[
                ("Документы Word", "*.docx"),
                ("Текстовые файлы", "*.txt"),
            ])
        if not path:
            return False
        return self._save_to(path)

    def _save_to(self, path):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".txt":
                content = self.editor.text.get("1.0", "end-1c")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                from . import docx_io

                if not ext:
                    path += ".docx"
                title = os.path.splitext(os.path.basename(path))[0]
                docx_io.save_docx(
                    self.editor.text, self.editor.tables, self.editor.images,
                    path, title=title)
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e), parent=self.root)
            return False
        self.current_path = path
        self.editor.dirty = False
        self.update_title()
        self.set_status(f"Сохранено: {os.path.basename(path)}")
        return True

    def export_pdf(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Экспорт в PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            from . import pdf_export

            margins = self.settings.get("margins_cm", [2, 2, 2, 2])
            pdf_export.export_pdf(
                self.editor.text, self.editor.tables, self.editor.images,
                path, title=os.path.basename(path),
                margins_cm=margins)
            self.set_status(f"PDF сохранён: {os.path.basename(path)}")
            res = messagebox.askyesno(
                "Экспорт в PDF",
                f"Файл сохранён:\n{path}\n\nОткрыть его?",
                parent=self.root)
            if res:
                self._open_file_os(path)
        except Exception as e:
            messagebox.showerror("Ошибка экспорта", str(e), parent=self.root)

    def print_doc(self):
        tmp = tempfile.mktemp(suffix=".pdf", prefix="wordfree_print_")
        try:
            from . import pdf_export

            margins = self.settings.get("margins_cm", [2, 2, 2, 2])
            pdf_export.export_pdf(
                self.editor.text, self.editor.tables, self.editor.images,
                tmp, title="Печать", margins_cm=margins)
        except Exception as e:
            messagebox.showerror("Печать", f"Не удалось подготовить документ:\n{e}",
                                 parent=self.root)
            return
        if sys.platform.startswith("win"):
            try:
                os.startfile(tmp, "print")  # noqa: S606
                self.set_status("Отправлено на печать")
                return
            except Exception:
                self._open_file_os(tmp)
                self.set_status("PDF открыт — используйте печать в просмотрщике")
                return
        if shutil.which("lp"):
            try:
                subprocess.run(["lp", tmp], check=False)
                self.set_status("Отправлено на печать")
                return
            except Exception:
                pass
        self._open_file_os(tmp)
        self.set_status("PDF открыт — используйте печать в просмотрщике")

    @staticmethod
    def _open_file_os(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    # ================================ LanguageTool ================================
    def _start_languagetool(self):
        ed = self.editor
        if not ed.grammar.use_lt:
            self.lt_status = "выключена"
            return
        if not ed.grammar.lt.java_available():
            self.lt_status = "нет Java — только правила"
            self.gstatus.configure(
                text="Грамматика: для полной проверки установите Java 17+\n"
                     "(проверка по встроенным правилам работает всегда)")
            return
        self.lt_status = "загрузка…"
        self._lt_result = "pending"

        def work():
            ok = ed.grammar.ensure_lt()
            self._lt_result = ok

        threading.Thread(target=work, daemon=True).start()
        self.root.after(400, self._poll_lt)

    def _poll_lt(self):
        res = getattr(self, "_lt_result", "pending")
        if res == "pending":
            self.root.after(400, self._poll_lt)
            return
        ok = bool(res)
        status = "LanguageTool (ru)" if ok else "правила"
        self._lt_done(ok, status)

    def _lt_done(self, ok, status):
        self.lt_status = status
        self.editor._schedule_check()
        if not ok:
            err = self.editor.grammar.lt.error or ""
            self.gstatus.configure(
                text="Грамматика: встроенные правила.\n"
                     f"LanguageTool не запустился ({err[:80]})")

    # ================================ состояние/статус ================================
    def refresh_format_state(self):
        if not hasattr(self, "editor"):
            return
        fmt = self.editor.selection_fmt()
        active = {"bold": False, "italic": False, "underline": False, "strike": False}
        for k in active:
            active[k] = bool(fmt.get(k))
        for btn, key in [(self.btn_b, "bold"), (self.btn_i, "italic"),
                         (self.btn_u, "underline"), (self.btn_s, "strike")]:
            try:
                btn.configure(relief="sunken" if active[key] else "raised")
            except tk.TclError:
                pass
        pinfo = self.editor.current_para_info()
        for key, b in self.btn_al.items():
            try:
                on = pinfo["align"] == key
                b.configure(relief="sunken" if on else "raised")
            except tk.TclError:
                pass
        if fmt.get("font"):
            try:
                self.font_combo.set(fmt["font"])
            except Exception:
                pass
        self.size_combo.set(str(fmt.get("size") or 11))
        style_map = {"normal": "Обычный", "h1": "Заголовок 1",
                     "h2": "Заголовок 2", "h3": "Заголовок 3"}
        self.style_combo.set(style_map.get(pinfo["style"], "Обычный"))
        self._update_counts()

    def _set_style(self, style):
        mapping = {"normal": "Обычный", "h1": "Заголовок 1",
                   "h2": "Заголовок 2", "h3": "Заголовок 3"}
        self.style_combo.set(mapping[style])
        self.editor.set_style(style)

    def update_title(self):
        name = os.path.basename(self.current_path) if self.current_path else "Безымянный"
        ed = getattr(self, "editor", None)
        star = " *" if (ed is not None and ed.dirty) else ""
        self.root.title(f"{name}{star} — {APP_NAME}")

    def set_status(self, text):
        try:
            self.lbl_left.configure(text=text)
        except tk.TclError:
            pass

    def _update_counts(self):
        st = self.editor.stats()
        self.lbl_mid.configure(
            text=f"Слов: {st['words']}    Знаков: {st['chars']}    Строк: {st['lines']}")
        self.lbl_right.configure(text=f"Грамматика: {self.lt_status}")

    def on_check_finished(self, n_err, results):
        spell_n = len(results.get("spell", []))
        gram_n = len(results.get("grammar", []))
        parts = []
        if spell_n:
            parts.append(f"орфография: {spell_n}")
        if gram_n:
            parts.append(f"грамматика: {gram_n}")
        if not parts:
            self.gstatus.configure(text="Ошибок не найдено ✓")
        else:
            self.gstatus.configure(text="Найдено: " + ", ".join(parts))
        # список в панели
        self._gissues = []
        content = self.editor.text.get("1.0", "end-1c")
        for s, e, w in results.get("spell", []):
            self._gissues.append(("spell", s, e, content[s:e],
                                  f"Возможная орфографическая ошибка: «{w}»"))
        for it in results.get("grammar", []):
            self._gissues.append(
                ("grammar", it.start, it.end, content[it.start:it.end],
                 (it.suggestion + " — " if it.suggestion else "") + it.message))
        self.glist.delete(0, "end")
        for kind, s, e, txt, msg in self._gissues:
            icon = "🔤" if kind == "spell" else "📐"
            t = txt.replace("\n", " ")
            if len(t) > 26:
                t = t[:26] + "…"
            self.glist.insert("end", f"{icon} {t}: {msg[:70]}")
        self._update_counts()

    def _on_glist(self, event=None):
        sel = self.glist.curselection()
        if not sel:
            return
        kind, s, e, txt, msg = self._gissues[sel[0]]
        from .editor import line_starts_of, offset_to_index

        content = self.editor.text.get("1.0", "end-1c")
        starts = line_starts_of(content)
        a = offset_to_index(starts, s)
        b = offset_to_index(starts, e)
        if a and b:
            t = self.editor.text
            t.tag_remove("find_cur", "1.0", "end")
            t.tag_add("find_cur", a, b)
            t.mark_set("insert", b)
            t.see(a)

    # ================================ выход ================================
    def on_close(self):
        if not self._confirm_discard():
            return
        self.save_settings()
        try:
            self.editor.grammar.close()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    resources.setup_languagetool_cache()
    app = WordFreeApp()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        app.open_path(sys.argv[1])
    app.run()
