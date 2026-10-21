# -*- coding: utf-8 -*-
"""把龙虎榜原始数据聚合成看板结构：左栏席位 + 右栏个股净买卖明细。"""


def load_json(path):
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def short_name(full):
    """把营业部全称压成样图风格的简称：
    营业部类 -> 只留地名（中信建投证券北京朝外大街证券营业部 -> 北京朝外大街）
    分公司类 -> 券商简称+地名+分（国新证券北京分公司 -> 国新北京分）
    总部类   -> 券商简称+总部（华泰证券总部 -> 华泰总部）
    """
    s = (full or "").strip()
    for k in ("股份有限公司", "有限责任公司", "有限公司"):
        s = s.replace(k, "")
    branch = s.endswith("分公司")
    if branch:
        s = s[:-3]
    for k in ("证券营业部", "营业部"):
        s = s.replace(k, "")
    s = s.strip()
    if s.startswith("中国国际金融"):
        s = s[len("中国国际金融"):]
    if "证券" in s:
        pre, _, post = s.partition("证券")
        pre, post = pre.strip(), post.strip()
        if post == "总部":
            return pre + "总部"
        if branch and post:
            return (post + "分") if post.startswith(pre) else (pre + post + "分")
        return post or pre + "证券"
    return s or (full or "")


def classify(dept, mapping):
    """返回 (类别, 标签)：类别为 seat(单独一行) / group(归入分组) / skip(丢弃)"""
    for kw in mapping.get("排除席位", []):
        if kw in dept:
            return "skip", None
    for gname, rule in mapping.get("分组", {}).items():
        builtin = rule.get("内置")
        if builtin and builtin == dept:
            return "group", gname
        for kw in rule.get("关键词", []):
            if kw in dept:
                return "group", gname
    for entry in mapping.get("游资", []):
        for kw in entry.get("关键词", []):
            if kw in dept:
                return "seat", entry["显示名"]
    return "seat", short_name(dept)


def fmt_amount(v):
    """金额格式：>=1亿 用 1.10y，否则 2523w"""
    a = abs(v)
    if a >= 1e8:
        return "%.2fy" % (a / 1e8)
    return "%.0fw" % (a / 1e4)


def _net_by_dept_stock(buys, sells):
    """席位 x 个股 净额。
    买入表与卖出表各只带一侧金额（另一侧为 None），同一席位可能同时出现在两张表里；
    必须先按「席位 + 个股 + 上榜原因」把买入、卖出合并成净额，否则会把单边买入金额当成净买。
    同一席位同一只票还会因「日榜 / 三日榜」等不同上榜原因重复出现，
    合并后再按绝对值最大取一条，避免重复计算。
    """
    per_reason = {}
    for rows in (buys, sells):
        for r in rows:
            key = (r.get("OPERATEDEPT_NAME") or "", r.get("SECURITY_CODE") or "",
                   r.get("EXPLANATION") or "")
            slot = per_reason.setdefault(key, {"buy": None, "sell": None})
            b, s = r.get("BUY"), r.get("SELL")
            if b is not None and (slot["buy"] is None or b > slot["buy"]):
                slot["buy"] = b
            if s is not None and (slot["sell"] is None or s > slot["sell"]):
                slot["sell"] = s

    agg = {}
    for (dept, code, _reason), slot in per_reason.items():
        value = (slot["buy"] or 0.0) - (slot["sell"] or 0.0)
        key = (dept, code)
        if key not in agg or abs(value) > abs(agg[key]):
            agg[key] = value
    return agg


def build(raw, mapping, style, market=None):
    # 1) 个股名称 / 是否三日榜
    info = {}
    for r in raw["stocks"]:
        code = r.get("SECURITY_CODE")
        if not code:
            continue
        txt = "%s%s" % (r.get("EXPLANATION") or "", r.get("EXPLAIN") or "")
        cur = info.setdefault(code, {"name": r.get("SECURITY_NAME_ABBR") or code, "three": False})
        # 可转债 / 科创板的上榜原因写作“连续3个交易日”，其余写作“连续三个交易日”
        cur["three"] = cur["three"] or ("连续三个交易日" in txt or "连续3个交易日" in txt)

    # 2) 席位 x 个股 净额（买入表 + 卖出表按「席位+个股+上榜原因」合并）
    net = _net_by_dept_stock(raw["buys"], raw["sells"])

    # 3) 按席位归类
    seat_items, group_items = {}, {}
    for (dept, code), value in net.items():
        if not value:
            continue
        kind, label = classify(dept, mapping)
        if kind == "skip":
            continue
        bucket = group_items if kind == "group" else seat_items
        bucket.setdefault(label, {})
        bucket[label][code] = bucket[label].get(code, 0.0) + value

    def to_items(code_map):
        items = []
        for code, value in code_map.items():
            meta = info.get(code) or {"name": code, "three": False}
            items.append({"name": meta["name"], "three": meta["three"], "net": value})
        items.sort(key=lambda it: (-it["net"] if it["net"] > 0 else 0, -abs(it["net"])))
        return items

    min_amt = style.get("min_net_amount", 0)

    def keep(items):
        out = [it for it in items if abs(it["net"]) >= min_amt]
        return out

    # 4) 游资单独行：先按映射表顺序，再按净额绝对值补足
    rows = []
    named_order = [e["显示名"] for e in mapping.get("游资", [])]
    used = set()
    for label in named_order:
        items = keep(to_items(seat_items.get(label, {})))
        if items:
            rows.append({"label": label, "kind": "seat", "items": items})
            used.add(label)

    # 未命中游资映射的泛席位（如“XX证券总部/XX分公司”）默认隐藏，避免榜单被大而杂的通道席位淹没
    if not style.get("only_named_seats"):
        rest = [(lbl, to_items(m)) for lbl, m in seat_items.items() if lbl not in used]
        rest = [(lbl, keep(items)) for lbl, items in rest]
        rest = [(lbl, items) for lbl, items in rest if items]
        rest.sort(key=lambda kv: -sum(abs(it["net"]) for it in kv[1]))
        for label, items in rest:
            if len(rows) >= style.get("max_seat_rows", 30):
                break
            rows.append({"label": label, "kind": "seat", "items": items})

    # 5) 分组行
    for gname in style.get("group_order", []):
        if gname == "机构":
            # 机构表同一只票可能因“日榜/三日榜”出现多行，只取净额绝对值最大的那条
            best = {}
            for r in raw["org"]:
                code = r.get("SECURITY_CODE")
                if not code:
                    continue
                value = r.get("NET_BUY_AMT") or 0.0
                if code not in best or abs(value) > abs(best[code]):
                    best[code] = value
            items = []
            for code, value in best.items():
                if abs(value) < min_amt:
                    continue
                meta = info.get(code) or {"name": code, "three": False}
                items.append({"name": meta["name"], "three": meta["three"], "net": value})
            items.sort(key=lambda it: (-it["net"] if it["net"] > 0 else 0, -abs(it["net"])))
            if items:
                rows.append({"label": gname, "kind": "plain", "items": items})
        elif gname == "拉萨天团":
            items = keep(to_items(group_items.get(gname, {})))
            if items:
                rows.append({"label": gname, "kind": "names", "items": items})
        else:
            items = keep(to_items(group_items.get(gname, {})))
            if items:
                rows.append({"label": gname, "kind": "seat", "items": items})

    # 6) 按配置隐藏指定栏目（如「机构」）
    exclude = set(style.get("exclude_labels", []))
    if exclude:
        rows = [r for r in rows if r["label"] not in exclude]

    y, m, d = (int(x) for x in raw["date"].split("-"))
    return {"date": raw["date"], "m": m, "d": d, "market": market, "rows": rows}
