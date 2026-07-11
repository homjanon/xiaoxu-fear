#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小旭恐惧指数 · 纯 akshare 取数器（用于 GitHub Actions / 无 tdx 环境）
================================================================

直接调用 akshare 拉取，无需通达信连接器：
  1. 上证指数日K  → 回撤 / 动量 / 均线偏离 / 波动率分位
  2. 当日盘面广度  → stock_market_activity_legu() 一次拿 上涨/下跌/涨停/跌停家数
                    （该接口只返「当日」，故本取数器天然产出「实时当日」恐惧指数）
  3. 当日主力/散户资金流向 → main_net / retail_net 真实来源（v2 统一口径：
                    stock_market_fund_flow() 的「主力/小单 净流入-净占比」÷100，
                    两者同口径可直接相减得「主力—散户背离」）
                    （开盘瞬间无数据；务必在盘后 16:30 执行，此时已定稿）

多源容错设计（关键）：akshare 单个函数只绑一个数据源，不会自动换源。
本取数器自行实现「源链」，任一源失败自动切下一个，全部失败才降级，绝不静默丢数据：
  - 广度：legu（legu host，本地/CI 均通）→ 新浪 stock_zh_a_spot（Sina host）→ 涨跌停池（EM，仅 limit 计数）
  - 资金流：东方财富 stock_market_fund_flow()（净占比口径，主力/小单同口径可相减得背离）。
            本机直连 push2his 被 TLS 中间设备掐；ensure_proxy() 自动探测本地代理(7890)并走代理；
            GitHub/CI 干净公网直连通。两端均取真值，仅当皆不可达才降级(主信号不受影响)。
拼装成 market json，可直接喂给 xiaoxu_fear_index.compute()。

用法：
  python fetch_market_akshare.py --vol_window 60
  # 或直接被 run_xxfi.py --akshare 调用
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoxu_fear_index import compute
from run_xxfi import max_drawdown, roll_vol   # 复用纯计算辅助函数，避免重复实现


def ensure_proxy():
    """探测本地代理(127.0.0.1:7890)是否可连；可连则注入 HTTPS_PROXY/HTTP_PROXY 环境变量，
    让 akshare 的东方财富资金流请求自动走代理，绕开本机对 push2his 直连的 TLS 掐断。

    背景：本机直连 push2his.eastmoney.com 的 API 会被 TLS 中间设备 Reset（server closed abruptly）；
    而本地 Clash 代理(7890)能通该 host。GitHub Actions 无 7890 端口、且为干净公网，
    探测失败自然走直连（直连通）。这样本地/远程两端都能拿到资金流真值，不依赖环境变量是否被继承。
    """
    import socket
    proxy = "http://127.0.0.1:7890"
    try:
        s = socket.create_connection(("127.0.0.1", 7890), timeout=3)
        s.close()
        for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            os.environ[k] = proxy
        return proxy
    except Exception:
        return None


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
    """盘面广度：多源兜底（legu → 新浪 spot → 涨跌停池）。

    返回 up/down/limit_up/limit_down。legu 与 新浪 spot 都能给完整涨跌家数；
    若两者皆败，仅用涨跌停池给 limit 计数，up/down 给中性 1/1（退化为指数版）。
    """
    import akshare as ak
    # 主源：legu（一次拿全，legu host 在本地/CI 均通）
    try:
        d = ak.stock_market_activity_legu()
        m = dict(zip(d["item"], d["value"]))
        return {
            "up": int(float(m.get("上涨", 0) or 0)),
            "down": int(float(m.get("下跌", 0) or 0)),
            "limit_up": int(float(m.get("涨停", 0) or 0)),
            "limit_down": int(float(m.get("跌停", 0) or 0)),
            "_breadth_source": "legu",
            "_breadth_date": str(m.get("统计日期", "")),
        }
    except Exception as e:
        print(f"[warn] legu 失败，尝试新浪 spot: {e}")
    # 兜底源1：新浪 stock_zh_a_spot（Sina host，本机代理不拦 eastmoney 时仍可用）
    try:
        s = ak.stock_zh_a_spot()
        up = int((s["涨跌幅"] > 0).sum())
        down = int((s["涨跌幅"] < 0).sum())
        limit_up = int((s["涨跌幅"] >= 9.8).sum())
        limit_down = int((s["涨跌幅"] <= -9.8).sum())
        return {
            "up": up, "down": down,
            "limit_up": limit_up, "limit_down": limit_down,
            "_breadth_source": "sina_spot",
        }
    except Exception as e:
        print(f"[warn] 新浪 spot 失败，尝试涨跌停池: {e}")
    # 兜底源2：涨跌停池（EM，仅给 limit 计数）
    try:
        from datetime import date
        dd = date.today().strftime("%Y%m%d")
        zt = ak.stock_zt_pool_em(date=dd)
        dt = ak.stock_zt_pool_dtgc_em(date=dd)
        return {
            "up": 1, "down": 1,
            "limit_up": len(zt), "limit_down": len(dt),
            "_breadth_source": "zt_pool_fallback",
        }
    except Exception as e2:
        print(f"[warn] 涨跌停池也失败，广度退化: {e2}")
        return {
            "up": 1, "down": 1, "limit_up": 1, "limit_down": 0,
            "_breadth_source": "failed",
        }


def fetch_fund_flow():
    """当日全市场主力/散户资金流向（东方财富大盘资金流，净占比口径）→ (main_net, retail_net, source)。

    统一用 stock_market_fund_flow()（全市场聚合，按日一行）取
    「主力净流入-净占比」与「小单净流入-净占比」，两者同为 净占比/100
    的带符号小数，可直接相减得到 v2「主力—散户背离」。
    本地若被公司代理拦 EM(push2his)，双双降级为 0；GitHub/CI 干净网络取真值。
    """
    import akshare as ak
    ensure_proxy()  # 本地代理可连则走代理绕开 push2his 直连掐断；GitHub 端直连
    try:
        df = ak.stock_market_fund_flow()
        if df is None or len(df) == 0:
            raise ValueError("空数据")
        row = df.iloc[-1]  # 最新交易日（全市场聚合，无市场分行）
        main = float(row["主力净流入-净占比"]) / 100.0
        retail = float(row["小单净流入-净占比"]) / 100.0
        return (main, retail), "eastmoney"
    except Exception as e:
        print(f"[warn] 东方财富大盘资金流失败（本地通常被代理拦），降级 main/retail=0: {e}")
        return (0.0, 0.0), "degraded"


def build_market_json(symbol="sh000001", vol_window=60):
    m = fetch_index(symbol, vol_window)
    b = fetch_breadth()
    (rn, mn), src = fetch_fund_flow()
    m.update(b)
    m["retail_net"] = rn                       # 散户(小单)净流入占比，盘后已定稿，失败降级 0
    m["main_net"] = mn                         # 主力净流入占比（v2 背离用），与 retail 同口径
    m["_retail_net_source"] = src              # 溯源：eastmoney / degraded
    m["_main_net_source"] = src
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
