#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
850天线抄底坐标 · 纯计算（仅标准库，零依赖，仿 dibudian_index.py 风格）
====================================================================

把「850天线取数器」采集到的四大指数日K，映射为一张「是否进入抄底区」的坐标卡。
不依赖任何外部库，与 XXFI（小旭恐惧指数）、冰点参考、底部区域判断完全独立。

观点来源：
  财经博主 plutus（2026-10）：「各大指数往下跌，可以大资金抄底的位置是 850天线」，
  并举例中证1000 ≈ 6500。850天线 = 最近 850 个交易日收盘价算术平均（≈3.4 年成本线）。

判定口径（每个指数独立，收盘优先于盘中）：
  ma850_i  = 最近 850 个交易日收盘均价（含当日）
  收盘跌破 ⇔ close < ma850
  盘中跌破 ⇔ low ≤ ma850 且 close > ma850（跌破后收回）
  综合状态 ⇔ 任一收盘跌破 → 按跌破家数分「局部 / 多数 / 全面进入」
             否则任一盘中跌破 → 盘中跌破后收回
             否则 → 未到
  可取指数 < 2 个 → 暂未获取（单个指数失败只标该格，不拖累整体）

「最近一次收盘跌破 / 盘中跌破」同样由日K序列直接回溯（历史 MA 逐日滚动计算），
不引入任何跨日状态文件，避免状态污染。

输入字段（由 fetch_ma850_akshare.build_ma850_inputs() 产出）：
  indices : [{"code","name","dates","closes","lows","src"}]
            - dates / closes / lows 等长，按时间升序，最后一根为最新交易日
            - 取数失败的指数可为 {"code","name","error": "..."}（无序列）
  _data_date / _src : 数据日期与命中源（可选）
"""
import json
from typing import Any, Dict, List, Optional

LOOKBACK = 850  # 850 个交易日 ≈ 3.4 年

# 展示顺序：中证1000 放首位（plutus 原文举例），其余按大盘权重
INDEXES = [
    ("sh000852", "中证1000"),
    ("sh000300", "沪深300"),
    ("sh000001", "上证指数"),
    ("sz399006", "创业板指"),
]
PRIMARY_CODE = "sh000852"

STATE_TEXT = {
    "below": "收盘跌破",
    "touched": "盘中跌破",
    "above": "线上",
    "na": "暂未获取",
}

VERDICTS = {
    "entered_full": ("全面进入 850 抄底区", "🟢"),
    "entered_major": ("多数进入 850 抄底区", "🟢"),
    "entered_partial": ("局部进入 850 抄底区", "🟢"),
    "touched": ("盘中跌破后收回", "🟠"),
    "not_reached": ("未到 850 抄底区", "⚪"),
    "na": ("暂未获取", "—"),
}


def _num(v: Any) -> Optional[float]:
    if v is None or v == "暂未获取":
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN → None
    except (TypeError, ValueError):
        return None


def _ma_series(closes: List[float]) -> List[Optional[float]]:
    """逐日滚动 MA850（O(n)）。不足 850 根的位置为 None。"""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < LOOKBACK:
        return out
    s = sum(closes[:LOOKBACK])
    out[LOOKBACK - 1] = s / LOOKBACK
    for i in range(LOOKBACK, n):
        s += closes[i] - closes[i - LOOKBACK]
        out[i] = s / LOOKBACK
    return out


def _compute_one(item: Dict[str, Any]) -> Dict[str, Any]:
    code = item.get("code")
    name = item.get("name") or code
    dates = item.get("dates") or []
    closes = [_num(x) for x in (item.get("closes") or [])]
    lows_raw = item.get("lows") or []
    lows = [_num(x) for x in lows_raw] if lows_raw else []

    base = {
        "code": code, "name": name, "state": "na", "state_text": STATE_TEXT["na"],
        "close": None, "low": None, "ma850": None, "dev": None, "low_dev": None,
        "last_close_below": None, "last_low_touch": None,
        "days_since_close_below": None, "days_since_low_touch": None,
        "days_below": 0,
        "src": item.get("src"), "error": item.get("error"),
    }
    if len(closes) < LOOKBACK or any(c is None for c in closes):
        base["error"] = base["error"] or f"样本不足（{len(closes)}/{LOOKBACK}）"
        return base

    ma_series = _ma_series(closes)
    ma = ma_series[-1]
    close = closes[-1]
    low = lows[-1] if len(lows) == len(closes) and lows[-1] is not None else None

    dev = close / ma - 1
    low_dev = (low / ma - 1) if low is not None else None
    if dev < 0:
        state = "below"
    elif low is not None and low <= ma:
        state = "touched"
    else:
        state = "above"

    # 历史最近触发：MA 序列逐日滚动，无未来函数
    last_below = last_touch = None
    for i in range(len(closes) - 1, LOOKBACK - 2, -1):
        m = ma_series[i]
        if m is None:
            continue
        if last_below is None and closes[i] < m:
            last_below = (i, dates[i] if i < len(dates) else None)
        if last_touch is None and i < len(lows) and lows[i] is not None and lows[i] <= m:
            last_touch = (i, dates[i] if i < len(dates) else None)
        if last_below is not None and last_touch is not None:
            break

    n = len(closes)
    # 连续在线下天数（从最新一根往回数，遇到线上即停）
    days_below = 0
    for i in range(n - 1, LOOKBACK - 2, -1):
        m = ma_series[i]
        if m is None or closes[i] >= m:
            break
        days_below += 1

    base.update({
        "state": state, "state_text": STATE_TEXT[state],
        "close": round(close, 2), "low": round(low, 2) if low is not None else None,
        "ma850": round(ma, 2),
        "dev": round(dev, 4),
        "low_dev": round(low_dev, 4) if low_dev is not None else None,
        "last_close_below": last_below[1] if last_below else None,
        "last_low_touch": last_touch[1] if last_touch else None,
        "days_since_close_below": (n - 1 - last_below[0]) if last_below else None,
        "days_since_low_touch": (n - 1 - last_touch[0]) if last_touch else None,
        "days_below": days_below,
    })
    return base


def compute(d: Dict[str, Any]) -> Dict[str, Any]:
    """输入四大指数日K → 850天线抄底坐标 dict（供 render_html / JSON 直接消费）。"""
    raw = {x.get("code"): x for x in (d.get("indices") or []) if x.get("code")}
    items = [_compute_one(raw.get(code) or {"code": code, "name": name,
                                            "error": "暂未获取"})
             for code, name in INDEXES]

    avail = [x for x in items if x["state"] != "na"]
    below_count = sum(1 for x in items if x["state"] == "below")
    touch_count = sum(1 for x in items if x["state"] == "touched")

    if len(avail) < 2:
        verdict = "na"
    elif below_count >= 4:
        verdict = "entered_full"
    elif below_count >= 2:
        verdict = "entered_major"
    elif below_count == 1:
        verdict = "entered_partial"
    elif touch_count > 0:
        verdict = "touched"
    else:
        verdict = "not_reached"

    # 最近（收盘偏离最小）的指数：主状态副标题用
    closest = min(avail, key=lambda x: x["dev"]) if avail else None
    # 右侧坐标锚点固定中证1000；缺失时退化为最近指数
    primary = next((x for x in items if x["code"] == PRIMARY_CODE and x["state"] != "na"),
                   closest)
    for x in items:
        x["is_primary"] = bool(primary and x["code"] == primary["code"])

    text, emoji = VERDICTS[verdict]
    return {
        "verdict": verdict,
        "verdict_text": text,
        "verdict_emoji": emoji,
        "below_count": below_count,
        "touch_count": touch_count,
        "available_count": len(avail),
        "closest_code": closest["code"] if closest else None,
        "closest_name": closest["name"] if closest else None,
        "closest_dev": closest["dev"] if closest else None,
        "primary": primary,
        "indices": items,
        "_data_date": str(d.get("_data_date") or "")[:10],
        "_src": d.get("_src"),
        "_source_view": "财经博主 plutus（2026-10）：各大指数跌至 850 天线为大资金抄底位",
    }


def _demo(entered=0, touched=0):
    """构造演示序列：前 849 根平盘 1000，最后一根按状态设收盘/最低。"""
    def series(close, low):
        closes = [1000.0] * (LOOKBACK - 1) + [float(close)]
        lows = [999.0] * (LOOKBACK - 1) + [float(low)]
        dates = [f"d{i:04d}" for i in range(LOOKBACK)]
        return {"dates": dates, "closes": closes, "lows": lows, "src": "demo"}

    specs = [
        ("sh000852", "中证1000", 1035.0, 1020.0),
        ("sh000300", "沪深300", 1040.0, 1025.0),
        ("sh000001", "上证指数", 1015.0, 1005.0),
        ("sz399006", "创业板指", 1050.0, 1030.0),
    ]
    out = []
    for i, (code, name, c, lo) in enumerate(specs):
        row = {"code": code, "name": name, **series(c, lo)}
        if i < entered:
            row.update(series(980.0, 960.0))
        elif i < entered + touched:
            row.update(series(1020.0, 970.0))
        out.append(row)
    return {"indices": out, "_data_date": "2026-10-23", "_src": "demo"}


def main():
    ap = __import__("argparse").ArgumentParser(description="850天线抄底坐标 纯计算（演示）")
    ap.add_argument("--json", default=None, help="直接传入输入 JSON 字符串")
    ap.add_argument("--demo-touched", action="store_true", help="2 个指数盘中跌破后收回")
    ap.add_argument("--demo-entered", action="store_true", help="3 个指数收盘跌破")
    ap.add_argument("--demo-none", action="store_true", help="全部在 850 线上方")
    args = ap.parse_args()
    if args.demo_touched:
        d = _demo(touched=2)
    elif args.demo_entered:
        d = _demo(entered=3)
    elif args.demo_none:
        d = _demo()
    elif args.json:
        d = json.loads(args.json)
    else:
        print("需 --demo-touched / --demo-entered / --demo-none / --json"); raise SystemExit(1)
    print(json.dumps(compute(d), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
