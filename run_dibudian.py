#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
底部区域判断 · 编排入口
====================
把取数(fetch_dibudian_akshare) → 计算(dibudian_index) → 产物(output/dibudian_report.json)
串起来，作为小旭恐惧指数(XXFI)的**旁挂参考指标**（不写入 xxfi_report.json，不影响XXFI）。

与冰点参考平行的独立指标；额外携带「跨日持久状态」dibudian_state.json：
  - 当日满足底部区域条件 → 更新 last_bottom_date 为当日
  - 当日不满足 → 保持上次记录的日期（一直显示，直到被下一个满足条件日取代）

用法：
  python run_dibudian.py --akshare --out output     # 联网取数计算（建议盘后跑）
  python run_dibudian.py --demo-bottom --out output # 内置"底部区域日(地量)"样例
  python run_dibudian.py --demo-normal --out output # 内置"非底部区域日"样例
  python run_dibudian.py --json '{"today_total":...,"max90_total":...}' --out output

产物 output/dibudian_report.json 字段：
  {today_total, sh_today, sz_today, max90_total, ratio, threshold,
   is_bottom_today, last_bottom_date, last_bottom_volume, hist30(近30日回看),
   _data_date, _src, _note}
产物 output/dibudian_state.json 字段（跨日保留）：
  {last_bottom_date, last_bottom_volume, _updated_at}
"""
import argparse, json, os, sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dibudian_index import compute
import fetch_dibudian_akshare as fd

STATE_FILE = "dibudian_state.json"
REPORT_FILE = "dibudian_report.json"

CST = datetime.timezone(datetime.timedelta(hours=8))


def load_state(out_dir):
    p = os.path.join(out_dir, STATE_FILE)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print(f"[warn] 读取 {STATE_FILE} 失败，视为空状态: {e}")
    return {}


def save_state(out_dir, state):
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, STATE_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def demo_bottom():
    return {"today_total": 3000e8, "max90_total": 8000e8, "sh_today": 1300e8, "sz_today": 1700e8,
            "_data_date": fd._bj_today(), "_src": "demo"}


def demo_normal():
    return {"today_total": 9000e8, "max90_total": 8000e8, "sh_today": 4000e8, "sz_today": 5000e8,
            "_data_date": fd._bj_today(), "_src": "demo"}


def format_report(res):
    lines = []
    lines.append("# 底部区域判断 · 旁挂指标\n")
    lines.append("> 参考指标，不纳入 XXFI 计算口径，不影响小旭恐惧指数。")
    lines.append(f"> 数据日期：{res.get('_data_date','')}　|　判定：**{res.get('verdict_text','')}**\n")
    lines.append(f"- 当日全市场成交额：{res.get('today_total')}")
    lines.append(f"- 近90日最高成交额：{res.get('max90_total')}")
    lines.append(f"- 当前比率：{res.get('ratio')}　（阈值 ≤ {res.get('threshold')}）")
    lines.append(f"- 最近一次底部区域日：{res.get('last_bottom_date') or '暂未记录'}")
    lines.append("\n---")
    lines.append("> 底部区域 = 地量区域。当日全市场成交额缩至近90日最高的一半及以下，视为抛压衰竭的底部区域信号。该日期持续显示，直到被下一个满足条件的交易日取代。")
    return "\n".join(lines)


def write(res, m, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = dict(res)
    out["_note"] = "参考指标，不纳入XXFI计算口径，不影响小旭恐惧指数"
    out["hist30"] = m.get("hist30")   # 近30日成交额回看（供趋势图）
    out["inputs"] = {k: v for k, v in m.items() if not k.startswith("_")}
    # 报告
    p_json = os.path.join(out_dir, REPORT_FILE)
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 状态（仅 last_* 持久字段，供下次读取）
    state = {
        "last_bottom_date": out.get("last_bottom_date"),
        "last_bottom_volume": out.get("last_bottom_volume"),
        "_updated_at": datetime.datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(out_dir, state)
    print(format_report(out))
    print(f"\n报告已写入:\n  {p_json}\n  {os.path.join(out_dir, STATE_FILE)}")
    return out


def main():
    ap = argparse.ArgumentParser(description="底部区域判断 编排入口")
    ap.add_argument("--akshare", action="store_true", help="联网取数（新浪实时 spot 当日全市场口径 + 本地通达信回填滚动缓存）")
    ap.add_argument("--demo-bottom", action="store_true", help="内置底部区域日样例")
    ap.add_argument("--demo-normal", action="store_true", help="内置非底部区域日样例")
    ap.add_argument("--json", default=None, help="直接传入输入 JSON 字符串")
    ap.add_argument("--out", default="output", help="报告输出目录")
    args = ap.parse_args()

    if args.demo_bottom:
        m = demo_bottom()
    elif args.demo_normal:
        m = demo_normal()
    elif args.json:
        m = json.loads(args.json)
    elif args.akshare:
        m = fd.build_dibudian_inputs()
    else:
        print("ERROR: 需 --akshare / --demo-bottom / --demo-normal / --json"); sys.exit(1)

    computed = compute(m)

    # 跨日持久：收盘后且满足才更新日期，否则保持旧值（从 state.json 读回）
    state = load_state(args.out)
    now = datetime.datetime.now(CST)
    after_close = now.hour >= 15
    if computed.get("is_bottom_today") is True and after_close:
        new_date = computed.get("_data_date")
        new_vol = computed.get("today_total")
        print(f"[state] 今日满足条件(收盘后) → 更新底部区域日为 {new_date}")
    else:
        new_date = state.get("last_bottom_date")
        new_vol = state.get("last_bottom_volume")
        if new_date:
            print(f"[state] 非底部区域日或未收盘 → 保持上次底部区域日 {new_date}")
        else:
            print("[state] 今日未满足，且无历史记录")

    computed["last_bottom_date"] = new_date
    computed["last_bottom_volume"] = new_vol
    write(computed, m, args.out)


if __name__ == "__main__":
    main()
