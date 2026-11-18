#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
akshare 接口兼容层（2026-11-18）
================================

背景：akshare 1.20.44~1.20.46 批量更名接口，旧名在 1.20.65 已从包内移除
（访问旧名会抛 AttributeError）。本项目 requirements 固定 1.18.64，当前不受影响；
但一旦升级 akshare，下列 7 个接口会连环失效，且各 fetch 的 try/except 会静默降级。

策略：**新名优先、旧名兜底**。所有调用点统一走本模块的命名包装，
新版 / 旧版 akshare 均可运行。

升级 akshare 前先跑零网络自检：
  python ak_compat.py --check
"""
import sys

# (包装名, 新名, 旧名)  —— 2026-11-18 对照 akshare 1.20.65 实测
RENAMES = [
    ("calendar_trade_date_hist", "calendar_trade_date_hist_sina", "tool_trade_date_hist_sina"),
    ("index_daily", "index_zh_daily_sina", "stock_zh_index_daily"),
    ("index_daily_tx", "index_zh_daily_tx", "stock_zh_index_daily_tx"),
    ("index_spot_sina", "index_zh_spot_sina", "stock_zh_index_spot_sina"),
    ("index_spot_em", "index_zh_spot_em", "stock_zh_index_spot_em"),
    ("stock_a_spot", "stock_zh_a_spot_sina", "stock_zh_a_spot"),
    ("fund_flow_individual", "stock_fund_flow_individual_ths", "stock_fund_flow_individual"),
]


def resolve(new_name, old_name):
    """返回 (命中的函数名, 函数对象)：新名优先、旧名兜底。"""
    import akshare as ak
    for name in (new_name, old_name):
        fn = getattr(ak, name, None)
        if fn is not None:
            return name, fn
    raise AttributeError(
        f"akshare 缺少接口 {new_name} / {old_name}"
        f"（版本 {getattr(ak, '__version__', '?')}）"
    )


def _call(new_name, old_name, *args, **kwargs):
    return resolve(new_name, old_name)[1](*args, **kwargs)


# ---- 命名包装：调用点只依赖这些名字，不再直接写 akshare 函数名 ----
def calendar_trade_date_hist():
    return _call("calendar_trade_date_hist_sina", "tool_trade_date_hist_sina")


def index_daily(symbol):
    return _call("index_zh_daily_sina", "stock_zh_index_daily", symbol=symbol)


def index_daily_tx(symbol):
    return _call("index_zh_daily_tx", "stock_zh_index_daily_tx", symbol=symbol)


def index_spot_sina():
    return _call("index_zh_spot_sina", "stock_zh_index_spot_sina")


def index_spot_em(symbol="沪深重要指数"):
    return _call("index_zh_spot_em", "stock_zh_index_spot_em", symbol=symbol)


def stock_a_spot():
    return _call("stock_zh_a_spot_sina", "stock_zh_a_spot")


def fund_flow_individual(symbol="即时"):
    return _call("stock_fund_flow_individual_ths", "stock_fund_flow_individual",
                 symbol=symbol)


def check():
    """零网络自检：打印每个包装命中的新名/旧名，全部可用返回 0。"""
    import akshare as ak
    print(f"akshare {getattr(ak, '__version__', '?')}")
    missing = []
    for wrapper, new_name, old_name in RENAMES:
        try:
            name, _fn = resolve(new_name, old_name)
            print(f"  [ok]   {wrapper:26} -> {name}")
        except Exception as e:  # noqa: BLE001
            missing.append(wrapper)
            print(f"  [FAIL] {wrapper:26} {e}")
    if missing:
        print(f"缺少 {len(missing)} 个接口: {missing}")
        return 1
    print(f"全部 {len(RENAMES)} 个接口可用")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(check())
    print(__doc__)