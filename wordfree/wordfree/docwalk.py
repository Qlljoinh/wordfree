"""Обход содержимого Text-виджета: превращает его в модель блоков (абзацы, таблицы, картинки).

Модель используется при сохранении в .docx и при экспорте в PDF.

Блок-абзац:
  {
    'type': 'paragraph',
    'start': '2.0', 'end': '2.end',          # индексы в Text
    'pfmt':  {'align': 'left', 'style': 'normal'|'h1'|'h2'|'h3',
              'list': None|'bullet'|'number', 'line_spacing': 1.0,
              'space_after': 0, 'indent_left': 0, 'indent_first': 0,
              'page_break': False},
    'flow':  [ {'kind':'text','fmt':{...},'text':'...'} |
               {'kind':'image','name':'img3','index':'2.5'} ]
  }
Блок-таблица:
  { 'type':'table', 'table_id': 3, 'start': '4.0', 'end': '5.0' }

fmt (символьный): {'bold','italic','underline','strike','font','size','color','highlight'}
Размеры отступов — в пикселях (как в Tk); в docx/pdf переводятся в пункты (1pt = 4/3 px).
"""

CHAR_TAG_EXACT = ("b", "i", "u", "s")
CHAR_TAG_PREFIXES = ("font_", "size_", "color_", "hl_")

PX_PER_PT = 96.0 / 72.0  # пиксели на пункт (Tk считает положительный размер в пунктах, но отступы — в пикселях экрана)


def _is_char_tag(name):
    return name in CHAR_TAG_EXACT or name.startswith(CHAR_TAG_PREFIXES)


def parse_char_tags(tagnames):
    fmt = {}
    for t in tagnames:
        if t == "b":
            fmt["bold"] = True
        elif t == "i":
            fmt["italic"] = True
        elif t == "u":
            fmt["underline"] = True
        elif t == "s":
            fmt["strike"] = True
        elif t.startswith("font_"):
            fmt["font"] = t[5:].replace("_", " ")
        elif t.startswith("size_"):
            try:
                fmt["size"] = int(t[5:])
            except ValueError:
                pass
        elif t.startswith("color_"):
            fmt["color"] = "#" + t[6:]
        elif t.startswith("hl_"):
            fmt["highlight"] = "#" + t[6:]
    return fmt


def parse_paragraph_tags(tagnames):
    pfmt = {
        "align": "left",
        "style": "normal",
        "list": None,
        "line_spacing": 1.0,
        "space_after": 0,
        "indent_left": 0,
        "indent_first": 0,
        "page_break": False,
    }
    for t in tagnames:
        if t in ("al_left", "al_center", "al_right", "al_justify"):
            pfmt["align"] = t[3:]
        elif t in ("style_h1", "style_h2", "style_h3"):
            pfmt["style"] = t[6:]
        elif t == "list_bullet":
            pfmt["list"] = "bullet"
        elif t == "list_number":
            pfmt["list"] = "number"
        elif t.startswith("sp_line_"):
            try:
                pfmt["line_spacing"] = float(t[8:])
            except ValueError:
                pass
        elif t.startswith("sp_after_"):
            try:
                pfmt["space_after"] = int(t[9:])
            except ValueError:
                pass
        elif t.startswith("ind_left_"):
            try:
                pfmt["indent_left"] = int(t[9:])
            except ValueError:
                pass
        elif t.startswith("ind_first_"):
            try:
                pfmt["indent_first"] = int(t[10:])
            except ValueError:
                pass
        elif t == "pb":
            pfmt["page_break"] = True
    return pfmt


def px_to_pt(px):
    return px / PX_PER_PT


def _pos(ix):
    """Индекс 'строка.колонка' (или 'строка.end') -> кортеж для корректных сравнений."""
    line, col = ix.split(".", 1)
    return (int(line), int(col) if col.isdigit() else 10 ** 9)


def iter_blocks(text):
    """Генератор блоков по содержимому виджета text (tk.Text)."""
    last_line = int(text.index("end-1c").split(".")[0])
    all_tags = list(text.tag_names())
    char_tags = [t for t in all_tags if _is_char_tag(t)]
    img_tags = [t for t in all_tags if t.startswith("img_")]

    for ln in range(1, last_line + 1):
        start = f"{ln}.0"
        end = f"{ln}.end"
        tags_at = text.tag_names(start)

        # таблица?
        tbl = [t for t in tags_at if t.startswith("tbl_")]
        if tbl:
            yield {
                "type": "table",
                "table_id": int(tbl[0][4:]),
                "start": start,
                "end": f"{ln + 1}.0",
            }
            continue

        pfmt = parse_paragraph_tags(tags_at)

        # границы сегментов внутри строки
        ls, le = _pos(start), _pos(end)
        bounds = {ls, le}
        for tag in char_tags + img_tags:
            ranges = text.tag_ranges(tag)
            for i in range(0, len(ranges), 2):
                sp, ep = _pos(str(ranges[i])), _pos(str(ranges[i + 1]))
                if ep <= ls or sp >= le:
                    continue
                if sp > ls:
                    bounds.add(sp)
                if ep < le:
                    bounds.add(ep)
        ordered = sorted(bounds)
        ordered = [f"{l}.{c}" for l, c in ordered]

        flow = []
        for a, b in zip(ordered, ordered[1:]):
            seg_text = text.get(a, b)
            if seg_text == "":
                continue
            seg_tags = text.tag_names(a)
            img = [t for t in seg_tags if t.startswith("img_")]
            if "\ufffc" in seg_text:
                if img:
                    flow.append({"kind": "image", "name": img[0][4:], "index": a})
                continue
            fmt = parse_char_tags(seg_tags)
            if flow and flow[-1]["kind"] == "text" and flow[-1]["fmt"] == fmt:
                flow[-1]["text"] += seg_text
            else:
                flow.append({"kind": "text", "fmt": fmt, "text": seg_text})

        yield {"type": "paragraph", "start": start, "end": end, "pfmt": pfmt, "flow": flow}
