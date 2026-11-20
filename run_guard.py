#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国家队护盘追踪 · 编排入口
========================
取数(fetch_guard_akshare) → 计算(guard_index) → 产物(output/guard_report.json)

作为 XXFI 的**旁挂参考卡**（不写入 xxfi_report.json，不影响 XXFI），
放在「冰点参考」与「850天线抄底坐标」之间。

用法：
  python run_guard.py --akshare --out output       # 联网取数（盘后跑）
  python run_guard.py --demo-buy --out output      # 样例：2 只宽基尾盘扫货
  python run_guard.py --demo-weak --out output     # 样例：单只异动
  python run_guard.py --demo-none --out output     # 样例：未发现护盘
  python run_guard.py --demo-degraded --out output # 样例：全链降级
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_guard_akshare as fg
import guard_index as gi

REPORT_FILE = "guard_report.json"
VERDICT_HIST = "guard_verdict_history.jsonl"
VERDICT_KEEP = 20          # 判定流水只保留最近 20 个交易日
CST = datetime.timezone(datetime.timedelta(hours=8))


def format_report(r):
    s = r.get("share") or {}
    lines = ["# 国家队护盘追踪 · 宽基 ETF\n"]
    lines.append("> 旁挂参考卡，不构成投资建议，不参与 XXFI 计算。"
                 "结论为形态推断，不是身份认定。")
    if r.get("peak_scope") == "tail":
        slot = "买入时段：%s（最集中 %s · %s 亿）" % (r.get("window"), r.get("peak_window"), r.get("peak_amt_yi"))
    elif r.get("peak_scope") == "day" and r.get("peak_amt_yi"):
        slot = "最活跃 5 分钟：%s · %s 亿（非尾盘）" % (r.get("peak_window"), r.get("peak_amt_yi"))
    else:
        slot = "时段：暂未获取"
    lines.append("> 数据日期：%s　|　判定：**%s**　|　%s\n"
                 % (r.get("_data_date"), r.get("verdict_text"), slot))
    lines.append("| ETF | 尾盘成交(亿) | 占全天 | 全天(亿) | 尾盘涨跌 |")
    lines.append("|---|---|---|---|---|")
    for x in r.get("rows", []):
        lines.append("| %s | %.1f | %.1f%% | %.1f | %s |"
                     % (x["label"], x["tail_yi"], x["tail_pct"], x["all_yi"],
                        ("%.2f%%" % x.get("tail_ret", 0)) if "tail_ret" in x else "—"))
    lines.append("\n- 其余 %d 只尾盘合计 %.0f 亿；全部 %d 只合计 **%.0f 亿**"
                 % (r.get("rest_n", 0), r.get("rest_tail_yi", 0), r.get("n_etf", 0),
                    r.get("total_tail_yi", 0)))
    lines.append("- 昨日份额（%s）：**%+.1f 亿**　%d/%d 只净申购　连续 %d 日　近5日 %+.0f 亿"
                 % (s.get("date") or "—", s.get("net_yi", 0), s.get("pos_cnt", 0),
                    s.get("basket_cnt", 0), s.get("days_pos", 0), s.get("d5_yi", 0)))
    if r.get("missing"):
        lines.append("- 分时暂未获取：%s" % "、".join(r["missing"]))
    lines.append("\n---")
    lines.append("> 口径：尾盘 = 14:45–15:00；份额 = 上交所按日归档（T+1 发布），"
                 "深市无历史份额接口，靠每日快照累积。")
    lines.append("> 数据源：%s" % (r.get("_src") or "—"))
    return "\n".join(lines)


def append_verdict(out_dir, res):
    """判定流水：按日期去重，只保留最近 VERDICT_KEEP 条（封顶，不无限增长）"""
    p = os.path.join(out_dir, VERDICT_HIST)
    rows = []
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                rows = [json.loads(x) for x in f if x.strip()]
        except Exception as e:
            print(f"[warn] 判定流水读取失败，重建: {e}")
            rows = []
    row = {
        "date": res.get("_data_date"),
        "verdict": res.get("verdict"),
        "text": res.get("verdict_text"),
        "tail_yi": res.get("total_tail_yi"),
        "net_yi": (res.get("share") or {}).get("net_yi", 0),
        "top": (res["rows"][0]["label"] if res.get("rows") else ""),
        "share_date": (res.get("share") or {}).get("date"),
    }
    rows = [r for r in rows if r.get("date") != row["date"]]
    rows.append(row)
    rows.sort(key=lambda r: r.get("date") or "")
    rows = rows[-VERDICT_KEEP:]
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def write(res, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = dict(res)
    out["_note"] = "旁挂参考卡，不参与 XXFI 计算；形态推断，非身份认定"
    p = os.path.join(out_dir, REPORT_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(format_report(out))
    print(f"\n报告已写入: {p}")
    hp = append_verdict(out_dir, out)
    print(f"判定流水: {hp}")
    return out


def main():
    ap = argparse.ArgumentParser(description="国家队护盘追踪 编排入口")
    ap.add_argument("--akshare", action="store_true", help="联网取数")
    ap.add_argument("--demo-buy", action="store_true")
    ap.add_argument("--demo-weak", action="store_true")
    ap.add_argument("--demo-none", action="store_true")
    ap.add_argument("--demo-degraded", action="store_true")
    ap.add_argument("--json", default=None, help="直接传入输入 JSON 字符串")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    if args.demo_buy:
        m = gi._demo("buy")
    elif args.demo_weak:
        m = gi._demo("weak")
    elif args.demo_none:
        m = gi._demo("none")
    elif args.demo_degraded:
        m = gi._demo_degraded()
    elif args.json:
        m = json.loads(args.json)
    elif args.akshare:
        m = fg.build_guard_inputs(out_dir=args.out)
    else:
        print("ERROR: 需 --akshare / --demo-buy / --demo-weak / --demo-none / --demo-degraded / --json")
        sys.exit(1)

    res = gi.compute(m)
    res["_generated_at"] = m.get("_generated_at") or datetime.datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    write(res, args.out)


if __name__ == "__main__":
    main()
