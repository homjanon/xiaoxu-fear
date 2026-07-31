#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部区域判断 · 取数器（akshare · 东财 daily_em 全市场口径 + 新浪 spot 交叉校验）
============================================================================

取数目标：全市场沪深成交额（用户指定口径：全市场，非指数成分股）
  - 当日 + 近90日历史 **统一用东财 stock_zh_index_daily_em**（上证 sh000001 + 深证成指 sz399001）
  - 东财指数日线 amount = 全市场成交额口径（≈2.5万亿级），与用户查到的全市场对得上

为什么不用腾讯 daily_tx（旧方案，已废弃）：
  - 实测腾讯 daily_tx 的 amount 是**指数成分股成交额（约半量）**：2026-07-31 上证5975亿+深证7194亿=1.317万亿，
    而全市场应为 ≈2.5万亿（新浪 spot 验证：上证1.1877万亿+深证1.3543万亿=2.542万亿）。
  - 半量口径会让卡片显示的绝对值与用户查到的对不上。
  - 新浪历史日线 stock_zh_index_daily **不含成交额列**，故历史只能走东财（东财日线带 amount）。

口径校验（防再错）：同时拉新浪 spot 当日全市场成交额写入报告 inputs.sina_spot_today，
  首次 CI 跑完核对 em_today 是否 ≈ sina_spot_today（≈2.5万亿）：
  - 对上 → 东财口径正确，完工；
  - 若东财也只有 ≈1.3万亿（半量）→ 说明东财该接口也是成分股口径，则需改为深证综指(sz399106)或纯新浪滚动方案。

单位：东财 daily_em 的 amount 字段为「元」（腾讯才是「千元」），**不再 ×1000**。

东财连通：东财端点已迁移 push2*，本模块注入正则补丁（push2/push2his → push2delay，HTTP/1.1 可通），
  与冰点 fetch_bingdian_akshare 同思路，GitHub Actions 云端已验证可达。

健壮性：
  - 列名兼容多种写法（'amount'/'成交额'/'成交金额'、'date'/'日期'）
  - 单指数取数失败时该侧记 None；两侧皆无则整体返回暂未获取
  - 新浪 spot 仅作交叉校验，失败不影响主流程（主流程用东财）
"""
import datetime
import os
import re

import akshare as ak
import pandas as pd

SH_CODE = "sh000001"   # 上证指数（全上海市场）
SZ_CODE = "sz399001"   # 深证成指（全深圳市场代理）
LOOKBACK = 90          # 近90个交易日


# ---------------- 东财 push2delay 连通补丁（与 fetch_bingdian_akshare 同思路） ----------------
def _patch_eastmoney_push2delay():
    try:
        import requests
        if getattr(requests.Session.request, "_bd_patched", False):
            return
        _orig = requests.Session.request
        _HOST_RE = re.compile(r'push2(?:his)?\.eastmoney\.com')

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


def fetch_em_total():
    """全市场沪深成交额（口径：东财 stock_zh_index_daily_em，上证+深证成交额之和）。

    返回 dict（字段 today_total/sh_today/sz_today/max90_total/_src/_data_date）：
      - 当日 total     = daily_em 最新 bar（上证 amount + 深证 amount）（元，东财为元非千元）
      - 近90日最高     = 两指数按交易日对齐求和后，最近 90 根 bar 的最大值（元）
      - _data_date     = daily_em 最新 bar 的实际交易日（非本地当前日，避免盘前/盘中滞后错位）
    当日若恰为近90日最高，ratio=1.0（>0.5）自然非底部区域日，逻辑自洽。
    """
    out = {
        "today_total": None, "sh_today": None, "sz_today": None,
        "max90_total": None, "_src": "暂未获取", "_data_date": None,
    }
    try:
        sh = ak.stock_zh_index_daily_em(symbol=SH_CODE)
        sz = ak.stock_zh_index_daily_em(symbol=SZ_CODE)
    except Exception as e:
        print(f"[warn] 东财 index daily_em 失败: {e}")
        return out

    for name, d in (("sh", sh), ("sz", sz)):
        dc = _col(d, "date", "日期")
        ac = _col(d, "amount", "成交额", "成交金额")
        if dc is None or ac is None:
            print(f"[warn] daily_em({name}) 列名异常: {list(d.columns)}")
            return out
        d["_d"] = d[dc].astype(str).str[:10]
        d["_amt"] = pd.to_numeric(d[ac], errors="coerce")   # 东财 amount 为「元」，不再 ×1000

    if sh.empty or sz.empty:
        print("[warn] daily_em 返回空表")
        return out

    # 当日：两指数各自最新 bar（按日期排序后取末根）
    sh_last = sh.sort_values("_d").iloc[-1]
    sz_last = sz.sort_values("_d").iloc[-1]
    sh_amt = _parse_amount(sh_last["_amt"])
    sz_amt = _parse_amount(sz_last["_amt"])
    if sh_amt is None or sz_amt is None:
        print("[warn] daily_em 当日成交额解析失败")
        return out
    today_total = sh_amt + sz_amt
    today_date = str(sh_last["_d"])[:10]

    # 历史：按交易日对齐求和，取近 LOOKBACK 日最大值
    m = pd.merge(
        sh[["_d", "_amt"]].rename(columns={"_amt": "sh_amt"}),
        sz[["_d", "_amt"]].rename(columns={"_amt": "sz_amt"}),
        on="_d", how="inner",
    ).dropna(subset=["sh_amt", "sz_amt"])
    if m.empty:
        print("[warn] daily_em 两指数无交集交易日")
        out.update({"today_total": today_total, "sh_today": sh_amt, "sz_today": sz_amt,
                    "_src": f"eastmoney_daily_em({today_date})", "_data_date": today_date})
        return out
    m["total"] = m["sh_amt"] + m["sz_amt"]
    m = m.sort_values("_d").reset_index(drop=True)
    max90 = float(m.tail(LOOKBACK)["total"].max())
    out.update({
        "today_total": today_total, "sh_today": sh_amt, "sz_today": sz_amt,
        "max90_total": max90, "_src": f"eastmoney_daily_em({today_date})", "_data_date": today_date,
    })
    return out


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
    _data_date 取东财 daily_em 最新 bar 实际交易日；取数失败兜底为本地当前日。
    """
    f = fetch_em_total()
    f.update(fetch_sina_spot_total())
    if not f.get("_data_date"):
        f["_data_date"] = _bj_today()
    return f


if __name__ == "__main__":
    import json
    inp = build_dibudian_inputs()
    print(json.dumps(inp, ensure_ascii=False, indent=2, default=str))
