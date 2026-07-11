#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小旭恐惧指数 · 开盘自动播报 runner
=================================
从「指数日K文件（如上证指数/沪深300）」自动计算指数派生分量（回撤/动量/均线偏离/波动率分位），
再合并「盘面广度 JSON」（涨跌家数/涨跌停/散户流向，由调用方用 tdx_quotes/screener 采集），
计算 XXFI 并生成播报报告（md + json）。

用法：
  python run_xxfi.py --hs300 <指数日K文件路径> \
                     --breadth '{"up":2400,"down":2600,"limit_up":55,"limit_down":25,"retail_net":-0.01}' \
                     --out <报告输出目录>

  或纯 akshare 模式（CI / 无 tdx 环境，直接联网取数）：
  python run_xxfi.py --akshare --vol_window 60 --out <报告输出目录>

  或直接给完整市场 JSON（覆盖自动计算）：
  python run_xxfi.py --json '{"drawdown":-0.05,"ret20":0.01,...}'

  广度缺失时自动降级为「指数版 XXFI」（仅用沪深300派生分量），并在报告中标注。
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoxu_fear_index import compute

def parse_kline(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    js = json.loads(text[text.find("{"):])
    rows = js["Rows"]
    closes = [float(r["Close"]) for r in rows]
    dates = [r["Data"] for r in rows]
    name = js.get("AttachInfo", {}).get("Name", "上证指数")
    return closes, dates, name

def max_drawdown(prices):
    peak = prices[0]; mdd = 0.0
    for p in prices:
        if p > peak: peak = p
        dd = (p - peak) / peak
        if dd < mdd: mdd = dd
    return mdd

def roll_vol(prices, w=20):
    vols = []
    for i in range(w, len(prices)):
        seg = prices[i-w:i]
        rets = [seg[j]/seg[j-1]-1 for j in range(1, len(seg))]
        m = sum(rets)/len(rets)
        var = sum((r-m)**2 for r in rets)/len(rets)
        vols.append(var**0.5)
    return vols

def index_components(path, vol_window=260):
    closes, dates, name = parse_kline(path)
    last20 = closes[-20:]
    dd = max_drawdown(last20)
    ret20 = last20[-1]/last20[0] - 1
    ma20 = sum(last20)/len(last20)
    above = (closes[-1]-ma20)/ma20
    vols = roll_vol(closes, 20)
    cur = vols[-1]
    # 波动率分位：取当前20日波动率在"近 vol_window 日"波动率分布中的分位。
    # vol_window=260(默认) 看全年相对水平；vol_window=60 看近60日"纯情绪"相对水平，
    # 后者对近期波动更敏感、可剔除长期低波动基线的抬高效应。
    win = vols[-vol_window:]
    vol_pct = sum(1 for v in win if v <= cur)/len(win)
    return {"drawdown": dd, "ret20": ret20, "above_ma20": above, "vol_pct": vol_pct,
            "vol_window": vol_window}, \
           dates[-1], closes[-1], name

def format_report(res, d):
    c = res["components"]
    conf = "完整（含盘面广度）" if d.get("_breadth_provided") else "指数版（广度缺失，仅沪深300派生分量，置信度较低）"
    lines = []
    lines.append("# 小旭恐惧指数 · 开盘播报\n")
    if "_hs300_date" in d:
        idx = d.get("_index_name", "沪深300")
        lines.append(f"> 数据基准：{idx} 收盘 {d['_hs300_close']:.2f}（{d['_hs300_date']}）　|　数据模式：{conf}\n")
    lines.append(f"## XXFI（主表·决定信号）= **{res['XXFI']}**　|　贪婪指数（副表·辅助诊断）= {res['GreedIndex']}")
    lines.append(f"**等级**：{res['level']}（以 XXFI 主表判定）")
    lines.append(f"**反向信号**：`{res['contrarian_signal']}`")
    lines.append(f"> {res['advice']}\n")
    lines.append("> 注：XXFI 与贪婪指数为两套独立公式，不相加=100、非互补对子；贪婪指数仅作辅助诊断（如局部热闹但非全面过热）。\n")
    lines.append("### 分项得分")
    lines.append("| 维度 | 分量 | 得分 |")
    lines.append("|---|---|---|")
    lines.append(f"| 恐惧 | 近20日最大回撤 | {c['fear']['drawdown']} |")
    lines.append(f"| 恐惧 | 涨跌家数比 | {c['fear']['breadth']} |")
    lines.append(f"| 恐惧 | 跌停/涨停比 | {c['fear']['limitdown']} |")
    lines.append(f"| 恐惧 | 波动率分位 | {c['fear']['vol']} |")
    lines.append(f"| 贪婪 | 近20日动量 | {c['greed']['momentum']} |")
    lines.append(f"| 贪婪 | 涨停/跌停比 | {c['greed']['limitup']} |")
    lines.append(f"| 贪婪 | 散户净流入 | {c['greed']['retailin']} |")
    lines.append(f"| 贪婪 | 高于20日均线 | {c['greed']['overbought']} |")
    lines.append(f"| 贪婪 | 主力—散户背离 | {c['greed']['divergence']} |")
    lines.append("")
    lines.append("### 输入快照")
    idx = d.get("_index_name", "沪深300")
    lines.append(f"- {idx} 近20日回撤：{d.get('drawdown',0)*100:.2f}%")
    lines.append(f"- {idx} 近20日涨幅：{d.get('ret20',0)*100:.2f}%")
    lines.append(f"- {idx} 高于20日线：{d.get('above_ma20',0)*100:.2f}%")
    vw = d.get("vol_window", 260)
    lines.append(f"- 波动率历史分位：{d.get('vol_pct',0)*100:.0f}%（窗口={vw}日）")
    lines.append(f"- 涨跌家数：{d.get('up','-')} / {d.get('down','-')}　涨停/跌停：{d.get('limit_up','-')} / {d.get('limit_down','-')}")
    lines.append(f"- 主力净流入占比：{float(d.get('main_net',0) or 0)*100:.2f}%（源：{d.get('_main_net_source','-')}）")
    lines.append(f"- 散户净流入占比：{float(d.get('retail_net',0) or 0)*100:.2f}%（源：{d.get('_retail_net_source','-')}）")
    div = res.get("divergence")
    div_s = res.get("divergence_state", "-")
    lines.append(f"- 主力—散户背离：{div_s}" + (f"（diff={div:+.4f}）" if div is not None else "（无数据）"))
    lines.append(f"- 数据溯源：广度={d.get('_breadth_source','-')}　主力/散户资金流={d.get('_main_net_source','-')}")
    lines.append("")
    lines.append("---")
    lines.append("> 反向指标仅在情绪极端+趋势反转时有效，须配合自身交易系统与止损纪律，切勿单独作为买卖依据。")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="小旭恐惧指数 开盘播报 runner")
    ap.add_argument("--hs300", help="沪深300日K文件路径(tdx导出)")
    ap.add_argument("--breadth", default=None, help='盘面广度JSON: {"up":,"down":,"limit_up":,"limit_down":,"retail_net":}')
    ap.add_argument("--breadth_file", default=None, help="盘面广度JSON文件路径")
    ap.add_argument("--out", default=".", help="报告输出目录")
    ap.add_argument("--vol_window", type=int, default=260, help="波动率分位窗口(交易日数)，默认260(全年)；设60看近60日\"纯情绪\"相对水平")
    ap.add_argument("--akshare", action="store_true", help="纯 akshare 取数模式（CI/无 tdx 环境），直接联网拉指数与盘面广度")
    ap.add_argument("--json", default=None, help="直接传入完整市场JSON(覆盖其它)")
    ap.add_argument("--backfill", type=int, default=0,
                    help="历史回溯 N 个交易日（baostock 取真实广度），写入 history.jsonl 并重算最新报告")
    args = ap.parse_args()

    if args.backfill:
        import fetch_history_baostock as fh
        fh.backfill_history(args.backfill, args.vol_window, args.out)
        return

    if args.json:
        d = json.loads(args.json)
        d["_breadth_provided"] = True
    elif args.akshare:
        import fetch_market_akshare as fm
        d = fm.build_market_json(vol_window=args.vol_window)
        d["_index_name"] = d.get("_index_name", "上证指数(sh000001)")
        d["_hs300_date"] = d.get("_last_date", d.get("_breadth_date", ""))
        d["_hs300_close"] = d.get("_last_close", 0.0)
        d["_breadth_provided"] = True
    else:
        if not args.hs300:
            print("ERROR: 需提供 --hs300 或 --json"); sys.exit(1)
        comp, ddate, dclose, iname = index_components(args.hs300, args.vol_window)
        breadth = {}
        if args.breadth_file:
            breadth = json.load(open(args.breadth_file, encoding="utf-8"))
        elif args.breadth:
            breadth = json.loads(args.breadth)
        d = dict(comp)
        d.update({
            "up": breadth.get("up", 1),
            "down": breadth.get("down", 1),
            "limit_up": breadth.get("limit_up", 1),
            "limit_down": breadth.get("limit_down", 0),
            "retail_net": breadth.get("retail_net", 0.0),
            "main_net": breadth.get("main_net", None),
        })
        d["_hs300_date"] = ddate
        d["_hs300_close"] = dclose
        d["_index_name"] = iname
        d["_breadth_provided"] = bool(breadth)

    res = compute(d)
    write_outputs(res, d, args.out, args.vol_window)


def write_outputs(res, d, out_dir, vol_window=260):
    os.makedirs(out_dir, exist_ok=True)
    md = format_report(res, d)
    p_md = os.path.join(out_dir, "xxfi_report.md")
    p_json = os.path.join(out_dir, "xxfi_report.json")
    out = dict(res)
    out["_data_date"] = str(d.get("_hs300_date", "") or d.get("_breadth_date", ""))[:10]
    out["_index_name"] = d.get("_index_name", "")
    out["_vol_window"] = d.get("vol_window", vol_window)
    # 溯源提顶层，便于 HTML/历史展示（缺失容错）
    out["_breadth_source"] = d.get("_breadth_source", (res.get("inputs") or {}).get("_breadth_source", "-"))
    out["_retail_net_source"] = d.get("_retail_net_source", (res.get("inputs") or {}).get("_retail_net_source", "-"))
    out["_main_net_source"] = d.get("_main_net_source", (res.get("inputs") or {}).get("_main_net_source", "-"))
    out["divergence"] = res.get("divergence")
    out["divergence_state"] = res.get("divergence_state")
    with open(p_md, "w", encoding="utf-8") as f: f.write(md)
    with open(p_json, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, indent=2)
    print(md)
    print(f"\n报告已写入:\n  {p_md}\n  {p_json}")
    return out

if __name__ == "__main__":
    main()
