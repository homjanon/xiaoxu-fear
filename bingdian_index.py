#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股冰点 · 纯计算（仅标准库，零依赖，仿 xiaoxu_fear_index.py 风格）
================================================================

把「冰点取数器」采集到的 4 维度实测值，映射为「是否冰点」判定。
不依赖任何外部库，与 XXFI（小旭恐惧指数）完全独立 —— 不影响其任何原始计算/展示。

设计立场（与《A股冰点量化框架.md》一致）：
  冰点 = 市场情绪极度恐慌、带血筹码居多的状态，是触发短线买入的关键时机；
  真正的冰点一年 3 次以内，不符合纪律就绝不出手。

4 个独立维度（全部同时满足 = 冰点）：
  D1 下跌广度    : 下跌家数 >= 4000  且  下跌占比 >= 85%
  D2 指数/ETF跌幅: 上证 <= -2.0%  且  创业板指 <= -2.5%  且  核心ETF跌幅<=-2.5%占比 >= 60%
  D3 跌停数量    : 跌停 >= 50  且  跌停/涨停 >= 3   （板块差异化·剔除ST）
  D4 放量恐慌    : 放量倍数(当日上证成交额 / 上证近20日均) >= 1.3

输入字段（由 fetch_bingdian_akshare.build_bingdian_inputs() 产出）：
  down, total, down_ratio            # D1
  sh_chg, cyb_chg, etf_down_ratio   # D2
  limit_down, limit_up, ld_lu_ratio # D3（板块差异化·剔除ST 后的权威值）
  volume_mult                        # D4
  溯源标记 _src_D1 / _src_D2 / _src_D3 / _src_D4：
      "legu" / "eastmoney_spot" / "eastmoney_index" / "eastmoney_etf" /
      "tencent_daily" / "暂未获取" / "legu(聚合·未板块区分)" 等
  任一维度取数失败 → 对应字段置为字符串 "暂未获取"，pass=None；全部失败 → 冰点整体"暂未获取"。
"""
import json
from typing import Any, Dict, List, Optional

# ---------------- 阈值（与《A股冰点量化框架.md》严格一致） ----------------
TH = {
    "D1_down_count": 4000,        # 下跌家数下限
    "D1_down_ratio": 0.85,        # 下跌占比下限
    "D2_sh": -2.0,                # 上证综指跌幅上限(%)
    "D2_cyb": -2.5,               # 创业板指跌幅上限(%)
    "D2_etf_ratio": 0.60,         # 核心ETF跌幅<=-2.5%占比下限
    "D3_limit_down": 50,          # 跌停家数下限
    "D3_ld_lu_ratio": 3.0,        # 跌停/涨停比下限
    "D4_volume_mult": 1.3,        # 放量倍数下限
}


def _ok(v: Any) -> bool:
    """值是否可用（非 None 且非 '暂未获取' 字符串）"""
    return v is not None and v != "暂未获取"


def _num(v: Any):
    if not _ok(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------- 各维度展示格式化 ----------------
def _fmt_d1(down, total, ratio) -> str:
    if not (_ok(down) and _ok(total) and _ok(ratio)):
        return "暂未获取"
    return f"下跌 {int(down)}/{int(total)}（{float(ratio)*100:.1f}%）"

def _fmt_d2(sh, cyb, etf) -> str:
    if not (_ok(sh) and _ok(cyb) and _ok(etf)):
        return "暂未获取"
    return f"上证 {float(sh):.2f}% 创业 {float(cyb):.2f}% · ETF跌 {float(etf)*100:.0f}%"

def _fmt_d3(ld, lu, lr) -> str:
    if not (_ok(ld) and _ok(lu) and _ok(lr)):
        return "暂未获取"
    return f"跌停 {int(ld)}/涨停 {int(lu)}（比 {float(lr):.1f}）"

def _fmt_d4(vm) -> str:
    if not _ok(vm):
        return "暂未获取"
    return f"{float(vm):.2f} 倍"


def compute(d: Dict[str, Any]) -> Dict[str, Any]:
    """输入 4 维度实测 + 溯源 → 冰点判定 dict。

    返回结构（供 render_html / 输出 JSON 直接消费）：
      verdict / verdict_text / verdict_emoji
      dimensions: [{key,name,value,threshold,pass,source}, ...]   # pass: bool|None
      missing: [维度key...]   # 取数失败（暂未获取）的维度
      _data_date
    """
    # ---- D1 下跌广度 ----
    down, total, ratio = d.get("down"), d.get("total"), d.get("down_ratio")
    d1_avail = _ok(down) and _ok(total) and _ok(ratio)
    d1 = d1_avail and int(_num(down)) >= TH["D1_down_count"] and float(_num(ratio)) >= TH["D1_down_ratio"]

    # ---- D2 指数/ETF 跌幅 ----
    sh, cyb, etf = d.get("sh_chg"), d.get("cyb_chg"), d.get("etf_down_ratio")
    d2_avail = _ok(sh) and _ok(cyb) and _ok(etf)
    d2 = d2_avail and float(_num(sh)) <= TH["D2_sh"] and float(_num(cyb)) <= TH["D2_cyb"] \
        and float(_num(etf)) >= TH["D2_etf_ratio"]

    # ---- D3 跌停数量（板块差异化·剔除ST 后的权威值）----
    ld, lu, ldl = d.get("limit_down"), d.get("limit_up"), d.get("ld_lu_ratio")
    d3_avail = _ok(ld) and _ok(lu) and _ok(ldl)
    d3 = d3_avail and int(_num(ld)) >= TH["D3_limit_down"] and float(_num(ldl)) >= TH["D3_ld_lu_ratio"]

    # ---- D4 放量恐慌 ----
    vm = d.get("volume_mult")
    d4_avail = _ok(vm)
    d4 = d4_avail and float(_num(vm)) >= TH["D4_volume_mult"]

    verdict = bool(d1 and d2 and d3 and d4)

    dimensions = [
        {
            "key": "D1", "name": "下跌广度",
            "value": _fmt_d1(down, total, ratio),
            "threshold": f"下跌≥{TH['D1_down_count']} 且 占比≥{TH['D1_down_ratio']*100:.0f}%",
            "pass": (d1 if d1_avail else None),
            "source": d.get("_src_D1", "—"),
        },
        {
            "key": "D2", "name": "指数/ETF跌幅",
            "value": _fmt_d2(sh, cyb, etf),
            "threshold": f"上证≤{TH['D2_sh']}% 创业≤{TH['D2_cyb']}% ETF跌≥{TH['D2_etf_ratio']*100:.0f}%",
            "pass": (d2 if d2_avail else None),
            "source": d.get("_src_D2", "—"),
        },
        {
            "key": "D3", "name": "跌停数量",
            "value": _fmt_d3(ld, lu, ldl),
            "threshold": f"跌停≥{TH['D3_limit_down']} 且 比≥{TH['D3_ld_lu_ratio']:.0f}",
            "pass": (d3 if d3_avail else None),
            "source": d.get("_src_D3", "—"),
        },
        {
            "key": "D4", "name": "放量恐慌",
            "value": _fmt_d4(vm),
            "threshold": f"放量倍数≥{TH['D4_volume_mult']}",
            "pass": (d4 if d4_avail else None),
            "source": d.get("_src_D4", "—"),
        },
    ]

    missing = [dim["key"] for dim in dimensions if dim["pass"] is None]

    return {
        "verdict": verdict,
        "verdict_text": "冰点" if verdict else "非冰点",
        "verdict_emoji": "🔥" if verdict else "🧊",
        "verdict_full": ("🔥 冰点触发 · 极端恐慌带血筹码" if verdict
                         else "🧊 未至冰点 · 纪律不出手"),
        "dimensions": dimensions,
        "missing": missing,
        "_data_date": str(d.get("_data_date", ""))[:10],
    }


def main():
    ap = __import__("argparse").ArgumentParser(description="A股冰点 纯计算（演示）")
    ap.add_argument("--json", default=None, help="直接传入冰点输入 JSON 字符串")
    ap.add_argument("--demo", action="store_true", help="内置冰点日样例")
    args = ap.parse_args()
    if args.demo:
        d = {
            "down": 5100, "total": 5400, "down_ratio": 5100/5400,
            "sh_chg": -3.6, "cyb_chg": -3.5, "etf_down_ratio": 0.75,
            "limit_down": 133, "limit_up": 12, "ld_lu_ratio": 133/12,
            "volume_mult": 1.8,
            "_src_D1": "legu", "_src_D2": "eastmoney_index",
            "_src_D3": "eastmoney_spot", "_src_D4": "tencent_daily",
            "_data_date": "2026-03-23",
        }
    elif args.json:
        d = json.loads(args.json)
    else:
        print("需 --demo 或 --json"); raise SystemExit(1)
    print(json.dumps(compute(d), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
