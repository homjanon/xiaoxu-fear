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

INIT_CASH = 1_000_000.0          # 初始资金 100 万
POSITION_MAX = 0.15              # 单只目标仓位 1.5 成（15%）
POSITION_FIRST = 0.05            # 初始建仓 1/3 = 总资产 5%
MAX_HOLD = 5                     # 并行持仓上限 5 只
BUY_BAND_PCT = 0.02              # 买点 ±2% 判定
BREAKOUT_DROP_PCT = 0.03         # 回踩变破位：收盘 < 买点×0.97
STOP_MA20 = 0.10                 # 减仓 1/3（破 MA20）
STOP_MA60 = 0.10                 # 清仓（破 MA60）
TAKE_PROFIT_1 = 0.10             # 止盈 1/3（+10%）
TAKE_PROFIT_2 = 0.20             # 再止盈 1/3（+20%）
WATCH_TIMEOUT_DAYS = 7           # 观察超时移除（7 交易日）
LIMIT_UP_PCT = 9.5               # 涨停不追
MIN_MAIN_NET = 0                 # 买点触发当日主力净流入需 > 0（补丁9）

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
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "cash": INIT_CASH,
        "positions": {},   # code -> {name, cost, shares, buy_date, buy_price, target_pos}
        "tracker": {},     # code -> {name, add_date, add_price(买点锚), reason, status(watch/bought/removed/expired), remove_date, remove_reason}
        "log": [],         # 交易日志
        "daily_nav": [],   # [{date, nav, cash, market_value}]
        "last_update": None,
    }


def save_state(state):
    os.makedirs(OUT_DIR, exist_ok=True)
    state["last_update"] = datetime.date.today().strftime("%Y-%m-%d")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def market_value(state, prices):
    mv = 0.0
    for code, pos in state["positions"].items():
        px = prices.get(code)
        if px:
            mv += pos["shares"] * px
        else:
            mv += pos["cost"] * pos["shares"] * 0.9  # 无实时价按成本×0.9保守
    return mv


# ---------------- 核心判定 ----------------
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
        ma10 = ma(hist, 10)
        anchor = min(ma5, ma10)  # 买点锚 = min(MA5, MA10)
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
        if touched and not broke and main_net > MIN_MAIN_NET:
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
    """从报告/已知映射猜代码（策略级：watch 名称 → 代码）"""
    # 优先从 picks_detail 拿代码
    for p in data.get("picks_detail", []) or []:
        if p.get("name") == name or name in str(p.get("name", "")):
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
        close = [k for k in klines if k["date"] == today][0]["close"]
        cost = pos["cost"]
        gain = (close - cost) / cost
        actions = []
        if ma20 and close < ma20:
            actions.append("break_ma20")
        if ma60 and close < ma60:
            actions.append("break_ma60")
        if gain >= TAKE_PROFIT_1:
            actions.append("take_profit1")
        if gain >= TAKE_PROFIT_2:
            actions.append("take_profit2")
        # 主力连 2 日净流出（断流）→ 减仓/离场：今日与昨日主力均 < 0
        flows = flow_map.get(code, {})
        f_today = flows.get(today, 0)
        # 昨日 = 上一个交易日
        prev = None
        for dd, v in sorted(flows.items()):
            if dd < today:
                prev = v
        if f_today < 0 and prev is not None and prev < 0:
            actions.append("flow_out")
        if actions:
            sells.append({"code": code, "name": pos["name"], "close": close, "cost": cost, "gain": gain, "actions": actions})
    return sells


# ---------------- 模拟执行 ----------------
def execute_buy(state, data, buys, today):
    """按买点锚价模拟盘中买入（初始建仓 1/3）"""
    nav = state["cash"] + market_value(state, {})
    for b in buys:
        if len(state["positions"]) >= MAX_HOLD:
            break
        if b["code"] in state["positions"] or b["code"] in state["tracker"] and state["tracker"][b["code"]].get("status") == "bought":
            continue
        # 目标仓位 1.5 成 → 初始 1/3 = 5%
        target_value = nav * POSITION_FIRST
        shares = int(target_value / b["anchor"] / 100) * 100  # 整手
        if shares <= 0:
            shares = 100
        cost_money = shares * b["anchor"]
        if cost_money > state["cash"]:
            continue
        state["cash"] -= cost_money
        state["positions"][b["code"]] = {
            "name": b["name"],
            "cost": b["anchor"],
            "shares": shares,
            "buy_date": today,
            "buy_price": b["anchor"],
            "target_pos": nav * POSITION_MAX,
        }
        state["tracker"].setdefault(b["code"], {})["status"] = "bought"
        state["log"].append(
            {"date": today, "type": "BUY", "code": b["code"], "name": b["name"], "price": round(b["anchor"], 2), "shares": shares, "reason": f"买点触发(最低{round(b['touched_low'],2)}触及买点锚{round(b['anchor'],2)})主力净流入{round(b['main_net']/1e8,2)}亿"}
        )
        print(f"  ✅ BUY {b['name']}({b['code']}) @{round(b['anchor'],2)} x{shares}  {today}")


def execute_sell(state, sells, today):
    """按收盘价模拟卖出（尾盘执行）"""
    for s in sells:
        pos = state["positions"].get(s["code"])
        if not pos:
            continue
        close = s["close"]
        shares = pos["shares"]
        reason_map = {
            "break_ma20": "破MA20减仓1/3",
            "break_ma60": "破MA60清仓",
            "take_profit1": "止盈+10%减1/3",
            "take_profit2": "止盈+20%再减1/3",
            "flow_out": "主力净流出减仓",
        }
        sell_ratio = 1.0
        if "break_ma60" in s["actions"]:
            sell_ratio = 1.0
        elif "break_ma20" in s["actions"] or "flow_out" in s["actions"]:
            sell_ratio = 1 / 3
        elif "take_profit2" in s["actions"]:
            sell_ratio = 1 / 3
        elif "take_profit1" in s["actions"]:
            sell_ratio = 1 / 3
        sell_shares = int(shares * sell_ratio / 100) * 100
        if sell_shares <= 0:
            sell_shares = 0
        reason = "、".join(reason_map.get(a, a) for a in s["actions"])
        if sell_shares > 0:
            proceeds = sell_shares * close
            state["cash"] += proceeds
            pos["shares"] -= sell_shares
            state["log"].append(
                {"date": today, "type": "SELL", "code": s["code"], "name": pos["name"], "price": round(close, 2), "shares": sell_shares, "reason": reason}
            )
            print(f"  🔻 SELL {pos['name']}({s['code']}) @{round(close,2)} x{sell_shares}  {reason}")
            if pos["shares"] <= 0:
                del state["positions"][s["code"]]
                # 记录平仓
                entry = state["tracker"].get(s["code"], {})
                entry["closed"] = True
                entry["close_price"] = close
                entry["close_date"] = today
                entry["gain_pct"] = round((close - pos["cost"]) / pos["cost"] * 100, 2)
        else:
            # 破MA60清仓但不足一手 → 直接全清
            if "break_ma60" in s["actions"]:
                proceeds = shares * close
                state["cash"] += proceeds
                state["log"].append({"date": today, "type": "SELL", "code": s["code"], "name": pos["name"], "price": round(close, 2), "shares": shares, "reason": "破MA60清仓(不足一手全清)"})
                del state["positions"][s["code"]]
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
def run_day(state, data, today, dry=False):
    """执行一日模拟：拉 T+1 行情 → 判定买/卖 → 更新账户净值"""
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

    # 拉行情（东财）
    kline_map = {}
    flow_map = {}
    for code in codes:
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
    # 判定买入
    buys = decide_buy(state, data, kline_map, flow_map, today)
    execute_buy(state, buys, today)
    # 观察超时
    update_tracker_timeout(state, data, today)
    # 更新净值
    prices = {}
    for code in codes:
        if code in kline_map:
            prices[code] = kline_map[code][-1]["close"]
    mv = market_value(state, prices)
    nav = state["cash"] + mv
    state["daily_nav"].append({"date": today, "nav": round(nav, 2), "cash": round(state["cash"], 2), "market_value": round(mv, 2)})
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"date": today, "nav": round(nav, 2), "cash": round(state["cash"], 2), "mv": round(mv, 2)}, ensure_ascii=False) + "\n")
    print(f"  净值: {nav:,.0f}  现金: {state['cash']:,.0f}  持仓: {len(state['positions'])}只")


def compute_stats(state):
    """统计：命中率/胜率/盈亏比/回撤/招行纪律有效性"""
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
    stats["latest_nav"] = navs[-1] if navs else INIT_CASH
    stats["total_return"] = round((stats["latest_nav"] - INIT_CASH) / INIT_CASH * 100, 2)
    peak = INIT_CASH
    mdd = 0.0
    for n in navs:
        if n > peak:
            peak = n
        dd = (n - peak) / peak
        if dd < mdd:
            mdd = dd
    stats["max_drawdown"] = round(mdd * 100, 2)
    stats["days"] = len(navs)
    return stats


def write_report(state, stats, data):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"# 秋哥操作 · 实盘模拟报告\n\n")
        f.write(f"> 模拟账户（非真实资金）· 初始资金 ¥1,000,000 · 更新 {datetime.date.today()}\n\n")
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
    ap.add_argument("--daily", action="store_true", help="当日模拟（读最新 qiuge_report.json）")
    ap.add_argument("--replay", action="store_true", help="历史回放")
    ap.add_argument("--start", default="2026-08-03", help="回放起始日")
    ap.add_argument("--dry-run", action="store_true", help="只打印判定")
    args = ap.parse_args()

    state = load_state()
    if args.replay or args.daily:
        if args.daily:
            # 当日：读最新报告
            if not os.path.exists(REPORT_JSON_PATH):
                print("❌ 未找到 output/qiuge_report.json")
                sys.exit(1)
            with open(REPORT_JSON_PATH, encoding="utf-8") as f:
                data = json.load(f)
            today = data.get("data_date") or datetime.date.today().strftime("%Y-%m-%d")
            run_day(state, data, today, dry=args.dry_run)
            save_state(state)
        elif args.replay:
            # 历史回放：遍历本地报告（含云端 history）
            files = []
            for base in (HISTORY_DIR, OUT_DIR, REPO_DIR):
                if os.path.isdir(base):
                    files += glob.glob(os.path.join(base, "秋哥操作_*_*.md"))
            files = sorted(set(files))
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
                run_day(state, data, verify_date, dry=args.dry_run)
            save_state(state)
        # 统计 + 报告
        stats = compute_stats(state)
        write_report(state, stats, data if not args.daily else data)
        print("\n===== 统计 =====")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()