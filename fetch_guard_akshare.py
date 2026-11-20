#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家队护盘追踪 · 取数器（akshare + 新浪分时）
============================================================================

只负责「把原始数据取回来」，判定与文案全部在 guard_index.compute()（纯计算）。

四条数据链：
  1) ETF 分时（11 只）：新浪 5 分钟 1023 根（一次带 21 个交易日，同时得到
     「全天成交额 / 三段分布 / 收盘价 / 放量倍数」）；失败退腾讯 1 分钟（仅当日，
     放量倍数记 None）。
  2) 沪市份额：`fund_etf_scale_sse(date=)`，一次返回全市场 900+ 只；
     当日份额 T+1 才发布，取「最近已发布日」与其前一交易日算净申购。
  3) 深市份额：`fund_etf_scale_szse()` **无 date 参数**，只能取当前快照；
     数据日用「净值 ≈ 收盘价」反推（份额 T+1 发布，直接标今天会错一天）。
  4) 份额历史：output/guard_share_history.jsonl，每日追加一行（幂等）；
     首次运行（不足 20 行）自动回补最近 25 个交易日。

降级：任一条链失败只标「暂未获取」，绝不影响 XXFI / 冰点 / 底部区域 / 850。
"""
import datetime
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trade_calendar import is_trade_day

CST = datetime.timezone(datetime.timedelta(hours=8))
HIST = "guard_share_history.jsonl"
BACKFILL_BUDGET = 150          # 回补总时长上限（秒）；超时留待下次，绝不拖垮 CI

# 本机沙箱/CI 都可能带 HTTP(S)_PROXY，国内数据源必须直连
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

# (代码, 展示名, 分组, 市场)
PANEL = [
    ("sh510050", "上证50ETF", "上证50", "SSE"),
    ("sh510300", "300ETF·华泰", "沪深300", "SSE"),
    ("sz159919", "300ETF·嘉实", "沪深300", "SZSE"),
    ("sh510310", "300ETF·易方达", "沪深300", "SSE"),
    ("sh510330", "300ETF·华夏", "沪深300", "SSE"),
    ("sh510500", "中证500ETF", "中证500", "SSE"),
    ("sz159922", "500ETF·嘉实", "中证500", "SZSE"),
    ("sz159949", "创业板50ETF", "创业板", "SZSE"),
    ("sz159915", "创业板ETF", "创业板", "SZSE"),
    ("sh588000", "科创50ETF", "科创50", "SSE"),
    ("sh588080", "科创50·易方达", "科创50", "SSE"),
]
SSE_CODES = [c for c, _n, _g, m in PANEL if m == "SSE"]
SZ_CODES = [c for c, _n, _g, m in PANEL if m == "SZSE"]

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 交易所（上交所/深交所）在 GitHub Actions 美国 IP 被 ConnectionReset（2026-11-20 实测），
# 把跑批时间从 10s 拖到 9min。CI 侧一律跳过取数，只读本地推送的份额历史。
# 本地跑（能连通）时不要设这个变量，即可正常取数 + 回补。
SKIP_EXCHANGE = os.environ.get("GUARD_SKIP_EXCHANGE", "").strip() in ("1", "true", "yes")


def _bj_now():
    return datetime.datetime.now(CST)


def _nj_today():
    return _bj_now().strftime("%Y-%m-%d")


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://gu.qq.com/",
    })
    return _OPENER.open(req, timeout=timeout).read().decode("utf-8", "ignore")


# ----------------------------------------------------------------- 分时
def _bars_sina(code):
    """新浪 5 分钟：返回 [{t, c, a}]，按时间升序；bar 以结束时间标注"""
    raw = _get("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
               "?symbol=%s&scale=5&ma=no&datalen=1023" % code)
    out = [{"t": r["day"], "c": float(r["close"]), "a": float(r["amount"])}
           for r in json.loads(raw)]
    out.sort(key=lambda x: x["t"])
    return out


def _bars_tx(code):
    """腾讯 1 分钟（仅当日）：累计额差分成分钟额"""
    raw = _get("https://web.ifzq.gtimg.cn/appstock/app/day/query?code=%s&days=1" % code)
    day = json.loads(raw)["data"][code]["data"][-1]
    d = day["date"]
    bars, prev = [], 0.0
    for line in day["data"]:
        p = line.split(" ")
        if len(p) < 4:
            continue
        ca = float(p[3])
        bars.append({"t": "%s-%s-%s %s:%s:00" % (d[:4], d[4:6], d[6:], p[0][:2], p[0][2:]),
                     "c": float(p[1]), "a": max(0.0, ca - prev)})
        prev = ca
    return bars


def fetch_bars(code):
    for label, fn in (("sina5m", _bars_sina), ("tx1m", _bars_tx)):
        try:
            bars = fn(code)
            if bars:
                return bars, label
        except Exception as e:
            print(f"[warn] {code} {label} 失败: {e}")
    return [], None


def _hm(t):
    return t[11:16]


def summarize_day(bars, day):
    """单只 ETF 某日统计：三段成交额、尾盘占比、收盘、14:45 价、放量倍数"""
    today = sorted([b for b in bars if b["t"][:10] == day], key=lambda x: x["t"])
    if not today:
        return None
    am = md = tl = 0.0
    buckets = {}
    for b in today:
        t = _hm(b["t"])
        buckets[t] = buckets.get(t, 0.0) + b["a"]
        if t in ("14:50", "14:55", "15:00"):
            tl += b["a"]
        elif "09:30" <= t <= "11:30":
            am += b["a"]
        else:
            md += b["a"]
    tot = am + md + tl
    p1445 = next((b["c"] for b in today if _hm(b["t"]) == "14:45"), None)
    close = today[-1]["c"]
    ds = sorted({b["t"][:10] for b in bars})
    idx = ds.index(day)
    hist = [sum(b["a"] for b in bars if b["t"][:10] == d) for d in ds[max(0, idx - 10):idx]]
    med = sorted(hist)[len(hist) // 2] if hist else 0
    return {
        "amt_all_yi": round(tot / 1e8, 2), "amt_am_yi": round(am / 1e8, 2),
        "amt_md_yi": round(md / 1e8, 2), "amt_tail_yi": round(tl / 1e8, 2),
        "tail_pct": round((tl / tot * 100) if tot else 0.0, 1),
        "tail_ret": round(((close / p1445 - 1) * 100) if p1445 else 0.0, 2),
        "close": close,
        "mult": round(tot / med, 2) if med else None,
        "buckets": {k: round(v / 1e8, 3) for k, v in buckets.items()},
    }


# ----------------------------------------------------------------- 份额
def read_sse(date_str):
    """取「不晚于 date_str 的最近已发布日」的沪市份额：返回 (asof, {code: shares})

    CI 跑在境外，上交所域名可能不可达；最多回退 4 天，避免把 job 拖死。
    """
    import akshare as ak
    for off in range(0, 4):
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d") - datetime.timedelta(days=off)
        try:
            df = ak.fund_etf_scale_sse(date=d.strftime("%Y%m%d"))
            df["基金代码"] = df["基金代码"].astype(str)
            m = dict(zip(df["基金代码"], df["基金份额"]))
            # 面板里是 sh510050 这类带前缀代码，交易所接口返回 "510050"
            hit = {c: float(m[c[2:]]) for c in SSE_CODES
                   if c[2:] in m and m[c[2:]] == m[c[2:]]}
            if len(hit) >= 4:
                return str(df["统计日期"].iloc[0])[:10], hit
        except Exception:
            continue
    return None, {}


def read_szse():
    import akshare as ak
    try:
        df = ak.fund_etf_scale_szse()
        df["基金代码"] = df["基金代码"].astype(str)
        shares, navs = {}, {}
        for c in SZ_CODES:
            r = df[df["基金代码"] == c[2:]]   # 交易所返回 "159919"，面板里是 "sz159919"
            if len(r) == 0:
                continue
            shares[c] = float(r.iloc[0]["基金份额"])
            try:
                navs[c] = float(r.iloc[0]["净值"])
            except Exception:
                pass
        return shares, navs
    except Exception as e:
        print(f"[warn] 深市份额取数失败: {e}")
        return {}, {}


def szse_asof(navs, closes_by_code, fallback):
    """净值反推数据日：取「收盘价最接近净值」的交易日"""
    votes = {}
    for c, nav in navs.items():
        if not nav or nav != nav:
            continue
        for d, px in (closes_by_code.get(c) or {}).items():
            if px and abs(px / nav - 1) <= 0.006:
                votes[d] = votes.get(d, 0) + 1
    if not votes:
        return fallback, False
    return max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0], True


# ----------------------------------------------------------------- 历史
def load_hist(out_dir):
    p = os.path.join(out_dir, HIST)
    rows = []
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except Exception as e:
            print(f"[warn] 份额历史读取失败: {e}")
    return rows


def save_hist(out_dir, rows):
    p = os.path.join(out_dir, HIST)
    os.makedirs(out_dir, exist_ok=True)
    uniq = {r["date"]: r for r in rows}
    with open(p, "w", encoding="utf-8") as f:
        for d in sorted(uniq):
            f.write(json.dumps(uniq[d], ensure_ascii=False) + "\n")
    return p


def calc_net(cur, prev, closes):
    """净申购金额（亿元）：Δ份额 × 当日收盘价"""
    net, detail = 0.0, {}
    for c in SSE_CODES:
        if c not in cur or c not in prev:
            continue
        dsh = cur[c] - prev[c]
        px = closes.get(c)
        amt = (dsh * px / 1e8) if px else 0.0
        net += amt
        detail[c] = {"dsh_yi": round(dsh / 1e8, 4), "amt_yi": round(amt, 2)}
    return round(net, 2), detail


def backfill_hist(out_dir, rows, today, closes_by_code=None, need=20, span=22):
    """历史不足 need 行时，用沪市份额接口回补最近 span 个交易日"""
    if len(rows) >= need:
        return rows
    print("[info] 份额历史不足 %d 行，回补最近 %d 个交易日 ..." % (need, span))
    try:
        from ak_compat import calendar_trade_date_hist
        cal = [str(x)[:10] for x in calendar_trade_date_hist().iloc[:, 0].tolist()
               if str(x)[:10] <= today]
    except Exception as e:
        print(f"[warn] 交易日历失败，跳过回补: {e}")
        return rows
    snaps = {}
    closes = closes_by_code or {}
    deadline = time.time() + BACKFILL_BUDGET
    for d in cal[-span:]:
        if time.time() > deadline:
            print("[warn] 回补超时（%ds），已取 %d 天，剩余留待下次运行补齐" % (BACKFILL_BUDGET, len(snaps)))
            break
        asof, hit = read_sse(d)
        if asof and hit:
            snaps[asof] = hit
    ds = sorted(snaps)
    if len(ds) < 2:
        return rows
    if not closes:
        for c in SSE_CODES:
            try:
                bars = _bars_sina(c)
                closes[c] = {b["t"][:10]: b["c"] for b in bars}
            except Exception:
                closes[c] = {}
    have = {r["date"] for r in rows}
    for a, b in zip(ds, ds[1:]):
        if b in have:
            continue
        px = {c: (closes.get(c) or {}).get(b) for c in SSE_CODES}
        if sum(1 for v in px.values() if v) < 4:
            continue          # 该日没有收盘价（分时只回溯 21 个交易日），不写 0 值
        net, detail = calc_net(snaps[b], snaps[a], px)
        rows.append({"date": b, "net_yi": net, "detail": detail, "src": "backfill"})
    print("[info] 回补完成，历史 %d 行" % len(rows))
    return rows


# ----------------------------------------------------------------- 主入口
def build_guard_inputs(out_dir="output"):
    today = _nj_today()
    trade = is_trade_day(today)

    # 1) 分时（每只只取一次，缓存复用）
    cache, srcs = {}, set()
    for code, _l, _g, _m in PANEL:
        bars, src = fetch_bars(code)
        cache[code] = bars
        if src:
            srcs.add(src)
    days = {}
    for code, bars in cache.items():
        if bars:
            d = bars[-1]["t"][:10]
            days[d] = days.get(d, 0) + 1
    data_date = max(days.items(), key=lambda kv: (kv[1], kv[0]))[0] if days else today

    etfs, closes_by_code, closes_today = [], {}, {}
    for code, label, group, _m in PANEL:
        bars = cache.get(code) or []
        st = summarize_day(bars, data_date) if bars else None
        closes_by_code[code] = {b["t"][:10]: b["c"] for b in bars}
        if not st:
            etfs.append({"code": code, "label": label, "group": group, "error": "分时暂未获取"})
            continue
        closes_today[code] = st["close"]
        st.update({"code": code, "label": label, "group": group})
        etfs.append(st)

    # 2) 沪市份额：最近已发布日 vs 前一交易日
    # 写入闸门（README §门控 第二道防线）：非交易日 / 盘中一律不落库，只读不写
    now = _bj_now()
    can_write = trade and now.hour >= 15

    # 交易所连通性：CI（美国 IP）实测被 ConnectionReset，单次探针失败即整条链放弃，
    # 否则逐日重试会把 10s 的步骤拖成 9min；失败时 ② 段回落到本地已推送的份额历史。
    exchange_ok = not SKIP_EXCHANGE
    probe_asof, probe_hit = (None, {})
    if exchange_ok:
        probe_asof, probe_hit = read_sse(today)
        exchange_ok = bool(probe_asof and probe_hit)
        if not exchange_ok:
            print("[warn] 交易所份额接口不可达，改用本地已推送的份额历史")

    hist = load_hist(out_dir)
    if can_write and exchange_ok:
        hist = backfill_hist(out_dir, hist, today, closes_by_code)
    asof, cur = (probe_asof, probe_hit) if exchange_ok else (None, {})
    net, detail, prev_date, prev = 0.0, {}, None, {}
    if asof and cur:
        prev_date, prev = read_sse(
            (datetime.datetime.strptime(asof, "%Y-%m-%d") - datetime.timedelta(days=1)).strftime("%Y-%m-%d"))
        px_asof = {c: (closes_by_code.get(c) or {}).get(asof) or closes_today.get(c) for c in SSE_CODES}
        net, detail = calc_net(cur, prev, px_asof)
        uniq = {r["date"]: r for r in hist}
        old = uniq.get(asof)
        if can_write and (not old or old.get("src") != "daily"):
            uniq[asof] = {"date": asof, "net_yi": net, "detail": detail, "src": "daily"}
            hist = list(uniq.values())
            save_hist(out_dir, hist)
        elif not can_write:
            print("[info] 非交易日或未收盘，份额历史只读不写")
        net = uniq[asof]["net_yi"]
        detail = uniq[asof].get("detail", detail)

    # 3) 深市快照（只落盘，不参与净申购：无历史无法算 Δ）
    sz_shares, sz_navs = read_szse() if exchange_ok else ({}, {})
    sz_asof, inferred = (None, False)
    if sz_shares and can_write:
        sz_asof, inferred = szse_asof(sz_navs, closes_by_code, fallback=today)
        p = os.path.join(out_dir, "guard_szse_snapshot.json")
        snap = {}
        if os.path.exists(p):
            try:
                snap = json.load(open(p, encoding="utf-8"))
            except Exception:
                snap = {}
        snap[sz_asof or today] = {"shares": sz_shares, "nav": sz_navs, "snap_at": today}
        os.makedirs(out_dir, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)

    share_src = "live" if (asof and cur) else "history"
    if share_src == "history" and hist:
        last = sorted(hist, key=lambda r: r["date"])[-1]
        asof = last["date"]
        net = last.get("net_yi", 0.0)
        detail = last.get("detail", {}) or {}

    return {
        "date": data_date,
        "today": today,
        "is_trade_day": trade,
        "etfs": etfs,
        "share": {
            "date": asof,
            "prev_date": prev_date,
            "net_yi": net,
            "detail": detail,
            "history": sorted(hist, key=lambda r: r["date"])[-20:],
            "src": share_src,
        },
        "szse": {"asof": sz_asof, "asof_inferred": inferred,
                 "n_codes": len(sz_shares), "n_hist_days": len(hist)},
        "_src": " / ".join(sorted(srcs)) + (" / sse" if share_src == "live" else " / sse(history)") + (" / szse" if sz_shares else ""),
        "_generated_at": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    print(json.dumps(build_guard_inputs(), ensure_ascii=False, indent=2, default=str)[:3000])
