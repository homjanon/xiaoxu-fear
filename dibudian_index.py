#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部区域判断 · 纯计算（仅标准库，零依赖，仿 bingdian_index.py 风格）
================================================================

把「底部区域取数器」采集到的全市场成交额，映射为「是否底部区域日」判定。
不依赖任何外部库，与 XXFI（小旭恐惧指数）、冰点参考完全独立。

设计立场：
  底部区域 = 地量区域。当全市场成交额缩至「近三个月（90交易日）最高成交额」的一半及以下，
  视为市场极度冷清、抛压衰竭，是底部区域的信号。

  该指标是一个「状态标记」而非瞬时值：一旦某日满足条件被记为底部区域日，
  该日期会一直显示在卡片上，直到下一个满足条件的日期出现并取代它。

输入字段（由 fetch_dibudian_akshare.build_dibudian_inputs() 产出）：
  today_total : 当日全市场成交额（上证+深证成交额之和，单位：元）
  max90_total : 近90交易日全市场成交额最高值（单位：元）
  sh_today / sz_today : 当日上证/深证成交额（明细，可选）
  _data_date : 数据日期

阈值（与《底部区域判断》需求严格一致）：
  THRESHOLD = 0.5  → 当日成交额 <= 近90日最高 × 50% 即判为底部区域日
  LOOKBACK   = 90   → 近90个交易日（约一个完整季度）
"""
import json
from typing import Any, Dict, Optional

LOOKBACK = 90       # 近90个交易日
THRESHOLD = 0.5     # 一半阈值：当日 <= 近90日最高 × 50%


def _num(v: Any) -> Optional[float]:
    """值是否可用（非 None 且非 '暂未获取' 字符串，非 NaN）"""
    if v is None or v == "暂未获取":
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN → None
    except (TypeError, ValueError):
        return None


def compute(d: Dict[str, Any]) -> Dict[str, Any]:
    """输入当日+近90日最高成交额 → 底部区域判定 dict。

    返回结构（供 render_html / 输出 JSON 直接消费）：
      today_total / sh_today / sz_today / max90_total
      ratio                 : 当日 / 近90日最高
      threshold
      is_bottom_today       : 当日是否满足底部区域条件（None 表示取数失败）
      verdict_text / verdict_emoji
      _data_date

    注：持久逻辑（last_bottom_date 跨日保持）在 run_dibudian.py 编排层处理，
        本函数只负责纯判定，保持零依赖、可单测。
    """
    today = _num(d.get("today_total"))
    max90 = _num(d.get("max90_total"))
    sh = _num(d.get("sh_today"))
    sz = _num(d.get("sz_today"))

    if today is None or max90 is None or max90 <= 0:
        return {
            "today_total": today, "sh_today": sh, "sz_today": sz, "max90_total": max90,
            "ratio": None, "threshold": THRESHOLD,
            "is_bottom_today": None,
            "verdict_text": "暂未获取", "verdict_emoji": "—",
            "_data_date": str(d.get("_data_date", ""))[:10],
            "_src": d.get("_src"), "_sina_src": d.get("_sina_src"),
        }

    ratio = today / max90
    is_bottom_today = bool(today <= max90 * THRESHOLD)

    return {
        "today_total": today, "sh_today": sh, "sz_today": sz, "max90_total": max90,
        "ratio": round(ratio, 4),
        "threshold": THRESHOLD,
        "is_bottom_today": is_bottom_today,
        "verdict_text": "底部区域日" if is_bottom_today else "非底部区域日",
        "verdict_emoji": "🟢" if is_bottom_today else "⚪",
        "_data_date": str(d.get("_data_date", ""))[:10],
        "_src": d.get("_src"), "_sina_src": d.get("_sina_src"),
    }


def main():
    ap = __import__("argparse").ArgumentParser(description="底部区域判断 纯计算（演示）")
    ap.add_argument("--json", default=None, help="直接传入输入 JSON 字符串")
    ap.add_argument("--demo-bottom", action="store_true", help="内置底部区域日样例（地量）")
    ap.add_argument("--demo-normal", action="store_true", help="内置非底部区域日样例")
    args = ap.parse_args()
    if args.demo_bottom:
        # 地量：当日 3000亿，近90日峰值 8000亿 → 比值 0.375 ≤ 0.5，是底部区域日
        d = {"today_total": 3000e8, "max90_total": 8000e8, "sh_today": 1300e8, "sz_today": 1700e8,
             "_data_date": "2026-07-31"}
    elif args.demo_normal:
        # 正常量：当日 9000亿，近90日峰值 8000亿 → 比值 1.125 > 0.5，非底部区域日
        d = {"today_total": 9000e8, "max90_total": 8000e8, "sh_today": 4000e8, "sz_today": 5000e8,
             "_data_date": "2026-07-31"}
    elif args.json:
        d = json.loads(args.json)
    else:
        print("需 --demo-bottom / --demo-normal / --json"); raise SystemExit(1)
    print(json.dumps(compute(d), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
