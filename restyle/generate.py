# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import ROWS, LASHA, FOOTNOTE

RED, GREEN = "#E41A1A", "#169668"


def item_html(tag, name, is3, amt):
    cls = "buy" if tag == "净买" else "sell"
    t = '<span class="tag">(三日)</span>' if is3 else ""
    return (f'<div class="item"><span class="badge {cls}">{tag}</span>'
            f'<span class="name">{name}</span>{t}'
            f'<span class="amt {cls}">{amt}</span></div>')


def chunk(seq, n=4):
    return [seq[i:i + n] for i in range(0, len(seq), n)]


rows = []
for seat, items in ROWS:
    lines = chunk(items, 4)
    body = ""
    for ln in lines:
        cells = "".join(f'<td class="cell">{item_html(*it)}</td>' for it in ln)
        cells += '<td class="cell"></td>' * (4 - len(ln))
        body += f"<tr>{cells}</tr>"
    rows.append(
        f'<tr class="row"><td class="seat"><span>{seat}</span></td>'
        f'<td class="items"><table class="grid">{body}</table></td></tr>'
    )

chips = chunk(LASHA, 6)
lasha_body = ""
for ln in chips:
    cells = "".join(f'<td class="chipcell"><span class="chip">{n}</span></td>' for n in ln)
    cells += '<td class="chipcell"></td>' * (6 - len(ln))
    lasha_body += f"<tr>{cells}</tr>"
rows.append(
    f'<tr class="row last"><td class="seat"><span>拉萨天团</span></td>'
    f'<td class="items"><table class="grid c6">{lasha_body}</table></td></tr>'
)

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>龙虎榜</title>
<style>
  @page {{ size: 1080px 2600px; margin: 0; }}
  * {{ margin:0; padding:0; }}
  body {{
    width:1080px; background:#FAF5F2; padding:26px 32px 22px;
    font-family:"Noto Sans CJK SC","Source Han Sans SC",sans-serif;
    color:#26201E;
  }}
  table {{ border-collapse:collapse; }}
  .head {{ width:1016px; }}
  .head td {{ vertical-align:middle; }}
  .bar {{ display:inline-block; width:8px; height:46px; background:#E41A1A;
          border-radius:3px; margin-right:16px; vertical-align:middle; }}
  .d {{ font-size:42px; font-weight:900; letter-spacing:1px; }}
  .sub {{ font-size:42px; font-weight:900; color:#E41A1A; letter-spacing:2px; margin-left:10px; }}
  .lg {{ display:inline-block; font-size:13.5px; font-weight:700; color:#fff;
         padding:6px 13px; border-radius:5px; letter-spacing:.5px; }}
  .lg.buy {{ background:#E41A1A; }}
  .lg.sell {{ background:#169668; margin-left:8px; }}
  .rule {{ height:7px; margin:13px 2px 14px; border-radius:4px;
           background:linear-gradient(90deg,#F44848,#E41A1A 45%,#C20E0E); }}
  .card {{ width:1016px; background:#FFFFFF; border:1px solid #F4E6DF; border-radius:14px; }}
  .row {{ border-bottom:1px solid #F8EFEA; }}
  .row.last {{ border-bottom:none; }}
  .seat {{ width:98px; vertical-align:middle; padding:2px 0; }}
  .seat span {{ display:inline-block; height:31px; line-height:31px; width:100%;
          text-align:center; color:#fff; font-size:14px; font-weight:700; letter-spacing:.3px;
          border-radius:8px; background:linear-gradient(180deg,#F14141,#D91414); }}
  .items {{ padding:2px 8px 2px 11px; vertical-align:middle; }}
  .grid {{ width:100%; }}
  .grid td.cell {{ width:25%; vertical-align:middle; padding:2px 8px 2px 0; }}
  .item {{ background:#FBF7F3; border:1px solid #F5E9E2; border-radius:6px; padding:2.5px 6px; }}
  .grid.c6 td.chipcell {{ width:16.66%; padding:2px 3px; }}
  .badge {{ display:inline-block; font-size:11px; font-weight:700; color:#fff;
            padding:3px 5px; border-radius:4px; margin-right:6px; vertical-align:2px; }}
  .badge.buy {{ background:#E41A1A; }}
  .badge.sell {{ background:#169668; }}
  .name {{ font-size:15px; font-weight:700; color:#26201E; line-height:1.2; }}
  .tag {{ font-size:11px; color:#BAAEA8; margin:0 1px 0 5px; vertical-align:1px; }}
  .amt {{ font-size:15px; font-weight:700; margin-left:6px; }}
  .amt.buy {{ color:#E41A1A; }}
  .amt.sell {{ color:#169668; }}
  .chip {{ display:block; text-align:center; font-size:13px; font-weight:500; color:#4E4642;
           background:#FBF7F3; border:1px solid #F5E9E2; border-radius:5px; padding:3px 0; }}
  .foot {{ width:1016px; margin-top:15px; padding-top:13px; border-top:1px solid #EEDDD5;
           text-align:center; font-size:12.5px; color:#A99C95; letter-spacing:.3px; }}
</style></head>
<body>
  <table class="head"><tr>
    <td><span class="bar"></span><span class="d">10月21日</span><span class="sub">游资龙虎榜</span></td>
    <td align="right"><span class="lg buy">净买</span><span class="lg sell">净卖</span></td>
  </tr></table>
  <div class="rule"></div>
  <table class="card">
    {"".join(rows)}
  </table>
  <div class="foot">{FOOTNOTE}</div>
</body></html>"""

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(HTML)
print("written", out)
