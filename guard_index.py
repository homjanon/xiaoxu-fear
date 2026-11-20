#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家队护盘追踪 · 纯计算（零网络）
============================================================================

输入：fetch_guard_akshare.build_guard_inputs() 的返回值
输出：guard_report.json（render_html.render_guard_card 消费）

判定只看两件可验证的事，不做加权总分：
  A. 行为（当日）：有没有 ≥2 只宽基 ETF 在**尾盘 14:45–15:00** 出现「占比 ≥50% 且金额 ≥20 亿」
  B. 事实（T-1）：份额日变化 × 均价 = 净申购（唯一能区分「真买」与「对倒」的口径）

三档结论：疑似买入·尾盘扫货 / 疑似买入·单只异动 / 未发现护盘
不做 0–100 总分——权重没有样本外验证，硬给分会让结论看起来比实际更确定。
"""
import os

TAIL_MIN_PCT = 50.0
TAIL_MIN_YI = 20.0
STRONG_N = 2
TOP_N = 4


def _fmt_hm(hm):
    """bar 结束时间 → 区间文本（bar 以结束时间标注）"""
    h, m = int(hm[:2]), int(hm[3:])
    tot = h * 60 + m - 5
    return "%02d:%02d–%s" % (tot // 60, tot % 60, hm)


def _rows(etfs):
    ok = [e for e in etfs if not e.get("error") and e.get("amt_all_yi")]
    ok.sort(key=lambda e: -e.get("amt_tail_yi", 0))
    return ok


def _verdict(rows):
    if not rows:
        return "na", "暂未获取", "今日分时未取到，无法判断", []
    hits = [r for r in rows if r["tail_pct"] >= TAIL_MIN_PCT and r["amt_tail_yi"] >= TAIL_MIN_YI]
    if len(hits) >= STRONG_N:
        kind = "buy"
        text = "疑似买入 · 尾盘扫货"
    elif len(hits) == 1:
        kind = "weak"
        text = "疑似买入 · 单只异动"
    else:
        kind, text = "none", "未发现护盘"
    sub = ""
    if hits:
        avg_ret = sum(h.get("tail_ret", 0) for h in hits) / len(hits)
        names = "、".join(h["label"] for h in hits[:2])
        if avg_ret >= 0.2:
            sub = "%d 只宽基 ETF 尾盘放巨量，%s 尾盘被拉起 %+.2f%%" % (len(hits), names, avg_ret)
        elif avg_ret <= -0.2:
            sub = "%d 只尾盘放巨量（%s），但价格没拉起来 %+.2f%%" % (len(hits), names, avg_ret)
        else:
            sub = "%d 只尾盘放巨量（%s），价格基本持平" % (len(hits), names)
    elif rows:
        top = rows[0]
        sub = "最大的一笔是 %s：尾盘 %d%%，未达「占比≥50%% 且 ≥20 亿」" % (
            top["label"], round(top["tail_pct"]))
    else:
        sub = "今日分时未取到，无法判断"
    return kind, text, sub, hits


def _peak(rows, tail_only=False):
    """最集中的 5 分钟：tail_only=True 时只在 14:45–15:00 内找"""
    agg = {}
    for r in rows:
        for k, v in (r.get("buckets") or {}).items():
            if tail_only and k not in ("14:50", "14:55", "15:00"):
                continue
            agg[k] = agg.get(k, 0.0) + v
    if not agg:
        return None, 0.0
    k = max(agg.items(), key=lambda kv: kv[1])
    return _fmt_hm(k[0]), k[1]


def _share_block(share):
    hist = share.get("history") or []
    detail = share.get("detail") or {}
    pos = sum(1 for v in detail.values() if v.get("amt_yi", 0) > 0)
    cnt = len(detail)
    days_pos = 0
    for r in reversed(hist):
        if r.get("net_yi", 0) > 50:
            days_pos += 1
        else:
            break
    d5 = sum(r.get("net_yi", 0) for r in hist[-5:])
    return {
        "date": share.get("date"),
        "net_yi": share.get("net_yi", 0.0),
        "pos_cnt": pos,
        "basket_cnt": cnt,
        "days_pos": days_pos,
        "d5_yi": round(d5, 1),
        "series": [{"date": r["date"], "net_yi": r.get("net_yi", 0)} for r in hist],
        "src": share.get("src") or "live",
    }


def compute(inp):
    etfs = inp.get("etfs") or []
    rows = _rows(etfs)
    kind, text, sub, hits = _verdict(rows)
    if kind in ("buy", "weak"):
        peak_win, peak_yi = _peak(rows, tail_only=True)
        peak_scope = "tail"
    else:
        peak_win, peak_yi = _peak(rows, tail_only=False)
        peak_scope = "day"

    top = rows[:TOP_N]
    total_tail = sum(r.get("amt_tail_yi", 0) for r in rows)
    rest_n = max(0, len(rows) - len(top))
    rest_tail = round(total_tail - sum(r.get("amt_tail_yi", 0) for r in top), 1)

    out_rows = []
    for r in top:
        tot = r.get("amt_all_yi") or 0
        out_rows.append({
            "code": r["code"], "label": r["label"], "group": r["group"],
            "tail_yi": round(r.get("amt_tail_yi", 0), 1),
            "tail_pct": round(r.get("tail_pct", 0), 1),
            "am_pct": round((r.get("amt_am_yi", 0) / tot * 100) if tot else 0, 2),
            "md_pct": round((r.get("amt_md_yi", 0) / tot * 100) if tot else 0, 2),
            "all_yi": round(tot, 1),
            "tail_ret": round(r.get("tail_ret", 0), 2),
            "mult": r.get("mult"),
            "hit": (r.get("tail_pct", 0) >= TAIL_MIN_PCT and r.get("amt_tail_yi", 0) >= TAIL_MIN_YI),
        })

    share = _share_block(inp.get("share") or {})
    missing = [e["label"] for e in etfs if e.get("error")]

    rep = {
        "_data_date": inp.get("date"),
        "_generated_at": inp.get("_generated_at"),
        "_src": inp.get("_src"),
        "_note": "旁挂参考卡，不参与 XXFI 计算；结论为形态推断，不是身份认定",
        "verdict": kind,
        "verdict_text": text,
        "verdict_sub": sub,
        "window": "14:45–15:00",
        "peak_window": peak_win or "—",
        "peak_amt_yi": round(peak_yi, 0),
        "peak_scope": peak_scope,
        "rows": out_rows,
        "rest_n": rest_n,
        "rest_tail_yi": rest_tail,
        "total_tail_yi": round(total_tail, 0),
        "n_etf": len(rows),
        "hit_n": len(hits),
        "share": share,
        "missing": missing,
    }
    return rep


# ------------------------------------------------------------------ demo
def _demo(kind="buy"):
    def etf(code, label, group, tail, pct, am=6.0, md=30.0, ret=0.4):
        tot = tail + am + md
        return {"code": code, "label": label, "group": group,
                "amt_all_yi": tot, "amt_am_yi": am, "amt_md_yi": md, "amt_tail_yi": tail,
                "tail_pct": tail / tot * 100, "tail_ret": ret, "close": 1.0, "mult": 3.0,
                "buckets": {"14:50": tail * 0.4, "14:55": tail * 0.45, "15:00": tail * 0.15,
                            "10:00": am * 0.5, "13:30": md * 0.5}}

    if kind == "buy":
        etfs = [etf("sz159919", "300ETF·嘉实", "沪深300", 220.9, 94.1),
                etf("sh510050", "上证50ETF", "上证50", 165.9, 68.2),
                etf("sh510300", "300ETF·华泰", "沪深300", 30.7, 16.9, am=20, md=130, ret=0.1),
                etf("sh510500", "中证500ETF", "中证500", 28.9, 24.9, am=12, md=74, ret=-0.5),
                etf("sh588080", "科创50·易方达", "科创50", 11.1, 19.9, am=9, md=35, ret=-0.9)]
        share = {"date": "2026-11-19", "prev_date": "2026-11-18", "net_yi": 360.7,
                 "detail": {"510050": {"amt_yi": 5.2}, "510300": {"amt_yi": 75.4},
                            "510310": {"amt_yi": 14.8}, "510330": {"amt_yi": 96.7},
                            "510500": {"amt_yi": 78.6}, "588000": {"amt_yi": -10.1},
                            "588080": {"amt_yi": 100.2}},
                 "history": [{"date": "2026-11-%02d" % (5 + i), "net_yi": v} for i, v in enumerate(
                     [35.1, 17.2, 3.2, -14.6, -14.8, -108.8, -49.9, 139.6, 123.9, 93.9, 360.7])]}
    elif kind == "weak":
        etfs = [etf("sh510050", "上证50ETF", "上证50", 40.0, 55.0, am=10, md=22, ret=0.3),
                etf("sh510300", "300ETF·华泰", "沪深300", 15.0, 15.0, am=30, md=55, ret=-0.2)]
        share = {"date": "2026-11-19", "net_yi": 8.0, "detail": {"510050": {"amt_yi": 8.0}},
                 "history": [{"date": "2026-11-19", "net_yi": 8.0}]}
    else:
        etfs = [etf("sh510300", "300ETF·华泰", "沪深300", 8.0, 9.0, am=40, md=42, ret=-0.3),
                etf("sh510500", "中证500ETF", "中证500", 3.0, 8.0, am=20, md=14, ret=-0.6)]
        share = {"date": "2026-11-19", "net_yi": -60.0, "detail": {"510050": {"amt_yi": -30.0}},
                 "history": [{"date": "2026-11-19", "net_yi": -60.0}]}
    return {
        "date": "2026-11-20", "today": "2026-11-20", "is_trade_day": True,
        "etfs": etfs, "share": share,
        "szse": {"asof": "2026-11-19", "asof_inferred": True, "n_codes": 4, "n_hist_days": 11},
        "_src": "demo", "_generated_at": "demo",
    }


def _demo_degraded():
    return {"date": "2026-11-20", "today": "2026-11-20", "is_trade_day": True,
            "etfs": [{"code": "sh510050", "label": "上证50ETF", "group": "上证50",
                      "error": "分时暂未获取"}],
            "share": {"date": None, "net_yi": 0.0, "detail": {}, "history": []},
            "szse": {}, "_src": "", "_generated_at": "demo"}


if __name__ == "__main__":
    import json
    import sys
    kind = sys.argv[1] if len(sys.argv) > 1 else "buy"
    inp = _demo_degraded() if kind == "degraded" else _demo(kind)
    print(json.dumps(compute(inp), ensure_ascii=False, indent=2))
