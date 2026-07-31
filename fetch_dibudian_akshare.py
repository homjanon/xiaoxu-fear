#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部区域判断 · 取数器（akshare · 腾讯 daily_tx 全程同源）
================================================

取数目标：全市场沪深成交额（用户指定口径 A 的同源实现）
  - 当日 + 近90日历史 **统一用腾讯 stock_zh_index_daily_tx**（上证 sh000001 + 深证成指 sz399001）

为什么不用新浪 spot 做当日、新浪 daily 做历史：
  - 实测发现新浪 spot 的"上证指数成交额"（约1.19万亿）与腾讯 daily_tx 同日的 amount×1000
    （约0.60万亿）口径不同（spot 偏沪市全量、daily_tx 是指数成分股），混用会让比值失真；
  - 且新浪 stock_zh_index_daily **不含成交额(amount)列**，历史根本取不到。
  → 故当日与历史 **全程走腾讯 daily_tx（同一口径：两核心指数成分股成交额之和）**，
    比值才有意义。腾讯源为 HTTP/1.1 直连、无需补丁，GitHub Actions 美 IP 已验证稳定
    （冰点 D4 即用同款 stock_zh_index_daily_tx 取上证成交额建基准）。

单位：腾讯 daily_tx 的 amount 字段为「千元」，统一 ×1000 转「元」，与计算/展示一致。

健壮性：
  - 列名兼容多种写法（'amount'/'成交额'/'成交金额'、'date'/'日期'）
  - 单指数取数失败时该侧记 None；两侧皆无则整体返回暂未获取
"""
import datetime
import os

import akshare as ak
import pandas as pd

SH_CODE = "sh000001"   # 上证指数
SZ_CODE = "sz399001"   # 深证成指
LOOKBACK = 90          # 近90个交易日


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


def fetch_daily_tx_total():
    """全市场沪深成交额（口径：两核心指数成分股成交额之和，腾讯 daily_tx 源）。

    返回 dict（字段 today_total/sh_today/sz_today/max90_total/_src/_data_date）：
      - 当日 total     = daily_tx 最新 bar（上证 amount + 深证 amount）×1000（元）
      - 近90日最高     = 两指数按交易日对齐求和后，最近 90 根 bar 的最大值（元）
      - _data_date     = daily_tx 最新 bar 的实际交易日（非本地当前日，避免盘前/盘中滞后错位）
    当日若恰为近90日最高，ratio=1.0（>0.5）自然非底部区域日，逻辑自洽。
    """
    out = {
        "today_total": None, "sh_today": None, "sz_today": None,
        "max90_total": None, "_src": "暂未获取", "_data_date": None,
    }
    try:
        sh = ak.stock_zh_index_daily_tx(symbol=SH_CODE)
        sz = ak.stock_zh_index_daily_tx(symbol=SZ_CODE)
    except Exception as e:
        print(f"[warn] 腾讯 index daily_tx 失败: {e}")
        return out

    for name, d in (("sh", sh), ("sz", sz)):
        dc = _col(d, "date", "日期")
        ac = _col(d, "amount", "成交额", "成交金额")
        if dc is None or ac is None:
            print(f"[warn] daily_tx({name}) 列名异常: {list(d.columns)}")
            return out
        d["_d"] = d[dc].astype(str).str[:10]
        d["_amt"] = pd.to_numeric(d[ac], errors="coerce") * 1000.0  # 千元 → 元

    if sh.empty or sz.empty:
        print("[warn] daily_tx 返回空表")
        return out

    # 当日：两指数各自最新 bar（按日期排序后取末根）
    sh_last = sh.sort_values("_d").iloc[-1]
    sz_last = sz.sort_values("_d").iloc[-1]
    sh_amt = float(sh_last["_amt"])
    sz_amt = float(sz_last["_amt"])
    today_total = sh_amt + sz_amt
    today_date = str(sh_last["_d"])[:10]

    # 历史：按交易日对齐求和，取近 LOOKBACK 日最大值
    m = pd.merge(
        sh[["_d", "_amt"]].rename(columns={"_amt": "sh_amt"}),
        sz[["_d", "_amt"]].rename(columns={"_amt": "sz_amt"}),
        on="_d", how="inner",
    ).dropna(subset=["sh_amt", "sz_amt"])
    if m.empty:
        print("[warn] daily_tx 两指数无交集交易日")
        out.update({"today_total": today_total, "sh_today": sh_amt, "sz_today": sz_amt,
                    "_src": f"tencent_daily_tx({today_date})", "_data_date": today_date})
        return out
    m["total"] = m["sh_amt"] + m["sz_amt"]
    m = m.sort_values("_d").reset_index(drop=True)
    max90 = float(m.tail(LOOKBACK)["total"].max())
    out.update({
        "today_total": today_total, "sh_today": sh_amt, "sz_today": sz_amt,
        "max90_total": max90, "_src": f"tencent_daily_tx({today_date})", "_data_date": today_date,
    })
    return out


def build_dibudian_inputs():
    """产出 dibudian_index.compute() 所需的输入 dict。

    字段：today_total / sh_today / sz_today / max90_total / _data_date / _src
    _data_date 取 daily_tx 最新 bar 实际交易日；取数失败兜底为本地当前日。
    """
    f = fetch_daily_tx_total()
    if not f.get("_data_date"):
        f["_data_date"] = _bj_today()
    return f


if __name__ == "__main__":
    import json
    inp = build_dibudian_inputs()
    print(json.dumps(inp, ensure_ascii=False, indent=2, default=str))
