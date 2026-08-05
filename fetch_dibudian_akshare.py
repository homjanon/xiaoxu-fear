#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部区域判断 · 取数器（akshare · 全市场口径）
============================================================================
全市场沪深成交额（口径：全市场，非指数成分股）：
  当日 + 近90日历史峰值，统一用「全市场口径」：
    上证指数( sh000001 ) + 深证成指( sz399001 ) 的全市场成交额之和（元）。

取数链路（简洁、稳健，已绕过东财代理拦截）：
  当日（today_total）：新浪实时 spot —— stock_zh_index_spot_sina()
        返回上证指数 + 深证成指「全市场」成交额（元，已验证 2026-07-31 ≈ 2.542万亿）。
        东财 daily_em( push2his ) / 东财指数 spot 在本机及 CI 均被代理拦截，不可靠，已弃用；
        腾讯 daily_tx 为成分股半量口径（≈1.3万亿），与全市场对不上，亦弃用。
        用户明确指定改用新浪直连，已实测可用。

  近90日峰值（max90_total）+ 近30日回看（hist30）：本地滚动缓存 output/_turnover_cache.json
        冷启动由本地通达信连接器（tdx_kline）一次性回填 2025-12 ~ 2026-07 全部交易日
        全市场成交额（元），经 build_cache.py 合并为 {date: total_yuan} 提交仓库；
        之后每次运行把「当日(新浪)」追加进缓存并保留最近 CACHE_KEEP 日滚动，
        由 CI 的 git-auto-commit 持久化回仓库（实现滚动 90 日峰值）。

为什么是「全市场口径」：
  - 腾讯 stock_zh_index_daily_tx 的 amount 是**指数成分股成交额（约半量）**，
    会让卡片绝对值与用户查到的对不上，故废弃。
  - 新浪历史日线 stock_zh_index_daily 不含成交额列，故历史峰值走缓存（通达信回填）。
"""
import datetime
import json
import os

import akshare as ak

SH_CODE = "sh000001"   # 上证指数（全上海市场）
SZ_CODE = "sz399001"   # 深证成指（全深圳市场代理）
LOOKBACK = 90          # 近90个交易日
CACHE_KEEP = 400       # 缓存保留最近交易日数（滚动窗口，远大于90以支持回看）

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output", "_turnover_cache.json"
)


def _bj_now():
    CST = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(CST)


def _bj_today():
    return _bj_now().strftime("%Y-%m-%d")


def _parse_amount(v):
    """把成交额字段解析为 float（元）。兼容纯数字串与带千分位的串。"""
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------------- 当日全市场成交额：新浪实时 spot ----------------
def _fetch_sina_spot_today():
    """新浪实时 spot 全市场成交额（元）。

    返回 (total, sh, sz, date)；任一为 None 时上层以 0 处理或降级。
    新浪 spot 的「成交额」为全市场口径（上证+深证各自全市场成交）。
    """
    date = _bj_today()
    try:
        spot = ak.stock_zh_index_spot_sina()
    except Exception as e:
        print(f"[warn] 新浪 spot 失败（当日取数降级）: {e}")
        return None, None, None, date
    try:
        sh = spot[spot["代码"] == SH_CODE]
        sz = spot[spot["代码"] == SZ_CODE]
        sh_v = _parse_amount(sh.iloc[0]["成交额"]) if len(sh) else None
        sz_v = _parse_amount(sz.iloc[0]["成交额"]) if len(sz) else None
        if sh_v is None or sz_v is None:
            return None, None, None, date
        return sh_v + sz_v, sh_v, sz_v, date
    except Exception as e:
        print(f"[warn] 新浪 spot 解析失败: {e}")
        return None, None, None, date


# ---------------- 滚动缓存（近90日峰值 + 近30日回看，跨日持久） ----------------
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
        items = list(cache.items())
        if len(items) > CACHE_KEEP:
            items = items[-CACHE_KEEP:]
        json.dump(dict(items), open(CACHE_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
    except Exception as e:
        print(f"[warn] 成交额缓存写入失败: {e}")


def _max90_from_cache(cache: dict):
    vals = [v for v in cache.values() if isinstance(v, (int, float)) and v > 0]
    if not vals:
        return None
    return max(vals[-LOOKBACK:]) if len(vals) >= LOOKBACK else max(vals)


def _hist_from_cache(cache: dict, n=30):
    items = [(k, v) for k, v in cache.items()
             if isinstance(v, (int, float)) and v > 0]
    items = items[-n:] if len(items) >= n else items
    return [{"date": k, "total": v} for k, v in items]


def fetch_em_total():
    """产出底部区域判断所需的全市场成交额输入（当日 + 近90日最高 + 近30日回看）。

    链路：
      当日 = 新浪实时 spot（全市场口径，元）
      近90日峰值 = 本地滚动缓存最大值（缓存由通达信回填 + 每次追加当日滚动）
      近30日回看 = 缓存尾部 30 日（供趋势图）
      同时把当日追加进缓存并落盘（跨日滚动；CI 经 git-auto-commit 持久化）。
      周末不写入缓存（避免非交易日污染 90 日峰值窗口）。
    取数失败：返回 None 字段，卡片显示「暂未获取」，不影响 XXFI。
    """
    total, sh, sz, date = _fetch_sina_spot_today()
    if total is None:
        return {"today_total": None, "sh_today": None, "sz_today": None,
                "max90_total": None, "hist30": [],
                "_src": "暂未获取", "_data_date": date}
    cache = _load_turnover_cache()
    # 防污染（根治）：仅「_data_date==当天(北京) 且 已收盘(≥15:00) 且 工作日 且 同日未写过」写入。
    # 盘中快照(<15:00)/周末/非交易日(_data_date≠当天) 跳过；同日已存在跳过(防手动&cron重复)。
    now = _bj_now()
    date_is_today = (date == now.strftime("%Y-%m-%d"))
    after_close = (now.hour >= 15)
    if date_is_today and after_close and now.weekday() < 5 and date not in cache:
        cache[date] = total
    _save_turnover_cache(cache)
    max90 = _max90_from_cache(cache)
    hist30 = _hist_from_cache(cache, 30)
    return {
        "today_total": total, "sh_today": sh, "sz_today": sz,
        "max90_total": max90, "hist30": hist30,
        "_src": f"sina_spot+cache({date})", "_data_date": date,
    }


def build_dibudian_inputs():
    """产出 dibudian_index.compute() 所需的输入 dict。

    字段：today_total / sh_today / sz_today / max90_total / hist30 / _data_date / _src
    _data_date 取新浪实际数据日期；取数失败兜底为本地当前日。
    """
    f = fetch_em_total()
    if not f.get("_data_date"):
        f["_data_date"] = _bj_today()
    return f


if __name__ == "__main__":
    import json as _json
    inp = build_dibudian_inputs()
    print(_json.dumps(inp, ensure_ascii=False, indent=2, default=str))
