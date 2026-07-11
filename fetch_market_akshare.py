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
  - 广度（上涨/下跌家数/涨停/跌停）：legu（本地/CI 均通）→ 新浪 stock_zh_a_spot（Sina host）
                    → 东财涨跌停池 stock_zt_pool_em
  - 资金流：东方财富 stock_market_fund_flow()（净占比口径，主力/小单同口径可相减得背离），
            GitHub/CI 干净公网直连通；
            本机直连 push2his 被出口 IP 拦截时：retail_net 回退同花顺个股资金流聚合代理，
            main_net 回退 GitHub Pages 已发布值（xxfi_report.json），否则中性降级。
拼装成 market json，可直接喂给 xiaoxu_fear_index.compute()。

用法：
  python fetch_market_akshare.py --vol_window 60
  # 或直接被 run_xxfi.py --akshare 调用
"""
import sys, os, json, argparse, datetime, ssl, gzip, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoxu_fear_index import compute
from run_xxfi import max_drawdown, roll_vol   # 复用纯计算辅助函数，避免重复实现
from retry_utils import retry_on_network, jitter, random_ua


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


def _fetch_up_down():
    """上涨/下跌家数两源兜底：legu → 新浪 spot。返回 (up, down, src)。"""
    import akshare as ak
    try:
        d = ak.stock_market_activity_legu()
        m = dict(zip(d["item"], d["value"]))
        return int(float(m.get("上涨", 0) or 0)), int(float(m.get("下跌", 0) or 0)), "legu"
    except Exception as e:
        print(f"[warn] legu 失败，尝试新浪 spot: {e}")
    try:
        s = ak.stock_zh_a_spot()
        return int((s["涨跌幅"] > 0).sum()), int((s["涨跌幅"] < 0).sum()), "sina_spot"
    except Exception as e:
        print(f"[warn] 新浪 spot 失败，up/down 退化为 1/1: {e}")
        return 1, 1, "failed"


def fetch_breadth():
    """盘面广度：多源容错，本地与 GitHub 同源以保证指数一致性。

    源链顺序（两端一致）：legu → 新浪 spot → 东财涨跌停池。
      - legu 在本地/CI 均直连通 → 主表口径两端一致（关键）。
    两端均尽量取真值；仅当皆不可达才降级。
    """
    import akshare as ak
    # 主源：legu（一次拿全，本地/CI 均通，保证两端同源一致性）
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
    # 兜底源1：新浪 stock_zh_a_spot（Sina host）
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
        print(f"[warn] 新浪 spot 失败，尝试东财涨跌停池兜底: {e}")
    # 兜底源：涨跌停池（EM，仅给 limit 计数）
    try:
        dd = datetime.date.today().strftime("%Y-%m-%d")
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


def _cn_num(s):
    """把带中文单位（万/亿）的数值字符串转成 float（元）。无法解析返回 0.0。"""
    s = str(s).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "--", "None", "nan"):
        return 0.0
    mult = 1.0
    if "亿" in s:
        mult = 1e8
    elif "万" in s:
        mult = 1e4
    s = s.replace("亿", "").replace("万", "")
    try:
        return float(s) * mult
    except Exception:
        return 0.0


def _fetch_retail_tonghuashun():
    """同花顺个股资金流聚合，作为零售净流入占比的本地代理。

    同花顺无「小单净占比」拆分，只有个股整体净额；这里汇总全市场个股 净额/成交额
    得到整体资金净流入比率，作为 retail_net 的近似（标签 tonghuashun_proxy）。
    本地东财被拦截时启用；GitHub 走东财真值不经过此分支。
    """
    import akshare as ak
    try:
        df = ak.stock_fund_flow_individual(symbol="即时")
        net = df["净额"].apply(_cn_num).sum()
        amt = df["成交额"].apply(_cn_num).sum()
        if amt <= 0:
            return 0.0, "tonghuashun_proxy(无成交额)"
        return net / amt, "tonghuashun_proxy"
    except Exception as e:
        print(f"[warn] 同花顺零售代理失败，retail=0: {e}")
        return 0.0, "degraded"


def _fetch_published_fund_flow():
    """从 GitHub Pages 抓取最近一次发布报告的 inputs.main_net / inputs.retail_net，
    用于本地对齐「背离」与「散户净流入」两个维度。

    需要 xxfi_report.json 已发布到 Pages docs/ 目录。
    这是「本地 vs GitHub 一致性」收口的关键：本地无主力/散户净占比源时，采用云端已算出的真值，
    使本地与 GitHub 完全对齐。若抓取失败 → 返回 (None, None)，调用方优雅降级。
    """
    url = "https://homjanon.github.io/xiaoxu-fear/xxfi_report.json"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": random_ua()})
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            j = json.loads(r.read().decode("utf-8"))
        inp = j.get("inputs") or {}
        return inp.get("main_net"), inp.get("retail_net")
    except Exception:
        return None, None


def fetch_fund_flow():
    """当日全市场主力/散户资金流向 → (main_net, retail_net, source)。

    源链顺序（两端一致）：东方财富 stock_market_fund_flow()（净占比口径，主力/小单同口径可相减得背离）。
    两端均试东财真值；本地若被出口 IP 拦截则：
        retail_net 回退同花顺个股资金流聚合代理（tonghuashun_proxy）；
        main_net 回退 GitHub Pages 已发布值。
    全部不可达才降级为 (None, degraded)，由 compute() 将背离置为中性占位。
    """
    import akshare as ak
    ensure_proxy()  # 本地代理可连则走代理绕开 push2his 直连掐断；GitHub 端直连

    @retry_on_network(max_attempts=3)
    def _try_em_fund_flow():
        jitter(0.3, 1.0)
        df = ak.stock_market_fund_flow()
        if df is None or len(df) == 0:
            raise ValueError("空数据")
        row = df.iloc[-1]
        main = float(row["主力净流入-净占比"]) / 100.0
        retail = float(row["小单净流入-净占比"]) / 100.0
        return (main, retail), "eastmoney"

    try:
        return _try_em_fund_flow()
    except Exception as e:
        print(f"[warn] 东方财富大盘资金流失败（本地通常被出口拦，已重试3次），尝试本地兜底源: {e}")

    # —— 本地兜底：GitHub 已发布值回填 main+retail ——
    pub_main, pub_retail = _fetch_published_fund_flow()
    if pub_main is not None or pub_retail is not None:
        main = pub_main
        retail = pub_retail if pub_retail is not None else _fetch_retail_tonghuashun()[0]
        return (main, retail), "github_published(对齐云端)"

    # GitHub 未发布时：retail 同花顺代理，main 降级
    retail, r_src = _fetch_retail_tonghuashun()
    combined = f"local_fallback(retail={r_src},main=degraded)"
    return (None, retail), combined


def build_market_json(symbol="sh000001", vol_window=60):
    m = fetch_index(symbol, vol_window)
    b = fetch_breadth()
    (mn, rn), src = fetch_fund_flow()          # fetch_fund_flow 返回 (main_net, retail_net)
    m.update(b)
    m["main_net"] = mn                         # 主力净流入占比（v2 背离用），与 retail 同口径
    m["retail_net"] = rn                       # 散户(小单)净流入占比，盘后已定稿，失败降级 0/代理
    m["_retail_net_source"] = src              # 溯源：eastmoney / local_fallback(...)
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
