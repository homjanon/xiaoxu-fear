#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部区域判断 · 取数器（akshare · 全市场口径）
============================================================================

取数目标：全市场沪深成交额（用户指定口径：全市场，非指数成分股）
  当日 + 近90日历史峰值，统一用「全市场口径」：
    上证指数( sh000001 ) + 深证成指( sz399001 ) 的全市场成交额之和。

为什么是「全市场口径」：
  - 腾讯 stock_zh_index_daily_tx 的 amount 是**指数成分股成交额（约半量）**：
    2026-07-31 上证5975亿+深证7194亿=1.317万亿，而全市场应为 ≈2.5万亿
    （新浪 spot 验证：上证1.1877万亿+深证1.3543万亿=2.542万亿）。
  - 半量口径会让卡片显示的绝对值与用户查到的对不上，故废弃。
  - 新浪历史日线 stock_zh_index_daily **不含成交额列**，故历史无法走新浪。

取数链路（健壮性优先，逐级兜底）：
  主源：东财 stock_zh_index_daily_em（push2his 直连）
        → 当日=最新 bar（上证+深证 amount，元），近90日峰值=tail(90) 最大值。
        → 东财 daily_em 的 amount 为「元」（腾讯才是「千元」），**不再 ×1000**。
  兜底：若 daily_em 在 CI 不可达（历史 kline 端点偶发受限）：
        当日改走东财指数 spot（stock_zh_index_spot_em，全市场口径·元，已验证 CI 可达）；
        近90日峰值改走本地滚动缓存 output/_turnover_cache.json
          （冷启动时用腾讯 daily_tx 半量历史 × 校正因子回填为全市场口径）。
  交叉校验：同时拉新浪 spot 当日全市场成交额写入报告（不参与判定），
        首次 CI 跑完核对 em_today 是否 ≈ 新浪 spot（≈2.5万亿）→ 验证口径正确。

东财连通说明：
  - 实时端点 push2.eastmoney.com 已迁移，注入正则补丁改写为 push2delay（HTTP/1.1 可通，
    与冰点 fetch_bingdian_akshare 同思路，GitHub Actions 云端已验证可达）。
  - **历史端点 push2his.eastmoney.com 不改写**（直连），因为 push2delay 仅代理实时、
    不代理历史 kline；改写反而会让 daily_em 返回空表。
"""
import datetime
import json
import os
import re

import akshare as ak
import pandas as pd

SH_CODE = "sh000001"   # 上证指数（全上海市场）
SZ_CODE = "sz399001"   # 深证成指（全深圳市场代理）
LOOKBACK = 90          # 近90个交易日

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output", "_turnover_cache.json"
)


# ---------------- 东财连通补丁（仅改写实时 push2 → push2delay；历史 push2his 直连） ----------------
def _patch_eastmoney_push2delay():
    try:
        import requests
        if getattr(requests.Session.request, "_bd_patched", False):
            return
        _orig = requests.Session.request
        # 只改写实时行情端点 push2.（如 48.push2. / push2.）；历史 kline 端点 push2his. 保持直连
        _HOST_RE = re.compile(r'(?<!\w)push2\.eastmoney\.com')

        def _w(self, method, url, *a, **k):
            if isinstance(url, str):
                url = _HOST_RE.sub('push2delay.eastmoney.com', url)
            k.setdefault("timeout", 15)
            return _orig(self, method, url, *a, **k)

        _w._bd_patched = True
        requests.Session.request = _w
    except Exception as e:
        print(f"[warn] 底部区域 push2delay 补丁注入失败（东财源将降级）: {e}")


_patch_eastmoney_push2delay()


def _bj_now():
    CST = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(CST)


def _bj_today():
    return _bj_now().strftime("%Y-%m-%d")


def _col(df: pd.DataFrame, *names):
    """按候选列名依次匹配，返回首个存在的列名；都不存在返回 None"""
    for n in names:
        if n in df.columns:
            return n
    return None


def _parse_amount(v):
    """把成交额字段解析为 float（元）。兼容纯数字串与带千分位的串。"""
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------------- 主源：东财 daily_em（push2his 直连） ----------------
def _fetch_em_daily():
    """东财 stock_zh_index_daily_em（当日 + 近90日最高全市场成交额，元）。

    返回 dict（today_total/sh_today/sz_today/max90_total/_src/_data_date）；
    任一关键量缺失则返回 None 字段（交由上层落 spot+缓存 兜底）。
    """
    out = {
        "today_total": None, "sh_today": None, "sz_today": None,
        "max90_total": None, "_src": "暂未获取", "_data_date": None,
    }
    try:
        sh = ak.stock_zh_index_daily_em(symbol=SH_CODE)
        sz = ak.stock_zh_index_daily_em(symbol=SZ_CODE)
    except Exception as e:
        print(f"[warn] 东财 daily_em 失败（落 spot+缓存兜底）: {e}")
        return out

    for name, d in (("sh", sh), ("sz", sz)):
        dc = _col(d, "date", "日期")
        ac = _col(d, "amount", "成交额", "成交金额")
        if dc is None or ac is None:
            print(f"[warn] daily_em({name}) 列名异常: {list(d.columns)}（落 spot+缓存兜底）")
            return out
        d["_d"] = d[dc].astype(str).str[:10]
        d["_amt"] = pd.to_numeric(d[ac], errors="coerce")   # 东财 amount 为「元」，不再 ×1000

    if sh.empty or sz.empty:
        print("[warn] daily_em 返回空表（落 spot+缓存兜底）")
        return out

    # 当日：两指数各自最新 bar
    sh_last = sh.sort_values("_d").iloc[-1]
    sz_last = sz.sort_values("_d").iloc[-1]
    sh_amt = _parse_amount(sh_last["_amt"])
    sz_amt = _parse_amount(sz_last["_amt"])
    if sh_amt is None or sz_amt is None:
        print("[warn] daily_em 当日成交额解析失败（落 spot+缓存兜底）")
        return out
    today_total = sh_amt + sz_amt
    data_date = str(sh_last["_d"])[:10]

    # 历史：按交易日对齐求和，取近 LOOKBACK 日最大值
    m = pd.merge(
        sh[["_d", "_amt"]].rename(columns={"_amt": "sh_amt"}),
        sz[["_d", "_amt"]].rename(columns={"_amt": "sz_amt"}),
        on="_d", how="inner",
    ).dropna(subset=["sh_amt", "sz_amt"])
    if m.empty:
        print("[warn] daily_em 两指数无交集交易日（落 spot+缓存兜底）")
        out.update({"today_total": today_total, "sh_today": sh_amt, "sz_today": sz_amt,
                    "_src": f"eastmoney_daily_em({data_date})", "_data_date": data_date})
        return out
    m["total"] = m["sh_amt"] + m["sz_amt"]
    m = m.sort_values("_d").reset_index(drop=True)
    max90 = float(m.tail(LOOKBACK)["total"].max())
    out.update({
        "today_total": today_total, "sh_today": sh_amt, "sz_today": sz_amt,
        "max90_total": max90, "_src": f"eastmoney_daily_em({data_date})", "_data_date": data_date,
    })
    return out


# ---------------- 兜底：东财指数 spot（当日全市场口径） ----------------
def _fetch_index_spot_turnover():
    """东财指数 spot（沪深重要指数）：上证指数 + 深证成指 成交额（全市场口径，元）。

    返回 (sh, sz, date)；缺失侧为 None（上层按 0 处理）。
    深证成指 若不在「沪深重要指数」列表内，则补拉「深证系列指数」获取。
    """
    date = _bj_today()
    try:
        idx = ak.stock_zh_index_spot_em(symbol="沪深重要指数")
        sh = idx[idx["名称"] == "上证指数"]
        sz = idx[idx["名称"] == "深证成指"]
        sh_v = float(sh["成交额"].values[0]) if len(sh) else None
        sz_v = float(sz["成交额"].values[0]) if len(sz) else None
        if sz_v is None:
            idx2 = ak.stock_zh_index_spot_em(symbol="深证系列指数")
            sz2 = idx2[idx2["名称"] == "深证成指"]
            sz_v = float(sz2["成交额"].values[0]) if len(sz2) else None
        return sh_v, sz_v, date
    except Exception as e:
        print(f"[warn] EM 指数spot失败: {e}")
        return None, None, date


# ---------------- 滚动缓存（近90日峰值，跨日持久） ----------------
def _load_turnover_cache():
    try:
        if os.path.exists(CACHE_FILE):
            d = json.load(open(CACHE_FILE, encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _save_turnover_cache(cache: dict):
    try:
        d = os.path.dirname(CACHE_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        # 仅保留最近 120 个交易日，避免无限增长
        items = list(cache.items())
        if len(items) > 120:
            items = items[-120:]
        json.dump(dict(items), open(CACHE_FILE, "w", encoding="utf-8"))
    except Exception as e:
        print(f"[warn] 成交额缓存写入失败: {e}")


def _max90_from_cache(cache: dict):
    vals = [v for v in cache.values() if isinstance(v, (int, float)) and v > 0]
    if not vals:
        return None
    return max(vals[-LOOKBACK:]) if len(vals) >= LOOKBACK else max(vals)


def _backfill_from_tx(today_full):
    """冷启动：腾讯 daily_tx（半量口径）回填近 LOOKBACK 日历史，
    并用「今日全量 / 今日半量」校正因子换算为全市场口径，与当日口径一致。
    返回 {date: total_full}；失败返回 {}。
    """
    try:
        sh = ak.stock_zh_index_daily_tx(symbol=SH_CODE)
        sz = ak.stock_zh_index_daily_tx(symbol=SZ_CODE)
        for d in (sh, sz):
            dc = _col(d, "date", "日期")
            d["_d"] = d[dc].astype(str).str[:10]
            d["_amt"] = pd.to_numeric(d[_col(d, "amount", "成交额")], errors="coerce") * 1000.0  # 千元→元（半量）
        m = pd.merge(
            sh[["_d", "_amt"]].rename(columns={"_amt": "sh"}),
            sz[["_d", "_amt"]].rename(columns={"_amt": "sz"}),
            on="_d", how="inner",
        ).dropna(subset=["sh", "sz"])
        if m.empty:
            return {}
        m["total_half"] = m["sh"] + m["sz"]
        m = m.sort_values("_d").reset_index(drop=True)
        today_half = float(m.iloc[-1]["total_half"])
        factor = (today_full / today_half) if today_half else 2.0
        recent = m.tail(LOOKBACK)
        return {str(r["_d"])[:10]: float(r["total_half"]) * factor for _, r in recent.iterrows()}
    except Exception as e:
        print(f"[warn] 腾讯历史回填失败（90日峰值将仅含缓存样本）: {e}")
        return {}


def fetch_em_total():
    """产出底部区域判断所需的全市场成交额输入（当日 + 近90日最高）。

    链路：主源 daily_em 成功 → 直接返回（今日+90峰值，全市场口径）；
          失败 → 东财指数 spot 取当日 + 滚动缓存取90峰值（冷启动用腾讯回填）；
          全失败 → 暂未获取（卡片显示「暂未获取」，不影响 XXFI）。
    """
    d = _fetch_em_daily()
    if d["today_total"] is not None and d["max90_total"] is not None:
        return d

    # 兜底：spot 当日 + 缓存 90峰值
    sh, sz, date = _fetch_index_spot_turnover()
    if sh is None and sz is None:
        return {"today_total": None, "sh_today": None, "sz_today": None,
                "max90_total": None, "_src": "暂未获取", "_data_date": date}
    today = (sh or 0) + (sz or 0)
    cache = _load_turnover_cache()
    if not cache:
        cache = _backfill_from_tx(today)
    cache[date] = today
    _save_turnover_cache(cache)
    max90 = _max90_from_cache(cache)
    return {
        "today_total": today, "sh_today": sh, "sz_today": sz,
        "max90_total": max90, "_src": f"em_spot+cache({date})", "_data_date": date,
    }


# ---------------- 交叉校验：新浪实时 spot（全市场口径，不参与判定） ----------------
def fetch_sina_spot_total():
    """新浪实时 spot 全市场成交额（交叉校验用，不参与判定）。

    返回 dict（sina_spot_today / sina_spot_date / _sina_src），失败返回 None 值。
    新浪 spot 的「成交额」为全市场口径（2026-07-31 实测 上证1.1877万亿+深证1.3543万亿=2.542万亿），
    用作东财口径的对照基准。
    """
    out = {"sina_spot_today": None, "sina_spot_date": None, "_sina_src": "暂未获取"}
    try:
        spot = ak.stock_zh_index_spot_sina()
    except Exception as e:
        print(f"[warn] 新浪 spot 失败（仅影响交叉校验）: {e}")
        return out
    try:
        sh = spot[spot["代码"] == SH_CODE]
        sz = spot[spot["代码"] == SZ_CODE]
        sh_v = _parse_amount(sh.iloc[0]["成交额"]) if len(sh) else None
        sz_v = _parse_amount(sz.iloc[0]["成交额"]) if len(sz) else None
        if sh_v is not None and sz_v is not None:
            d = _bj_today()
            out.update({
                "sina_spot_today": sh_v + sz_v,
                "sina_spot_date": d,
                "_sina_src": f"sina_spot({d})",
            })
    except Exception as e:
        print(f"[warn] 新浪 spot 解析失败: {e}")
    return out


def build_dibudian_inputs():
    """产出 dibudian_index.compute() 所需的输入 dict。

    字段：today_total / sh_today / sz_today / max90_total / _data_date / _src
          + sina_spot_today / sina_spot_date / _sina_src（交叉校验，不参与判定）
    _data_date 取东财源实际数据日期；取数失败兜底为本地当前日。
    """
    f = fetch_em_total()
    f.update(fetch_sina_spot_total())
    if not f.get("_data_date"):
        f["_data_date"] = _bj_today()
    return f


if __name__ == "__main__":
    import json as _json
    inp = build_dibudian_inputs()
    print(_json.dumps(inp, ensure_ascii=False, indent=2, default=str))
