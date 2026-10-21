# -*- coding: utf-8 -*-
"""渲染：极简版式 —— 白底、浅分隔、净买/净卖标签、顶部大盘概览条。

输出：
  render_png  -> 高清 PNG（发布用）
  render_html -> HTML（预览 / 微调）
"""
import copy
import html as html_mod

from PIL import Image, ImageDraw, ImageFont

from lhb_build import fmt_amount

_font_cache = {}

# 配置里的字体路径按 Windows 编写；在 macOS / Linux 上按顺序兜底，避免渲染成方块
_FALLBACK_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

# 相邻片段之间的间距
_GAPS = {("chip", "name"): 9, ("name", "three"): 2, ("three", "amt"): 5, ("name", "amt"): 11}
_DEFAULT_GAP = 6


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _market_cells(market):
    """返回大盘概览条可展示的栏目；空数据时返回空列表，避免占位留白。"""
    if not market:
        return []
    cells = []
    if market.get("index"):
        cells.append("index")
    if market.get("up") is not None:
        cells.append("breadth")
    if market.get("zt") is not None:
        cells.append("limit")
    return cells


def _font(paths, size):
    size = max(1, int(round(size)))
    key = (tuple(paths), size)
    if key not in _font_cache:
        font = None
        for path in list(paths) + _FALLBACK_FONTS:
            try:
                font = ImageFont.truetype(path, size)
                break
            except Exception:
                continue
        _font_cache[key] = font or ImageFont.load_default()
    return _font_cache[key]


def _role_font(role, style):
    if role == "chip":
        return _font(style["font_bold"], style["chip"]["font_size"])
    if role == "three":
        return _font(style["font_bold"], style["three_font_size"])
    return _font(style["font_bold"], style["content"]["font_size"])


def _seg_list(item, kind):
    """把一条明细拆成绘制片段：chip(净买/净卖) / name / three / amt。"""
    if kind == "names":
        return [("name", item["name"])]
    segs = [("chip", "净买" if item["net"] > 0 else "净卖"), ("name", item["name"])]
    if item.get("three"):
        segs.append(("three", "(三日)"))
    segs.append(("amt", fmt_amount(item["net"])))
    return segs


def _seg_w(role, text, draw, style):
    w = draw.textlength(text, font=_role_font(role, style))
    if role == "chip":
        w += style["chip"]["pad_x"] * 2
    return w


def _gap(role, nxt, style):
    base = _GAPS.get((role, nxt), _DEFAULT_GAP)
    return base * style["content"].get("_scale", 1.0)


def _item_w(segs, draw, style):
    total = 0.0
    for i, (role, text) in enumerate(segs):
        total += _seg_w(role, text, draw, style)
        if i + 1 < len(segs):
            total += _gap(role, segs[i + 1][0], style)
    return total


def _scale_style(style, s):
    """按比例缩放内容区字号与间距，保证一行能放下固定数量的股票。"""
    st = copy.deepcopy(style)
    c = st["content"]
    for key in ("font_size", "item_gap", "name_gap", "first_line_center",
                "line_pitch", "base_height"):
        c[key] = c[key] * s
    st["chip"]["font_size"] *= s
    st["chip"]["height"] *= s
    st["chip"]["pad_x"] *= s
    st["three_font_size"] *= s
    st["row"]["group_pad"] *= s
    c["_scale"] = s
    return st


def _fit_content_style(board, style, draw, avail):
    """从原始字号开始向下试探，找到能让每行固定 per_line 个股票的最大字号。"""
    c = style["content"]
    per = max(1, int(c.get("per_line", 4)))
    base_font = float(c["font_size"])
    min_scale = max(0.35, min(1.0, float(c.get("min_font_size", 15)) / base_font))
    max_lines = style.get("max_lines", {})
    dflt = max_lines.get("_default", 3)

    def fits(st):
        gap = st["content"]["item_gap"]
        for row in board["rows"]:
            limit = max_lines.get(row["label"], dflt)
            items = row["items"][:limit * per]
            for i in range(0, len(items), per):
                chunk = items[i:i + per]
                widths = [_item_w(_seg_list(it, row["kind"]), draw, st) for it in chunk]
                if not widths:
                    continue
                total = sum(widths) + gap * (len(widths) - 1)
                if total > avail + 0.5:
                    return False
        return True

    # 二分查找能放下的最大字号，比逐档试探快，也更不容易抖
    lo, hi = min_scale, 1.0
    best = _scale_style(style, min_scale)
    for _ in range(14):
        mid = (lo + hi) / 2.0
        st = _scale_style(style, mid)
        if fits(st):
            best, lo = st, mid
        else:
            hi = mid
    return best


def _fit_label_size(paths, base_size, text, max_w, draw):
    size = base_size
    while size > 14:
        if draw.textlength(text, font=_font(paths, size)) <= max_w:
            return size
        size -= 1
    return 14


def _layout(board, style, draw, avail):
    c = style["content"]
    line_pitch, first, base_h = c["line_pitch"], c["first_line_center"], c["base_height"]
    item_gap = c["item_gap"]
    per = max(1, int(c.get("per_line", 4)))
    group_pad = style["row"]["group_pad"]
    groups = set(style.get("group_order", []))
    max_lines = style.get("max_lines", {})
    dflt = max_lines.get("_default", 3)

    rows = []
    for row in board["rows"]:
        limit = max_lines.get(row["label"], dflt)
        items = row["items"][:limit * per]
        lines = []
        for i in range(0, len(items), per):
            chunk = items[i:i + per]
            segs = [_seg_list(it, row["kind"]) for it in chunk]
            widths = [_item_w(sg, draw, style) for sg in segs]
            n = len(chunk)
            # 满行左右两端对齐，末行按常规间距左排
            gap = item_gap
            if n == per and n > 1:
                gap = max(item_gap, (avail - sum(widths)) / (n - 1))
            line, x = [], 0.0
            for j, item in enumerate(chunk):
                line.append((item, segs[j], x))
                x += widths[j] + gap
            lines.append(line)
        is_group = row["label"] in groups
        pad = group_pad if is_group else 0
        rows.append({
            "label": row["label"], "kind": row["kind"], "group": is_group,
            "lines": lines, "first_center": first + pad,
            "height": base_h + (len(lines) - 1) * line_pitch + pad * 2,
        })
    return rows


def _draw_item(d, x, cy, segs, net, kind, style, c_up, c_down, c_ink):
    for i, (role, text) in enumerate(segs):
        w = _seg_w(role, text, d, style)
        if role == "chip":
            h = style["chip"]["height"]
            d.rounded_rectangle([x, cy - h / 2, x + w, cy + h / 2],
                                radius=style["chip"]["radius"],
                                fill=c_up if net > 0 else c_down)
            d.text((x + w / 2, cy), text, font=_role_font("chip", style),
                   fill=_hex(style["chip"]["color"]), anchor="mm")
        elif role == "three":
            d.text((x, cy), text, font=_role_font("three", style),
                   fill=_hex(style["three_color"]), anchor="lm")
        elif role == "amt":
            d.text((x, cy), text, font=_role_font("amt", style),
                   fill=c_ink if kind == "names" else (c_up if net > 0 else c_down),
                   anchor="lm")
        else:
            d.text((x, cy), text, font=_role_font("name", style), fill=c_ink, anchor="lm")
        if i + 1 < len(segs):
            x += w + _gap(role, segs[i + 1][0], style)


def _draw_market(d, W, y0, style, market, c_up, c_down):
    m = style["market"]
    pad_x = style["pad_x"]
    x0, x1 = pad_x, W - pad_x
    h = m["height"]
    d.rounded_rectangle([x0, y0, x1, y0 + h], radius=m["radius"], fill=_hex(m["bg"]))

    cells = _market_cells(market)
    if not cells:
        return

    zp = m["zone_pad"]
    ix0, ix1 = x0 + zp, x1 - zp
    col_w = (ix1 - ix0) / len(cells)
    lab_font = _font(style["font_bold"], m["label_size"])
    big_font = _font(style["font_bold"], m["big_size"])
    num_font = _font(style["font_bold"], m["num_size"])
    chg_font = _font(style["font_bold"], m["chg_size"])
    lab_c = _hex(m["label_color"])
    cy_lab, cy_val = y0 + 30, y0 + h - 31

    for i in range(1, len(cells)):
        dx = ix0 + col_w * i
        d.rectangle([dx - 1, y0 + 24, dx, y0 + h - 24], fill=_hex(m["divider"]))

    for i, kind in enumerate(cells):
        cx = ix0 + col_w * i
        if kind == "index":
            idx = market["index"]
            d.text((cx, cy_lab), "上证指数", font=lab_font, fill=lab_c, anchor="lm")
            col = c_up if idx["chg_pct"] >= 0 else c_down
            val = "%.2f" % idx["point"]
            d.text((cx, cy_val), val, font=big_font, fill=col, anchor="lm")
            d.text((cx + d.textlength(val, big_font) + 14, cy_val - 1),
                   "%+.2f%%" % idx["chg_pct"], font=chg_font, fill=col, anchor="lm")
        elif kind == "breadth":
            d.text((cx, cy_lab), "涨跌家数", font=lab_font, fill=lab_c, anchor="lm")
            t = "涨 %d" % market["up"]
            d.text((cx, cy_val), t, font=num_font, fill=c_up, anchor="lm")
            d.text((cx + d.textlength(t, num_font) + 20, cy_val), "跌 %d" % market["down"],
                   font=num_font, fill=c_down, anchor="lm")
        else:
            d.text((cx, cy_lab), "涨跌停", font=lab_font, fill=lab_c, anchor="lm")
            t = "涨停 %d" % market["zt"]
            d.text((cx, cy_val), t, font=num_font, fill=c_up, anchor="lm")
            d.text((cx + d.textlength(t, num_font) + 20, cy_val), "跌停 %d" % market["dt"],
                   font=num_font, fill=c_down, anchor="lm")


def _draw_frame(d, W, H, style):
    """蓝框美化版的边框：外层粗框 + 内层细线（可选）。"""
    f = style.get("frame") or {}
    if not f.get("enabled"):
        return
    mg, fw = f.get("margin", 6), f.get("width", 10)
    r = f.get("radius", 30)
    d.rounded_rectangle([mg, mg, W - 1 - mg, H - 1 - mg], radius=r,
                        outline=_hex(f.get("color", "#1E5AA8")), width=fw)
    if f.get("inner_width"):
        ig = mg + fw + f.get("inner_gap", 7)
        d.rounded_rectangle([ig, ig, W - 1 - ig, H - 1 - ig], radius=max(6, r - fw),
                            outline=_hex(f.get("inner_color", "#A9C6E8")),
                            width=f.get("inner_width", 2))


def _draw_accent(d, W, style):
    """标题下方的短强调线，让页面更聚焦。"""
    a = (style.get("title") or {}).get("accent") or {}
    if not a.get("enabled"):
        return
    hw, hh = a.get("width", 72) / 2, a.get("height", 6) / 2
    cy = a.get("center_y", 120)
    d.rounded_rectangle([W / 2 - hw, cy - hh, W / 2 + hw, cy + hh],
                        radius=hh, fill=_hex(a.get("color", "#141414")))


def _apply_watermark(img, W, H, style):
    """在画面正中叠加一道斜向水印（默认 -30°，透明度 5%）。"""
    wm = style.get("watermark") or {}
    if not wm.get("enabled") or not wm.get("text"):
        return img
    size = wm.get("font_size", 120)
    font = _font(style["font_bold"], size)
    tw = int(font.getlength(wm["text"])) + size * 2
    th = int(size * 1.4) + size
    layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    r, g, b = _hex(wm.get("color", "#000000"))
    alpha = int(round(255 * float(wm.get("opacity", 0.05))))
    ImageDraw.Draw(layer).text((tw / 2, th / 2), wm["text"], font=font,
                               fill=(r, g, b, alpha), anchor="mm")
    layer = layer.rotate(wm.get("angle", -30), expand=True, resample=Image.BICUBIC)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov.paste(layer, ((W - layer.width) // 2, (H - layer.height) // 2))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def _fit_pad(style):
    """适配画布时给装饰边框预留的内边距，避免内容压到边框线上。"""
    fit = style.get("fit") or {}
    pad = fit.get("pad", 0)
    fr = style.get("frame") or {}
    if fr.get("enabled"):
        inset = (fr.get("margin", 6) + fr.get("width", 10) +
                 fr.get("inner_gap", 7) + (fr.get("inner_width", 2) or 0))
        pad = max(pad, inset)
    return pad


def _fit_canvas(img, style):
    """把版面等比缩放并居中放进目标画布（3:4 / 9:16）。
    max_scale 默认 1，内容比画布小时不放大，避免栅格模糊。"""
    fit = style.get("fit") or {}
    if not fit.get("enabled"):
        return img
    TW, TH = fit.get("w", 1080), fit.get("h", 1440)
    pad = _fit_pad(style)
    w, h = img.size
    s = min((TW - 2 * pad) / float(w), (TH - 2 * pad) / float(h),
            float(fit.get("max_scale", 1)))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    canvas = Image.new("RGB", (TW, TH), _hex(fit.get("bg", "#FFFFFF")))
    canvas.paste(img.resize((nw, nh), Image.LANCZOS), ((TW - nw) // 2, (TH - nh) // 2))
    return canvas


def render_png(board, style, out_path):
    W = style["canvas_width"]
    pad_x = style["pad_x"]
    label_w = style["label_col"]["width"]

    content_x0 = pad_x + label_w
    avail = (W - pad_x - style["content"]["right_pad"]) - content_x0

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    # 每行固定 per_line 个股票，按内容宽度自适应字号
    style = _fit_content_style(board, style, probe, avail)
    title, c = style["title"], style["content"]
    row_style, footer = style["row"], style["footer"]

    c_up, c_down = _hex(style["color_up"]), _hex(style["color_down"])
    c_ink = _hex(style["label_col"]["color"])
    font_title = _font(style["font_bold"], title["font_size"])
    font_foot = _font(style["font_bold"], footer["font_size"])

    rows = _layout(board, style, probe, avail)
    for r in rows:
        r["lab_size"] = _fit_label_size(style["font_bold"], style["label_col"]["font_size"],
                                        r["label"], label_w - 16, probe)
    body_h = sum(r["height"] for r in rows)

    market = board.get("market") if style.get("show_market", True) else None
    market_cells = _market_cells(market)
    list_top = title["height"]
    if market_cells:
        list_top += style["market"]["height"] + style["market"]["margin_bottom"]
    H = int(round(list_top + body_h + footer["height"]))

    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # 标题 + 强调线
    d.text((W / 2, title["center_y"]),
           title["template"].format(m=board["m"], d=board["d"]),
           font=font_title, fill=_hex(title["color"]), anchor="mm")
    _draw_accent(d, W, style)

    # 大盘概览条
    if market_cells:
        _draw_market(d, W, title["height"], style, market, c_up, c_down)

    # 列表
    yy = list_top
    for row in rows:
        if row["group"]:
            d.rectangle([pad_x, yy, W - pad_x - 1, yy + row_style["group_line_width"] - 1],
                        fill=_hex(row_style["group_line_color"]))
        elif row_style["line_width"]:
            d.rectangle([pad_x, yy, W - pad_x - 1, yy + row_style["line_width"] - 1],
                        fill=_hex(row_style["line_color"]))
        d.text((pad_x, yy + row["first_center"]), row["label"],
               font=_font(style["font_bold"], row["lab_size"]), fill=c_ink, anchor="lm")
        for k, line in enumerate(row["lines"]):
            cy = yy + row["first_center"] + k * c["line_pitch"]
            for item, segs, lx in line:
                _draw_item(d, content_x0 + lx, cy, segs, item["net"], row["kind"],
                           style, c_up, c_down, c_ink)
        yy += row["height"]

    # 页脚
    foot_top = list_top + body_h
    d.rectangle([pad_x, foot_top, W - pad_x - 1, foot_top], fill=_hex(footer["line_color"]))
    d.text((W / 2, foot_top + footer["height"] * 0.6), footer["text"],
           font=font_foot, fill=_hex(footer["color"]), anchor="mm")

    # 适配目标画布（小红书 3:4 / 抖音 9:16）
    img = _fit_canvas(img, style)
    W, H = img.size
    _draw_frame(ImageDraw.Draw(img), W, H, style)
    img = _apply_watermark(img, W, H, style)
    img.save(out_path, "PNG")
    return out_path, W, H


def _seg_html(role, text, net, kind):
    if role == "chip":
        cls = "chip up" if net > 0 else "chip down"
        return "<span class=\"%s\">%s</span>" % (cls, html_mod.escape(text))
    if role == "three":
        return "<span class=\"three\">%s</span>" % html_mod.escape(text)
    if role == "amt":
        cls = "bk" if kind == "names" else ("up" if net > 0 else "down")
        return "<span class=\"%s\">%s</span>" % (cls, html_mod.escape(text))
    return "<span class=\"nm\">%s</span>" % html_mod.escape(text)


def render_html(board, style, out_path):
    W = style["canvas_width"]
    pad_x = style["pad_x"]
    label_w = style["label_col"]["width"]
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    avail = (W - pad_x - style["content"]["right_pad"]) - (pad_x + label_w)
    # 与 PNG 用同一套字号自适应结果，保证预览和成图一致
    style = _fit_content_style(board, style, probe, avail)
    title, c, m, footer = style["title"], style["content"], style["market"], style["footer"]
    per = max(1, int(c.get("per_line", 4)))
    groups = set(style.get("group_order", []))
    use_market = style.get("show_market", True)
    market = (board.get("market") or {}) if use_market else {}

    fr = style.get("frame") or {}
    fmg, fwid, frad = fr.get("margin", 6), fr.get("width", 10), fr.get("radius", 30)
    fii = fmg + fwid + fr.get("inner_gap", 7)
    fiw, ficol = fr.get("inner_width", 2), fr.get("inner_color", "#A9C6E8")
    firad = max(6, frad - fwid)
    wm = style.get("watermark") or {}
    wm_on = bool(wm.get("enabled"))
    ac = title.get("accent") or {}
    ac_on = bool(ac.get("enabled"))

    # 画布适配：HTML 预览用 transform 等比缩放来模拟 3:4 / 9:16
    _rows = _layout(board, style, probe, avail)
    market_cells = _market_cells(market)
    board_h = title["height"] + sum(r["height"] for r in _rows) + footer["height"]
    if market_cells:
        board_h += m["height"] + m["margin_bottom"]
    fit = style.get("fit") or {}
    fpad = _fit_pad(style)
    if fit.get("enabled"):
        sw, sh, sbg = fit.get("w", 1080), fit.get("h", 1440), fit.get("bg", "#FFFFFF")
        sc = min((sw - 2 * fpad) / float(W),
                 (sh - 2 * fpad) / float(board_h),
                 float(fit.get("max_scale", 1)))
    else:
        sw, sh, sbg, sc = W, board_h, "#FFFFFF", 1.0

    # 行高按 PNG 的 first_line_center / line_pitch 换算，保证预览与成图高度一致
    lp = c["line_pitch"]
    row_pt = max(0, int(round(c["first_line_center"] - lp / 2.0)))
    row_pb = max(0, int(round(c["base_height"] - c["first_line_center"] - lp / 2.0)))
    gp = style["row"]["group_pad"]
    glw = style["row"]["group_line_width"]
    g_pt = max(0, row_pt + gp - glw)
    g_pb = row_pb + gp
    title_line = int(round(title["center_y"] * 2))
    foot_line = max(1, footer["height"] - 1)

    css = """
  html,body{margin:0;padding:28px 0;background:#f2f3f5;}
  .stage{position:relative;width:%(sw)dpx;height:%(sh)dpx;margin:0 auto;background:%(sbg)s;overflow:hidden;
         display:flex;align-items:center;justify-content:center;}
  .stage>.board{transform:scale(%(sc)s);}
  .board{position:relative;overflow:hidden;width:%(W)dpx;margin:0 auto;background:#fff;box-sizing:border-box;
         padding:0 %(pad)dpx;font-family:"Microsoft YaHei","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Source Han Sans SC",sans-serif;}
  .stage::after{content:"%(wtxt)s";position:absolute;left:50%%;top:50%%;transform:translate(-50%%,-50%%) rotate(%(wang)ddeg);
                font-size:%(wfs)dpx;font-weight:700;color:%(wcol)s;opacity:%(wop)s;white-space:nowrap;pointer-events:none;z-index:9;}
  .fr{position:absolute;inset:%(fmg)dpx;border:%(fwid)dpx solid %(fcol)s;border-radius:%(frad)dpx;pointer-events:none;z-index:8;}
  .fri{position:absolute;inset:%(fii)dpx;border:%(fiw)dpx solid %(ficol)s;border-radius:%(firad)dpx;pointer-events:none;z-index:8;}
  .title{position:relative;height:%(th)dpx;line-height:%(tline)dpx;text-align:center;color:%(tc)s;
         font-weight:700;font-size:%(tf)dpx;}
  .title::after{content:"";position:absolute;left:50%%;top:%(aty)dpx;transform:translateX(-50%%);
                width:%(atw)dpx;height:%(ath)dpx;border-radius:%(athr)dpx;background:%(atc)s;}
  .market{display:flex;align-items:center;height:%(mh)dpx;background:%(mbg)s;border-radius:%(mrad)dpx;
          margin-bottom:%(mmb)dpx;padding:0 %(mzp)dpx;box-sizing:border-box;}
  .mcol{flex:1;border-left:1px solid %(mdiv)s;}
  .mcol:first-child{border-left:none;}
  .mlab{font-size:%(mls)dpx;color:%(mlc)s;}
  .mbig{font-size:%(mbs)dpx;font-weight:700;line-height:1.15;}
  .mnum{font-size:%(mns)dpx;font-weight:700;line-height:1.15;}
  .up{color:%(cup)s;} .down{color:%(cdn)s;} .bk{color:#111;}
  .row{display:flex;align-items:flex-start;padding:%(rpt)dpx 0 %(rpb)dpx;box-sizing:border-box;}
  .row.g{border-top:%(glw)dpx solid %(glc)s;padding:%(gpt)dpx 0 %(gpb)dpx;}
  .lab{width:%(lw)dpx;flex:0 0 %(lw)dpx;font-weight:700;font-size:%(lf)dpx;color:%(lc)s;
       line-height:%(lp)dpx;}
  .items{flex:1;font-size:%(bf)dpx;font-weight:700;line-height:%(lp)dpx;}
  .ln{display:flex;align-items:center;justify-content:space-between;height:%(lp)dpx;white-space:nowrap;}
  .ln.part{justify-content:flex-start;gap:%(ig)dpx;}
  .it{display:inline-block;white-space:nowrap;}
  .it>*{display:inline-block;vertical-align:middle;}
  .chip{color:#fff;font-size:%(chf)dpx;font-weight:700;border-radius:%(chrad)dpx;
        padding:1px %(chpx)dpx;margin-right:%(chg)dpx;line-height:1.4;}
  .chip.up{background:%(cup)s;} .chip.down{background:%(cdn)s;}
  .nm{margin-right:%(ngf)dpx;}
  .three{color:%(tc3)s;font-size:%(tf3)dpx;margin-right:4px;}
  .foot{border-top:1px solid %(fline)s;height:%(fh)dpx;line-height:%(flh)dpx;text-align:center;
        color:%(fc)s;font-size:%(ff)dpx;box-sizing:border-box;}
""" % dict(W=W, pad=pad_x, th=title["height"], tc=title["color"], tf=title["font_size"],
           mh=m["height"], mbg=m["bg"], mrad=m["radius"], mmb=m["margin_bottom"], mzp=m["zone_pad"],
           mdiv=m["divider"], mls=m["label_size"], mlc=m["label_color"], mbs=m["big_size"],
           mns=m["num_size"], cup=style["color_up"], cdn=style["color_down"],
           rpt=row_pt, rpb=row_pb, gpt=g_pt, gpb=g_pb, lp=lp, tline=title_line,
           glw=glw,
           glc=style["row"]["group_line_color"], lw=label_w, lf=style["label_col"]["font_size"],
           lc=style["label_col"]["color"], bf=c["font_size"], ig=c["item_gap"],
           chf=style["chip"]["font_size"], chrad=style["chip"]["radius"], chpx=style["chip"]["pad_x"],
           chg=9, ngf=c["name_gap"], tc3=style["three_color"], tf3=style["three_font_size"],
           fline=footer["line_color"], fh=footer["height"], flh=foot_line, fc=footer["color"],
           ff=footer["font_size"],
           wtxt=(wm.get("text", "") if wm_on else ""), wang=wm.get("angle", -30),
           wfs=wm.get("font_size", 120), wcol=wm.get("color", "#000000"),
           wop=(wm.get("opacity", 0.05) if wm_on else 0),
           fmg=fmg, fwid=fwid, fcol=fr.get("color", "#1E5AA8"), frad=frad,
           fii=fii, fiw=fiw, ficol=ficol, firad=firad,
           aty=(ac.get("center_y", 120) - ac.get("height", 6) / 2),
           atw=(ac.get("width", 72) if ac_on else 0),
           ath=(ac.get("height", 6) if ac_on else 0),
           athr=(ac.get("height", 6) / 2 if ac_on else 0),
           atc=ac.get("color", "#141414"),
           sw=sw, sh=sh, sbg=sbg, sc=("%.5f" % sc))

    idx = market.get("index")
    cells = []
    if "index" in market_cells:
        icls = "up" if (idx.get("chg_pct") or 0) >= 0 else "down"
        cells.append("<div class=\"mcol\"><div class=\"mlab\">上证指数</div>"
                     "<div class=\"%s\">%.2f <span class=\"mnum\">%+.2f%%</span></div></div>"
                     % (icls, idx["point"], idx["chg_pct"]))
    if "breadth" in market_cells:
        cells.append("<div class=\"mcol\"><div class=\"mlab\">涨跌家数</div>"
                     "<div class=\"mnum\">涨 <span class=\"up\">%d</span>&nbsp; 跌 "
                     "<span class=\"down\">%d</span></div></div>" % (market["up"], market["down"]))
    if "limit" in market_cells:
        cells.append("<div class=\"mcol\"><div class=\"mlab\">涨跌停</div>"
                     "<div class=\"mnum\">涨停 <span class=\"up\">%d</span>&nbsp; 跌停 "
                     "<span class=\"down\">%d</span></div></div>" % (market["zt"], market["dt"]))
    market_html = "<div class=\"market\">%s</div>" % "".join(cells) if cells else ""

    body = []
    for row, lrow in zip(board["rows"], _rows):
        lines_html = []
        for line in lrow["lines"]:
            parts = []
            for item, segs, _lx in line:
                inner = "".join(_seg_html(role, text, item["net"], row["kind"])
                                for role, text in segs)
                parts.append("<span class=\"it\">%s</span>" % inner)
            ln_cls = "ln" if len(line) >= per else "ln part"
            lines_html.append("<div class=\"%s\">%s</div>" % (ln_cls, "".join(parts)))
        cls = "row g" if row["label"] in groups else "row"
        body.append("<div class=\"%s\"><div class=\"lab\">%s</div><div class=\"items\">%s</div></div>"
                    % (cls, html_mod.escape(row["label"]), "".join(lines_html)))

    frame_html = ""
    if fr.get("enabled"):
        frame_html = "<div class=\"fr\"></div>"
        if fiw:
            frame_html += "<div class=\"fri\"></div>"

    # 浏览器字体度量与 PIL 存在细微差异，按实际排版尺寸自适应，避免预览被裁切
    fit_flag = 1 if fit.get("enabled") else 0

    doc = ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>%s</title><style>%s</style></head><body><div class=\"stage\">"
           "<div class=\"board\"><div class=\"title\">%s</div>%s%s"
           "<div class=\"foot\">%s</div></div>%s</div>"
           "<script>(function(){var st=document.querySelector('.stage'),"
           "bd=document.querySelector('.board');function fit(){"
           "if(%d){var p=%d,s=Math.min((st.clientWidth-2*p)/bd.offsetWidth,"
           "(st.clientHeight-2*p)/bd.offsetHeight);bd.style.transform='scale('+s+')';}"
           "else{bd.style.transform='none';st.style.height=bd.offsetHeight+'px';}}"
           "fit();window.addEventListener('load',fit);})();</script>"
           "</body></html>") % (
        html_mod.escape(title["template"].format(m=board["m"], d=board["d"])), css,
        html_mod.escape(title["template"].format(m=board["m"], d=board["d"])),
        market_html, "".join(body),
        html_mod.escape(footer["text"]), frame_html, fit_flag, fpad)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path
