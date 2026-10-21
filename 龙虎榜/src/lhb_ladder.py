# -*- coding: utf-8 -*-
"""天梯风渲染：白底、红字标题、红色席位标签 + 圆角个股卡片。

参考「游资龙虎榜」天梯版式：每行一个席位，4 个股票一行；拉萨天团 6 个一行。
输出固定 3:4。
"""
from PIL import Image, ImageDraw

from lhb_build import fmt_amount
from lhb_render import _font, _hex, _fit_canvas

W = 1080
M = 30                    # 左右页边距
SEAT_W = 108              # 红色席位标签宽度
SEAT_H = 32
SEAT_GAP = 10
CARD_PAD_X = 6
CARD_PAD_Y = 4
COLS = 4
NAME_COLS = 6
CELL_H = 30
CELL_GAP = 8
LINE_GAP = 5
ROW_GAP = 5

C_RED = "#E03131"
C_GREEN = "#159A55"
C_CELL = "#F6F7F9"
C_CELL_LINE = "#ECEDF0"
C_ROW_LINE = "#E9EAED"
C_INK = "#1A1A1A"
C_GRAY = "#9A9FA8"


def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def _row_lines(row, style):
    max_lines = style.get("max_lines", {})
    dflt = max_lines.get("_default", 3)
    if row["kind"] == "names":
        return _chunks(row["items"], NAME_COLS)
    limit = max_lines.get(row["label"], dflt)
    return _chunks(row["items"][:limit * COLS], COLS)


def _seat_pill(d, x, y, label, style):
    size = 18
    f = _font(style["font_bold"], size)
    while d.textlength(label, font=f) > SEAT_W - 10 and size > 11:
        size -= 1
        f = _font(style["font_bold"], size)
    d.text((x + SEAT_W / 2, y + SEAT_H / 2), label, font=f,
           fill=_hex(C_INK), anchor="mm")


def _draw_cell(d, x, y, w, h, item, kind, style, c_up, c_down):
    d.rounded_rectangle([x, y, x + w, y + h], radius=6,
                        fill=_hex(C_CELL), outline=_hex(C_CELL_LINE), width=1)
    cy = y + h / 2.0
    if kind == "names":
        size = 18
        f = _font(style["font_bold"], size)
        while d.textlength(item["name"], font=f) > w - 10 and size > 11:
            size -= 1
            f = _font(style["font_bold"], size)
        d.text((x + w / 2, cy), item["name"], font=f, fill=_hex(C_INK), anchor="mm")
        return

    up = item["net"] > 0
    col = _hex(c_up if up else c_down)
    f_chip = _font(style["font_bold"], 12)
    chip = "净买" if up else "净卖"
    cw = int(d.textlength(chip, font=f_chip)) + 12
    ch = 21

    name = item["name"]
    size = 18
    f_name = _font(style["font_bold"], size)
    while d.textlength(name, font=f_name) > w - (cw + 58) and size > 12:
        size -= 1
        f_name = _font(style["font_bold"], size)
    f_tag = _font(style["font_bold"], 9)
    tag = "(三日)" if item.get("three") else ""
    f_amt = _font(style["font_bold"], 15)
    amt = fmt_amount(item["net"])

    x0 = x + 6
    d.rounded_rectangle([x0, cy - ch / 2, x0 + cw, cy + ch / 2], radius=4, fill=col)
    d.text((x0 + cw / 2, cy), chip, font=f_chip, fill=(255, 255, 255), anchor="mm")
    x0 += cw + 4

    d.text((x0, cy), name, font=f_name, fill=_hex(C_INK), anchor="lm")
    x0 += d.textlength(name, font=f_name)
    if tag:
        d.text((x0 + 2, cy + 1), tag, font=f_tag, fill=_hex(C_GRAY), anchor="lm")
        x0 += d.textlength(tag, font=f_tag) + 2
    x0 += 4
    d.text((x0, cy), amt, font=f_amt, fill=col, anchor="lm")


def _draw_row(d, yy, row, lines, style, c_up, c_down):
    n = max(1, len(lines))
    h = CARD_PAD_Y * 2 + n * CELL_H + (n - 1) * LINE_GAP
    d.rounded_rectangle([M, yy, W - M, yy + h], radius=8,
                        fill=(255, 255, 255), outline=_hex(C_ROW_LINE), width=1)
    _seat_pill(d, M + CARD_PAD_X, yy + (h - SEAT_H) / 2, row["label"], style)

    x0 = M + CARD_PAD_X + SEAT_W + SEAT_GAP
    area = (W - M - CARD_PAD_X) - x0
    cols = NAME_COLS if row["kind"] == "names" else COLS
    cw = (area - (cols - 1) * CELL_GAP) / float(cols)

    for ln, line in enumerate(lines):
        cy = yy + CARD_PAD_Y + ln * (CELL_H + LINE_GAP)
        for i, item in enumerate(line):
            cx = x0 + i * (cw + CELL_GAP)
            _draw_cell(d, cx, cy, cw, CELL_H, item, row["kind"], style, c_up, c_down)
    return h


def _draw_header(d, board, style):
    top = 22
    f_title = _font(style["font_bold"], 43)
    d.rounded_rectangle([M, top + 2, M + 6, top + 46], radius=3, fill=_hex(C_RED))
    x = M + 18
    date_txt = "%d月%d日" % (board["m"], board["d"])
    d.text((x, top + 24), date_txt, font=f_title, fill=_hex(C_INK), anchor="lm")
    x += d.textlength(date_txt, font=f_title) + 10
    d.text((x, top + 24), "游资龙虎榜", font=f_title, fill=_hex(C_RED), anchor="lm")

    # 右上角图例
    f_leg = _font(style["font_bold"], 15)
    pad, gap, lh = 12, 10, 28
    ly = top + 10
    w1 = int(d.textlength("净买", font=f_leg)) + pad * 2
    w2 = int(d.textlength("净卖", font=f_leg)) + pad * 2
    x2 = W - M - w2
    x1 = x2 - gap - w1
    for x, text, color in ((x1, "净买", C_RED), (x2, "净卖", C_GREEN)):
        d.rounded_rectangle([x, ly, x + (w1 if text == "净买" else w2), ly + lh],
                            radius=5, fill=_hex(color))
        d.text((x + (w1 if text == "净买" else w2) / 2, ly + lh / 2), text,
               font=f_leg, fill=(255, 255, 255), anchor="mm")

    # 红色分隔线
    d.rectangle([M, 78, W, 83], fill=_hex(C_RED))
    return 92


def render_png(board, style, out_path):
    c_up, c_down = style.get("color_up", "#D63333"), style.get("color_down", "#159A55")

    rows = []
    body_h = 0
    for row in board["rows"]:
        lines = _row_lines(row, style)
        n = max(1, len(lines))
        h = CARD_PAD_Y * 2 + n * CELL_H + (n - 1) * LINE_GAP
        rows.append((row, lines, h))
        body_h += h + ROW_GAP
    body_h = max(0, body_h - ROW_GAP)

    top = 92
    H = int(top + body_h + 30)

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    _draw_header(d, board, style)

    yy = top
    for row, lines, h in rows:
        _draw_row(d, yy, row, lines, style, c_up, c_down)
        yy += h + ROW_GAP

    f_foot = _font(style["font_bold"], 10)
    d.text((W / 2, H - 15),
           "红色为净买，绿色为净卖；数据由公开信息整理，仅供参考，不构成投资建议。",
           font=f_foot, fill=_hex(C_GRAY), anchor="mm")

    img = _fit_canvas(img, style)
    img.save(out_path, "PNG")
    return out_path, img.width, img.height
