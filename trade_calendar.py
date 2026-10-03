#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易日判据（全项目唯一来源）。

为什么单独一个模块
------------------
2026-10-03 事故：workflow 层用「akshare 交易日历」判门控，而各写入闸门（dibudian 缓存、
bingdian D4 缓存、history 追加）各自用「now.weekday() < 5」近似判定。两套条件在
「周中法定假期」（如中秋 09-25 周五、国庆 10-01 周四 / 10-02 周五）上不等价
—— 门控判"非交易日"、写入闸门判"工作日" → 假期照样写入，产生幽灵数据。

本模块把判据收敛到一处，门控与所有写入闸门共用，杜绝"两个条件碰巧等价"。

降级策略
--------
交易日历取数失败时降级为「周一~周五」并打印醒目 warn。之所以可接受：workflow 的
`check` 步骤持有独立且失败即报错（不会静默放行）的日历判定，是权威第一道闸门。
"""
import datetime
import os
import sys

CST = datetime.timezone(datetime.timedelta(hours=8))

_CAL = {"loaded": False, "days": set()}


def _load_calendar():
    if _CAL["loaded"]:
        return
    _CAL["loaded"] = True
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        _CAL["days"] = {str(x)[:10] for x in df["trade_date"].tolist()}
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 交易日历加载失败，降级为「周一~周五」判定（注意：周中法定假期会被误判为交易日）: {e}")


def is_trade_day(d=None):
    """d: 'YYYY-MM-DD' / date / datetime / None(=北京今天)。返回是否 A 股交易日。"""
    _load_calendar()
    if d is None:
        d = datetime.datetime.now(CST).strftime("%Y-%m-%d")
    s = str(d)[:10]
    if _CAL["days"]:
        return s in _CAL["days"]
    try:
        y, m, dd = map(int, s.split("-"))
        return datetime.date(y, m, dd).weekday() < 5
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    for x in ["2026-09-24", "2026-09-25", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-08"]:
        print(x, "交易日" if is_trade_day(x) else "非交易日")
