#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
850天线抄底坐标 · 取数器（akshare · 四大指数日K）
============================================================================

观点来源：财经博主 plutus（2026-10）——「各大指数往下跌，可以大资金抄底的位置是
850天线」，并举例中证1000 ≈ 6500。本取数器只负责把四大指数日K取回来，
MA850 与状态判定全部在 ma850_index.compute()（纯计算）。

源链（与项目现有指数源链一致）：
  指数日K：新浪 stock_zh_index_daily → 腾讯 stock_zh_index_daily_tx
          新浪本地 0.2~0.5s/指数；腾讯可兜底（收盘价偏差 < 0.0001%），但 9~24s/指数，
          故仅在某指数新浪失败时才启用，不让兜底拖慢每日任务。
  当日补点：新浪实时 spot stock_zh_index_spot_sina()（一次取齐四指数）
          日K末根滞后约 1 天（项目既有结论），收盘后补当日收盘/最低，
          使卡片 _data_date 落到当日；仅在「今天是交易日且日K末根早于今天」时补，
          非交易日/周末不补，避免把上一交易日收盘重复标成今天。

容错：
  单个指数双源均失败 → 该指数标「暂未获取」，其余指数照常计算；
  四个指数全部失败 → 卡片整体「暂未获取」。绝不影响 XXFI / 冰点 / 底部区域。
"""
import datetime
import os
import sys

import akshare as ak

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ma850_index import INDEXES, LOOKBACK
from trade_calendar import is_trade_day

CST = datetime.timezone(datetime.timedelta(hours=8))


def _bj_now():
    return datetime.datetime.now(CST)


def _bj_today():
    return _bj_now().strftime("%Y-%m-%d")


def _last_date(dates):
    return dates[-1] if dates else None


def _fetch_spot_map():
    """新浪实时 spot：{code: (close, low)}。失败返回 {}（不阻塞日K）。"""
    try:
        sp = ak.stock_zh_index_spot_sina()
        out = {}
        for code, _name in INDEXES:
            row = sp[sp["代码"] == code]
            if len(row) == 0:
                continue
            close = float(row.iloc[0]["最新价"])
            try:
                low = float(row.iloc[0]["最低"])
            except (KeyError, TypeError, ValueError):
                low = None
            if close and close == close:
                out[code] = (close, low if (low and low == low) else None)
        return out
    except Exception as e:
        print(f"[warn] 新浪指数 spot 失败（不补当日，仅用日K）: {e}")
        return {}


def _fetch_daily(code):
    """单指数日K：新浪 → 腾讯。返回 (row, src_label) 或 (None, last_error)。"""
    sources = [
        ("sina", lambda: ak.stock_zh_index_daily(symbol=code)),
        ("tx", lambda: ak.stock_zh_index_daily_tx(symbol=code)),
    ]
    last_err = None
    for label, fn in sources:
        try:
            df = fn()
            dates = [str(x)[:10] for x in df["date"].tolist()]
            closes = [float(x) for x in df["close"].tolist()]
            lows = ([float(x) for x in df["low"].tolist()]
                    if "low" in df.columns else [])
            if len(closes) < LOOKBACK:
                raise ValueError(f"{label} 日K仅 {len(closes)} 根，不足 {LOOKBACK}")
            print(f"[ok] {code} 日K命中 {label}（{len(closes)} 根，{dates[0]}~{dates[-1]}）")
            return {"dates": dates, "closes": closes, "lows": lows}, label
        except Exception as e:
            last_err = f"{label}: {e}"
            print(f"[warn] {code} {last_err}")
    return None, last_err


def build_ma850_inputs():
    """产出 ma850_index.compute() 所需输入：四大指数日K（含当日 spot 补点）。"""
    today = _bj_today()
    trade_today = is_trade_day(today)
    spot = _fetch_spot_map() if trade_today else {}

    rows = []
    for code, name in INDEXES:
        row, src = _fetch_daily(code)
        if row is None:
            rows.append({"code": code, "name": name, "error": src or "暂未获取"})
            continue
        # 当日补点：仅交易日且日K末根早于今天
        if trade_today and _last_date(row["dates"]) and _last_date(row["dates"]) < today:
            if code in spot:
                close, low = spot[code]
                row["dates"].append(today)
                row["closes"].append(close)
                if low is not None:
                    if len(row["lows"]) == len(row["closes"]) - 1:
                        row["lows"].append(low)
                    else:
                        row["lows"] = []  # 历史 low 缺失/不齐时放弃盘中判定
                src = f"{src}+spot"
        row.update({"code": code, "name": name, "src": src})
        rows.append(row)

    avail_dates = [_last_date(r.get("dates")) for r in rows if r.get("dates")]
    data_date = max([d for d in avail_dates if d], default=today)
    labels = [r.get("src") for r in rows if r.get("src")]
    src_summary = " / ".join(f"{u}×{labels.count(u)}" for u in sorted(set(labels))) or "暂未获取"

    return {
        "indices": rows,
        "_data_date": data_date,
        "_src": src_summary,
        "_generated_at": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(build_ma850_inputs(), ensure_ascii=False, indent=2,
                      default=str)[:4000])
