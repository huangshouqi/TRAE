# -*- coding: utf-8 -*-
"""龙虎榜数据抓取：东方财富数据中心公开接口（无需 token）。

用到的报表：
  RPT_DAILYBILLBOARD_DETAILSNEW  当日龙虎榜个股清单
  RPT_BILLBOARD_DAILYDETAILSBUY  当日买入前五席位明细
  RPT_BILLBOARD_DAILYDETAILSSELL 当日卖出前五席位明细
  RPT_ORGANIZATION_TRADE_DETAILS 当日机构专用买卖统计
"""
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _request(report, filt, page=1, size=500, sort=None, sort_type=-1, retries=3):
    params = {
        "reportName": report, "columns": "ALL", "source": "WEB", "client": "WEB",
        "pageNumber": str(page), "pageSize": str(size), "filter": filt,
    }
    if sort:
        params["sortColumns"] = sort
        params["sortTypes"] = str(sort_type)
    url = BASE + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:                      # 网络抖动重试
            last = exc
            time.sleep(1.2 * (i + 1))
    raise RuntimeError("接口请求失败 %s: %s" % (report, last))


def _fetch_all(report, filt, sort="NET", sort_type=-1, size=500):
    rows, page = [], 1
    while True:
        data = _request(report, filt, page=page, size=size, sort=sort, sort_type=sort_type)
        result = data.get("result") or {}
        batch = result.get("data") or []
        rows.extend(batch)
        pages = result.get("pages") or 1
        if page >= pages or not batch:
            break
        page += 1
    return rows


PUSH2HIS = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PUSH2LIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"
PUSH2EX = "https://push2ex.eastmoney.com"


def _http_json(url, retries=3, pause=1.2):
    """通用行情接口（东方财富 push 系列，无需 token）。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            time.sleep(pause * (i + 1))
    raise RuntimeError("行情接口请求失败: %s" % last)


def _http_text(url, referer, retries=3, pause=1.2, encoding="utf-8"):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as resp:
                return resp.read().decode(encoding, "ignore")
        except Exception as exc:
            last = exc
            time.sleep(pause * (i + 1))
    raise RuntimeError("行情接口请求失败: %s" % last)


def _em_index(trade_date):
    """东方财富 上证指数 日K（历史交易日可查）。"""
    url = ("%s?secid=1.000001&fields1=f1,f2,f3,f4,f5,f6"
           "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
           "&klt=101&fqt=1&beg=%s&end=%s" % (PUSH2HIS, trade_date, trade_date))
    klines = ((_http_json(url, retries=2).get("data") or {}).get("klines")) or []
    if not klines:
        return None
    p = klines[-1].split(",")
    return {"name": "上证指数", "point": float(p[2]),
            "chg_pct": float(p[8]), "chg_amt": float(p[9])}


def _tx_index(trade_date):
    """腾讯 上证指数 日K（历史交易日可查）。"""
    beg = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           "?param=sh000001,day,%s,%s,20,qfq" % (beg, trade_date))
    data = json.loads(_http_text(url, "https://gu.qq.com/"))["data"]["sh000001"]
    rows = data.get("qfqday") or data.get("day") or []
    series = [(r[0], float(r[2])) for r in rows]
    pos = next((i for i, s in enumerate(series) if s[0] == trade_date), None)
    if pos is None:
        return None
    close = series[pos][1]
    prev = series[pos - 1][1] if pos > 0 else close
    chg = close - prev
    return {"name": "上证指数", "point": close,
            "chg_pct": (chg / prev * 100.0) if prev else 0.0, "chg_amt": chg}


def _sina_index():
    """新浪 上证指数 实时（仅当日有效）。"""
    text = _http_text("https://hq.sinajs.cn/list=s_sh000001",
                      "https://finance.sina.com.cn/", encoding="gbk")
    payload = text.split('"')[1] if '"' in text else ""
    p = payload.split(",")
    if len(p) < 4:
        return None
    return {"name": "上证指数", "point": float(p[1]),
            "chg_pct": float(p[3]), "chg_amt": float(p[2])}


def fetch_index(trade_date, allow_live=True):
    """上证指数：东财日K -> 腾讯日K ->（仅当日）新浪实时，逐级兜底。"""
    for fn in (_em_index, _tx_index):
        try:
            r = fn(trade_date)
            if r:
                return r
        except Exception:
            continue
    if not allow_live:
        return None
    try:
        return _sina_index()
    except Exception:
        return None


def _pool_total(kind, sort_key, trade_date):
    d = trade_date.replace("-", "")
    url = ("%s/getTopic%sPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
           "&Pageindex=0&pagesize=1&sort=%s&date=%s"
           % (PUSH2EX, kind, urllib.parse.quote(sort_key), d))
    return (_http_json(url).get("data") or {}).get("tc")


def fetch_limit_counts(trade_date):
    """涨停 / 跌停家数（按交易日，历史可查）。数据池不覆盖时返回 None。"""
    zt = _pool_total("ZT", "fbt:asc", trade_date)
    dt = _pool_total("DT", "fund:asc", trade_date)
    if (zt or 0) == 0 and (dt or 0) == 0:
        return {"zt": None, "dt": None}
    return {"zt": zt, "dt": dt}


def fetch_breadth():
    """沪深京涨 / 跌 / 平家数（仅当日实时快照，取不到返回 None）。"""
    url = ("%s?ut=fa5fd1943c7b386f172d6893dbfba10b&fltt=2&invt=2"
           "&fields=f104,f105,f106&secids=1.000001,0.399001,0.899050" % PUSH2LIST)
    try:
        diff = (_http_json(url, retries=3, pause=4.0).get("data") or {}).get("diff") or []
    except Exception:
        return None
    up = down = flat = 0
    for x in diff:
        up += int(x.get("f104") or 0)
        down += int(x.get("f105") or 0)
        flat += int(x.get("f106") or 0)
    if up + down + flat == 0:
        return None
    return {"up": up, "down": down, "flat": flat}


def fetch_market(trade_date, with_breadth=True, allow_live=True):
    """大盘概览：上证指数 + 涨停/跌停 + 涨跌家数。任一项缺失为 None，不影响主流程。"""
    market = {"index": None, "zt": None, "dt": None, "up": None, "down": None, "flat": None}
    try:
        market["index"] = fetch_index(trade_date, allow_live=allow_live)
    except Exception as exc:
        print("   [市场] 指数获取失败：%s" % exc)
    try:
        market.update(fetch_limit_counts(trade_date))
    except Exception as exc:
        print("   [市场] 涨跌停家数获取失败：%s" % exc)
    if with_breadth and allow_live:
        breadth = fetch_breadth()
        if breadth:
            market.update(breadth)
        else:
            print("   [市场] 涨跌家数暂不可用（实时接口限流）")
    return market


def resolve_trade_date(explicit=None, max_back=15):
    """未指定日期时，从今天往前找最近一个有龙虎榜数据的交易日。"""
    if explicit:
        return explicit
    today = datetime.now().strftime("%Y-%m-%d")
    for i in range(max_back):
        d = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
        data = _request("RPT_DAILYBILLBOARD_DETAILSNEW", "(TRADE_DATE='%s')" % d, size=1)
        rows = (data.get("result") or {}).get("data") or []
        if rows:
            return d
    raise RuntimeError("最近 %d 天都没有龙虎榜数据" % max_back)


def fetch_day(trade_date):
    """抓取某个交易日的全部龙虎榜原始数据。"""
    stocks = _fetch_all("RPT_DAILYBILLBOARD_DETAILSNEW",
                        "(TRADE_DATE='%s')" % trade_date, sort="SECURITY_CODE", sort_type=1, size=1000)
    buys = _fetch_all("RPT_BILLBOARD_DAILYDETAILSBUY",
                      "(TRADE_DATE='%s')" % trade_date, sort="NET", sort_type=-1, size=1000)
    sells = _fetch_all("RPT_BILLBOARD_DAILYDETAILSSELL",
                       "(TRADE_DATE='%s')" % trade_date, sort="NET", sort_type=-1, size=1000)
    org = _fetch_all("RPT_ORGANIZATION_TRADE_DETAILS",
                     "(TRADE_DATE='%s')" % trade_date, sort="NET_BUY_AMT", sort_type=-1, size=1000)
    return {"date": trade_date, "stocks": stocks, "buys": buys, "sells": sells, "org": org}


if __name__ == "__main__":
    import sys
    d = resolve_trade_date(sys.argv[1] if len(sys.argv) > 1 else None)
    raw = fetch_day(d)
    print(d, "个股", len(raw["stocks"]), "买席", len(raw["buys"]),
          "卖席", len(raw["sells"]), "机构", len(raw["org"]))
    print("大盘", fetch_market(d))
