#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小旭恐惧指数 (XiaoXu Fear Index, XXFI) 计算脚本
================================================
用途：把"当前市场数据"映射为一个 0-100 的恐惧/贪婪反向情绪指标，
      类似 VIX（恐慌指数）/ VXN（科技恐慌指数）的"散户反向参考"版本。

核心思想（来自小旭 2024-2026 操作实录的实证校准）：
  - 小旭在"市场恐惧、连续下跌后恐慌割肉"时，股价往往已处阶段低位，
    随后多出现修复/反弹（卖飞）。→ 她的恐惧极致 ≈ 市场阶段性底部。
  - 小旭在"市场贪婪、连续大涨后追高买入"时，股价往往已处阶段高位，
    随后多出现回落/套牢（买在山顶）。→ 她的贪婪极致 ≈ 市场阶段性顶部。
  因此 XXFI 越高（越恐惧），反向越应看多；XXFI 越低（越贪婪），反向越应看空。

输入（由调用方通过 tdx / westock / akshare 等接口采集后传入，单位见示例）：
  --drawdown   沪深300(或对应宽基) 近20日最大回撤，小数，如 -0.08 表示 -8%
  --ret20      沪深300 近20日累计涨幅，小数，如 0.03
  --above_ma20 沪深300 收盘价高于20日均线的幅度，小数，如 0.01
  --up         上涨家数（或板块内上涨数）
  --down       下跌家数
  --limit_up   涨停家数
  --limit_down 跌停家数
  --vol_pct    当前市场波动率的历史分位(0-1)，如 0.85 表示处于一年高位
  --retail_net 散户(小单)资金净流入占比，小数，负为净流出，如 -0.03
  --json       直接以 JSON 字符串传入上述全部字段
  --demo       运行内置校准样例（不读外部数据）

输出：XXFI 数值、等级、反向信号、各分项得分（JSON + 可读文本）。
"""
import argparse, json, sys

# ---------------- 校准常量（基于小旭实录实证） ----------------
# 实录中"恐慌割肉"样本（前5日累计 -15% 左右，卖后反弹 +9%~+24%）：
#   ST臻镭 2026-04-29（前5日 -15.3%，卖后最高 +24.4%）
#   江丰电子 2026-07-08（前5日 -16.6%，卖后最高 +9.2%）
# 实录中"追高买在山顶"样本（买后 5 日 -12%~-21%）：
#   博杰股份 2026-06-25（窗口 100% 分位，买后 -20.8%）
#   光电股份 2026-06-29（前5日 +8.9%，买后 -18.5%）
#   澜起科技 2026-05-27（买后 -12.5%）
# 因此：恐惧分高 → 反向买入；贪婪分高 → 反向卖出。

WEIGHTS = {
    "fear":   {"drawdown": 0.30, "breadth": 0.25, "limitdown": 0.20, "vol": 0.25},
    "greed":  {"momentum": 0.30, "limitup": 0.20, "retailin": 0.25, "overbought": 0.25},
}

def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

def compute(d):
    # ---- 恐惧分项 (0-100，越大越恐惧) ----
    dd = abs(d.get("drawdown", 0.0))            # 取回撤绝对值
    f_drawdown = clamp(dd * 500)                # 8%回撤→40；16%→80；20%→100
    down, up = d.get("down", 1), max(1, d.get("up", 1))
    breadth = down / up
    f_breadth = clamp((breadth - 0.5) * 100)    # 1.0→50；1.5→100；0.5→0
    lu, ld = max(1, d.get("limit_up", 1)), d.get("limit_down", 0)
    f_limitdown = clamp((ld / lu) * 50)         # 跌停/涨停=1→50；2→100
    vol_pct = d.get("vol_pct", 0.5)
    f_vol = clamp(vol_pct * 100)

    fear_score = (WEIGHTS["fear"]["drawdown"] * f_drawdown +
                  WEIGHTS["fear"]["breadth"] * f_breadth +
                  WEIGHTS["fear"]["limitdown"] * f_limitdown +
                  WEIGHTS["fear"]["vol"] * f_vol)

    # ---- 贪婪分项 (0-100，越大越贪婪) ----
    ret20 = d.get("ret20", 0.0)
    g_momentum = clamp(ret20 * 500)             # 20日涨10%→50；20%→100
    g_limitup = clamp((lu / max(1, ld)) * 50)   # 涨停/跌停=1→50；2→100
    retail_net = d.get("retail_net", 0.0)
    g_retailin = clamp(retail_net * 200)        # 散户净流入5%→100；-5%→0
    above = d.get("above_ma20", 0.0)
    g_overbought = clamp(above * 500)           # 高于均线10%→50；20%→100

    greed_score = (WEIGHTS["greed"]["momentum"] * g_momentum +
                   WEIGHTS["greed"]["limitup"] * g_limitup +
                   WEIGHTS["greed"]["retailin"] * g_retailin +
                   WEIGHTS["greed"]["overbought"] * g_overbought)

    # XXFI 头条 = 恐惧指数（高=恐惧）；反向信号按 XXFI 绝对区间判定，
    # 不再做"恐惧分 vs 贪婪分"的相对比较（低恐惧=相对贪婪，应判 REDUCE/SELL）。
    xxfi = fear_score
    if xxfi >= 75:
        extreme = "FEAR"; contrarian = "BUY"
    elif xxfi >= 60:
        extreme = "FEAR"; contrarian = "ACCUMULATE"
    elif xxfi >= 40:
        extreme = "NEUTRAL"; contrarian = "HOLD"
    elif xxfi >= 25:
        extreme = "GREED"; contrarian = "REDUCE"
    else:
        extreme = "GREED"; contrarian = "SELL"

    level, advice = interpret(xxfi, greed_score)
    return {
        "XXFI": round(xxfi, 1),
        "GreedIndex": round(greed_score, 1),
        "extreme": extreme,
        "contrarian_signal": contrarian,
        "level": level,
        "advice": advice,
        "components": {
            "fear": {
                "drawdown": round(f_drawdown, 1),
                "breadth": round(f_breadth, 1),
                "limitdown": round(f_limitdown, 1),
                "vol": round(f_vol, 1),
            },
            "greed": {
                "momentum": round(g_momentum, 1),
                "limitup": round(g_limitup, 1),
                "retailin": round(g_retailin, 1),
                "overbought": round(g_overbought, 1),
            },
        },
        "inputs": d,
    }

def interpret(xxfi, greed):
    if xxfi >= 75:
        return ("极度恐惧（小旭式恐慌割肉区）",
                "历史校准：小旭在连跌后恐慌割肉，卖后多现 +9%~+24% 反弹。→ 反向强烈看多，分批低吸。")
    if xxfi >= 60:
        return ("恐惧（偏谨慎，她倾向割肉）",
                "市场情绪偏弱，但接近她‘卖飞’区。→ 逢低吸纳，避免跟风杀跌。")
    if xxfi >= 40:
        return ("中性",
                "恐惧与贪婪均衡，无明显反向极值。→ 按自身策略持有，不依赖本指标。")
    if xxfi >= 25:
        return ("偏贪婪（情绪偏热，她倾向追高）",
                "市场恐惧偏低、热度偏高。→ 逢高减仓，不追涨；小旭常在连续大涨后追高买在山顶。")
    return ("极度贪婪（小旭式追涨山顶区）",
            "历史校准：小旭追高买在山顶后多现 -12%~-21% 回落。→ 反向强烈看空，减仓避险。")

def main():
    ap = argparse.ArgumentParser(description="小旭恐惧指数 XXFI 计算")
    ap.add_argument("--drawdown", type=float, default=0.0)
    ap.add_argument("--ret20", type=float, default=0.0)
    ap.add_argument("--above_ma20", type=float, default=0.0)
    ap.add_argument("--up", type=int, default=1)
    ap.add_argument("--down", type=int, default=1)
    ap.add_argument("--limit_up", type=int, default=1)
    ap.add_argument("--limit_down", type=int, default=0)
    ap.add_argument("--vol_pct", type=float, default=0.5)
    ap.add_argument("--retail_net", type=float, default=0.0)
    ap.add_argument("--json", type=str, default=None, help="JSON 字符串传入全部字段")
    ap.add_argument("--demo", action="store_true", help="运行内置校准样例")
    args = ap.parse_args()

    if args.demo:
        print("==== 校准样例 1：恐慌割肉环境（对应 ST臻镭/江丰电子）====")
        d1 = {"drawdown": -0.15, "ret20": -0.10, "above_ma20": -0.06, "up": 800, "down": 4200,
              "limit_up": 20, "limit_down": 90, "vol_pct": 0.85, "retail_net": -0.04}
        print(json.dumps(compute(d1), ensure_ascii=False, indent=2))
        print("\n==== 校准样例 2：追高狂热环境（对应 博杰/光电/澜起）====")
        d2 = {"drawdown": -0.01, "ret20": 0.18, "above_ma20": 0.09, "up": 4100, "down": 900,
              "limit_up": 120, "limit_down": 5, "vol_pct": 0.45, "retail_net": 0.05}
        print(json.dumps(compute(d2), ensure_ascii=False, indent=2))
        return

    if args.json:
        d = json.loads(args.json)
    else:
        d = {
            "drawdown": args.drawdown, "ret20": args.ret20, "above_ma20": args.above_ma20,
            "up": args.up, "down": args.down, "limit_up": args.limit_up,
            "limit_down": args.limit_down, "vol_pct": args.vol_pct, "retail_net": args.retail_net,
        }
    print(json.dumps(compute(d), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
