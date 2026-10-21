# -*- coding: utf-8 -*-
"""天梯风渲染：白底、红字标题、黑色席位名 + 圆角个股卡片。

参考「游资龙虎榜」天梯版式：每行一个席位，4 个股票一行；拉萨天团 6 个一行。
输出固定 3:4 高清图（2160×2880）。
"""
from PIL import Image, ImageDraw

from lhb_build import fmt_amount
from lhb_render import _font, _hex, _fit_canvas

K = 2                      # 2 倍高清
W = 1080 * K
M = 12 * K                 # 左右页边距（尽量填满画面）
SEAT_W = 124 * K           # 席位名列宽（按 5 字名称为准整体放大）
SEAT_H = 26 * K
SEAT_GAP = 10 * K
CARD_PAD_X = 6 * K
CARD_PAD_Y = 3 * K
COLS = 4
NAME_COLS = 6
CELL_H = 24.5 * K
CELL_GAP = 8 * K
LINE_GAP = 3 * K
ROW_GAP = 3 * K

C_RED = "#E41A1A"
C_GREEN = "#169668"
C_PAGE = "#FAF5F2"
C_CELL = "#FBF7F3"
C_ROW_LINE = "#F4E6DF"
C_INK = "#26201E"
C_GRAY = "#A99C95"
C_FOOT_LINE = "#EFE3DC"


def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def _row_lines(row, style):
    max_lines = style.get("max_lines", {})
    dflt = max_lines.get("_default", 3)
    if row["kind"] == "names":
        return _chunks(row["items"], NAME_COLS)
    limit = max_lines.get(row["label"], dflt)
    return _chunks(row["items"][:limit * COLS], COLS)


def _seat_size(labels, style, d):
    """以最长的 5 字席位名为统一标准，所有席位名用同一字号。"""
    size = 24 * K
    avail = SEAT_W - 12 * K
    while size > 12 * K:
        f = _font(style["font_bold"], size)
        if all(d.textlength(t, font=f) <= avail for t in labels):
            return size
        size -= 1
    return 12 * K


def _seat_name(d, x, y, label, size, style):
    """席位名：左对齐，字号统一。"""
    d.text((x + 8 * K, y + SEAT_H / 2), label,
           font=_font(style["font_bold"], size),
           fill=_hex(C_INK), anchor="lm")


def _draw_cell(d, x, y, w, h, item, kind, style, c_up, c_down):
    d.rounded_rectangle([x, y, x + w, y + h], radius=6 * K, fill=_hex(C_CELL))
    cy = y + h / 2.0
    if kind == "names":
        size = 19 * K
        f = _font(style["font_bold"], size)
        while d.textlength(item["name"], font=f) > w - 10 * K and size > 12 * K:
            size -= 1
            f = _font(style["font_bold"], size)
        d.text((x + w / 2, cy), item["name"], font=f, fill=_hex(C_INK), anchor="mm")
        return

    up = item["net"] > 0
    col = _hex(c_up if up else c_down)
    f_chip = _font(style["font_bold"], 12 * K)
    chip = "净买" if up else "净卖"
    cw = int(d.textlength(chip, font=f_chip)) + 12 * K
    ch = 18 * K

    name = item["name"]
    size = 19 * K
    f_name = _font(style["font_bold"], size)
    while d.textlength(name, font=f_name) > w - (cw + 58 * K) and size > 12 * K:
        size -= 1
        f_name = _font(style["font_bold"], size)
    f_tag = _font(style["font_bold"], 9 * K)
    tag = "(三日)" if item.get("three") else ""
    f_amt = _font(style["font_bold"], 15 * K)
    amt = fmt_amount(item["net"])

    x0 = x + 6 * K
    d.rounded_rectangle([x0, cy - ch / 2, x0 + cw, cy + ch / 2], radius=4 * K, fill=col)
    d.text((x0 + cw / 2, cy), chip, font=f_chip, fill=(255, 255, 255), anchor="mm")
    x0 += cw + 4 * K

    d.text((x0, cy), name, font=f_name, fill=_hex(C_INK), anchor="lm")
    x0 += d.textlength(name, font=f_name)
    if tag:
        d.text((x0 + 2 * K, cy + 1 * K), tag, font=f_tag, fill=_hex(C_GRAY), anchor="lm")
        x0 += d.textlength(tag, font=f_tag) + 2 * K
    x0 += 4 * K
    d.text((x0, cy), amt, font=f_amt, fill=col, anchor="lm")


def _draw_row(d, yy, row, lines, style, c_up, c_down, seat_size):
    n = max(1, len(lines))
    h = CARD_PAD_Y * 2 + n * CELL_H + (n - 1) * LINE_GAP
    d.rounded_rectangle([M, yy, W - M, yy + h], radius=8 * K,
                        fill=(255, 255, 255), outline=_hex(C_ROW_LINE), width=1 * K)
    _seat_name(d, M + CARD_PAD_X, yy + (h - SEAT_H) / 2, row["label"], seat_size, style)

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


def _draw_legend(d, style):
    """右上角「净买 / 净卖」图例。"""
    f = _font(style["font_bold"], 15 * K)
    pad, gap, lh = 12 * K, 10 * K, 28 * K
    ly = 32 * K
    w1 = int(d.textlength("净买", font=f)) + pad * 2
    w2 = int(d.textlength("净卖", font=f)) + pad * 2
    x2 = W - M - w2
    x1 = x2 - gap - w1
    for x, text, color, w in ((x1, "净买", C_RED, w1), (x2, "净卖", C_GREEN, w2)):
        d.rounded_rectangle([x, ly, x + w, ly + lh], radius=5 * K, fill=_hex(color))
        d.text((x + w / 2, ly + lh / 2), text, font=f, fill=(255, 255, 255), anchor="mm")


def _draw_header(d, board, style):
    f_title = _font(style["font_bold"], 52 * K)
    date_txt = "%d月%d日" % (board["m"], board["d"])
    red_txt = "游资龙虎榜"
    gap = 10 * K
    w_date = d.textlength(date_txt, font=f_title)
    w_red = d.textlength(red_txt, font=f_title)

    if style.get("center_title"):
        x = (W - (w_date + gap + w_red)) / 2
    else:
        x = M

    d.text((x, 58 * K), date_txt, font=f_title, fill=_hex(C_INK), anchor="lm")
    x += w_date + gap
    d.text((x, 58 * K), red_txt, font=f_title, fill=_hex(C_RED), anchor="lm")

    if style.get("show_legend"):
        _draw_legend(d, style)

    # 红色分隔线
    d.rectangle([M, 100 * K, W - M, 103 * K], fill=_hex(C_RED))
    return 112 * K


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

    top = 112 * K
    H = int(top + body_h + 51 * K)

    img = Image.new("RGB", (W, H), _hex(C_PAGE))
    d = ImageDraw.Draw(img)
    _draw_header(d, board, style)
    seat_size = _seat_size([r["label"] for r in board["rows"]], style, d)

    yy = top
    for row, lines, h in rows:
        _draw_row(d, yy, row, lines, style, c_up, c_down, seat_size)
        yy += h + ROW_GAP

    # 页脚分隔线 + 说明文字
    d.rectangle([M, H - 40 * K, W - M, H - 40 * K + 1 * K], fill=_hex(C_FOOT_LINE))
    f_foot = _font(style["font_bold"], 10 * K)
    d.text((W / 2, H - 20 * K),
           "红色为净买，绿色为净卖；数据由公开信息整理，仅供参考，不构成投资建议。",
           font=f_foot, fill=_hex(C_GRAY), anchor="mm")

    st = dict(style)
    st["fit"] = {"enabled": True, "w": W, "h": W * 4 // 3,
                 "pad": 0, "max_scale": 1, "bg": C_PAGE}
    img = _fit_canvas(img, st)
    img.save(out_path, "PNG")
    return out_path, img.width, img.height
