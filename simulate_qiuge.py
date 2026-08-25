#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋哥操作 · 实盘模拟器（Paper Trading Simulator）
=================================================
模拟账户按秋哥纪律自动执行「推荐观察池 → 买点触发 → 盘中买入 / 破位止盈止损」，
逐日验证推荐准确度，产出可量化统计（命中率/胜率/净值/回撤），无幸存者偏差。

输入：
  - output/qiuge_report.json（当日推荐：watch / picks / 招行判定 / position_max / index）
  - 历史报告目录 output/history/（含 QIUGE_DATA 块，供历史回放 & 当日复核）
  - 东财公开行情接口（日K / 主力资金），云端可访问

用法：
  python simulate_qiuge.py --daily                      # 当日模拟（读最新报告）
  python simulate_qiuge.py --replay                     # 历史回放（8/3 起全部报告）
  python simulate_qiuge.py --replay --start 2026-08-03  # 指定起始日
  python simulate_qiuge.py --daily --dry-run            # 只打印判定不写状态

输出：
  - output/simulation_state.json   账户状态（现金/持仓/交易日志/tracker）
  - output/simulation_history.jsonl 逐日净值累积
  - output/accuracy_stats.json    全部统计指标
  - output/simulation_report.md   可读报告
"""
import argparse
import json
import os
import re
import sys
import datetime
import time
import urllib.request
import urllib.parse
import glob

# ---------------- 配置 ----------------
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(REPO_DIR, "output")
HISTORY_DIR = os.path.join(OUT_DIR, "history")
STATE_PATH = os.path.join(OUT_DIR, "simulation_state.json")
HISTORY_PATH = os.path.join(OUT_DIR, "simulation_history.jsonl")
STATS_PATH = os.path.join(OUT_DIR, "accuracy_stats.json")
REPORT_PATH = os.path.join(OUT_DIR, "simulation_report.md")
REPORT_JSON_PATH = os.path.join(OUT_DIR, "qiuge_report.json")

INIT_CASH = 700_000.0           # 模拟仓现金 70 万（8/3 新增，用于 watch/picks 买卖）
BASELINE_NAV = 1_103_600.0     # 账户起点净值（2026-08-03）：招行 10000×40.36 + 70 万
# 初始持仓：招行 600036 底仓，2024-09-25 以 30 元买入 10000 股（真实持仓，参与模拟交易）
INITIAL_POSITIONS = {
    "600036": {"name": "招商银行", "cost": 30.0, "shares": 10000, "buy_date": "2024-09-25"}
}
POSITION_MAX = 0.15              # 单只目标仓位 1.5 成（15%）
POSITION_FIRST = 0.05            # 初始建仓 1/3 = 总资产 5%
MAX_HOLD = 5                     # 并行持仓上限 5 只
BUY_BUDGET = 60_000.0            # 单笔买入预算 6 万；一手价格超预算则按一手买（可突破）
BUY_FEE_RATE = 0.00025           # 买入佣金 万2.5
SELL_FEE_RATE = 0.00075          # 卖出佣金 万2.5 + 印花税 千0.5
# ---- 招行核心仓（核心-卫星模型，2026-08-22 用户拍板）----
CORE_CODE = "600036"
CORE_INIT_SHARES = 10000        # 初始底仓股数；满仓基准=pos["base"]（历史峰值，随扩大型加仓自动抬升）
CORE_CAP_PCT = 0.55             # 硬顶：招行市值 ≤ 总资产×55%
CORE_ADD_STEP = 1000            # 扩大型加仓步长（股）
ZH_FUND = {"bvps": 44.9, "div_ps": 2.016}   # 来源 cmb-tracker/fundamentals.json，随季报手动更新
BUY_BAND_PCT = 0.02              # 买点 ±2% 判定
BREAKOUT_DROP_PCT = 0.03         # 回踩变破位：收盘 < 买点×0.97
STOP_MA20 = 0.10                 # 减仓 1/3（破 MA20）
STOP_MA60 = 0.10                 # 清仓（破 MA60）
TAKE_PROFIT = 0.15              # 底仓（招行）止盈：+15% 减 1/3
TP_SMALL = 0.03                # 短线弱势档：+3% 小目标全卖（英科 +1.6% 就走实证）
TP_10 = 0.10                   # 短线强势档分批：+10% 卖初始 1/3
TP_20 = 0.20                   # 短线强势档分批：+20% 卖初始 1/3
TP_40 = 0.40                   # 短线强势档分批：+40% 卖初始 1/3（分批完成）
WATCH_TIMEOUT_DAYS = 7           # 观察超时移除（7 交易日）
LIMIT_UP_PCT = 9.5               # 涨停不追
MIN_MAIN_NET = 0                 # 买点触发当日主力净流入需 > 0（补丁9）
STRONG_MAIN_NET = 5e8            # 强资金例外：单日主力净流入≥5亿可跳过二次确认当日上车（紫金式教科书确认）

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


# ---------------- 工具 ----------------
def http_get(url, params=None, timeout=10):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def is_trade_date(dt):
    """东财交易日历（云端可访问接口）判断是否交易日"""
    try:
        txt = http_get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            {
                "reportName": "RPT_TRADE_CALENDAR",
                "columns": "ALL",
                "filter": f"(TRADE_DATE>='{dt - datetime.timedelta(days=5)}')(TRADE_DATE<='{dt}')",
                "pageNumber": "1",
                "pageSize": "10",
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
            },
            timeout=8,
        )
        d = json.loads(txt)
        for row in d.get("result", {}).get("data", []):
            if row.get("TRADE_DATE") == dt.strftime("%Y-%m-%d") and row.get("OPEN_OR_CLOSE") == "1":
                return True
        return False
    except Exception:
        # 降级：周末肯定不是交易日
        return dt.weekday() < 5


def get_flow_history(code, market="1", days=100):
    """东财历史主力资金流（近100日），返回 {date: 主力净额(元)}（f52）"""
    secid = f"{market}.{code}"
    txt = http_get(
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "klt": "101",
            "lmt": str(days),
        },
        timeout=10,
    )
    try:
        d = json.loads(txt)
        klines = (d.get("data") or {}).get("klines") or []
        out = {}
        for k in klines:
            p = k.split(",")
            out[p[0]] = float(p[1])  # f52 = 主力净额
        return out
    except Exception:
        return {}


def get_kline_tencent(code, market="1", days=70):
    """腾讯 K 线兜底（qfq 前复权），返回同 get_kline 结构"""
    sym = f"sh{code}" if market == "1" else f"sz{code}"
    try:
        txt = http_get(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            {"param": f"{sym},day,,,{days},qfq"},
            timeout=10,
        )
        d = json.loads(txt)
        qfq = ((d.get("data") or {}).get(sym) or {}).get("qfqday") or []
        out = []
        for p in qfq:
            if len(p) < 6:
                continue
            out.append({
                "date": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "amount": 0.0,
                "pct_chg": 0.0,  # 腾讯未直接给涨跌幅，用 close 序列算
            })
        # 补 pct_chg（相邻收盘）
        for i in range(1, len(out)):
            if out[i - 1]["close"]:
                out[i]["pct_chg"] = round((out[i]["close"] - out[i - 1]["close"]) / out[i - 1]["close"] * 100, 2)
        return out
    except Exception:
        return []


def get_kline(code, market="1", days=70):
    """东财日K（前复权），返回 [{date, open, high, low, close, amount, pct_chg}]"""
    secid = f"{market}.{code}" if not code.startswith(("1.", "0.", "2.")) else code
    txt = http_get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "beg": "0",
            "end": "20500101",
            "lmt": str(days),
        },
        timeout=10,
    )
    d = json.loads(txt)
    klines = (d.get("data") or {}).get("klines") or []
    out = []
    for k in klines:
        p = k.split(",")
        out.append(
            {
                "date": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "amount": float(p[5]),
                "pct_chg": float(p[8]) if len(p) > 8 else 0.0,
            }
        )
    return out


def get_quote(code, market="1"):
    """东财实时行情快照：最新价/涨跌/主力净额(可选)"""
    secid = f"{market}.{code}"
    txt = http_get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {
            "secid": secid,
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f62,f168,f169",
            "fltt": "2",
            "invt": "2",
        },
        timeout=10,
    )
    d = json.loads(txt)
    data = d.get("data") or {}
    if not data:
        return None
    return {
        "price": data.get("f43"),
        "chg_pct": data.get("f170"),
        "main_net": data.get("f62"),  # 元
        "high": data.get("f44"),
        "low": data.get("f45"),
    }


def get_ulist_main_net(secids):
    """东财 ulist 批量主力净额（元）"""
    txt = http_get(
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        {"secids": ",".join(secids), "fields": "f2,f3,f12,f14,f62", "fltt": "2", "invt": "2"},
        timeout=10,
    )
    d = json.loads(txt)
    diff = (d.get("data") or {}).get("diff") or []
    return {x["f12"]: x.get("f62") or 0 for x in diff}


def ma(klines, n):
    closes = [k["close"] for k in klines]
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def find_prev_trade_report(target_date):
    """找 target_date 前一交易日的报告（回退跳过周末），返回 {date_str, data}"""
    d = target_date
    for back in range(1, 8):
        dd = d - datetime.timedelta(days=back)
        if dd.weekday() >= 5:
            continue
        for base in (HISTORY_DIR, OUT_DIR, REPO_DIR):
            if not os.path.isdir(base):
                continue
            for f in sorted(glob.glob(os.path.join(base, "秋哥操作_*" + dd.strftime("%Y%m%d") + ".md"))):
                data = extract_qiuge_data(f)
                if data:
                    return dd.strftime("%Y-%m-%d"), data
    return None, None


def pull_history_reports(remote_repo="homjanon/qiugecaozuo", local_dir=None):
    """用 gh api 从 qiugecaozuo/output/history 拉全部历史报告到本地 output/history/
    返回拉取的文件数。失败则返回 0（不阻塞）。
    """
    import subprocess
    if local_dir is None:
        local_dir = HISTORY_DIR
    os.makedirs(local_dir, exist_ok=True)
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{remote_repo}/contents/output/history",
             "--jq", ".[].name"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            print(f"  [pull] 拉取 {remote_repo} history 列表失败: {r.stderr[:120]}")
            return 0
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        n = 0
        for name in names:
            if not name.endswith(".md"):
                continue
            content = subprocess.run(
                ["gh", "api", f"repos/{remote_repo}/contents/output/history/{name}",
                 "-H", "Accept: application/vnd.github.raw"],
                capture_output=True, text=True, timeout=30,
            )
            if content.returncode == 0:
                with open(os.path.join(local_dir, name), "w", encoding="utf-8") as f:
                    f.write(content.stdout)
                n += 1
        print(f"  [pull] 已拉取 {n} 份历史报告到 {local_dir}")
        return n
    except Exception as e:
        print(f"  [pull] 拉取历史报告失败: {str(e)[:120]}")
        return 0


def extract_qiuge_data(md_path):
    try:
        with open(md_path, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return None
    m = re.search(r"<!--\s*QIUGE_DATA_START\s*-->\s*(.*?)\s*<!--\s*QIUGE_DATA_END\s*-->", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def load_state():
    state = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    # 确保初始持仓（招行 600036）在持仓列表中（除非已卖出移除）
    if "600036" not in state.get("positions", {}):
        INITIAL = INITIAL_POSITIONS.get("600036")
        if INITIAL:
            state.setdefault("positions", {})["600036"] = {
                "name": INITIAL["name"], "cost": INITIAL["cost"], "shares": INITIAL["shares"],
                "base": INITIAL["shares"],
                "init_shares": INITIAL["shares"],
                "buy_date": INITIAL["buy_date"], "buy_price": INITIAL["cost"],
                "target_pos": INITIAL["cost"] * INITIAL["shares"],
            }
    # 模拟仓现金固定 70 万（8/3 新增，与招行底仓无关）
    if "cash" not in state or state["cash"] is None or state["cash"] < INIT_CASH:
        state["cash"] = INIT_CASH
    state.setdefault("positions", {})
    state.setdefault("tracker", {})
    state.setdefault("log", [])
    state.setdefault("daily_nav", [])
    state.setdefault("last_update", None)
    if not state["positions"]:
        state["positions"] = {}
    if "600036" not in state["positions"]:
        INITIAL = INITIAL_POSITIONS.get("600036")
        if INITIAL:
            state["positions"]["600036"] = {
                "name": INITIAL["name"], "cost": INITIAL["cost"], "shares": INITIAL["shares"],
                "base": INITIAL["shares"],
                "buy_date": INITIAL["buy_date"], "buy_price": INITIAL["cost"],
                "target_pos": INITIAL["cost"] * INITIAL["shares"],
            }
    state.setdefault("profit_pool", 0.0)   # 利润池：短线已实现净盈亏累积（供核心仓扩大型加仓）
    return state


def save_state(state):
    os.makedirs(OUT_DIR, exist_ok=True)
    state["last_update"] = datetime.date.today().strftime("%Y-%m-%d")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def market_value(state, prices):
    """持仓市值：优先当日价，缺失时用最近可得收盘价（last_close 惯性计价，不用拍脑袋折扣）"""
    mv = 0.0
    for code, pos in state["positions"].items():
        px = prices.get(code) or pos.get("last_close")
        if px:
            mv += pos["shares"] * px
        else:
            mv += pos["cost"] * pos["shares"]  # 连 last_close 都没有（首日）按成本
    return mv


# ---------------- 核心判定 ----------------
def parse_zone_high(name):
    """从 watch 名称的括号注记提取买区上沿：'中国广核(回踩3.95-4.05)'→4.05；'药明康德(等回踩115-118上车)'→118
    无区间注记（如纯代码'拓荆科技(688072)'）返回 None。"""
    m = re.search(r"[（(]([^)）]*)[)）]", name)
    if not m:
        return None
    zm = re.search(r"(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)", m.group(1))
    if not zm:
        return None
    hi = float(zm.group(2))
    if hi > 5000:   # 过滤非价格的数字（代码类）
        return None
    return hi


def decide_buy(state, data, kline_map, flow_map, today):
    """判定 watch 标的是否触发买点（当日最低价触及买点价 + 资金确认，按买点价盘中成交）

    日期切片：MA 只取 today 之前的数据（防未来数据泄漏）；
    主力净额取 today 当日的历史资金流（f52）。
    """
    buys = []
    watch = data.get("watch", []) or []
    today_d = datetime.date.fromisoformat(today)
    for name in watch:
        code = name_to_code(name, data)
        if not code:
            continue
        klines = kline_map.get(code)
        if not klines or len(klines) < 20:
            continue
        # 只取 today 及以前的 K 线
        hist = [k for k in klines if k["date"] <= today]
        if len(hist) < 12:
            continue
        ma5 = ma(hist, 5)
        # 双锚取低（门槛一量化）：锚 = min(MA5, 报告买区上沿)，防比报告买贵（广核 8/4 教训）
        zone_high = parse_zone_high(name)
        anchor = min([a for a in (ma5, zone_high) if a])
        # 当日 K（today 那根）
        today_k = None
        for k in klines:
            if k["date"] == today:
                today_k = k
                break
        if not today_k:
            continue
        low, close = today_k["low"], today_k["close"]
        chg = today_k["pct_chg"]
        main_net = flow_map.get(code, {}).get(today, 0)
        # 涨停不追
        if chg >= LIMIT_UP_PCT:
            continue
        # 触及买点：当日最低价 <= 买点锚 × (1+2%)（盘中触及附近）
        touched = low <= anchor * (1 + BUY_BAND_PCT)
        broke = close < anchor * (1 - BREAKOUT_DROP_PCT)  # 收盘破位
        if not (touched and not broke):
            # 未触及或已破位：二次确认计数清零（补丁7）
            tr = state["tracker"].setdefault(code, {"name": name})
            tr["confirm_days"] = 0
            continue
        # ===== 补丁7 二次确认 + 强资金例外（对齐状态机12a）=====
        tr = state["tracker"].setdefault(code, {"name": name})
        if main_net > MIN_MAIN_NET:
            tr["confirm_days"] = tr.get("confirm_days", 0) + 1
        else:
            tr["confirm_days"] = 0  # 资金未确认，重新计数
        strong = main_net >= STRONG_MAIN_NET          # 单日主力≥5亿：紫金式教科书确认，允许当日上车
        confirmed = tr.get("confirm_days", 0) >= 2     # 连续2日"触及+资金>0"
        if confirmed or strong:
            tr["confirm_days"] = 0  # 买入后清零
            buys.append(
                {
                    "code": code,
                    "name": name,
                    "anchor": anchor,
                    "touched_low": low,
                    "close": close,
                    "main_net": main_net,
                    "chg": chg,
                }
            )
    return buys


def name_to_code(name, data):
    """从报告/已知映射猜代码（策略级：watch 名称 → 代码）
    兼容 '药明康德(回踩123-125)' 带括号注记格式：剥离括号取纯名称
    """
    # 剥离括号注记（中文/英文括号）
    pure = re.sub(r"[（(].*?[)）]", "", name).strip()
    if len(pure) > 12:
        return ""
    # 优先从 picks_detail 拿代码
    for p in data.get("picks_detail", []) or []:
        if p.get("name") == pure or pure in str(p.get("name", "")):
            return str(p.get("code", ""))
    # 常见映射表（8月看过的票）
    KNOWN = {
        "药明康德": "603259", "蓝思科技": "300433", "紫金矿业": "601899",
        "凯莱英": "002821", "盛达资源": "000603", "中际旭创": "300308",
        "新易盛": "300502", "士兰微": "600460", "生益科技": "600183",
        "歌尔股份": "002241", "寒武纪": "688256", "沪电股份": "002463",
        "兆易创新": "603986", "国瓷材料": "300285", "星网锐捷": "002396",
        "白银有色": "601212", "德明利": "001309", "诺德股份": "600110",
        "东山精密": "002384", "工业富联": "601138", "兴业银锡": "000426",
        "思源电气": "002028", "美的集团": "000333", "扬杰科技": "300373",
        "中国平安": "601318", "中钨高新": "000657", "中金黄金": "600489",
        "光迅科技": "002281", "飞龙股份": "002536", "江钨装备": "600397",
        "旭光电子": "600353", "融捷股份": "002192", "兴森科技": "002436",
        "北方铜业": "000737", "瑞斯康达": "603803", "顺络电子": "002138",
        "源杰科技": "688498", "藏格矿业": "000408", "湖南裕能": "301358",
        "科沃斯": "603486", "华峰化学": "002064", "招商银行": "600036",
        "招行": "600036", "杰瑞股份": "002353", "拓荆科技": "688072",
        "芯源微": "688037", "中国卫星": "600118", "恒瑞医药": "600276",
        "片仔癀": "600436", "西部黄金": "601069", "中国广核": "003816",
        "荣盛石化": "002493", "生益电子": "688183", "中国平安": "601318",
    }
    for k, v in KNOWN.items():
        if k in name:
            return v
    return ""


def decide_sell(state, data, kline_map, flow_map, today):
    """判定持仓卖出：破MA20减1/3 / 破MA60清仓 / 主力连2日净流出 / 止盈10-20%（日期切片）"""
    sells = []
    for code, pos in list(state["positions"].items()):
        klines = kline_map.get(code)
        if not klines or len(klines) < 60:
            continue
        hist = [k for k in klines if k["date"] <= today]
        if len(hist) < 60:
            continue
        ma20 = ma(hist, 20)
        ma60 = ma(hist, 60)
        today_ks = [k for k in klines if k["date"] == today]
        if not today_ks:
            continue
        close = today_ks[0]["close"]
        cost = pos["cost"]
        gain = (close - cost) / cost
        flows = flow_map.get(code, {})
        f_today = flows.get(today, 0)
        dates = sorted(d for d in flows if d <= today)
        # 主力连续 2 日净流出（断流）
        prev = None
        for dd in dates:
            if dd < today:
                prev = flows[dd]
        flow_out2 = f_today < 0 and prev is not None and prev < 0
        actions = []
        if code == "600036":
            # ===== 底仓（招行，v3 温和纪律） =====
            if ma20 and close < ma20:
                actions.append("break_ma20")
            if ma60 and close < ma60:
                actions.append("break_ma60")
            if gain >= TAKE_PROFIT:
                actions.append("take_profit")
            if flow_out2:
                actions.append("flow_out")
        else:
            # ===== 短线股（资金定档 v7） =====
            # 强势档：近 3 日主力净流入合计 > 0（顺风车还在）
            last3 = [flows[d] for d in dates[-3:]]
            strong = sum(last3) > 0
            # 高位射击星（上影 ≥5% 且收盘低于开盘）→ 减仓
            tk = today_ks[0]
            upper_shadow = (tk["high"] - max(tk["close"], tk["open"])) / tk["close"] if tk["close"] else 0
            if upper_shadow >= 0.05 and tk["close"] < tk["open"]:
                actions.append("shooting_star")
            # 无条件全卖（优先级最高）
            if ma60 and close < ma60:
                actions.append("break_ma60")
            elif ma20 and close < ma20 and f_today < 0:
                actions.append("break_ma20_flow")  # 破MA20+当日主力流出 → 全卖
            elif flow_out2:
                actions.append("flow_out2")  # 连续2日净流出 → 降档全卖
            elif strong:
                # 强势档：分批止盈（10/20/40% 各卖初始 1/3）
                if gain >= TP_40 and not pos.get("tp40_done"):
                    actions.append("tp40")
                elif gain >= TP_20 and not pos.get("tp20_done"):
                    actions.append("tp20")
                elif gain >= TP_10 and not pos.get("tp10_done"):
                    actions.append("tp10")
            else:
                # 弱势档：小目标止盈（+3% 全卖，积少成多）
                if gain >= TP_SMALL:
                    actions.append("tp_small")
        if actions:
            sells.append({"code": code, "name": pos["name"], "close": close, "cost": cost, "gain": gain, "actions": actions})
    return sells


# ---------------- 模拟执行 ----------------
def execute_buy(state, data, buys, today):
    """按买点锚价模拟盘中买入（初始建仓 1/3）"""
    # nav 用持仓最近收盘价计市值（last_close 惯性），不再传空字典
    _px = {c: pos.get("last_close") for c, pos in state["positions"].items() if pos.get("last_close")}
    nav = state["cash"] + market_value(state, _px)
    for b in buys:
        if len(state["positions"]) >= MAX_HOLD:
            break
        if b["code"] in state["positions"] or b["code"] in state["tracker"] and state["tracker"][b["code"]].get("status") == "bought":
            continue
        # 单笔预算 6 万；股价过高（一手 > 6 万）则按一手买（可突破预算）
        target_value = BUY_BUDGET
        shares = int(target_value / b["anchor"] / 100) * 100  # 整手
        if shares <= 0:
            shares = 100  # 一手保底（高价股突破 6 万限制）
        cost_money = shares * b["anchor"]
        fee = cost_money * BUY_FEE_RATE  # 买入佣金 万2.5
        if cost_money + fee > state["cash"]:
            continue
        state["cash"] -= (cost_money + fee)
        state["positions"][b["code"]] = {
            "name": re.sub(r"[（(].*?[)）]", "", b["name"]).strip(),
            "cost": b["anchor"],
            "shares": shares,
            "init_shares": shares,  # 初始股数（分批止盈按初始 1/3 卖）
            "buy_date": today,
            "buy_price": b["anchor"],
            "target_pos": nav * POSITION_MAX,
        }
        state["tracker"].setdefault(b["code"], {})["status"] = "bought"
        _clean_name = re.sub(r"[（(].*?[)）]", "", b["name"]).strip()  # 剥括号注记，防"芯源微(688037)(688037)"
        state["log"].append(
            {"date": today, "type": "BUY", "code": b["code"], "name": _clean_name, "price": round(b["anchor"], 2), "shares": shares, "reason": f"买点触发(最低{round(b['touched_low'],2)}触及买点锚{round(b['anchor'],2)})主力净流入{round(b['main_net']/1e8,2)}亿"}
        )
        print(f"  ✅ BUY {b['name']}({b['code']}) @{round(b['anchor'],2)} x{shares}  {today}")


def execute_sell(state, sells, today):
    """按收盘价模拟卖出（尾盘执行）：按动作类型分流（全卖 / 分批止盈 / 减仓）"""
    for s in sells:
        pos = state["positions"].get(s["code"])
        if not pos:
            continue
        close = s["close"]
        shares = pos["shares"]
        actions = s["actions"]
        is_base = s["code"] == "600036"
        reason_map = {
            "break_ma20": "破MA20减仓1/3",
            "break_ma60": "破MA60清仓",
            "take_profit": "止盈+15%减1/3",
            "flow_out": "主力净流出减仓",
            "break_ma20_flow": "破MA20+主力流出清仓",
            "flow_out2": "主力连2日流出清仓",
            "tp_small": "短线+3%止盈全卖",
            "tp10": "分批止盈+10%卖1/3",
            "tp20": "分批止盈+20%卖1/3",
            "tp40": "分批止盈+40%卖1/3",
            "shooting_star": "高位射击星减仓1/3",
        }

        # 卖出股数 & 动作执行
        if "break_ma60" in actions:
            # 无条件清仓（止损铁律）
            sell_shares = shares
            mark = "clear"
        elif not is_base:
            # ===== 短线股 =====
            if "break_ma20_flow" in actions or "flow_out2" in actions or "tp_small" in actions:
                sell_shares = shares  # 全卖
                mark = "clear"
            elif "tp40" in actions or "tp20" in actions or "tp10" in actions:
                # 分批止盈：每档卖初始股数 1/3（不贪最后一个铜板）
                init = pos.get("init_shares", shares)
                sell_shares = int(init / 3 / 100) * 100
                if sell_shares <= 0:
                    sell_shares = 100
                mark = "tp"
                if "tp40" in actions:
                    pos["tp40_done"] = True
                elif "tp20" in actions:
                    pos["tp20_done"] = True
                elif "tp10" in actions:
                    pos["tp10_done"] = True
            elif "shooting_star" in actions and not pos.get("sell_done"):
                sell_shares = int(shares / 3 / 100) * 100
                if sell_shares <= 0:
                    sell_shares = 100
                mark = "cut"
            else:
                print(f"  [skip-sell] {pos['name']} 无执行动作（信号={actions}）")
                continue
        else:
            # ===== 底仓（招行）：防务减仓与止盈各自一次性；恢复满仓后防务重新武装 =====
            defence = any(a in actions for a in ("break_ma20", "flow_out"))
            tp_sig = "take_profit" in actions
            if defence and pos.get("defence_done"):
                defence = False  # 已防务减仓且未恢复满仓 → 不重复（补丁15一次性）
            if tp_sig and pos.get("tp_done"):
                tp_sig = False   # 止盈已执行（不随恢复重置，防"接回即止盈"振荡）
            if not defence and not tp_sig:
                if actions:
                    print(f"  [skip-sell] {pos['name']} 减仓信号已执行过（信号={actions}）")
                continue
            sell_shares = int(shares / 3 / 100) * 100
            if sell_shares <= 0:
                sell_shares = 100
            mark = "cut"

        if sell_shares > shares:
            sell_shares = shares
        if sell_shares <= 0:
            continue
        reason = "、".join(reason_map.get(a, a) for a in actions)
        proceeds = sell_shares * close * (1 - SELL_FEE_RATE)  # 卖出佣金+印花税 万7.5
        state["cash"] += proceeds
        pos["shares"] -= sell_shares
        # 短线已实现盈亏入利润池（招行底仓的减仓属核心再平衡，不入池）
        if s["code"] != CORE_CODE:
            state["profit_pool"] = state.get("profit_pool", 0.0) + (close - pos["cost"]) * sell_shares
        # 摊薄成本法（券商通用）：卖出已实现盈亏摊入剩余持仓（盈利摊低/亏损摊高）
        if pos["shares"] > 0:
            pos["cost"] = round((pos["cost"] * (pos["shares"] + sell_shares) - close * sell_shares) / pos["shares"], 3)
        state["log"].append(
            {"date": today, "type": "SELL", "code": s["code"], "name": pos["name"], "price": round(close, 2), "shares": sell_shares, "reason": reason}
        )
        print(f"  🔻 SELL {pos['name']}({s['code']}) @{round(close,2)} x{sell_shares}  {reason}")
        # 标记
        if mark == "cut":
            if s["code"] == CORE_CODE:
                if "take_profit" in actions:
                    pos["tp_done"] = True       # 止盈一次性（不随恢复重置）
                if "break_ma20" in actions or "flow_out" in actions:
                    pos["defence_done"] = True  # 防务减仓一次性（恢复满仓后重新武装）
            else:
                pos["sell_done"] = True  # 射击星减仓一次性
        if mark == "clear":
            pos["sell_done"] = True
        if pos["shares"] <= 0:
            del state["positions"][s["code"]]
            # 记录平仓
            entry = state["tracker"].get(s["code"], {})
            entry["closed"] = True
            entry["close_price"] = close
            entry["close_date"] = today
            entry["gain_pct"] = round((close - pos["cost"]) / pos["cost"] * 100, 2)


def update_tracker_timeout(state, data, today):
    """观察超时移除：watch 超 7 交易日无买点 → 标记 expired"""
    watch = data.get("watch", []) or []
    for name in watch:
        code = name_to_code(name, data)
        if not code:
            continue
        tr = state["tracker"].setdefault(code, {"name": name, "add_date": today})
        if tr.get("status") not in ("bought", "removed", "expired"):
            tr.setdefault("add_date", today)
            # 简化:基于报告日期推进，超过 7 交易日（自然日约10天）算过期
            add_d = datetime.date.fromisoformat(tr["add_date"])
            today_d = datetime.date.fromisoformat(today)
            if (today_d - add_d).days >= 12:  # 12 自然日 ≈ 7交易日
                tr["status"] = "expired"
                tr["remove_date"] = today
                tr["remove_reason"] = "观察超时未触发"
                print(f"  ⏳ EXPIRED {name}({code}) 观察超时移除")


# ---------------- 每日主流程 ----------------
def decide_core_buy(state, kline_map, flow_map, today):
    """招行核心仓买入判定（核心-卫星模型）：
    恢复型：持股<初始10000 且 收盘收回MA20 且 当日主力>0 → 买回全部缺口（不受利润池约束）
    扩大型：估值BUY(PB<0.9&股息≥4%)+1000 / STRONG(PB<0.7&≥5%)+2000 /
            盈利回落≥15pp+1000 / ≥20pp+2000 —— 受利润池+55%硬顶约束，信号一次性
    """
    acts = []
    pos = state.get("positions", {}).get(CORE_CODE)
    if not pos:
        return acts  # 已清仓不自动重建（破MA60离场属人工决策范畴）
    klines = kline_map.get(CORE_CODE) or []
    tk = [k for k in klines if k["date"] == today]
    if not tk:
        return acts
    close = tk[0]["close"]
    hist = [k for k in klines if k["date"] <= today]
    ma20 = ma(hist, 20)
    flows = flow_map.get(CORE_CODE) or {}
    f_today = flows.get(today, 0)

    def total_assets():
        mv = sum(p["shares"] * p.get("last_close", p["cost"]) for c, p in state["positions"].items() if c != CORE_CODE)
        return state["cash"] + mv + pos["shares"] * close

    def feasible(shares):
        """现金够 + 硬顶内"""
        cost = shares * close * (1 + BUY_FEE_RATE)
        if state["cash"] < cost:
            return False, "现金不足"
        if (pos["shares"] + shares) * close > CORE_CAP_PCT * total_assets():
            return False, f"超{int(CORE_CAP_PCT*100)}%硬顶"
        return True, ""

    # ---- 恢复型 ----
    base = pos.get("base", CORE_INIT_SHARES)   # 满仓基准=历史峰值持股（扩大型加仓时抬升）
    deficit = base - pos["shares"]
    if deficit >= 100 and ma20 and close > ma20 and f_today > 0:
        ok, why = feasible(deficit)
        if ok:
            acts.append({"type": "restore", "shares": deficit, "price": close,
                         "reason": f"恢复持有(收回MA20+主力{f_today/1e8:+.2f}亿,买回缺口{deficit}股)"})
        else:
            print(f"  [core-restore] 跳过: {why}")

    # ---- 扩大型（信号一次性，done 标记存 pos）----
    pb = close / ZH_FUND["bvps"]
    dy = ZH_FUND["div_ps"] / close * 100
    pool = state.get("profit_pool", 0.0)
    spent = pos.get("expand_spent", 0.0)
    signals = []
    if pb < 0.9 and dy >= 4 and not pos.get("sig_buy"):
        signals.append(("sig_buy", CORE_ADD_STEP, f"估值BUY(PB={pb:.2f}<0.9,股息率{dy:.2f}%≥4%)"))
    if pb < 0.7 and dy >= 5 and not pos.get("sig_strong"):
        signals.append(("sig_strong", CORE_ADD_STEP * 2, f"估值STRONG(PB={pb:.2f}<0.7,股息率{dy:.2f}%≥5%)"))
    if len(hist) >= 60:
        roll_high = max(k["high"] for k in hist[-250:])
        dd_pp = (roll_high - close) / roll_high * 100
        if dd_pp >= 15 and not pos.get("sig_dd15"):
            signals.append(("sig_dd15", CORE_ADD_STEP, f"盈利回落{dd_pp:.1f}pp≥15"))
        if dd_pp >= 20 and not pos.get("sig_dd20"):
            signals.append(("sig_dd20", CORE_ADD_STEP * 2, f"盈利回落{dd_pp:.1f}pp≥20"))
    for flag, shares, why in signals:
        ok, why2 = feasible(shares)
        if not ok:
            print(f"  [core-expand] {why} 跳过: {why2}")
            continue
        cost = shares * close
        if spent + cost > pool:
            print(f"  [core-expand] {why} 跳过: 利润池不足(需{cost:.0f},池{pool:.0f},已用{spent:.0f})")
            continue
        acts.append({"type": "expand", "flag": flag, "shares": shares, "price": close,
                     "reason": f"扩大加仓+{shares}股({why},利润池{pool:.0f})"})
    return acts


def execute_core_buy(state, acts, today):
    """执行招行核心仓买入（当日收盘价成交，扣买入佣金）"""
    pos = state.get("positions", {}).get(CORE_CODE)
    if not pos:
        return
    for a in acts:
        shares, price = a["shares"], a["price"]
        cost_money = shares * price
        fee = cost_money * BUY_FEE_RATE
        state["cash"] -= (cost_money + fee)
        # 加权平均成本（含佣金，券商通用）
        pos["cost"] = round((pos["cost"] * pos["shares"] + cost_money + fee) / (pos["shares"] + shares), 3)
        pos["shares"] += shares
        if a["type"] == "expand":
            pos[a["flag"]] = True
            pos["expand_spent"] = pos.get("expand_spent", 0.0) + cost_money
            pos["base"] = pos.get("base", CORE_INIT_SHARES) + shares   # 峰值基准抬升
        if a["type"] == "restore":
            pos.pop("defence_done", None)   # 满仓恢复 → 防务重新武装（下一轮破位可再减）
            pos.pop("sell_done", None)      # 兼容旧标记
        state["log"].append(
            {"date": today, "type": "BUY", "code": CORE_CODE, "name": pos["name"],
             "price": round(price, 2), "shares": shares, "reason": a["reason"]}
        )
        print(f"  🏦 CORE-BUY {pos['name']} @{round(price,2)} x{shares}  {a['reason']}")


def run_day(state, data, today, dry=False, snapshot=None):
    """执行一日模拟：拉 T+1 行情 → 判定买/卖 → 更新账户净值
    snapshot: {code: {"kline": [...], "flows": {date: net}}}（本地采集快照，不联网）
    """
    print(f"\n===== 模拟日 {today} =====")
    watch = data.get("watch", []) or []
    picks = [p.get("code") for p in (data.get("picks_detail", []) or []) if p.get("code")]
    codes = []
    for name in watch:
        c = name_to_code(name, data)
        if c:
            codes.append(c)
    codes += picks
    codes = list(dict.fromkeys(codes))
    # 补上所有持仓标的（卖出判定需要：持仓可能不在当日报告 watch/picks 里）
    for c in state.get("positions", {}):
        codes.append(c)
    codes = list(dict.fromkeys(codes))
    # 只保留A股代码（沪6/深0/创业3开头），港股跳过
    codes = [c for c in codes if c and len(c) == 6 and c[0] in ("6", "0", "3")]

    # 拉行情（快照优先，否则 HTTP）
    kline_map = {}
    flow_map = {}
    for code in codes:
        if snapshot and code in snapshot:
            sn = snapshot[code]
            if sn.get("kline"):
                kline_map[code] = sn["kline"]
            if sn.get("flows"):
                flow_map[code] = sn["flows"]
            continue
        market = "1" if code.startswith(("6", "68", "60")) else "0"
        try:
            kline_map[code] = get_kline(code, market=market)
        except Exception as e:
            print(f"  [fetch] {code} 东财K线失败: {str(e)[:60]}")
        if not kline_map.get(code):
            kline_map[code] = get_kline_tencent(code, market=market)
            if kline_map.get(code):
                print(f"  [fetch] {code} 已用腾讯K线兜底")
        try:
            flow_map[code] = get_flow_history(code, market=market)
        except Exception as e:
            print(f"  [fetch] {code} 资金流失败: {str(e)[:60]}")

    if dry:
        buys = decide_buy(state, data, kline_map, flow_map, today)
        sells = decide_sell(state, data, kline_map, flow_map, today)
        print("  [dry-run] buys:", [(b["name"], round(b["anchor"], 2)) for b in buys])
        print("  [dry-run] sells:", [(s["name"], s["actions"]) for s in sells])
        return

    # 判定卖出（先卖再买）
    sells = decide_sell(state, data, kline_map, flow_map, today)
    execute_sell(state, sells, today)
    # 招行核心仓买入（恢复/扩大，先于卫星仓）
    core_acts = decide_core_buy(state, kline_map, flow_map, today)
    execute_core_buy(state, core_acts, today)
    # 判定买入
    buys = decide_buy(state, data, kline_map, flow_map, today)
    execute_buy(state, data, buys, today)
    # 观察超时
    update_tracker_timeout(state, data, today)
    # 更新净值（按 today 当日收盘，防未来数据泄漏）
    prices = {}
    for code in codes:
        kl = kline_map.get(code)
        if not kl:
            continue
        tk = [k for k in kl if k["date"] == today]
        prices[code] = tk[0]["close"] if tk else kl[-1]["close"]
    # 持仓行情字段（渲染持仓表用：最新收盘/昨收/当日涨跌/当日盈亏/总盈亏）
    for code, pos in state.get("positions", {}).items():
        kl = kline_map.get(code)
        if not kl:
            continue
        hist = sorted([k for k in kl if k["date"] <= today], key=lambda k: k["date"])
        if len(hist) >= 2:
            last, prev = hist[-1], hist[-2]
            px = last["close"]
            pos["last_close"] = px
            pos["prev_close"] = prev["close"]
            pos["chg_pct"] = round((px - prev["close"]) / prev["close"] * 100, 2)
            pos["day_pnl"] = round((px - prev["close"]) * pos["shares"], 2)
            pos["total_pnl"] = round((px - pos["cost"]) * pos["shares"], 2)
        elif hist:
            pos["last_close"] = hist[-1]["close"]
            pos["prev_close"] = pos["last_close"]
            pos["chg_pct"] = 0.0
            pos["day_pnl"] = 0.0
            pos["total_pnl"] = round((hist[-1]["close"] - pos["cost"]) * pos["shares"], 2)
    mv = market_value(state, prices)
    nav = state["cash"] + mv
    rec = {"date": today, "nav": round(nav, 2), "cash": round(state["cash"], 2), "market_value": round(mv, 2)}
    # 同日覆盖（多份报告可能验证同一天，如周五+周末报告都验证周一）
    if state["daily_nav"] and state["daily_nav"][-1]["date"] == today:
        state["daily_nav"][-1] = rec
    else:
        state["daily_nav"].append(rec)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": today, "nav": rec["nav"], "cash": rec["cash"], "mv": rec["market_value"]}, ensure_ascii=False) + "\n")
    print(f"  净值: {nav:,.0f}  现金: {state['cash']:,.0f}  持仓: {len(state['positions'])}只")


def compute_stats(state, bench=None):
    """统计：命中率/胜率/盈亏比/回撤/基准对比（沪深300/红利低波）"""
    stats = {"total_trades": 0, "wins": 0, "losses": 0, "open": 0}
    trades = []
    for code, entry in state.get("tracker", {}).items():
        if entry.get("closed"):
            g = entry.get("gain_pct", 0)
            trades.append({"code": code, "gain_pct": g})
            if g > 0:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
    stats["total_trades"] = stats["wins"] + stats["losses"]
    stats["open"] = sum(1 for p in state.get("positions", {}).values())
    stats["win_rate"] = round(stats["wins"] / stats["total_trades"] * 100, 1) if stats["total_trades"] else 0
    # 盈亏比
    wins = [t["gain_pct"] for t in trades if t["gain_pct"] > 0]
    losses = [t["gain_pct"] for t in trades if t["gain_pct"] <= 0]
    stats["avg_win"] = round(sum(wins) / len(wins), 2) if wins else 0
    stats["avg_loss"] = round(sum(losses) / len(losses), 2) if losses else 0
    stats["profit_factor"] = round(abs(stats["avg_win"] / stats["avg_loss"]), 2) if losses and stats["avg_loss"] != 0 else 0
    # 净值/回撤
    navs = [n["nav"] for n in state.get("daily_nav", [])]
    stats["latest_nav"] = navs[-1] if navs else BASELINE_NAV
    stats["total_return"] = round((stats["latest_nav"] - BASELINE_NAV) / BASELINE_NAV * 100, 2)
    peak = BASELINE_NAV
    mdd = 0.0
    for n in navs:
        if n > peak:
            peak = n
        dd = (n - peak) / peak
        if dd < mdd:
            mdd = dd
    stats["max_drawdown"] = round(mdd * 100, 2)
    stats["days"] = len(navs)
    # 总盈亏金额 + 基准同期对比（口径对齐：均从 2026-08-03 起算）
    stats["total_pnl"] = round(stats["latest_nav"] - BASELINE_NAV, 2)
    if bench:
        for key in ("hs300", "divlow"):
            ser = bench.get(key) or {}
            b0 = ser.get("2026-08-03")
            if b0 and ser:
                last_close = ser[max(ser)]  # 按日期取最新收盘（非最大值！）
                ret = (last_close / b0 - 1) * 100
                stats[f"{key}_return"] = round(ret, 2)
                stats[f"excess_{key}"] = round(stats["total_return"] - ret, 2)
    return stats


def write_report(state, stats, data):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"# 秋哥操作 · 实盘模拟报告\n\n")
        f.write(f"> 模拟账户（非真实资金）· 起点 2026-08-03 净值 ¥1,103,600（招行10000×40.36 + 70万） · 更新 {datetime.date.today()}\n\n")
        f.write(f"## 账户概览\n\n")
        f.write(f"| 指标 | 数值 |\n|---|---|\n")
        f.write(f"| 最新净值 | {stats['latest_nav']:,.0f} |\n")
        f.write(f"| 累计收益 | {stats['total_return']:+.2f}% |\n")
        f.write(f"| 最大回撤 | {stats['max_drawdown']:.2f}% |\n")
        f.write(f"| 交易数 | {stats['total_trades']} |\n")
        f.write(f"| 胜率 | {stats['win_rate']}% |\n")
        f.write(f"| 盈亏比 | {stats['profit_factor']} |\n")
        f.write(f"| 当前持仓 | {stats['open']} 只 |\n\n")
        f.write(f"## 当前持仓\n\n")
        f.write(f"| 代码 | 名称 | 成本 | 数量 | 买入日 |\n|---|---|---|---|---|\n")
        for code, p in state.get("positions", {}).items():
            f.write(f"| {code} | {p['name']} | {p['cost']:.2f} | {p['shares']} | {p['buy_date']} |\n")
        f.write(f"\n## 最近交易\n\n")
        f.write(f"| 日期 | 类型 | 标的 | 价格 | 数量 | 原因 |\n|---|---|---|---|---|---|\n")
        for t in state.get("log", [])[-20:]:
            f.write(f"| {t['date']} | {t['type']} | {t['name']} | {t.get('price','')} | {t.get('shares','')} | {t.get('reason','')} |\n")
        f.write(f"\n> 免责声明：本模拟仅供方法验证，不构成投资建议。\n")
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


# ---------------- 入口 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="【推荐】每日增量模拟：自动补齐缺跑天数，幂等可重复")
    ap.add_argument("--daily", action="store_true", help="(旧)当日模拟——已被 --auto 取代")
    ap.add_argument("--replay", action="store_true", help="(旧)全量回放——已被 --auto 取代（--auto=增量版replay）")
    ap.add_argument("--start", default="2026-08-03", help="回放起始日")
    ap.add_argument("--snapshot", default="data/simulation_snapshot.json", help="本地快照文件（tdx数据，优先于HTTP）")
    ap.add_argument("--dry-run", action="store_true", help="只打印判定")
    args = ap.parse_args()

    state = load_state()
    # 快照数据（本地用 tdx 采集，模拟器优先用快照不联网）
    snapshot = {}
    if os.path.exists(args.snapshot):
        with open(args.snapshot, encoding="utf-8") as f:
            snapshot = json.load(f)
    if args.replay or args.daily or args.auto:
        if args.daily:
            # 当日：读最新报告
            if not os.path.exists(REPORT_JSON_PATH):
                print("❌ 未找到 output/qiuge_report.json")
                sys.exit(1)
            with open(REPORT_JSON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            today = data.get("data_date") or datetime.date.today().strftime("%Y-%m-%d")
            # 快照新鲜度校验：快照最大日 < 报告日 → 拒绝运行（防止拿旧K线当当日判定）
            if snapshot:
                max_d = max((k.get("date") for v in snapshot.values() for k in (v.get("kline") or [])), default="")
                if max_d and max_d < today:
                    print(f"❌ 快照最大日 {max_d} < 报告日 {today}，请先采集当日快照（tdx K线+资金流）再跑 --daily")
                    sys.exit(1)
            run_day(state, data, today, dry=args.dry_run, snapshot=snapshot)
            save_state(state)
        elif args.replay or args.auto:
            # 增量模拟（--auto/--replay 同体）：遍历报告按验证日推进，
            # 已处理的验证日幂等跳过 → 每天跑=只处理昨日；缺跑N天=自动补齐N天
            if not (glob.glob(os.path.join(HISTORY_DIR, "秋哥操作_*.md")) or glob.glob(os.path.join(OUT_DIR, "秋哥操作_*.md"))):
                pull_history_reports()
            if not (glob.glob(os.path.join(HISTORY_DIR, "秋哥操作_*.md")) or glob.glob(os.path.join(OUT_DIR, "秋哥操作_*.md"))):
                pull_history_reports()
            # 历史回放：遍历本地报告（含云端 history）
            # 按"文件名"去重：同一文件名只取一份（根目录优先），避免重复处理同一验证日
            files = []
            seen_names = set()
            for base in (REPO_DIR, OUT_DIR, HISTORY_DIR):  # 根目录优先
                if not os.path.isdir(base):
                    continue
                for f in glob.glob(os.path.join(base, "秋哥操作_全量扫描_*.md")):  # 只匹配全量扫描系列
                    bn = os.path.basename(f)
                    if bn in seen_names:
                        continue
                    seen_names.add(bn)
                    files.append(f)
            files = sorted(files, key=lambda f: os.path.basename(f))  # 按文件名(含日期)排序，保证回放顺序
            # 净值起点：2026-08-03（8月第一个交易日）= 招行 10000×40.36 + 70万 = 1,103,600
            if not state.get("daily_nav"):
                state["daily_nav"] = [{"date": "2026-08-03", "nav": BASELINE_NAV, "cash": INIT_CASH, "market_value": BASELINE_NAV - INIT_CASH}]
                with open(HISTORY_PATH, "a", encoding="utf-8") as hf:
                    hf.write(json.dumps({"date": "2026-08-03", "nav": BASELINE_NAV, "cash": INIT_CASH, "mv": BASELINE_NAV - INIT_CASH}, ensure_ascii=False) + "\n")
                print(f"  [起点] 2026-08-03 净值 {BASELINE_NAV:,.0f}（招行10000×40.36 + 70万）")
            # 按日期过滤 >= start
            start_d = datetime.date.fromisoformat(args.start)
            for f in files:
                m = re.search(r"(\d{8})", os.path.basename(f))
                if not m:
                    continue
                d = datetime.date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8]))
                if d < start_d:
                    continue
                data = extract_qiuge_data(f)
                if not data:
                    continue
                dd = data.get("data_date") or d.strftime("%Y-%m-%d")
                # 下一交易日（回放验证日）——跳过周末
                nd = d
                for _ in range(7):
                    nd = nd + datetime.timedelta(days=1)
                    if nd.weekday() < 5:
                        break
                verify_date = nd.strftime("%Y-%m-%d")
                # 幂等增量：已处理过的验证日跳过（缺跑补课时中间日自动补齐，重复运行不重复交易）
                _last = state.get("last_processed_date")
                if _last and verify_date <= _last:
                    continue
                # 若快照有数据，跳过验证日在快照最大日期之后的报告（无未来数据）
                if snapshot:
                    max_d = max((k.get("date") for v in snapshot.values() for k in (v.get("kline") or [])), default="")
                    if max_d and verify_date > max_d:
                        print(f"  [skip] {verify_date} > 快照最大日 {max_d}，跳过（未来日无数据）")
                        continue
                run_day(state, data, verify_date, dry=args.dry_run, snapshot=snapshot)
            # 记录本次推进到的最大验证日（下次 --auto 从这里之后继续）
            _done = [rec["date"] for rec in state.get("daily_nav", [])]
            if _done:
                state["last_processed_date"] = max(_done)
            save_state(state)
        # 统计 + 报告
        stats = compute_stats(state, bench=snapshot.get("benchmarks"))
        _d = data if "data" in dir() else None
        write_report(state, stats, _d)
        print("\n===== 统计 =====")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()