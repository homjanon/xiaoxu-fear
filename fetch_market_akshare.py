#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小旭恐惧指数 · 纯 akshare 取数器（用于 GitHub Actions / 无 tdx 环境）
================================================================

直接调用 akshare 拉取，无需通达信连接器：
  1. 上证指数日K  → 回撤 / 动量 / 均线偏离 / 波动率分位
  2. 当日盘面广度  → stock_market_activity_legu() 一次拿 上涨/下跌/涨停/跌停家数
                    （该接口只返「当日」，故本取数器天然产出「实时当日」恐惧指数）
  3. 当日主力资金流向 → stock_individual_fund_flow_rank(indicator="今日")
                    算「净流入为正的家数占比」作为 retail_net 真实来源
                    （开盘瞬间无数据；务必在盘后 16:30 执行，此时已定稿）
拼装成 market json，可直接喂给 xiaoxu_fear_index.compute()。

降级：legu 失败退用涨跌停池计数；资金流失败 retail_net 退 0（不阻塞主流程）。

用法：
  python fetch_market_akshare.py --vol_window 60
  # 或直接被 run_xxfi.py --akshare 调用
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoxu_fear_index import compute
from run_xxfi import max_drawdown, roll_vol   # 复用纯计算辅助函数，避免重复实现


def index_components(closes, vol_window=260):
    """从收盘价序列算出指数派生分量（与 run_xxfi.index_components 口径一致）。"""
    last20 = closes[-20:]
    dd = max_drawdown(last20)
    ret20 = last20[-1] / last20[0] - 1
    ma20 = sum(last20) / len(last20)
    above = (closes[-1] - ma20) / ma20
    vols = roll_vol(closes, 20)
    cur = vols[-1]
    win = vols[-vol_window:]
    vol_pct = sum(1 for v in win if v <= cur) / len(win) if win else 0.0
    return {
        "drawdown": dd, "ret20": ret20, "above_ma20": above,
        "vol_pct": vol_pct, "vol_window": vol_window,
    }


def fetch_index(symbol="sh000001", vol_window=260):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=symbol)
    closes = [float(x) for x in df["close"].tolist()]
    comp = index_components(closes, vol_window)
    comp["_index_name"] = f"上证指数({symbol})"
    comp["_last_date"] = str(df["date"].iloc[-1])
    comp["_last_close"] = closes[-1]
    return comp


def fetch_breadth():
    """优先 legu（一次拿全），失败退用涨跌停池计数。"""
    import akshare as ak
    try:
        d = ak.stock_market_activity_legu()
        m = dict(zip(d["item"], d["value"]))
        return {
            "up": int(float(m.get("上涨", 0) or 0)),
            "down": int(float(m.get("下跌", 0) or 0)),
            "limit_up": int(float(m.get("涨停", 0) or 0)),
            "limit_down": int(float(m.get("跌停", 0) or 0)),
            "retail_net": 0.0,
            "_breadth_source": "legu",
            "_breadth_date": str(m.get("统计日期", "")),
        }
    except Exception as e:
        # 兜底：涨跌停池按当日计数（缺涨跌家数时给中性 1/1，让广度分量退化为指数版）
        try:
            from datetime import date
            dd = date.today().strftime("%Y%m%d")
            zt = ak.stock_zt_pool_em(date=dd)
            dt = ak.stock_zt_pool_dtgc_em(date=dd)
            return {
                "up": 1, "down": 1,
                "limit_up": len(zt), "limit_down": len(dt),
                "retail_net": 0.0,
                "_breadth_source": "zt_pool_fallback",
            }
        except Exception as e2:
            return {
                "up": 1, "down": 1, "limit_up": 1, "limit_down": 0,
                "retail_net": 0.0, "_breadth_source": "failed",
            }


def fetch_fund_flow():
    """当日全市场主力资金流向，作为 retail_net 的真实来源。

    用 stock_individual_fund_flow_rank(indicator="今日") 取全市场个股主力净流入，
    算「净流入为正的家数占比」= (pos - neg) / total，范围约 [-1, 1]，正=多数个股资金净流入。
    开盘瞬间无数据，必须在盘后执行（CI 设为北京 16:30）。
    eastmoney 源：CI 干净网络可用；本机若被代理/eastmoney 限流则降级 retail_net=0。
    """
    import akshare as ak
    try:
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        if df is None or len(df) == 0:
            return 0.0
        col = next((c for c in df.columns if "主力净流入" in c), None)
        if col is None:
            return 0.0
        net = df[col].astype(float)
        total = len(net)
        if total == 0:
            return 0.0
        pos = int((net > 0).sum())
        neg = int((net < 0).sum())
        return float((pos - neg) / total)
    except Exception as e:
        print(f"[warn] 资金流获取失败，降级 retail_net=0: {e}")
        return 0.0


def build_market_json(symbol="sh000001", vol_window=60):
    m = fetch_index(symbol, vol_window)
    m.update(fetch_breadth())
    m["retail_net"] = fetch_fund_flow()   # 真实资金流向（盘后已定稿），失败降级 0
    m["_breadth_provided"] = True
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="小旭恐惧指数 · akshare 取数器")
    ap.add_argument("--symbol", default="sh000001", help="指数代码，默认上证指数 sh000001")
    ap.add_argument("--vol_window", type=int, default=60, help="波动率分位窗口(交易日)，默认60(纯近期情绪)")
    args = ap.parse_args()
    mj = build_market_json(args.symbol, args.vol_window)
    print(json.dumps(mj, ensure_ascii=False, indent=2))
    # 顺便打印一次计算结果，便于本地调试
    res = compute(mj)
    print(f"\n→ XXFI={res['XXFI']}  贪婪={res['GreedIndex']}  等级={res['level']}  信号={res['contrarian_signal']}")
