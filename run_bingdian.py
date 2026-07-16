#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股冰点参考 · 编排入口
====================
把取数(fetch_bingdian_akshare) → 计算(bingdian_index) → 产物(output/bingdian_report.json)
串起来，作为小旭恐惧指数(XXFI)的**旁挂参考指标**（不写入 xxfi_report.json，不影响XXFI）。

用法：
  python run_bingdian.py --akshare --out output     # 联网取数计算（建议盘后跑，放量才有效）
  python run_bingdian.py --demo --out output        # 内置"冰点日"样例演示
  python run_bingdian.py --json '{"down":5100,...}' --out output   # 直接吃 JSON 输入

产物 output/bingdian_report.json 字段：
  {_data_date, _note, verdict, verdict_text, verdict_emoji, verdict_full, dimensions[], missing[]}
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bingdian_index import compute
import fetch_bingdian_akshare as fb


def demo_inputs():
    """内置"冰点日"样例：4 维度全满足（与《A股冰点量化框架.md》3月23日样本一致）"""
    return {
        "down": 5100, "total": 5400, "down_ratio": 5100 / 5400,
        "sh_chg": -3.6, "cyb_chg": -3.5, "etf_down_ratio": 0.75,
        "limit_down": 133, "limit_up": 12, "ld_lu_ratio": 133 / 12,
        "volume_mult": 1.8,
        "_src_D1": "legu", "_src_D2": "eastmoney_index",
        "_src_D3": "eastmoney_spot", "_src_D4": "tencent_daily",
        "_data_date": fb._bj_today(),
    }


def format_report(res, m):
    lines = []
    lines.append("# A股冰点参考 · 旁挂指标\n")
    lines.append("> 参考指标，不纳入 XXFI 计算口径，不影响小旭恐惧指数。")
    lines.append(f"> 数据日期：{res.get('_data_date','')}　|　结论：**{res['verdict_full']}**\n")
    lines.append("| 维度 | 实测 | 阈值 | 判定 | 源 |")
    lines.append("|---|---|---|---|---|")
    for d in res["dimensions"]:
        p = d.get("pass")
        mark = "✅" if p is True else ("❌" if p is False else "—")
        lines.append(f"| {d['key']} {d['name']} | {d['value']} | {d['threshold']} | {mark} | {d['source']} |")
    if res["missing"]:
        lines.append(f"\n> ⚠️ 暂未获取维度：{', '.join(res['missing'])}")
    lines.append("\n---")
    lines.append("> 冰点 = D1∧D2∧D3∧D4 全满足，即市场极端恐慌带血筹码。真正的冰点一年 3 次以内，不符合纪律绝不出手。")
    return "\n".join(lines)


def write(res, m, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = dict(res)
    out["_note"] = "参考指标，不纳入XXFI计算口径，不影响小旭恐惧指数"
    out["inputs"] = {k: v for k, v in m.items() if not k.startswith("_src")}
    p_json = os.path.join(out_dir, "bingdian_report.json")
    p_md = os.path.join(out_dir, "bingdian_report.md")
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(p_md, "w", encoding="utf-8") as f:
        f.write(format_report(res, m))
    print(format_report(res, m))
    print(f"\n报告已写入:\n  {p_json}\n  {p_md}")
    return out


def main():
    ap = argparse.ArgumentParser(description="A股冰点参考 编排入口")
    ap.add_argument("--akshare", action="store_true", help="联网取数（legu主→东财兜底）")
    ap.add_argument("--demo", action="store_true", help="内置冰点日样例")
    ap.add_argument("--json", default=None, help="直接传入冰点输入 JSON 字符串")
    ap.add_argument("--xxfi-report", default=None,
                    help="同轮 XXFI 报告路径，用于复用其 legu 广度(P0)；默认 <out>/xxfi_report.json")
    ap.add_argument("--out", default="output", help="报告输出目录")
    args = ap.parse_args()

    if args.demo:
        m = demo_inputs()
    elif args.json:
        m = json.loads(args.json)
    elif args.akshare:
        # P0：复用同轮 XXFI 已取的 legu 广度（避免重复取数 + 规避 legu 抖动兜底）
        xxfi_inputs = None
        xr = args.xxfi_report or os.path.join(args.out, "xxfi_report.json")
        if os.path.exists(xr):
            try:
                xxfi_inputs = json.load(open(xr, encoding="utf-8")).get("inputs")
                print(f"[P0] 复用 XXFI 广度（{xr}）: down={xxfi_inputs.get('down')} "
                      f"limit_down={xxfi_inputs.get('limit_down')}")
            except Exception as e:
                print(f"[warn] 读取 XXFI 报告失败，广度走自有链: {e}")
        else:
            print(f"[P0] 未找到 XXFI 报告（{xr}），广度走自有链")
        cache_path = os.path.join(args.out, "_sh_amt_cache.json")   # P2 放量缓存
        m = fb.build_bingdian_inputs(xxffi_inputs=xxfi_inputs, cache_path=cache_path)
    else:
        print("ERROR: 需 --akshare / --demo / --json"); sys.exit(1)

    res = compute(m)
    write(res, m, args.out)


if __name__ == "__main__":
    main()
