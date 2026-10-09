"""Диалоги WordFree: поиск/замена, проверка F7, шрифт, абзац, таблица, страница, справка."""
import tkinter as tk
from tkinter import colorchooser, font as tkfont, messagebox, ttk


# ============================ Найти и заменить ============================
class FindReplaceDialog:
    def __init__(self, app, replace_mode=False):
        self.app = app
        self.ed = app.editor
        self.win = tk.Toplevel(app.root)
        self.win.title("Найти и заменить" if replace_mode else "Найти")
        self.win.resizable(False, False)
        self.win.transient(app.root)
        self.win.attributes("-topmost", True)

        frm = ttk.Frame(self.win, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frm, text="Найти:").grid(row=0, column=0, sticky="w", pady=2)
        self.find_var = tk.StringVar(value=app.last_find or "")
        self.find_entry = ttk.Combobox(frm, textvariable=self.find_var, width=36)
        self.find_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)

        ttk.Label(frm, text="Заменить на:").grid(row=1, column=0, sticky="w", pady=2)
        self.repl_var = tk.StringVar()
        self.repl_entry = ttk.Combobox(frm, textvariable=self.repl_var, width=36)
        if replace_mode:
            self.repl_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)

        self.case_var = tk.BooleanVar(value=False)
        self.word_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Учитывать регистр", variable=self.case_var).grid(
            row=2, column=1, sticky="w", pady=2)
        ttk.Checkbutton(frm, text="Только целые слова", variable=self.word_var).grid(
            row=2, column=2, sticky="w", pady=2)

        btns = ttk.Frame(frm)
        btns.grid(row=0, column=3, rowspan=3, sticky="n", padx=(10, 0))
        ttk.Button(btns, text="Найти далее", command=self.on_find_next).pack(fill="x", pady=1)
        if replace_mode:
            ttk.Button(btns, text="Заменить", command=self.on_replace).pack(fill="x", pady=1)
            ttk.Button(btns, text="Заменить всё", command=self.on_replace_all).pack(fill="x", pady=1)
        ttk.Button(btns, text="Отмена", command=self.on_close).pack(fill="x", pady=(8, 1))

        self.status = ttk.Label(frm, text="", foreground="#555")
        self.status.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")
        self.win.bind("<Return>", lambda e: self.on_find_next())
        self.win.bind("<Escape>", lambda e: self.on_close())
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_find_next(self):
        needle = self.find_var.get()
        if not needle:
            return
        self.app.last_find = needle
        ok = self.ed.find_next(needle, self.case_var.get(), self.word_var.get())
        self.status.configure(
            text="" if ok else "Совпадений не найдено")

    def on_replace(self):
        needle = self.find_var.get()
        if not needle:
            return
        t = self.ed.text
        if t.tag_ranges("find_cur"):
            a, b = str(t.tag_ranges("find_cur")[0]), str(t.tag_ranges("find_cur")[1])
            self.ed.undo_stack.begin("edit", a)
            t.delete(a, b)
            t.insert(a, self.repl_var.get())
            self.ed.dirty = True
            self.app.update_title()
            self.ed._schedule_check()
        self.on_find_next()

    def on_replace_all(self):
        cnt = self.ed.replace_all(
            self.find_var.get(), self.repl_var.get(),
            self.case_var.get(), self.word_var.get())
        self.status.configure(text=f"Заменено: {cnt}")

    def on_close(self):
        self.ed.clear_find_tags()
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ============================ F7: проверка ============================
class CheckDialog:
    def __init__(self, app):
        self.app = app
        self.ed = app.editor
        self.issues = []
        self.win = tk.Toplevel(app.root)
        self.win.title("Проверка орфографии и грамматики")
        self.win.geometry("560x420")
        self.win.transient(app.root)
        self.win.attributes("-topmost", True)

        ttk.Label(
            self.win,
            text="Выберите ошибку и замените или проигнорируйте:",
            padding=(10, 8, 10, 4),
        ).pack(anchor="w")

        body = ttk.Frame(self.win, padding=(10, 0, 10, 0))
        body.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(body, activestyle="dotbox", font=("Arial", 11))
        sb = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.listbox.bind("<Double-Button-1>", lambda e: None)

        frm = ttk.Frame(self.win, padding=10)
        frm.pack(fill="x")
        ttk.Label(frm, text="Заменить на:").pack(side="left")
        self.sugg = ttk.Combobox(frm, width=34)
        self.sugg.pack(side="left", padx=6)
        self.btn_rep = ttk.Button(frm, text="Заменить", command=self.on_replace)
        self.btn_rep.pack(side="left", padx=3)
        self.btn_skip = ttk.Button(frm, text="Игнорировать", command=self.on_skip)
        self.btn_skip.pack(side="left", padx=3)
        self.btn_dict = ttk.Button(frm, text="В словарь", command=self.on_dict)
        self.btn_dict.pack(side="left", padx=3)
        ttk.Button(frm, text="Закрыть", command=self.on_close).pack(side="right", padx=3)

        # заморозить редактирование
        self.prev_state = str(self.ed.text.cget("state"))
        try:
            self.ed.text.configure(state="disabled")
        except tk.TclError:
            pass
        self._collect()
        self._fill()
        if self.issues:
            self.listbox.selection_set(0)
            self.listbox.event_generate("<<ListboxSelect>>")
            self.sugg.focus_set()
        else:
            messagebox.showinfo(
                "Проверка",
                "Ошибок не найдено. Текст выглядит отлично!",
                parent=self.win)
            self.on_close()
        self.win.bind("<Escape>", lambda e: self.on_close())
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

    def _collect(self):
        ed = self.ed
        content = ed.text.get("1.0", "end-1c")
        self.content = content
        lang = self.app.settings.get("language", "auto")
        if self.app.settings.get("check_spelling", True):
            for s, e, w in ed.spell.find_errors(content):
                if w.lower() in ed.ignored_words:
                    continue
                has_cyr = any("а" <= c.lower() <= "я" or c in "ёЁ" for c in w)
                if lang == "auto" or (lang == "ru") == has_cyr:
                    cands = ed.spell.candidates(w, limit=6)
                    self.issues.append({
                        "kind": "spell", "start": s, "end": e,
                        "text": w, "msg": "Возможная орфографическая ошибка",
                        "sugg": cands,
                    })
        if self.app.settings.get("check_grammar", True):
            issues = ed.grammar.check(content)
            for it in issues:
                txt = content[it.start:it.end].strip()
                if (it.rule, txt) in ed.ignored_grammar:
                    continue
                suggs = []
                if it.suggestion:
                    suggs = [it.suggestion]
                self.issues.append({
                    "kind": "grammar", "start": it.start, "end": it.end,
                    "text": content[it.start:it.end],
                    "msg": it.message, "rule": it.rule,
                    "sugg": suggs, "source": it.source,
                })
        self.issues.sort(key=lambda x: x["start"])

    def _fill(self):
        self.listbox.delete(0, "end")
        for it in self.issues:
            icon = "🔤" if it["kind"] == "spell" else "📐"
            preview = it["text"].replace("\n", " ")
            if len(preview) > 30:
                preview = preview[:30] + "…"
            self.listbox.insert(
                "end", f"{icon}  «{preview}» — {it['msg'][:60]}")

    def on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        it = self.issues[sel[0]]
        self.sugg["values"] = it["sugg"]
        if it["sugg"]:
            self.sugg.set(it["sugg"][0])
        else:
            self.sugg.set("")
        # показать в тексте
        ed = self.ed
        from .editor import line_starts_of, offset_to_index

        starts = line_starts_of(self.content)
        a, b = offset_to_index(starts, it["start"]), offset_to_index(starts, it["end"])
        if a and b:
            ed.text.see(a)
            try:
                ed.text.tag_remove("find_cur", "1.0", "end")
                ed.text.tag_add("find_cur", a, b)
            except tk.TclError:
                pass

    def on_replace(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        it = self.issues[sel[0]]
        new = self.sugg.get()
        if not new:
            messagebox.showwarning("Замена", "Введите замену", parent=self.win)
            return
        ed = self.ed
        # разморозить для правки
        self._apply_span(it, new)
        self._rebuild(skip_index=sel[0])

    def _apply_span(self, it, new):
        from .editor import line_starts_of, offset_to_index

        ed = self.ed
        content_now = ed.text.get("1.0", "end-1c")
        # сопоставляем по тексту ошибки из собранного снимка
        starts = line_starts_of(self.content)
        a, b = offset_to_index(starts, it["start"]), offset_to_index(starts, it["end"])
        if not a or not b:
            return
        ed.undo_stack.begin("edit", a)
        try:
            ed.text.delete(a, b)
            ed.text.insert(a, new)
        except tk.TclError:
            pass
        ed.dirty = True
        self.app.update_title()
        ed._schedule_check()

    def on_skip(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        it = self.issues[sel[0]]
        if it["kind"] == "spell":
            self.ed.ignored_words.add(it["text"].lower())
        else:
            txt = self.content[it["start"]:it["end"]].strip()
            self.ed.ignored_grammar.add((it.get("rule", ""), txt))
        self.ed._schedule_check()
        self._rebuild(skip_index=sel[0])

    def on_dict(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        it = self.issues[sel[0]]
        if it["kind"] != "spell":
            return
        self.ed.spell.add_user_word(it["text"])
        self.ed._schedule_check()
        self._rebuild(skip_index=sel[0])

    def _rebuild(self, skip_index=None):
        idx = skip_index or 0
        # пересобрать снимок с учётом замен и игнорируемых
        self.issues = []
        self._collect()
        self._fill()
        if self.issues:
            idx = min(idx, len(self.issues) - 1)
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)
            self.on_select()
        else:
            self.on_close()

    def on_close(self):
        try:
            self.ed.text.tag_remove("find_cur", "1.0", "end")
            self.ed.text.configure(state=self.prev_state)
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# ============================ Шрифт ============================
class FontDialog:
    def __init__(self, app):
        self.app = app
        self.ed = app.editor
        fmt = ed_fmt = self.ed.selection_fmt()
        self.win = tk.Toplevel(app.root)
        self.win.title("Шрифт")
        self.win.resizable(False, False)
        self.win.transient(app.root)
        self.win.attributes("-topmost", True)

        frm = ttk.Frame(self.win, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frm, text="Семейство:").grid(row=0, column=0, sticky="w")
        fams = sorted({f for f in tkfont.families() if not f.startswith("@")})
        common = ["Arial", "Calibri", "Cambria", "Times New Roman", "Courier New",
                  "Verdana", "Tahoma", "Georgia", "Segoe UI", "DejaVu Sans"]
        ordered = [f for f in common if f in fams] + [f for f in fams if f not in common]
        self.fam = ttk.Combobox(frm, values=ordered, width=30, height=14)
        self.fam.set(fmt.get("font") or (ordered[0] if ordered else "Arial"))
        self.fam.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(frm, text="Начертание:").grid(row=1, column=0, sticky="w")
        b, i = bool(fmt.get("bold")), bool(fmt.get("italic"))
        style = "Полужирный курсив" if (b and i) else "Полужирный" if b else "Курсив" if i else "Обычный"
        self.style = ttk.Combobox(
            frm, values=["Обычный", "Курсив", "Полужирный", "Полужирный курсив"],
            width=28, state="readonly")
        self.style.set(style)
        self.style.grid(row=1, column=1, columnspan=3, sticky="ew", pady=2)

        ttk.Label(frm, text="Размер:").grid(row=2, column=0, sticky="w")
        self.size = ttk.Combobox(
            frm, values=["8", "9", "10", "11", "12", "14", "16", "18", "20", "22",
                         "24", "26", "28", "36", "48", "72"], width=10)
        self.size.set(str(fmt.get("size") or 11))
        self.size.grid(row=2, column=1, sticky="w", pady=2)

        self.u_var = tk.BooleanVar(value=bool(fmt.get("underline")))
        self.s_var = tk.BooleanVar(value=bool(fmt.get("strike")))
        ttk.Checkbutton(frm, text="Подчёркнутый", variable=self.u_var).grid(
            row=2, column=2, sticky="w", padx=8)
        ttk.Checkbutton(frm, text="Зачёркнутый", variable=self.s_var).grid(
            row=2, column=3, sticky="w")

        ttk.Label(frm, text="Цвет:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.color = fmt.get("color") or "#000000"
        self.color_btn = tk.Button(
            frm, width=6, bg=self.color,
            command=self.pick_color, relief="groove")
        self.color_btn.grid(row=3, column=1, sticky="w", pady=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=4, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=self.win.destroy).pack(side="left", padx=4)
        self.win.bind("<Return>", lambda e: self.on_ok())

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color, parent=self.win, title="Цвет шрифта")
        if c and c[1]:
            self.color = c[1]
            self.color_btn.configure(bg=self.color)

    def on_ok(self):
        ed = self.ed
        ed.set_font_family(self.fam.get())
        ed.set_font_size(int(self.size.get() or 11))
        style = self.style.get()
        ed.apply_char("bold", style in ("Полужирный", "Полужирный курсив"))
        ed.apply_char("italic", style in ("Курсив", "Полужирный курсив"))
        ed.apply_char("underline", self.u_var.get())
        ed.apply_char("strike", self.s_var.get())
        if self.color and self.color.lower() not in ("#000000", "#000"):
            ed.set_font_color(self.color)
        self.win.destroy()


# ============================ Абзац ============================
class ParagraphDialog:
    def __init__(self, app):
        self.app = app
        self.ed = app.editor
        pfmt = self.ed.current_para_info()
        self.win = tk.Toplevel(app.root)
        self.win.title("Абзац")
        self.win.resizable(False, False)
        self.win.transient(app.root)
        self.win.attributes("-topmost", True)
        frm = ttk.Frame(self.win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Выравнивание:").grid(row=0, column=0, sticky="w")
        self.align = tk.StringVar(value=pfmt["align"])
        for k, (val, lab) in enumerate([
            ("left", "По левому краю"), ("center", "По центру"),
            ("right", "По правому краю"), ("justify", "По ширине")]):
            ttk.Radiobutton(frm, text=lab, value=val, variable=self.align).grid(
                row=1 + k // 2, column=k % 2, sticky="w", padx=6)

        ttk.Label(fram := frm, text="Межстрочный интервал:").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.line = ttk.Combobox(frm, values=["1.0", "1.15", "1.5", "2.0"], width=8)
        self.line.set("1.15")
        self.line.grid(row=3, column=1, sticky="w", pady=(10, 0))

        ttk.Label(frm, text="Интервал после (пт):").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.after_sp = ttk.Combobox(
            frm, values=["0", "6", "8", "10", "12", "18"], width=8)
        self.after_sp.set("6")
        self.after_sp.grid(row=4, column=1, sticky="w", pady=(6, 0))

        ttk.Label(frm, text="Отступ слева (px):").grid(row=5, column=0, sticky="w", pady=(6, 0))
        self.ind_left = ttk.Combobox(frm, values=["0", "24", "48", "72", "96"], width=8)
        self.ind_left.set("0")
        self.ind_left.grid(row=5, column=1, sticky="w", pady=(6, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=self.win.destroy).pack(side="left", padx=4)

    def on_ok(self):
        self.ed.set_align(self.align.get())
        try:
            self.ed.set_line_spacing(float(self.line.get()))
        except ValueError:
            pass
        try:
            self.ed.set_space_after(float(self.after_sp.get()))
        except ValueError:
            pass
        try:
            self.ed.set_indent("left", int(self.ind_left.get()))
        except ValueError:
            pass
        self.win.destroy()


# ============================ Таблица ============================
class TableDialog:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Вставка таблицы")
        self.win.resizable(False, False)
        self.win.transient(app.root)
        self.win.attributes("-topmost", True)
        frm = ttk.Frame(self.win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Строк:").grid(row=0, column=0, sticky="w", pady=4)
        self.rows = ttk.Spinbox(frm, from_=1, to=50, width=8)
        self.rows.set(3)
        self.rows.grid(row=0, column=1, pady=4, padx=8)
        ttk.Label(frm, text="Столбцов:").grid(row=1, column=0, sticky="w", pady=4)
        self.cols = ttk.Spinbox(frm, from_=1, to=20, width=8)
        self.cols.set(3)
        self.cols.grid(row=1, column=1, pady=4, padx=8)
        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Вставить", command=self.on_ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=self.win.destroy).pack(side="left", padx=4)
        self.win.bind("<Return>", lambda e: self.on_ok())

    def on_ok(self):
        try:
            rows = max(1, int(self.rows.get()))
            cols = max(1, int(self.cols.get()))
        except (ValueError, tk.TclError):
            rows, cols = 3, 3
        self.app.editor.insert_table(rows, cols)
        self.win.destroy()


# ============================ Параметры страницы ============================
class PageDialog:
    def __init__(self, app):
        self.app = app
        m = app.settings.get("margins_cm", [2.0, 2.0, 2.0, 2.0])
        self.win = tk.Toplevel(app.root)
        self.win.title("Параметры страницы")
        self.win.resizable(False, False)
        self.win.transient(app.root)
        self.win.attributes("-topmost", True)
        frm = ttk.Frame(self.win, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Формат: A4 (210 × 297 мм)").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.vars = []
        for k, lab in enumerate(["Верхнее (см)", "Нижнее (см)", "Левое (см)", "Правое (см)"]):
            ttk.Label(frm, text=lab).grid(row=1 + k, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=str(m[k]))
            ttk.Entry(frm, textvariable=v, width=8).grid(
                row=1 + k, column=1, padx=8, pady=3)
            self.vars.append(v)
        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="OK", command=self.on_ok).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=self.win.destroy).pack(side="left", padx=4)

    def on_ok(self):
        try:
            margins = [max(0.5, min(10.0, float(v.get().replace(",", ".")))) for v in self.vars]
        except ValueError:
            margins = [2.0, 2.0, 2.0, 2.0]
        self.app.settings["margins_cm"] = margins
        self.app.save_settings()
        self.win.destroy()


# ============================ О программе ============================
class AboutDialog:
    def __init__(self, app):
        win = tk.Toplevel(app.root)
        win.title("О программе")
        win.resizable(False, False)
        win.transient(app.root)
        win.attributes("-topmost", True)
        frm = ttk.Frame(win, padding=20)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="WordFree", font=("Arial", 20, "bold")).pack(anchor="w")
        ttk.Label(frm, text="Бесплатный текстовый редактор",
                  font=("Arial", 12)).pack(anchor="w", pady=(2, 10))
        info = (
            "Версия: 1.0\n"
            "Лицензия: свободное ПО, использование бесплатно.\n\n"
            "Возможности:\n"
            "• форматирование текста, стили заголовков, списки;\n"
            "• проверка орфографии (рус./англ.) и грамматики\n"
            "  (LanguageTool, при наличии Java);\n"
            "• таблицы, картинки, разрыв страницы;\n"
            "• открытие и сохранение .docx, экспорт в PDF, печать;\n"
            "• найти/заменить, отмена/повтор, вставка даты.\n\n"
            "Горячие клавиши: Ctrl+B/I/U, Ctrl+F/H, F7, Ctrl+S, Ctrl+P.\n\n"
            "Спасибо проектам LanguageTool, pyspellchecker,\n"
            "python-docx и reportlab."
        )
        ttk.Label(frm, text=info, justify="left").pack(anchor="w", pady=(0, 12))
        ttk.Button(frm, text="OK", command=win.destroy).pack(anchor="e")
