# -*- coding: utf-8 -*-
"""
每日「连板天梯」图片生成（红色系 / 抖音图文竖版长图）
数据来源：东方财富涨停股池（akshare）
运行：python daily_ladder.py [--date 20261015] [--from-cache]
"""
import argparse
import json
import math
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
_PYLIBS = os.path.join(BASE, "pylibs")
# pylibs 内是 Windows 版二进制依赖，非 Windows 环境改用系统已安装的包
if os.name == "nt" and os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

import pandas as pd
import requests
from PIL import Image, ImageDraw, ImageFont

DATA_DIR = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "output")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------- 字体（跨平台：Windows 微软雅黑 / Linux 思源黑体 Noto） ----------------
S = 3                       # 超采样倍率：内部按 S 倍分辨率渲染后降采样，文字更清晰锐利
_fc = {}
_ASSETS = os.path.join(BASE, "assets", "fonts")

# 按顺序探测：项目自带字体优先 → Windows 微软雅黑 → Linux 开源中文字体
# （Linux 路径同时覆盖 Debian/Ubuntu 与 RHEL/Alibaba Cloud Linux 两种字体目录布局）
_FONT_PATHS = {
    False: [os.path.join(_ASSETS, "regular.ttf"),
            os.path.join(_ASSETS, "msyh.ttc"),
            r"C:\Windows\Fonts\msyh.ttc",
            # Noto Sans CJK SC 单字体文件（Debian/Ubuntu 的 noto-cjk-otf 包）
            "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Regular.otf",
            "/usr/share/fonts/opentype/noto-cjk/NotoSansCJKsc-Regular.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc"],
    True:  [os.path.join(_ASSETS, "bold.ttf"),
            os.path.join(_ASSETS, "msyhbd.ttc"),
            r"C:\Windows\Fonts\msyhbd.ttc",
            # Noto Sans CJK SC Bold 单字体文件（此前缺失，导致粗体退化为文泉驿正黑）
            "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf",
            "/usr/share/fonts/opentype/noto-cjk/NotoSansCJKsc-Bold.otf",
            "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Bold.otf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/google-noto-sans-cjk-fonts/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc"],
}


def _pick_font(bold):
    for p in _FONT_PATHS[bold]:
        if os.path.exists(p):
            return p
    return None


def _scan_system_font(bold):
    """兜底：扫描系统字体目录找任意可用的 CJK 字体，适配不同发行版的目录/包名差异"""
    import glob
    keys = (["NotoSansCJKsc*Bold*", "NotoSansSC*Bold*", "SourceHanSansSC*Bold*",
             "NotoSansCJK*Bold*", "SourceHanSans*Bold*", "wqy-zenhei*"]
            if bold else
            ["NotoSansCJKsc*Regular*", "NotoSansSC*Regular*", "SourceHanSansSC*Regular*",
             "NotoSansCJK*Regular*", "SourceHanSans*Regular*",
             "wqy-zenhei*", "DroidSansFallback*", "NotoSansCJK*"])
    for k in keys:
        for ext in ("ttc", "ttf", "otf"):
            hits = sorted(glob.glob("/usr/share/fonts/**/" + k + "." + ext, recursive=True))
            if hits:
                return hits[0]
    return None


FONT_REG = (_pick_font(False) or _pick_font(True)
            or _scan_system_font(False) or _scan_system_font(True))
FONT_BOLD = (_pick_font(True) or _pick_font(False)
             or _scan_system_font(True) or _scan_system_font(False))
if FONT_REG is None:
    raise RuntimeError("未找到可用中文字体：请放置字体到 assets/fonts/，"
                       "或安装 fonts-noto-cjk / wqy-zenhei-fonts")


def F(size, bold=False):
    """逻辑字号 -> 字体对象（内部已按 S 放大，配合 SDraw 使用逻辑坐标）"""
    k = (size, bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FONT_BOLD if bold else FONT_REG,
                                    max(1, int(round(size * S))))
    return _fc[k]


def tw(draw, s, font):
    """逻辑文本宽度（SDraw 已把像素长度换算回逻辑单位）"""
    return draw.textlength(s, font=font)


class SDraw:
    """逻辑坐标绘制器：对外坐标/尺寸均为逻辑像素（1080x1440 设计稿），
    内部按 S 倍超采样真正绘制，避免 CJK 细笔画在小字号被吞掉、放大后发虚。"""

    def __init__(self, img, s=S):
        self.img = img
        self.s = s
        self._d = ImageDraw.Draw(img)

    def _p(self, xy):
        return (xy[0] * self.s, xy[1] * self.s)

    def text(self, xy, text, font=None, fill=None, anchor=None, **kw):
        return self._d.text(self._p(xy), text, font=font, fill=fill,
                            anchor=anchor, **kw)

    def textlength(self, text, font=None):
        return self._d.textlength(text, font=font) / self.s

    def textbbox(self, xy, text, font=None, anchor=None, **kw):
        b = self._d.textbbox(self._p(xy), text, font=font, anchor=anchor, **kw)
        return tuple(v / self.s for v in b)

    def line(self, xy, fill=None, width=1):
        pts = []
        for i in range(0, len(xy), 2):
            pts.extend([xy[i] * self.s, xy[i + 1] * self.s])
        self._d.line(pts, fill=fill, width=max(1, int(round(width * self.s))))


# ---------------- 配色（红色系，主色 #FF0000） ----------------
BG          = (250, 245, 242)
INK         = (38, 32, 30)
RED         = (228, 26, 26)
RED_DEEP    = (176, 0, 0)
RED_BRIGHT  = (250, 70, 70)
RED_SOFT    = (255, 241, 240)
GOLD        = (188, 138, 44)
GREEN       = (22, 150, 104)
BLUE        = (28, 92, 176)
YELLOW      = (198, 132, 16)
GRAY_T      = (140, 132, 124)
GRAY_L      = (170, 161, 153)
CARD_BD     = (236, 219, 212)
PANEL_BG    = (255, 255, 255)
WHITE       = (255, 255, 255)
WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 涨停板块前三名：分别以红 / 蓝 / 黄显示（表头标签与个股所属板块一致）
SEC_TXT  = [RED, BLUE, YELLOW]
SEC_TINT = [(255, 241, 240), (238, 244, 253), (255, 248, 232)]
SEC_BD   = [(250, 198, 196), (178, 205, 240), (242, 220, 158)]


# ============================================================
# 数据获取
# ============================================================
def col(df, *names):
    for n in names:
        if n in df.columns:
            return df[n]
    return pd.Series([None] * len(df))


def fnum(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except Exception:
        return default


def norm_time(t):
    s = "".join(c for c in str(t) if c.isdigit())
    if not s:
        return ""
    s = s.zfill(6)[:6]
    return f"{s[:2]}:{s[2:4]}"


def parse_stat(v):
    """涨停统计 '10/14' -> (10,14) 即 14天10板"""
    if isinstance(v, str) and "/" in v:
        try:
            a, b = v.split("/")[:2]
            return int(a), int(b)
        except Exception:
            return None
    return None


# 东财涨停池的「所属行业」被截断为 4 字（汽车零部件 → 汽车零部），
# 用行业板块全称表做前缀还原，保证板块名完整显示
_IND_FULL = []
IND_FIX_BUILTIN = {
    "汽车零部": "汽车零部件",
    "房地产开": "房地产开发",
    "自动化设": "自动化设备",
    "计算机设": "计算机设备",
    "工程咨询": "工程咨询服务",
    "互联网服": "互联网服务",
    "光学光电": "光学光电子",
}


def load_industry_names():
    """加载东财行业板块全称表（失败则回退内置映射）"""
    global _IND_FULL
    try:
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        names = [str(x).strip() for x in col(df, "板块名称", "行业名称", "名称").tolist()]
        _IND_FULL = sorted({n for n in names if n}, key=len)
        print(f"行业全称表已加载：{len(_IND_FULL)} 条")
    except Exception as e:
        print(f"行业全称表获取失败，改用内置映射：{e}")
    return _IND_FULL


def fix_industry(short):
    """把被截断的行业名还原为板块全称"""
    s = str(short or "").removesuffix("Ⅱ").removesuffix("II").strip()
    if not s:
        return "其他"
    if _IND_FULL:
        if s in _IND_FULL:
            return s
        for n in _IND_FULL:            # 已按长度升序，取最短匹配
            if len(n) > len(s) and n.startswith(s):
                return n
    return IND_FIX_BUILTIN.get(s, s)


def normalize_industries(data):
    """把数据里的截断行业名（缓存或拉取）统一还原为板块全称"""
    for s in data.get("stocks", []):
        s["industry"] = fix_industry(s.get("industry", ""))
    for lst in (data.get("failed") or {}).values():
        for s in lst:
            s["industry"] = fix_industry(s.get("industry", ""))
    return data


# ---------------- 题材归类（东财概念板块，贴合当日热点） ----------------
# 东财接口可用主机（轮询容错，规避单域名限流）
EM_HOSTS = ["push2.eastmoney.com", "push2his.eastmoney.com",
            "82.push2.eastmoney.com", "push2delay.eastmoney.com"]

# 非题材类概念（风格/资金/指数成分等），不参与热点题材归属
CONCEPT_BLOCK = {
    "融资融券", "沪股通", "深股通", "转债标的", "机构重仓", "基金重仓", "QFII重仓",
    "社保重仓", "券商重仓", "信托重仓", "保险重仓", "养老金", "预盈预增", "预亏预减",
    "高送转", "次新股", "注册制次新股", "创业板综", "科创板", "ST股", "低价股",
    "破净股", "小盘股", "中盘股", "大盘股", "含B股", "含H股", "AH股", "参股新三板",
    "参股期货", "参股券商", "参股保险", "参股银行", "股权转让", "举牌", "并购重组",
    "借壳上市", "创投", "债转股", "中字头", "央企改革", "央国企改革", "国企改革",
    "混改", "西部大开发", "雄安新区", "MSCI中国", "富时罗素", "标准普尔", "央视50",
    "上证50", "上证180", "中证500", "深证100", "沪深300", "北证50", "专精特新",
    "独角兽", "热门股", "权重股", "百元股", "微盘股", "高股息", "破发股",
}

# 属性/风格类概念（非题材主线）：含以下关键词的板块名不参与热点题材归属
CONCEPT_BLOCK_SUB = (
    "昨日", "振幅", "多板", "新进", "增发价", "涨停", "连板", "换手",
    "新高", "新低", "解禁", "回购", "增持", "减持", "游资", "龙虎榜",
    "机构调研", "业绩", "预增", "预减", "预盈", "预亏", "首亏", "中报",
    "季报", "年报", "超跌", "摘帽", "高送转", "破净",
    "破发", "低价", "高价", "微盘", "小盘", "中盘", "大盘", "举牌",
    "重组", "活跃", "热股", "增仓", "减仓", "题材股", "壳资源", "次新",
    # 地区/区域类概念（非题材主线，不参与热点归属）
    "三角", "粤港澳", "京津冀", "一带一路", "本地", "自贸", "成渝", "海南",
    "滨海", "雄安", "东北", "振兴", "西部",
)


def _is_blocked(nm):
    if nm in CONCEPT_BLOCK:
        return True
    return any(k in nm for k in CONCEPT_BLOCK_SUB)


# 东财兜底用的「大伞」概念：这类概念会被大量个股共享、共现次数天然很高，
# 但并不代表个股当日涨停原因，兜底选标签时降级处理
FALLBACK_UMBRELLA = {
    "电子", "机械设备", "人工智能", "新能源车", "消费", "科技", "物联网",
    "计算机", "计算机设备", "通用设备", "基础化工", "医药生物",
}


# 人工指定：个别个股当日主线题材（优先于自动归类结果）
THEME_OVERRIDE = {
    "001696": "低空经济",     # 宗申动力：低空经济核心（无人机/eVTOL 动力）
    "000099": "低空经济",     # 中信海直：低空经济（通航运营）龙头
    "601606": "军工",         # 长城军工：军工主线
}


def em_secid(code):
    """东财 secid：沪市 1.xxxxxx，其余 0.xxxxxx"""
    code = str(code)
    return ("1." if code.startswith(("6", "9")) else "0.") + code


def _em_diff(path, params):
    """轮询多个东财主机，返回 data.diff 列表（全部失败则抛错）"""
    last = None
    for host in EM_HOSTS:
        try:
            r = requests.get(f"https://{host}/api/qt{path}", params=params,
                             headers=HTTP_HEADERS, timeout=12)
            d = (r.json().get("data") or {}).get("diff") or {}
            d = list(d.values()) if isinstance(d, dict) else d
            if d:
                return d
        except Exception as e:
            last = e
            time.sleep(0.1)
    if last is not None:
        raise last
    return []


def _slist(c, spt):
    """东财个股所属板块列表：spt=3 全部板块，spt=1 仅行业；返回 [(板块代码, 板块名)]"""
    diff = _em_diff("/slist/get", {"spt": spt, "fltt": 2, "invt": 2,
                                   "fields": "f12,f13,f14",
                                   "secid": em_secid(c), "pn": 1, "pz": 300,
                                   "po": 1, "fid": "f3"})
    return [(d.get("f12"), d.get("f14")) for d in diff if d.get("f14")]


def fetch_stock_boards(codes):
    """个股所属板块：concepts = spt3(全部) - spt1(仅行业)，天然剔除行业/风格板块。
    作为同花顺涨停原因之外的兜底分类来源。"""
    out = {}
    for c in codes:
        try:
            all_b = _slist(c, 3)
            ind_codes = {bk for bk, _ in _slist(c, 1)}
            out[c] = [nm for bk, nm in all_b if bk not in ind_codes]
        except Exception:
            out[c] = []
        time.sleep(0.12)                 # 轻微限速，避免被东财限流
    return out


# ---------------- 同花顺「涨停原因」：最贴近个股当日涨停逻辑的分类源 ----------------
THS_ZT_URL = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
THS_FIELDS = ("199112,10,9001,330323,330324,330325,9002,330329,133971,133970,"
              "330330,330331,133969,330332,330334,330335")

# 事件/交易属性类原因：不作为板块概念展示
REASON_EVENT = ("复牌", "停牌", "摘帽", "业绩", "预增", "预减", "预盈", "预亏", "首亏",
                "订单", "中标", "增持", "减持", "回购", "解禁", "股权激励", "员工持股",
                "更名", "补贴", "补助", "诉讼", "扭亏", "减亏", "超跌", "反弹", "异动",
                "涨停", "连板", "新股", "次新", "高送转", "公告", "机构调研",
                "调查", "出售", "转让", "展期", "债务", "立案", "处罚", "问询",
                "重整", "破产", "注销", "分立", "迁址", "撤销", "海外业务", "全球销售")

# 涨停原因关键词 → 归一到统一的板块概念名（顺序即优先级，先匹配者胜出）
REASON_RULES = [
    (("低空", "无人机", "eVTOL", "evtol", "通用航空", "通航", "低空智联"), "低空经济"),
    (("飞行汽车",), "飞行汽车"),
    (("商业航天", "卫星", "北斗", "星座"), "商业航天"),
    (("军工", "弹药", "军民", "军贸", "兵装", "国防", "防务", "军用", "航空",
      "惯导", "特种装备", "航天"), "军工"),
    (("尊界", "问界", "智界", "享界", "鸿蒙智行"), "华为汽车"),
    (("重组", "并购", "借壳", "资产注入", "收购", "整合"), "并购重组"),
    (("传媒", "出版", "影视", "院线", "短剧", "漫剧", "游戏", "数字教育", "图书"), "传媒"),
    (("冰雪",), "冰雪产业"),
    (("机器人", "人形"), "机器人概念"),
    (("新能源车", "新能源汽车", "电驱", "锂电", "固态电池", "充电桩"), "新能源车"),
    (("汽车", "整车"), "汽车"),
    (("算力", "数据中心", "液冷", "CPO", "光模块", "智算"), "算力"),
    # AI 细分（必须排在「人工智能」之前）：同花顺给出的细分涨停原因各自成类，
    # 避免被「人工智能」这把大伞吞掉（端侧/物理AI/大模型/应用 是完全不同的方向）
    (("端侧AI", "端侧智能", "AI眼镜", "AI PC", "AIPC", "AI手机", "AIoT",
      "AI ISP", "AI服务器", "AI硬件", "智能终端"), "AI硬件"),
    (("物理AI", "具身智能", "具身仿真", "AI数字孪生"), "物理AI"),
    (("大模型", "AIGC", "智能体", "多模态"), "AI大模型"),
    (("AI应用", "行业应用"), "AI应用"),
    (("人工智能",), "人工智能"),
    (("PCB", "印制电路", "覆铜板", "电路板"), "PCB板"),
    (("半导体", "芯片", "存储", "光刻", "封装", "LED", "MEMS", "集成电路"), "半导体"),
    (("核聚变", "核能"), "可控核聚变"),
    (("光伏",), "光伏"),
    (("储能", "储氢", "氢能"), "储能"),
    (("医药", "原料药", "创新药", "中药", "疫苗", "眼科"), "医药"),
    (("券商", "证券"), "大金融"),
    (("房地产", "地产"), "房地产"),
    (("水泥", "建材", "熟料"), "建材"),
    (("化工", "化学", "氯碱", "有机胺", "新材料", "粘胶"), "化工"),
    (("电力", "电网", "核电", "风电"), "电力设备"),
    (("有色", "黄金", "稀土", "铜"), "有色金属"),
    (("物流", "港口", "航运", "供应链", "仓储"), "物流航运"),
    (("宠物",), "宠物经济"),
    (("白酒", "食品", "乳品", "按摩", "鳗鱼", "水产"), "消费"),
    # ---- 东财概念口径表（兜底用）----
    # 东财的概念名与同花顺「涨停原因」口径不一致，这里把常见概念归一到已用板块名，
    # 让兜底分类与主分类说同一套话；后续按需补充。
    (("印制电路", "覆铜板", "电路板"), "PCB板"),
    (("碳化硅", "氮化镓", "分立器件", "被动元件", "集成电路", "光刻机"), "半导体"),
    (("数据要素", "数据确权", "东数西算"), "数据要素"),
    (("数字货币", "跨境支付", "金融科技"), "大金融"),
    (("工业母机", "智能制造", "工业互联"), "智能制造"),
    (("减速器", "丝杠", "谐波", "空心杯"), "机器人概念"),
    (("智能驾驶", "无人驾驶", "车路协同"), "智能驾驶"),
    (("卫星互联网", "北斗", "卫星导航"), "商业航天"),
    (("大飞机", "航空发动机"), "军工"),
    (("水利建设", "装配建筑", "建筑装饰", "房屋检测", "工程咨询"), "基建"),
    (("石墨烯", "涂料油墨", "光刻胶", "纳米银"), "新材料"),
    (("影视概念", "数字阅读", "大众出版", "网红经济", "谷子经济", "知识产权"), "传媒"),
    (("CRO", "医疗研发外包", "脑机接口", "创新药", "医药生物", "医疗服务"), "医药"),
    (("在线教育", "教育培训"), "教育"),
    (("苹果概念", "无线耳机", "无线充电", "智能穿戴", "消费电子"), "消费电子"),
    (("DeepSeek概念", "算力概念", "光通信模块", "CPO概念"), "算力"),
]


# 规则输出的规范板块名：东财概念兜底时，归一到这里的候选同样算「已识别板块」
KNOWN_BOARDS = {out for _, out in REASON_RULES}


def rule_hit(name):
    """返回命中的规则序号（越小代表越具体）；无命中返回 None"""
    for i, (keys, _) in enumerate(REASON_RULES):
        if any(k in name for k in keys):
            return i
    return None


def map_theme(name):
    """把一个标签/概念名映射到规范板块名；无匹配返回 None"""
    i = rule_hit(name)
    return REASON_RULES[i][1] if i is not None else None


def pick_theme(tags):
    """从同花顺「涨停原因」标签里挑最相关的板块：优先第一个可归一到已知板块的标签；
    没有可归一的原因时，原样展示第一个非事件类涨停原因。"""
    raw_first = None
    for t in tags:
        t = str(t or "").strip()
        if not t or any(k in t for k in REASON_EVENT):
            continue
        hit = map_theme(t)
        if hit:
            return hit
        if raw_first is None:
            raw_first = t
    return raw_first


def fetch_ths_reasons(ds):
    """同花顺涨停池：code -> [涨停原因标签]（按 "+" 顺序，主因在前）"""
    r = requests.get(THS_ZT_URL, params={"page": 1, "limit": 200, "field": THS_FIELDS,
                                         "filter": "HS,GEM2STAR", "order_field": "330324",
                                         "order_type": 0, "date": ds},
                     headers={"User-Agent": HTTP_HEADERS["User-Agent"],
                              "Referer": "https://data.10jqka.com.cn/"}, timeout=15)
    r.raise_for_status()
    info = (r.json().get("data") or {}).get("info") or []
    out = {}
    for it in info:
        code = str(it.get("code") or "")
        rt = str(it.get("reason_type") or "").strip()
        if code and rt and rt != "None":
            out[code] = [t for t in rt.split("+") if t]
    return out


def load_theme_override():
    """个股题材人工覆盖表：data/theme_override.json（{"股票代码": "板块名"}），优先级最高"""
    path = os.path.join(DATA_DIR, "theme_override.json")
    try:
        with open(path, encoding="utf-8") as fp:
            d = json.load(fp) or {}
        return {str(k): str(v) for k, v in d.items()
                if not str(k).startswith("_") and v}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"  覆盖表 theme_override.json 读取失败：{e}")
        return {}


def attach_themes(data):
    """分类优先级：人工覆盖表 → 同花顺「涨停原因」→ 东财概念板块 → 东财行业"""
    stocks = data.get("stocks", [])
    failed = [x for v in (data.get("failed") or {}).values() for x in v]
    alls = list(stocks) + list(failed)
    if not alls:
        return data

    # 人工指定优先（内置 THEME_OVERRIDE + data/theme_override.json）
    override = dict(THEME_OVERRIDE)
    override.update(load_theme_override())
    if len(override) > len(THEME_OVERRIDE):
        print(f"  人工覆盖表：{len(load_theme_override())} 只")
    for s in alls:
        s["theme"] = override.get(s["code"])

    # 1) 同花顺涨停原因：最贴近个股当日涨停逻辑
    reasons = {}
    try:
        reasons = fetch_ths_reasons(data["date"])
        print(f"  同花顺涨停原因：{len(reasons)} 只")
    except Exception as e:
        print(f"  同花顺涨停原因获取失败，改用东财概念：{e}")
    for s in alls:
        if s["code"] not in override:
            s["theme"] = pick_theme(reasons.get(s["code"], [])) if reasons else None

    # 2) 未被涨停原因覆盖的个股，用东财概念板块兜底。
    #    打分顺序：能归到已知板块 > 非大伞概念 > 与个股所属行业一致 > 当日共现次数
    #             > 规则表越靠前（越具体） > 东财原顺序
    rest = [s for s in alls if not s.get("theme") and s["code"] not in override]
    if rest:
        try:
            boards = fetch_stock_boards([s["code"] for s in rest])
            cand, cnt = {}, {}
            for s in rest:
                names = []
                for nm in boards.get(s["code"], []):
                    nm = str(nm or "").strip().removesuffix("Ⅲ").removesuffix("Ⅱ")
                    # 过滤：风格/地区类概念、东财行业名、以及「其他XX」这类聚合概念
                    if not nm or _is_blocked(nm) or nm.endswith("板块") or nm.startswith("其他"):
                        continue
                    lb = map_theme(nm) or nm      # 东财概念名同样过一遍规则表，保持标签口径一致
                    if lb not in names:
                        names.append(lb)
                cand[s["code"]] = names
                for nm in names:
                    cnt[nm] = cnt.get(nm, 0) + 1
            for s in rest:
                ind = s.get("industry") or ""
                pick, best = None, None
                for i, nm in enumerate(cand[s["code"]]):
                    hit = rule_hit(nm)
                    score = (1 if nm in KNOWN_BOARDS else 0,                # 能归到已知板块
                             0 if nm in FALLBACK_UMBRELLA else 1,           # 大伞概念降级
                             1 if (ind and (nm in ind or ind in nm)) else 0,  # 与个股所属行业一致
                             cnt.get(nm, 0),                                # 当日共现次数
                             -(hit if hit is not None else 999),            # 规则表越靠前越具体
                             -i)                                            # 东财原顺序
                    if best is None or score > best:
                        best, pick = score, nm
                s["theme"] = pick
        except Exception as e:
            print(f"  东财概念兜底失败：{e}")

    dist = {}
    for s in stocks:
        lb = disp_ind(s)
        dist[lb] = dist.get(lb, 0) + 1
    top = sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    print("  分类分布：" + "、".join(f"{n}{c}" for n, c in top))
    return data


def retry(fn, n=3, wait=2.0, label=""):
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"  [重试 {i+1}/{n}] {label} {e}")
            time.sleep(wait)
    raise last


def fetch_pool(ak, ds):
    return retry(lambda: ak.stock_zt_pool_em(date=ds), label=f"涨停池 {ds}")


def find_pool(ak, end_date, stop_before=None, max_back=12):
    """从 end_date 向前找最近一个非空涨停池"""
    for i in range(max_back):
        d = end_date - timedelta(days=i)
        ds = d.strftime("%Y%m%d")
        if stop_before and ds >= stop_before:
            continue
        try:
            df = fetch_pool(ak, ds)
        except Exception:
            continue
        if df is not None and len(df) > 0:
            return ds, df
    return None, None


def build_stock(row):
    stat = parse_stat(row.get("涨停统计"))
    boards = int(fnum(row.get("连板数"), 1))
    return {
        "code": str(row.get("代码", "")),
        "name": str(row.get("名称", "")),
        "pct": round(fnum(row.get("涨跌幅")), 2),
        "industry": fix_industry(row.get("所属行业", "")),
        "seal": fnum(col_one(row, "封板资金", "封单资金")),
        "amount": fnum(row.get("成交额")),
        "first_time": norm_time(row.get("首次封板时间")),
        "last_time": norm_time(row.get("最后封板时间")),
        "break_cnt": int(fnum(row.get("炸板次数"))),
        "boards": boards,
        "stat_a": stat[0] if stat else boards,
        "stat_b": stat[1] if stat else boards,
        "open_limit": False,
    }


def col_one(row, *names):
    for n in names:
        if n in row.index:
            return row[n]
    return None


HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}


def tx_symbol(code):
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def tx_batch(codes, field_idx):
    """腾讯批量行情，取 ~ 分隔后的指定字段；返回 code -> 字段元组"""
    out = {}
    syms = [tx_symbol(c) for c in codes]
    for i in range(0, len(syms), 60):
        url = "http://qt.gtimg.cn/q=" + ",".join(syms[i:i + 60])
        txt = retry(lambda u=url: _http_get(u, gbk=True), n=3, wait=1.5, label="腾讯行情")
        for line in txt.split(";"):
            if "=\"" not in line:
                continue
            try:
                f = line.split("=\"", 1)[1].rstrip("\"").split("~")
                out[f[2]] = tuple(float(f[k]) if f[k] not in ("", "-") else 0.0
                                  for k in field_idx)
            except (IndexError, ValueError):
                continue
    return out


def _http_get(url, gbk=False, referer=None):
    h = dict(HTTP_HEADERS)
    if referer:
        h["Referer"] = referer
    r = requests.get(url, headers=h, timeout=15)
    r.raise_for_status()
    if gbk:
        r.encoding = "gbk"
    return r.text


def tx_index_and_turnover():
    """上证指数行情 + 沪深两市成交额（腾讯行情，金额单位：元）"""
    url = "http://qt.gtimg.cn/q=sh000001,sz399107"
    txt = retry(lambda: _http_get(url, gbk=True), label="指数快照")
    idx = {"name": "上证指数", "price": 0.0, "chg": 0.0, "pct": 0.0}
    turnover = 0.0
    for line in txt.split(";"):
        if "=\"" not in line:
            continue
        f = line.split("=\"", 1)[1].rstrip("\"").split("~")
        try:
            if f[2] == "000001":
                idx = {"name": "上证指数", "price": float(f[3]),
                       "chg": float(f[31]), "pct": float(f[32])}
            m = re.search(r"/\d{6,}/(\d+)", line)
            if m:
                turnover += float(m.group(1))
        except (IndexError, ValueError):
            continue
    return idx, turnover / 1e8  # noqa


def tx_open_prices(codes):
    """涨停个股开盘价/现价（识别一字/T字板），code -> (open, last)"""
    raw = tx_batch(codes, (5, 3))
    return {c: (v[0], v[1]) for c, v in raw.items()}


def legu_breadth():
    """乐咕乐股：全市场上涨/下跌/平盘家数"""
    import re
    txt = retry(lambda: _http_get(
        "https://legulegu.com/stockdata/market-activity",
        referer="https://www.legulegu.com/"), label="市场宽度")
    up = down = flat = 0
    m = re.search(r"(\d+)\s*家\s*上涨\D{0,8}?(\d+)\s*家\s*下跌", txt)
    if m:
        up, down = int(m.group(1)), int(m.group(2))
    m2 = re.search(r"(\d+)\s*家\s*(?:平盘|持平)", txt)
    if m2:
        flat = int(m2.group(1))
    if not up and not down:
        raise RuntimeError("市场宽度解析失败")
    return up, down, flat


def last_trading_day(d):
    """把周末（周六/周日）回退到最近的周五。
    涨停池接口在非交易日会照搬上一交易日的数据，却把日期标成请求日，
    因此起始查询日必须落在最近一个交易日（周五），避免日期与周几错标。"""
    while d.weekday() >= 5:              # 5=周六，6=周日
        d -= timedelta(days=1)
    return d


def cache_name(ds, midday=False):
    """缓存文件名：午盘版单独存放，避免覆盖当日收盘数据"""
    return f"{ds}{'_午盘' if midday else ''}.json"


def fetch_all(target_ds=None, midday=False):
    import akshare as ak

    load_industry_names()

    if target_ds:
        end = datetime.strptime(target_ds, "%Y%m%d").date()
    else:
        end = datetime.now().date()
    end = last_trading_day(end)

    ds, df = find_pool(ak, end)
    if ds is None:
        raise RuntimeError("近 12 天内均未取到涨停池数据，请检查网络或数据源")
    print(f"涨停池日期：{ds}，共 {len(df)} 只")

    stocks = [build_stock(r) for _, r in df.iterrows()]
    stocks.sort(key=lambda s: (s["last_time"] or "99:99", s["code"]))

    # 昨日涨停今日表现：按「昨日板级」聚合未晋级个股（今日未再封板）
    # failed[昨日板级] = [{code,name,industry,pct 今日涨跌幅}]
    failed = {}
    try:
        prev = retry(lambda: ak.stock_zt_pool_previous_em(date=ds), label="昨日涨停池")
        today_codes = {s["code"] for s in stocks}
        for _, r in prev.iterrows():
            yb = int(fnum(r.get("昨日连板数")))
            code = str(r.get("代码"))
            if yb >= 2 and code not in today_codes:
                failed.setdefault(yb, []).append({
                    "code": code,
                    "name": str(r.get("名称")),
                    "industry": fix_industry(r.get("所属行业", "")),
                    "pct": round(fnum(r.get("涨跌幅")), 2),
                })
        for lv in failed:
            failed[lv].sort(key=lambda x: -x["pct"])
        n_fail = sum(len(v) for v in failed.values())
        print(f"昨日连板今日未晋级：{n_fail} 只，分布于 "
              f"{', '.join(f'{k}板{len(v)}只' for k, v in sorted(failed.items(), reverse=True))}")
    except Exception as e:
        print(f"未晋级数据获取失败（不影响主图）：{e}")

    # 指数 + 两市成交额（腾讯行情）
    idx = {"name": "上证指数", "price": 0.0, "chg": 0.0, "pct": 0.0}
    turnover = 0.0
    try:
        idx, turnover = tx_index_and_turnover()
    except Exception as e:
        print(f"指数获取失败：{e}")

    # 全市场涨跌家数（乐咕）
    up = down = flat = 0
    try:
        up, down, flat = legu_breadth()
    except Exception as e:
        print(f"市场宽度获取失败：{e}")

    # 涨停个股开盘价（识别 T 字板）
    try:
        quotes = tx_open_prices([s["code"] for s in stocks])
        for s in stocks:
            q = quotes.get(s["code"])
            if q and q[1] > 0 and q[0] >= q[1] * 0.999:
                s["open_limit"] = True
    except Exception as e:
        print(f"开盘价获取失败：{e}")

    d = datetime.strptime(ds, "%Y%m%d").date()
    data = {
        "date": ds,
        "weekday": WEEK_CN[d.weekday()],
        "stocks": stocks,
        "failed": {str(k): v for k, v in failed.items()},
        "index": idx,
        "breadth": {"up": up, "down": down, "flat": flat, "turnover_yi": round(turnover, 0)},
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 题材归类：按当日最热概念覆盖东财行业（失败则沿用行业）
    try:
        attach_themes(data)
        n_theme = sum(1 for s in stocks if s.get("theme"))
        print(f"题材归类：{n_theme}/{len(stocks)} 只命中当日热点概念")
    except Exception as e:
        print(f"题材归类失败，沿用东财行业：{e}")

    cache = os.path.join(DATA_DIR, cache_name(ds, midday))
    with open(cache, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    print(f"数据已缓存：{cache}")
    return data


# ============================================================
# 渲染辅助
# ============================================================
def vgrad(size_w, size_h, c1, c2):
    strip = Image.new("RGB", (1, max(1, size_h)))
    px = strip.load()
    for i in range(size_h):
        t = 0 if size_h == 1 else i / (size_h - 1)
        px[0, i] = tuple(int(c1[j] + (c2[j] - c1[j]) * t) for j in range(3))
    return strip.resize((max(1, size_w), max(1, size_h)))


def paste_rrect(base, img_or_color, x, y, w, h, r, border=None, bw=1):
    """逻辑坐标圆角矩形贴图（内部按 S 倍超采样）"""
    s = S
    X, Y = int(round(x * s)), int(round(y * s))
    Wp, Hp = max(1, int(round(w * s))), max(1, int(round(h * s)))
    R = max(1, int(round(r * s)))
    if isinstance(img_or_color, tuple):
        layer = Image.new("RGB", (Wp, Hp), img_or_color)
    else:
        layer = img_or_color.convert("RGB").resize((Wp, Hp))
    mask = Image.new("L", (Wp, Hp), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, Wp - 1, Hp - 1], R, fill=255)
    base.paste(layer, (X, Y), mask)
    if border:
        ImageDraw.Draw(base).rounded_rectangle(
            [X, Y, X + Wp - 1, Y + Hp - 1], R, outline=border,
            width=max(1, int(round(bw * s))))


def fit_font(draw, text, max_w, size, bold=True, mn=20):
    s = size
    while s > mn and tw(draw, text, F(s, bold)) > max_w:
        s -= 1
    return F(s, bold)


def chip(draw, x, y, text, kind, fs=18, h=26, pad=9):
    """从 x 向右画小标签，返回宽度（逻辑坐标）"""
    f = F(fs, True)
    w = int(tw(draw, text, f)) + pad * 2
    if kind == "red":
        paste_rrect(_IMG, RED, x, y, w, h, 5)
        fill = WHITE
    elif kind == "gold":
        paste_rrect(_IMG, GOLD, x, y, w, h, 5)
        fill = WHITE
    else:  # outline red
        paste_rrect(_IMG, WHITE, x, y, w, h, 5, border=RED, bw=1)
        fill = RED
    draw.text((x + w / 2, y + h / 2 + 1), text, font=f, fill=fill, anchor="mm")
    return w


def seal_fmt(v):
    if v >= 1e8:
        return f"封单{v/1e8:.2f}亿"
    return f"封单{v/1e4:.0f}万"


def stock_badges(s):
    """仅保留「一字板」标识：09:25 开盘即封且全天未炸板"""
    if s["first_time"] <= "09:25" and s["break_cnt"] == 0:
        return [("一字板", "red")]
    return []


def disp_ind(s):
    """展示用板块名：优先当日热点题材，其次东财行业"""
    return s.get("theme") or s.get("industry") or "其他"


# ---------------- 个股单元格（6 列紧凑表格，单页 3:4 / 9:16） ----------------
# 6 列可增加总行数，让表格撑满画布高度，消除底部留白
CARD_COLS = 6
# 未晋级（昨日连板今日断板）配色
FAIL_BG = (248, 244, 241)
FAIL_BD = (237, 229, 224)
FAIL_NAME = (126, 118, 112)
FAIL_IND = (178, 168, 160)
FAIL_UP = (255, 0, 0)       # 未晋级收红（主色）
FAIL_DOWN = (72, 156, 106)  # 未晋级收绿
FAIL_X = (232, 122, 120)    # 小红叉：与未晋级股名同淡度（半透明红）
CHIP_CY = (196, 17, 224)    # 创业板标识：品红方块（参考图取色）


def market_tag(code):
    """创业板（300/301/302）返回「创」，其余返回 None"""
    return "创" if str(code)[:3] in ("300", "301", "302") else None



def _fit_ind(draw, ind, max_w, fs):
    af = F(fs, True)
    if tw(draw, ind, af) <= max_w or len(ind) <= 1:
        return ind
    t = ind[:-1]
    while t and tw(draw, t + "…", af) > max_w:
        t = t[:-1]
    return (t or ind[:1]) + "…"


def draw_name_tag(draw, name, code, cx, cy, max_w, fs, fill):
    """股名居中，创业板在名字右侧挂一枚品红「创」小牌；名字+牌 作为整体居中。
    返回 (股名实际中心 x, 股名所用字体)，供未晋级红叉按实际字形定位。"""
    tag = market_tag(code)
    side = round(fs * 1.06)                # 方块边长：略小于股名字高
    gap = max(2, int(round(fs * 0.10)))
    reserve = side + gap if tag else 0
    nf = fit_font(draw, name, max_w - reserve, fs, True, mn=12)
    nw = tw(draw, name, nf)
    x0 = cx - (nw + reserve) / 2
    ncx = x0 + nw / 2
    draw.text((ncx, cy), name, font=nf, fill=fill, anchor="mm")
    if tag:
        bx = x0 + nw + gap
        paste_rrect(_IMG, CHIP_CY, bx, cy - side / 2, side, side,
                    max(2, round(side * 0.2)))
        draw.text((bx + side / 2, cy + 1), tag, font=F(max(9, round(fs * 0.66)), True),
                  fill=WHITE, anchor="mm")
    return ncx, nf


def draw_cell(draw, s, x, y, w, h, failed=False, ind_color=None):
    """单格三行垂直居中：涨停时间/一字板 → 股名 → 所属板块。
    三行统一 mm 锚点，避免 CJK 字形下沿溢出被裁掉、或上下两行基线错位。"""
    pad = 6
    inner = w - pad * 2
    cx = x + w / 2
    ind_lbl = disp_ind(s)

    # 字号随涨停家数自适应：行高 h 由总家数反推（家数多→行矮字小，家数少→行高字大）。
    # 行距随字号同比变化（LEAD），避免行高较大时三行文字挤在一起。
    r_s = 15 / 22                  # 时间/板块 与 股名 的字号比（沿用原始设计比例）
    LEAD = 0.28                    # 行间留白（相对股名字号）
    FS_MAX = 28                    # 字号上限：行高再大也不继续放大，保证三行周边留白充足
    # 三行文字块总高 ≈ fs_n·[2·(1.12+LEAD) + 0.56·(1+r_s)]，令其占行高的 94% 反解股名字号
    fs_n = int(round(0.94 * h / (2 * (1.12 + LEAD) + 0.56 * (1 + r_s))))
    fs_n = max(10, min(FS_MAX, fs_n))   # 下限保证可读，上限保证疏朗且不超出单元格宽度
    fs_s = max(8, int(round(fs_n * r_s)))
    fs_t = fs_s                    # 时间字号与板块字号同号
    # 三行统一中心间距并整体垂直居中：「时间↔股名」与「股名↔板块」间距完全相同
    gap = max(1, int(round(fs_n * LEAD)))
    lh_n = round(fs_n * 1.12)          # 股名行高
    lh_s = round(fs_t * 1.12)          # 时间/板块行高
    step = max(lh_n, lh_s) + gap       # 相邻两行中心距（时间行与板块行一致）
    total = 2 * step + (lh_n + lh_s) / 2
    top = y + (h - total) / 2
    c1 = top + lh_n / 2
    c2 = c1 + step
    c3 = c2 + step

    if failed:
        paste_rrect(_IMG, FAIL_BG, x + 3, y + 3, w - 6, h - 6, 8,
                    border=FAIL_BD, bw=1)
        pct = s["pct"]
        ps = f"{'+' if pct >= 0 else ''}{pct:.2f}%"
        draw.text((cx, c1), ps, font=F(fs_t, True), anchor="mm",
                  fill=FAIL_UP if pct >= 0 else FAIL_DOWN)
        ncx, nf = draw_name_tag(draw, s["name"], s["code"], cx, c2, inner, fs_n,
                                FAIL_NAME)
        # 小红叉：按股名实际字形包围盒正中覆盖
        nb = draw.textbbox((ncx, c2), s["name"], font=nf, anchor="mm")
        xc, yc = (nb[0] + nb[2]) / 2, (nb[1] + nb[3]) / 2
        r = max(7, min(nb[2] - nb[0], nb[3] - nb[1]) * 0.34)
        for sgn in (1, -1):
            draw.line([xc + sgn * r, yc - r, xc - sgn * r, yc + r],
                      fill=FAIL_X, width=3)
        ind_s = _fit_ind(draw, ind_lbl, inner, fs_s)
        draw.text((cx, c3), ind_s, font=F(fs_s, True), anchor="mm", fill=FAIL_IND)
        return

    # 第一行：一字板 → 居中徽章（字号比股名略小、方块收紧）；其余 → 居中涨停时间
    if stock_badges(s):
        bfs = max(fs_s + 1, fs_n - 3)          # 比股票名小 3 号
        bh = round(bfs * 1.26)                 # 方块高度收紧
        bw_ = int(tw(draw, "一字板", F(bfs, True))) + 12
        chip(draw, cx - bw_ / 2, c1 - bh / 2, "一字板", "red",
             fs=bfs, h=bh, pad=6)
    else:
        ts_ = s["last_time"] or "--:--"
        draw.text((cx, c1), ts_, font=F(fs_t, True), anchor="mm", fill=GRAY_T)
    # 第二行：股票名称（居中，黑色；创业板挂「创」小牌）
    draw_name_tag(draw, s["name"], s["code"], cx, c2, inner, fs_n, INK)
    # 第三行：所属板块（居中）
    ind_s = _fit_ind(draw, ind_lbl, inner, fs_s)
    draw.text((cx, c3), ind_s, font=F(fs_s, True), anchor="mm",
              fill=ind_color or GRAY_T)


# ---------------- 连板分组 ----------------
def build_rows(items, failed_items):
    """晋级白卡在前、未晋级灰卡在后，按每行 CARD_COLS 张切行"""
    seq = [(s, True) for s in items] + [(s, False) for s in failed_items]
    return [seq[i:i + CARD_COLS] for i in range(0, len(seq), CARD_COLS)]


# ---------------- 混合颜色文本换行 ----------------
def wrap_tokens(draw, tokens, max_w, fs):
    lines, cur, width = [], [], 0
    f = F(fs, False)
    fb = F(fs, True)
    for txt, color, bold in tokens:
        w = tw(draw, txt, fb if bold else f)
        if cur and width + w > max_w:
            lines.append(cur)
            cur, width = [], 0
        cur.append((txt, color, bold))
        width += w
    if cur:
        lines.append(cur)
    return lines


def draw_tokens(draw, x, y, tokens, fs, lh=None, max_w=None):
    if max_w:
        lines = wrap_tokens(draw, tokens, max_w, fs)
    else:
        lines = [tokens]
    lh = lh or fs + 12
    for line in lines:
        cx = x
        for txt, color, bold in line:
            draw.text((cx, y), txt, font=F(fs, bold), fill=color)
            cx += tw(draw, txt, F(fs, bold))
        y += lh
    return len(lines) * lh


# ---------------- 主渲染（3:4 分页） ----------------
W = 1080
PAGE_H = 1440          # 3:4 竖版（1080 x 1440）
_IMG = None


# ---- 紧凑表头（参考图2） ----
def draw_full_header(ctx, pg):
    """顶部：标题（大盘信息并入右上）+ 风险提示 + 题材标签；返回天梯起始 y 与前三板块名"""
    global _IMG
    _IMG = pg["img"]
    d = pg["draw"]
    dt, br = ctx["dt"], ctx["breadth"]

    # ---- 标题行（原顶部红色通栏已删除，标题直接起于页面顶部）----
    y = 24
    base = y + 42                                  # 标题统一基线，保证两段文字在一条横线上
    paste_rrect(_IMG, RED, 30, y + 2, 7, 45, 3)    # 左侧红色竖条装饰
    tx = 48
    t1 = f"{dt.month}月{dt.day}日"
    t2 = "午盘涨停" if ctx.get("midday") else "连板天梯"
    d.text((tx, base), t1, font=F(46, True), fill=INK, anchor="ls")
    w1 = tw(d, t1, F(46, True))
    d.text((tx + w1 + 12, base), t2, font=F(46, True), fill=RED, anchor="ls")
    # 右上角：大盘信息（纯文字、无方框）——两行左边缘对齐；涨跌家数用红绿柱表示
    idx = ctx["index"]
    pc = RED if idx["pct"] >= 0 else GREEN
    pct_s = f"{'+' if idx['pct'] >= 0 else ''}{idx['pct']:.2f}%"
    l1 = [("上证指数 ", F(14), GRAY_T),
          (f"{idx['price']:.2f}", F(25, True), pc),
          ("  ", F(14), pc), (pct_s, F(17, True), pc)]
    l2 = [("成交 ", F(13), GRAY_T),
          (f"{br['turnover_yi']:.0f}亿", F(14, True), INK)]

    def _lt(x0, y_b, toks):
        x = x0
        for t, f, c in toks:
            d.text((x, y_b), t, font=f, fill=c, anchor="ls")
            x += tw(d, t, f)

    # 整块贴右边距，两行共用同一左起点（「成交」正对「上证指数」下方）
    w1 = sum(tw(d, t, f) for t, f, _ in l1)
    w2 = sum(tw(d, t, f) for t, f, _ in l2)
    GAP2 = 24

    # 涨跌家数：与成交量同一行（红涨 / 绿跌），下方为按家数比例分割的红绿横条
    up, down = br["up"], br["down"]
    tot = max(1, up + down)
    f_up, s_up = F(14, True), f"涨{up}"
    f_dn, s_dn = F(14, True), f"跌{down}"
    wu, wd = tw(d, s_up, f_up), tw(d, s_dn, f_dn)

    bx = W - 30 - max(w1, w2 + GAP2 + wu + GAP2 + wd)
    _lt(bx, y + 30, l1)
    _lt(bx, y + 52, l2)
    x_up = bx + w2 + GAP2
    d.text((x_up, y + 52), s_up, font=f_up, fill=RED, anchor="ls")
    d.text((x_up + wu + GAP2, y + 52), s_dn, font=f_dn, fill=GREEN, anchor="ls")

    # 红绿横条：红涨在左、绿跌在右，外端圆角、中缝平直
    bar_y, bar_h = y + 60, 7
    bar_w = W - 30 - bx
    r = bar_h / 2
    paste_rrect(_IMG, GREEN, bx, bar_y, bar_w, bar_h, r)
    red_w = 0 if up == 0 else max(bar_h, bar_w * up / tot)
    if red_w > 0:
        paste_rrect(_IMG, RED, bx, bar_y, red_w, bar_h, r)
        if red_w < bar_w:                     # 中缝保持平直：把红段右侧圆角补成直角
            paste_rrect(_IMG, RED, bx + red_w - r, bar_y, r, bar_h, 0)
    y += 68

    # ---- 小字风险提示（标题下方，浅灰）----
    d.text((30, y),
           "风险提示：内容仅为公开市场数据整理，不构成投资建议，历史表现不代表未来走势。",
           font=F(14), fill=(158, 148, 140))
    y += 26

    # ---- 题材标签：前三名红/蓝/黄，其余浅底描边 ----
    ind_cnt = {}
    for s in ctx["stocks"]:
        lb = disp_ind(s)
        ind_cnt[lb] = ind_cnt.get(lb, 0) + 1
    ranked = sorted(ind_cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    rank_map = {n: i for i, (n, _) in enumerate(ranked)}
    tags_show = ranked[:11]
    rest = sum(c for _, c in ranked[11:])
    if rest:
        tags_show.append(("其他", rest))
    chip_h, chip_fs = 32, 17
    cx, cy = 30, y
    for name, cnt in tags_show:
        txt = f"{name}({cnt})"
        w = int(tw(d, txt, F(chip_fs, True))) + 26
        if cx + w > W - 30 and cx > 30:
            cx, cy = 30, cy + chip_h + 8
        rk = rank_map.get(name, -1)
        if 0 <= rk < 3:
            bg, bd, fg = SEC_TINT[rk], SEC_BD[rk], SEC_TXT[rk]
        else:
            bg, bd, fg = WHITE, (228, 209, 201), (138, 106, 98)
        paste_rrect(_IMG, bg, cx, cy, w, chip_h, 16, border=bd, bw=1)
        d.text((cx + w / 2, cy + chip_h / 2 + 1), txt, font=F(chip_fs, True),
               fill=fg, anchor="mm")
        cx += w + 8
    y = cy + chip_h + 6

    return y + 4, [n for n, _ in ranked[:3]]


# ---------------- 防盗水印（对角平铺艺术字，5% 浓度，抗截图 / 裁角） ----------------
WM_TEXT = "©路扬LuYang"
WM_ALPHA = max(1, round(255 * 0.05))     # 浓度 5%
WM_RGB = (86, 74, 70)                    # 深墨灰（暖调）：浅底上呈淡纹理，红底上仍有痕迹
WM_ANGLE = -28                           # 对角倾斜角


def _wm_tile(fsize):
    """单块艺术字水印：微软雅黑粗体 + 字距，透明底、对角倾斜"""
    f = ImageFont.truetype(FONT_BOLD, max(1, fsize))
    sp = max(1, int(fsize * 0.12))                       # 字距，拉开更透气
    chars = list(WM_TEXT)
    tw_ = sum(f.getlength(c) for c in chars) + sp * (len(chars) - 1)
    asc, _desc = f.getmetrics()
    pad = int(fsize * 0.45)
    tile = Image.new("RGBA", (int(tw_) + pad * 2, asc + int(fsize * 0.30) + pad),
                     (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    x, by = pad, pad + asc
    for c in chars:
        td.text((x, by), c, font=f, fill=WM_RGB + (255,), anchor="ls")
        x += f.getlength(c) + sp
    return tile.rotate(WM_ANGLE, expand=True, resample=Image.BICUBIC)


def add_watermark(base, scale):
    """在 base（RGB，S 倍超采样画布）上平铺对角艺术字水印：
    整体 5% 浓度、覆盖全图（含中部与四角），转发截图 / 裁角均无法去除。"""
    tile = _wm_tile(int(round(48 * scale)))
    bb = tile.getchannel("A").getbbox()          # 裁掉透明边，按字形实际边界排布
    if bb:
        tile = tile.crop(bb)
    tile.putalpha(tile.getchannel("A").point(lambda v: v * WM_ALPHA // 255))
    Wp, Hp = base.size
    # 均匀网格：行列各自等间距铺满全图并整体居中，边缘对称、疏密一致
    nx = max(2, int(round(Wp / (tile.width * 1.5))))     # 间距加大：数量更少、观看更清爽
    ny = max(2, int(round(Hp / (tile.height * 1.9))))
    gap_x, gap_y = Wp / nx, Hp / ny
    layer = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
    for iy in range(ny):
        for ix in range(nx):
            cx = gap_x * (ix + 0.5)              # 每格中心，位移对称
            cy = gap_y * (iy + 0.5)
            layer.alpha_composite(tile, (int(cx - tile.width / 2),
                                         int(cy - tile.height / 2)))
    base.paste(layer, (0, 0), layer)
    return base


def render(data, out_path, ph=PAGE_H, midday=False):
    """单页渲染：宽固定 1080，高由 ph 决定（1440=3:4 / 1920=9:16），输出 2 倍高清图"""
    global _IMG
    stocks = data["stocks"]
    groups = {}
    for s in stocks:
        groups.setdefault(max(1, s["boards"]), []).append(s)
    failed = {int(k): v for k, v in data.get("failed", {}).items()}
    # 今日断板未晋级：上移一级显示（昨日 L 板 → 今日 L+1 板）
    failed_up = {k + 1: v for k, v in failed.items()}
    levels = sorted(set(groups.keys()) | set(failed_up.keys()), reverse=True)
    dt = datetime.strptime(data["date"], "%Y%m%d").date()

    img = Image.new("RGB", (W * S, ph * S), BG)      # 内部 S 倍超采样画布
    _IMG = img
    draw = SDraw(img)
    ctx = {
        "dt": dt, "weekday": data.get("weekday", ""), "index": data["index"],
        "breadth": data["breadth"], "stocks": stocks, "midday": midday,
    }
    table_y, top_sectors = draw_full_header(ctx, {"img": img, "draw": draw})
    ind_color = {n: SEC_TXT[i] for i, n in enumerate(top_sectors[:3])}

    # 板级 -> 卡片行（断板未晋级并入上移一级的板级，与晋级股并列）
    level_rows = []
    for lv in levels:
        rows = build_rows(groups.get(lv, []), failed_up.get(lv, []))
        if rows:
            level_rows.append((lv, rows, len(groups.get(lv, []))))
    total_rows = sum(len(r) for _, r, _ in level_rows)

    hdr_h = 38
    GAP = 14                    # 各板级分组之间的间隔
    body_y = table_y + hdr_h
    table_bottom = ph - 18
    n_gaps = GAP * max(0, len(level_rows) - 1)
    # 行高由涨停家数（总行数）反推：直接铺满可用高度（家数多则行矮字小、家数少则行高字大）
    pitch = max(40, (table_bottom - body_y - n_gaps) // max(1, total_rows))

    panel_x, panel_w = 24, W - 48
    rail_x, rail_w = panel_x + 8, 68
    gx0 = rail_x + rail_w + 8
    gx1 = panel_x + panel_w - 8
    step = (gx1 - gx0) / CARD_COLS

    # 表头栏（左：连板；右：列说明，主标题加粗 + 浅色注释分层）
    hx, hw = panel_x + 8, panel_w - 16
    paste_rrect(_IMG, vgrad(hw, hdr_h - 6, (255, 62, 62), (204, 0, 0)),
                hx, table_y + 6, hw, hdr_h - 6, 9)
    paste_rrect(_IMG, vgrad(rail_w, hdr_h - 6, (238, 44, 44), (166, 0, 0)),
                hx, table_y + 6, rail_w, hdr_h - 6, 9)
    hcy = table_y + 6 + (hdr_h - 6) / 2
    draw.text((rail_x + rail_w / 2, hcy), "连板", font=F(19, True),
              fill=WHITE, anchor="mm")
    seg1 = "涨停时间 · 个股 · 所属板块"
    w_s1 = tw(draw, seg1, F(16, True))
    sx0 = rail_x + rail_w + ((gx1 - rail_x - rail_w) - w_s1) / 2
    draw.text((sx0, hcy), seg1, font=F(16, True), fill=WHITE, anchor="lm")

    ry = body_y
    for level, rows, n_ok in level_rows:
        block_h = len(rows) * pitch
        # 每个板级独立圆角卡片（分组之间留出间隔）
        paste_rrect(_IMG, PANEL_BG, panel_x, ry, panel_w, block_h, 14,
                    border=(240, 224, 218), bw=1)
        # 板级红色渐变标签柱
        paste_rrect(_IMG, vgrad(rail_w, max(1, block_h - 12), (255, 77, 77), (195, 0, 0)),
                    rail_x, ry + 6, rail_w, block_h - 12, 9)
        rc = rail_x + rail_w / 2
        if level >= 2:
            draw.text((rc, ry + block_h / 2 - 14), str(level), font=F(28, True),
                      fill=WHITE, anchor="mm")
            draw.text((rc, ry + block_h / 2 + 11), "板", font=F(14, True),
                      fill=WHITE, anchor="mm")
        else:
            draw.text((rc, ry + block_h / 2 - 12), "首板", font=F(20, True),
                      fill=WHITE, anchor="mm")
            draw.text((rc, ry + block_h / 2 + 12), f"({n_ok})", font=F(14, True),
                      fill=(255, 226, 218), anchor="mm")
        for ri, row in enumerate(rows):
            y0 = ry + ri * pitch
            for ci, (s, ok) in enumerate(row):
                x0 = int(round(gx0 + ci * step))
                x1 = int(round(gx0 + (ci + 1) * step))
                draw_cell(draw, s, x0, y0, x1 - x0, pitch, failed=not ok,
                          ind_color=ind_color.get(disp_ind(s)))
        # 组内行分隔线 + 纵向分隔线
        for ri in range(len(rows) - 1):
            yb_ = ry + (ri + 1) * pitch
            draw.line([gx0, yb_, gx1, yb_], fill=(246, 240, 236), width=1)
        draw.line([gx0 - 4, ry + 8, gx0 - 4, ry + block_h - 8],
                  fill=(238, 226, 220), width=1)
        ry += block_h + GAP

    # 防盗水印：对角平铺艺术字（5% 浓度），覆盖全图后再降采样，两版输出均带水印
    add_watermark(img, S)

    # 超采样降采样：内部按 S 倍渲染后缩回目标尺寸，文字边缘更锐利、细笔画不再丢失
    # 只输出 2 倍高清图（放大查看不糊）
    img.resize((W * 2, ph * 2), Image.LANCZOS).save(out_path)
    return [out_path]


def build_caption(data, midday=False):
    """生成可直接粘贴到小红书 / 抖音的发布文案：返回 (标题, 正文, 话题标签)"""
    stocks = data.get("stocks", [])
    dt = datetime.strptime(data["date"], "%Y%m%d").date()
    br = data.get("breadth") or {}
    idx = data.get("index") or {}

    dist = {}                                   # 当日主线（按涨停家数）
    for s in stocks:
        lb = disp_ind(s)
        dist[lb] = dist.get(lb, 0) + 1
    top = sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))

    ladder = {}                                 # 连板梯队：板级 -> 个股
    for s in stocks:
        ladder.setdefault(max(1, int(s.get("boards") or 1)), []).append(s)
    levels = sorted(ladder, reverse=True)
    hi = levels[0] if levels else 0
    hi_name = ladder[hi][0]["name"] if hi else "—"

    title = (f"{dt.month}月{dt.day}日{'午盘涨停' if midday else '连板天梯'}｜"
             f"{'、'.join(n for n, _ in top[:2])}领涨")

    lines = [f"{dt.month}月{dt.day}日（{WEEK_CN[dt.weekday()]}）"
             f"A股{'午盘' if midday else ''}涨停复盘", ""]
    head = f"· 涨停 {len(stocks)} 家，首板 {len(ladder.get(1, []))} 家"
    if hi > 1:
        head += f"，最高 {hi} 板（{hi_name}）"
    lines.append(head)
    if br:
        lines.append(f"· 涨 {br.get('up', 0)} / 跌 {br.get('down', 0)}，"
                     f"成交 {br.get('turnover_yi', 0):.0f} 亿")
    if idx:
        lines.append(f"· 上证 {idx.get('price', 0):.2f}（{idx.get('pct', 0):+.2f}%）")
    heights = "、".join(f"{lv}板{len(ladder[lv])}家" for lv in levels if lv > 1)
    if heights:
        lines += ["", f"高度梯队：{heights}"]
    lines += ["", "今日主线（按涨停家数）："]
    for i, (nm, c) in enumerate(top[:6], 1):
        lines.append(f"{i}. {nm}  {c} 家")
    lines += ["", "风险提示：内容仅为公开市场数据整理，不构成投资建议，历史表现不代表未来走势。"]

    tags = ["#A股", "#涨停复盘", "#连板天梯", "#涨停板", "#题材轮动"]
    for nm, _ in top[:4]:
        t = "#" + nm.replace(" ", "").replace("(", "").replace(")", "")
        if t not in tags:
            tags.append(t)
    return title, "\n".join(lines), " ".join(tags)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="交易日 YYYYMMDD，默认今天（自动回退到最近交易日）")
    ap.add_argument("--from-cache", action="store_true", help="仅使用 data 目录缓存渲染")
    ap.add_argument("--midday", action="store_true",
                    help="午盘版：抓取 11:30 午间收盘快照，标题/文件名/文案加「午盘」")
    args = ap.parse_args()

    if args.from_cache:
        if args.date:
            ds = args.date
        else:
            if args.midday:
                files = sorted(f for f in os.listdir(DATA_DIR)
                               if f.endswith("_午盘.json"))
            else:
                files = sorted(f for f in os.listdir(DATA_DIR)
                               if f.endswith(".json") and not f.endswith("_午盘.json"))
            if not files:
                print("无缓存数据"); sys.exit(1)
            ds = files[-1][:8]
        with open(os.path.join(DATA_DIR, cache_name(ds, args.midday)), encoding="utf-8") as fp:
            data = json.load(fp)
    else:
        data = fetch_all(args.date, args.midday)

    normalize_industries(data)
    if args.from_cache:
        try:
            attach_themes(data)
            with open(os.path.join(DATA_DIR, cache_name(data['date'], args.midday)), "w",
                      encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"题材刷新失败，沿用缓存标注：{e}")
    ds = data["date"]
    dt = datetime.strptime(ds, "%Y%m%d").date()
    # 两套尺寸，均只输出 2 倍高清：3:4（2160x2880）与 9:16（2160x3840）
    mid_tag = "_午盘" if args.midday else ""
    paths = []
    for tag, ph in (("3x4", 1440), ("9x16", 1920)):
        out = os.path.join(OUT_DIR, f"{dt:%Y-%m-%d}_连板天梯{mid_tag}_{tag}@2x.png")
        paths += render(data, out, ph, args.midday)
    print(f"已生成 2 倍高清图片（{W * 2}x{1440 * 2} 与 {W * 2}x{1920 * 2}）：")
    for p in paths:
        print(f"  {p}")
    if not args.midday:                       # 午盘版不覆盖日报的 latest.png
        latest = os.path.join(OUT_DIR, "latest.png")
        Image.open(paths[0]).save(latest)
        print(f"最新副本：{latest}")

    # 发布文案（标题 + 正文 + 话题标签），可直接复制粘贴到小红书 / 抖音
    cap_title, cap_body, cap_tags = build_caption(data, args.midday)
    cap_path = os.path.join(OUT_DIR, f"{dt:%Y-%m-%d}{mid_tag}_发布文案.txt")
    with open(cap_path, "w", encoding="utf-8") as fp:
        fp.write(f"【标题】\n{cap_title}\n\n【正文】\n{cap_body}\n\n"
                 f"【话题标签】\n{cap_tags}\n")
    print(f"发布文案：{cap_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
