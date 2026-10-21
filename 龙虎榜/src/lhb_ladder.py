# -*- coding: utf-8 -*-
"""天梯风渲染：白底、顶部指数、彩色标签、红色分组条、左侧红色席位块 + 右侧卡片网格。

参考「连板天梯」版式做龙虎榜适配，输出固定 3:4。
"""
import math

from PIL import Image, ImageDraw

from lhb_render import _font, _hex, _fit_canvas

W = 1080
M = 40                    # 左右页边距
BLOCK_W = 60              # 左侧红色席位块宽度
CARD_X = M + BLOCK_W
CARD_W = W - M - CARD_X
COLS = 6                  # 每行股票数
CELL_W = CARD_W / float(COLS)
LINE_H = 30               # 单元格行高
PAD_Y = 2                 # 卡片上下内边距
SEC_GAP = 4               # 分组间距
FOOT_H = 26

C_RED = "#E03131"
C_BG = "#F6F7F9"
C_DIV = "#E6E8EC"
C_INK = "#1F1F1F"
C_GRAY = "#8A9099"
C_UP = "#D63333"
C_DOWN = "#129A55"

PILL_COLORS = [
    ("#D63333", "#FFF0F0", "#F2B8B8"),
    ("#1E6FD9", "#EEF4FF", "#BBD1F2"),
    ("#C77700", "#FFF6E8", "#F2D3A0"),
]
PILL_GRAY = ("#6B7280", "#F6F7F9", "#E1E4E8")


def _cn_amount(v):
    a = abs(v)
    if a >= 1e8:
        return "%.2f亿" % (a / 1e8)
    return "%.0f万" % (a / 1e4)


def _pill_items(board, limit=7):
    pairs = [(r["label"], len(r["items"])) for r in board["rows"]]
    pairs.sort(key=lambda kv: (-kv[1], kv[0]))
    head = pairs[:limit]
    rest = pairs[limit:]
    if rest:
        head.append(("其他", sum(c for _, c in rest)))
    return head


def _pill_layout(d, board, style, top):
    font = _font(style["font_bold"], 12)
    pads, gap = 11, 8
    x, y = M, top
    placed = []
    for i, (label, count) in enumerate(_pill_items(board)):
        text = "%s(%d)" % (label, count)
        pw = int(d.textlength(text, font=font)) + pads * 2
        if x + pw > W - M:
            x, y = M, y + 26 + 6
        placed.append((x, y, pw, 26, text, i))
        x += pw + gap
    return placed, y + 26


def _wrap_chars(text, per_line=3):
    return [text[i:i + per_line] for i in range(0, len(text), per_line)]


def _draw_header(d, board, style, market, top, c_up, c_down):
    title_font = _font(style["font_bold"], 36)
    date_txt = "%d月%d日" % (board["m"], board["d"])
    # 左侧红竖条 + 日期 + 红色主题
    d.rounded_rectangle([M, top + 3, M + 6, top + 49], radius=3, fill=_hex(C_RED))
    x = M + 18
    d.text((x, top + 26), date_txt, font=title_font, fill=_hex(C_INK), anchor="lm")
    x += d.textlength(date_txt, font=title_font) + 10
    d.text((x, top + 26), "游资龙虎榜", font=title_font, fill=_hex(C_RED), anchor="lm")

    # 右侧指数
    idx = (market or {}).get("index")
    if idx:
        f_lab = _font(style["font_bold"], 12)
        f_big = _font(style["font_bold"], 28)
        f_chg = _font(style["font_bold"], 15)
        col = _hex(c_up if idx["chg_pct"] >= 0 else c_down)
        d.text((W - M, top + 6), "上证指数", font=f_lab, fill=_hex(C_GRAY), anchor="rm")
        chg = "%+.2f%%" % idx["chg_pct"]
        cw = d.textlength(chg, font=f_chg)
        d.text((W - M, top + 34), chg, font=f_chg, fill=col, anchor="rm")
        d.text((W - M - cw - 10, top + 34), "%.2f" % idx["point"],
               font=f_big, fill=col, anchor="rm")
        m = market or {}
        if m.get("up") is not None and m.get("down") is not None:
            f_s = _font(style["font_bold"], 12)
            dy = top + 62
            t1, t2 = "涨 %d" % m["up"], "跌 %d" % m["down"]
            w2 = d.textlength(t2, font=f_s)
            d.text((W - M, dy), t2, font=f_s, fill=_hex(c_down), anchor="rm")
            d.text((W - M - w2 - 14, dy), t1, font=f_s, fill=_hex(c_up), anchor="rm")
        elif m.get("zt") is not None:
            f_s = _font(style["font_bold"], 12)
            dy = top + 62
            t1 = "涨停 %d" % m["zt"]
            t2 = "跌停 %d" % m.get("dt", 0)
            w2 = d.textlength(t2, font=f_s)
            d.text((W - M, dy), t2, font=f_s, fill=_hex(c_down), anchor="rm")
            d.text((W - M - w2 - 14, dy), t1, font=f_s, fill=_hex(c_up), anchor="rm")

    # 风险提示
    f_note = _font(style["font_bold"], 11)
    note = "风险提示：内容仅为公开市场数据整理，不构成投资建议，历史表现不代表未来走势。"
    d.text((M, top + 76), note, font=f_note, fill=_hex("#9AA0A6"), anchor="lm")

    # 标签
    pills, bottom = _pill_layout(d, board, style, top + 94)
    f_pill = _font(style["font_bold"], 12)
    for x, y, pw, ph, text, i in pills:
        fg, bg, bd = PILL_COLORS[i] if i < len(PILL_COLORS) else PILL_GRAY
        d.rounded_rectangle([x, y, x + pw, y + ph], radius=ph / 2,
                            fill=_hex(bg), outline=_hex(bd))
        d.text((x + pw / 2, y + ph / 2), text, font=f_pill, fill=_hex(fg), anchor="mm")

    # 红色栏目条
    bar_top = bottom + 8
    d.rounded_rectangle([M, bar_top, W - M, bar_top + 28], radius=5, fill=_hex(C_RED))
    f_bar = _font(style["font_bold"], 14)
    d.text((W / 2, bar_top + 14), "游资席位 · 净买 / 净卖 · 个股",
           font=f_bar, fill=(255, 255, 255), anchor="mm")
    return bar_top + 38


def _draw_cell(d, x, y, w, h, item, kind, style, c_up, c_down):
    cy = y + h / 2.0
    if kind == "names":
        size = 15
        f = _font(style["font_bold"], size)
        while d.textlength(item["name"], font=f) > w - 12 and size > 10:
            size -= 1
            f = _font(style["font_bold"], size)
        d.text((x + w / 2, cy), item["name"], font=f, fill=_hex(C_INK), anchor="mm")
        return

    up = item["net"] > 0
    col, col_hex = (_hex(c_up), c_up) if up else (_hex(c_down), c_down)
    f_badge = _font(style["font_bold"], 9)
    bw, bh = 16, 15
    size = 15
    f_name = _font(style["font_bold"], size)
    name = item["name"]
    while d.textlength(name, font=f_name) > w - 66 and size > 11:
        size -= 1
        f_name = _font(style["font_bold"], size)
    f_amt = _font(style["font_bold"], 11)
    tag = "(三日)" if item.get("three") else ""
    f_tag = _font(style["font_bold"], 8)
    amt = _cn_amount(item["net"])

    nw = d.textlength(name, font=f_name)
    tw = d.textlength(tag, font=f_tag) if tag else 0
    aw = d.textlength(amt, font=f_amt)
    total = bw + 5 + nw + ((tw + 3) if tag else 0) + 6 + aw
    sx = x + max(4, (w - total) / 2.0)

    d.rounded_rectangle([sx, cy - bh / 2, sx + bw, cy + bh / 2], radius=3, fill=col)
    d.text((sx + bw / 2, cy), "买" if up else "卖", font=f_badge,
           fill=(255, 255, 255), anchor="mm")
    sx += bw + 5
    d.text((sx, cy), name, font=f_name, fill=col, anchor="lm")
    sx += nw
    if tag:
        d.text((sx + 3, cy + 1), tag, font=f_tag, fill=_hex(C_GRAY), anchor="lm")
        sx += tw + 3
    sx += 6
    d.text((sx, cy), amt, font=f_amt, fill=col, anchor="lm")


def _draw_section(d, yy, row, style, c_up, c_down):
    per = COLS
    items = row["items"]
    lines = max(1, math.ceil(len(items) / float(per)))
    h = lines * LINE_H + PAD_Y * 2

    # 左红块
    d.rounded_rectangle([M, yy, M + BLOCK_W, yy + h], radius=5, fill=_hex(C_RED))
    f_lab = _font(style["font_bold"], 13)
    parts = _wrap_chars(row["label"])
    lh = 16
    ly = yy + h / 2 - (len(parts) - 1) * lh / 2.0
    for part in parts:
        d.text((M + BLOCK_W / 2, ly), part, font=f_lab, fill=(255, 255, 255), anchor="mm")
        ly += lh

    # 浅色卡片
    d.rounded_rectangle([CARD_X, yy, W - M, yy + h], radius=5, fill=_hex(C_BG))
    for i, item in enumerate(items):
        col, ln = i % per, i // per
        x0 = CARD_X + col * CELL_W
        y0 = yy + PAD_Y + ln * LINE_H
        _draw_cell(d, x0, y0, CELL_W, LINE_H, item, row["kind"], style, c_up, c_down)

    # 网格线
    for c in range(1, per):
        dx = CARD_X + c * CELL_W
        d.line([(dx, yy + 4), (dx, yy + h - 4)], fill=_hex(C_DIV), width=1)
    for ln in range(1, lines):
        dy = yy + PAD_Y + ln * LINE_H
        d.line([(CARD_X + 2, dy), (W - M - 2, dy)], fill=_hex(C_DIV), width=1)
    return h


def _watermark(img, style):
    wm = style.get("watermark") or {}
    if not wm.get("enabled") or not wm.get("text"):
        return img
    W_, H_ = img.size
    size = int(wm.get("font_size", 99) * 0.8)
    font = _font(style["font_bold"], size)
    tw = int(font.getlength(wm["text"])) + size
    th = int(size * 1.6)
    layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    r, g, b = _hex(wm.get("color", "#8A9099"))
    a = int(round(255 * float(wm.get("opacity", 0.05))))
    ImageDraw.Draw(layer).text((tw / 2, th / 2), wm["text"], font=font,
                               fill=(r, g, b, a), anchor="mm")
    layer = layer.rotate(wm.get("angle", -24), expand=True, resample=Image.BICUBIC)
    ov = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    for frac in (0.2, 0.5, 0.8):
        ov.paste(layer, ((W_ - layer.width) // 2, int(H_ * frac) - layer.height // 2), layer)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def render_png(board, style, out_path):
    c_up, c_down = style.get("color_up", C_UP), style.get("color_down", C_DOWN)

    # 先算正文高度
    body_h = 0
    for row in board["rows"]:
        lines = max(1, math.ceil(len(row["items"]) / float(COLS)))
        body_h += lines * LINE_H + PAD_Y * 2 + SEC_GAP
    body_h = max(0, body_h - SEC_GAP)

    # 头部高度用绘制函数估算：先画在临时画布上拿到底部
    tmp = Image.new("RGB", (W, 600), (255, 255, 255))
    td = ImageDraw.Draw(tmp)
    content_top = _draw_header(td, board, style, board.get("market"), 24, c_up, c_down)
    H = int(content_top + body_h + FOOT_H)

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    _draw_header(d, board, style, board.get("market"), 24, c_up, c_down)

    yy = content_top
    for row in board["rows"]:
        h = _draw_section(d, yy, row, style, c_up, c_down)
        yy += h + SEC_GAP

    # 页脚
    f_foot = _font(style["font_bold"], 10)
    d.text((W / 2, H - FOOT_H / 2), "红色为净买，绿色为净卖；数据由公开信息整理，仅供参考，不构成投资建议。",
           font=f_foot, fill=_hex(C_GRAY), anchor="mm")

    img = _fit_canvas(img, style)
    img = _watermark(img, style)
    img.save(out_path, "PNG")
    return out_path, img.width, img.height
