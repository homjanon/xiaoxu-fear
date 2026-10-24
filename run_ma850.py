#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
850天线抄底坐标 · 编排入口
========================
取数(fetch_ma850_akshare) → 计算(ma850_index) → 产物(output/ma850_report.json)

作为小旭恐惧指数(XXFI)的**旁挂参考卡**（不写入 xxfi_report.json，不影响 XXFI），
观点来源：财经博主 plutus（2026-10）——各大指数跌至 850 天线为大资金抄底位。

用法：
  python run_ma850.py --akshare --out output       # 联网取数（盘后跑，当日 spot 补点）
  python run_ma850.py --demo-touched --out output  # 样例：2 个指数盘中击穿后收回
  python run_ma850.py --demo-entered --out output  # 样例：3 个指数收盘跌破
  python run_ma850.py --demo-none --out output     # 样例：全部在线 850 上方
  python run_ma850.py --json '{"indices":[...]}' --out output
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ma850_index import compute, _demo
import fetch_ma850_akshare as fm

REPORT_FILE = "ma850_report.json"
CST = datetime.timezone(datetime.timedelta(hours=8))


def _pct(v):
    return f"{v*100:+.2f}%" if v is not None else "—"


def _price(v):
    return f"{v:.2f}" if v is not None else "—"


def format_report(res):
    lines = ["# 850天线抄底坐标 · plutus 观点\n"]
    lines.append("> 参考指标，不构成投资建议，不影响 XXFI 任何计算口径。")
    lines.append(f"> 数据日期：{res.get('_data_date','')}　|　判定：**{res.get('verdict_text','')}**"
                 f"（收盘跌破 {res.get('below_count',0)}/4 · 盘中击穿 {res.get('touch_count',0)}/4）\n")
    lines.append("| 指数 | 现价 | 850线 | 收盘偏离 | 当日最低 | 最低偏离 | 状态 | 最近收盘跌破 | 最近盘中击穿 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for x in res.get("indices", []):
        lines.append(
            f"| {x.get('name')} | {_price(x.get('close'))} | {_price(x.get('ma850'))} | "
            f"{_pct(x.get('dev'))} | {_price(x.get('low'))} | {_pct(x.get('low_dev'))} | "
            f"{x.get('state_text')} | {x.get('last_close_below') or '—'} | "
            f"{x.get('last_low_touch') or '—'} |"
        )
    lines.append("\n---")
    lines.append("> 850线 = 最近 850 个交易日收盘均价（移动靶/滞后指标）。"
                 "收盘跌破不等于立刻见底；历史小注：中证1000 深度跌破（低于5%）8 次，"
                 "抄底后 1 年 7/8 为正，但信号后平均仍先跌 10.3%（2010以来周K近似，样本少）。")
    lines.append(f"> 数据源：{res.get('_src') or '—'}")
    return "\n".join(lines)


def write(res, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = dict(res)
    out["_note"] = "参考指标，不构成投资建议；不纳入 XXFI 计算口径"
    p_json = os.path.join(out_dir, REPORT_FILE)
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(format_report(out))
    print(f"\n报告已写入: {p_json}")
    return out


def main():
    ap = argparse.ArgumentParser(description="850天线抄底坐标 编排入口")
    ap.add_argument("--akshare", action="store_true", help="联网取数（新浪日K → 腾讯兜底 + spot 补当日）")
    ap.add_argument("--demo-touched", action="store_true", help="样例：2 个指数盘中击穿后收回")
    ap.add_argument("--demo-entered", action="store_true", help="样例：3 个指数收盘跌破")
    ap.add_argument("--demo-none", action="store_true", help="样例：全部在 850 线上方")
    ap.add_argument("--json", default=None, help="直接传入输入 JSON 字符串")
    ap.add_argument("--out", default="output", help="报告输出目录")
    args = ap.parse_args()

    if args.demo_touched:
        m = _demo(touched=2)
    elif args.demo_entered:
        m = _demo(entered=3)
    elif args.demo_none:
        m = _demo()
    elif args.json:
        m = json.loads(args.json)
    elif args.akshare:
        m = fm.build_ma850_inputs()
    else:
        print("ERROR: 需 --akshare / --demo-touched / --demo-entered / --demo-none / --json")
        sys.exit(1)

    res = compute(m)
    res["_generated_at"] = m.get("_generated_at") or datetime.datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    write(res, args.out)


if __name__ == "__main__":
    main()
