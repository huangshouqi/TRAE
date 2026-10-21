# -*- coding: utf-8 -*-
"""一键入口：抓取龙虎榜 -> 聚合 -> 输出 PNG + HTML。

用法：
    python src/lhb_main.py                # 自动取最近一个交易日
    python src/lhb_main.py 2026-10-16     # 指定日期
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lhb_build
import lhb_fetch
import lhb_ladder
import lhb_render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "output")


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="交易日 YYYY-MM-DD，缺省自动取最新")
    ap.add_argument("--open", dest="open_after", action="store_true", help="生成后打开图片")
    args = ap.parse_args()

    style = lhb_build.load_json(os.path.join(CONFIG_DIR, "样式.json"))
    mapping = lhb_build.load_json(os.path.join(CONFIG_DIR, "席位映射.json"))

    styles = [("", style)]
    for tag, filename in (("_蓝框", "样式_蓝框.json"), ("_红框", "样式_红框.json")):
        cfg = os.path.join(CONFIG_DIR, filename)
        if os.path.exists(cfg):
            styles.append((tag, lhb_build.load_json(cfg)))
    # 天梯风：参考「连板天梯」版式
    ladder = dict(style)
    ladder["renderer"] = "ladder"
    ladder["show_market"] = False
    styles.append(("_天梯", ladder))

    # 最终版：天梯版式 + 居中主标题（3:4 高清）
    final = dict(ladder)
    final["center_title"] = True
    styles.append(("_最终版", final))

    latest = lhb_fetch.resolve_trade_date()
    date = args.date or latest
    is_latest = (date == latest)
    print("交易日：%s%s" % (date, "" if is_latest else "（历史）"))

    raw = lhb_fetch.fetch_day(date)
    print("抓取：个股 %d / 买席 %d / 卖席 %d / 机构 %d" % (
        len(raw["stocks"]), len(raw["buys"]), len(raw["sells"]), len(raw["org"])))
    _dump(os.path.join(DATA_DIR, "raw_%s.json" % date), raw)

    # 仅当样式启用了大盘概览条时才抓取，避免每次跑都多打几个接口
    market = None
    if any(st.get("show_market", True) for _, st in styles):
        today = datetime.date.today().isoformat()
        live = (date == today)  # 历史日期不能混入当天实时行情
        market = lhb_fetch.fetch_market(date, with_breadth=live, allow_live=live)

    board = lhb_build.build(raw, mapping, style, market)
    _dump(os.path.join(DATA_DIR, "board_%s.json" % date), board)
    print("聚合：%d 行" % len(board["rows"]))
    for row in board["rows"]:
        print("   %-8s %d 只" % (row["label"], len(row["items"])))

    os.makedirs(OUT_DIR, exist_ok=True)

    formats = [
        ("", (1080, 1440)),       # 常规版 3:4
    ]

    first_png = None
    for s_tag, base in styles:
        for f_tag, ratio in formats:
            st = dict(base)
            if ratio:
                st["fit"] = {"enabled": True, "w": ratio[0], "h": ratio[1],
                             "pad": 0, "max_scale": 1, "bg": "#FFFFFF"}
            tag = s_tag + f_tag
            png = os.path.join(OUT_DIR, "龙虎榜_%s%s.png" % (date, tag))
            if st.get("renderer") == "ladder":
                _, w, h = lhb_ladder.render_png(board, st, png)
            else:
                _, w, h = lhb_render.render_png(board, st, png)
            first_png = first_png or png
            print("输出：%s (%dx%d)" % (png, w, h))

    if args.open_after and first_png:
        opener = getattr(os, "startfile", None)
        if opener:
            opener(first_png)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", first_png])


if __name__ == "__main__":
    main()
