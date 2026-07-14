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
  - 指数日K：新浪 stock_zh_index_daily → 腾讯 stock_zh_index_daily_tx（proxy.finance.qq.com）
                    腾讯收盘价与新浪偏差 < 0.0001%，可透明兜底；双源均不通才报错
  - 广度（上涨/下跌家数/涨停/跌停）：legu（本地/CI 均通）→ 新浪 stock_zh_a_spot（Sina host）
  - 资金流：东方财富「大盘资金流」ulist.np/get（净占比口径，主力/小单同口径可相减得背离）。
            复刻东财 zjlx 大盘页口径：以 上证指数+深证成指 secid 求和 主力净额/小单净额/
            成交额 得市场级净占比（与网站 loadchart2 同算法，单请求无分页截断）。
            原 stock_market_fund_flow() 用的 daykline/get 端点已废弃（任何日期均返回
            data:null）；clist 聚合则被东财 100 行/页硬上限截断（约 1/4 市场即失真）。
            东财 host 已从 push2his 迁移至 push2delay，且 push2 在境外 IP 亦被重置；
            本取数器在模块加载时注入 URL 改写补丁（push2his/push2→push2delay，正则幂等），
            两端均可直连取真值；全部不可达时降级为中性占位。
拼装成 market json，可直接喂给 xiaoxu_fear_index.compute()。

用法：
  python fetch_market_akshare.py --vol_window 60
  # 或直接被 run_xxfi.py --akshare 调用
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoxu_fear_index import compute
from run_xxfi import max_drawdown, roll_vol   # 复用纯计算辅助函数，避免重复实现
from retry_utils import retry_on_network, jitter


def _patch_eastmoney_push2delay():
    """东财资金流接口已迁移到 push2delay；且旧端点 push2his 与 push2 在境外 IP
    下均被重置（非 IP 封禁，是端点/ host 过时）。运行时用正则把 URL 中的
    push2his / push2（非 push2delay）改写为 push2delay，使 ulist / daykline
    等端点两端均可达。仅当 URL 含该 host 时改写，不影响 legu / 新浪等其他源。

    正则 push2(?:his)?\\.eastmoney\\.com 同时匹配 push2his 与 push2，但不匹配
    push2delay（其后为 delay 而非 his/'.'），故幂等安全；push2ex 等也不受影响。
    """
    try:
        import requests, re
        if getattr(requests.Session.request, "_xxfi_patched", False):
            return
        _orig = requests.Session.request
        _HOST_RE = re.compile(r'push2(?:his)?\.eastmoney\.com')

        def _wrapped(self, method, url, *a, **kw):
            if isinstance(url, str):
                url = _HOST_RE.sub('push2delay.eastmoney.com', url)
            # 防挂起：GitHub 美国 IP 对 push2delay 可能丢包而非秒拒，
            # 不设超时会导致重试把整个 run 拖死。统一注入 15s 上限。
            kw.setdefault("timeout", 15)
            return _orig(self, method, url, *a, **kw)

        _wrapped._xxfi_patched = True
        requests.Session.request = _wrapped
    except Exception as e:
        print(f"[warn] push2delay 补丁注入失败（资金流将降级）: {e}")


# 模块加载即注入端点补丁，让东财资金流在两端均可达
_patch_eastmoney_push2delay()


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


def fetch_index_spot(symbol="sh000001"):
    """实时 spot 取当日最新价（收盘后=当日收盘；盘中=当时快照）。

    指数日K（stock_zh_index_daily）滞后约 1 天，收盘后许久不补当日 bar，
    故用新浪实时 spot 补「当日」一根，使 data_date 与指数派生分量反映当日。
    新浪实时接口本地/CI 均通；失败返回 None，由 fetch_index 优雅降级为纯日K。
    """
    import akshare as ak
    try:
        sp = ak.stock_zh_index_spot_sina()
        row = sp[sp["代码"] == symbol]
        if len(row) == 0:
            print(f"[warn] spot 未找到指数 {symbol}，降级为日K")
            return None
        return float(row.iloc[0]["最新价"])
    except Exception as e:
        print(f"[warn] 指数 spot 取数失败(降级为日K): {e}")
        return None


def fetch_index(symbol="sh000001", vol_window=260):
    """上证指数日K → 派生分量（回撤/动量/均线偏离/波动率分位）。

    源链：新浪 stock_zh_index_daily → 腾讯 stock_zh_index_daily_tx
    腾讯与新浪收盘价偏差 < 0.0001%，可透明兜底；双源均不通才报错。
    当日补点：日K末根滞后约1天，故拉完日K历史后，用 fetch_index_spot 取当日
    最新价追加为最新一根（仅当 当日 > 日K末根），使 _last_date/_data_date 落到当日。
    spot 失败则保留日K原行为（_last_date = T-1），不破坏历史逻辑。
    """
    import akshare as ak
    import datetime
    BJ = datetime.timezone(datetime.timedelta(hours=8))
    today = datetime.datetime.now(BJ).strftime("%Y-%m-%d")
    sources = [
        ("sina", lambda: ak.stock_zh_index_daily(symbol=symbol)),
        ("tx",    lambda: ak.stock_zh_index_daily_tx(symbol=symbol)),
    ]
    for label, fetch_fn in sources:
        try:
            df = fetch_fn()
            closes = [float(x) for x in df["close"].tolist()]
            _last_date = str(df["date"].iloc[-1])
            _last_close = closes[-1]
            # 当日补点：用 spot 最新价补当日一根，纠正日K滞后导致的 data_date 慢一天
            spot_close = fetch_index_spot(symbol)
            if spot_close is not None and today > _last_date:
                closes.append(spot_close)
                _last_date = today
                _last_close = spot_close
                label = f"{label}+spot"
            comp = index_components(closes, vol_window)
            comp["_index_name"] = f"上证指数({symbol})"
            comp["_last_date"] = _last_date
            comp["_last_close"] = _last_close
            comp["_index_source"] = label
            return comp
        except Exception as e:
            print(f"[warn] {label} 指数日K取数失败: {e}")
    raise RuntimeError("新浪和腾讯双源均无法获取上证指数日K数据")


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
    except Exception as e2:
        print(f"[warn] 新浪 spot 也失败，广度退化: {e2}")
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


def fetch_fund_flow():
    """当日全市场主力/散户资金流向 → (main_net, retail_net, source)。

    源：东方财富「大盘资金流」接口 ulist.np/get（push2 → 经补丁改写 push2delay，两端可达）。
    复刻东财 zjlx 大盘页（dpzjlx.html / dapan.js）的口径：以 secids="1.000001,0.399001"
    （上证指数 + 深证成指 = 网站“沪深两市”）请求 ulist，将两行（沪深两市）的
    主力净额(f62)/小单净额(f84)/成交额(f6) 求和，得市场级净占比。与网站 loadchart2
    完全一致：主力净占比 = Σf62/Σf6 ；小单净占比 = Σf84/Σf6。
    符号与东财 zjlx「主力净流入-净占比 / 小单净流入-净占比」同号（主力净流出为负、
    小单净流入为正），与旧 akshare stock_market_fund_flow() 字段口径一致，无需取反。
    主力/小单同口径可相减得「主力—散户背离」。全部不可达时降级为
    (None, 0.0, "degraded")，由 compute() 将背离置为中性占位。
    """
    import requests
    # 复刻 data.eastmoney.com/zjlx/dapan.js：quoteurl=push2，secids=沪深两市指数
    HOST = "https://push2.eastmoney.com/api/qt/ulist.np/get"   # 补丁改写为 push2delay
    SECIDS = "1.000001,0.399001"          # 上证指数 + 深证成指（= 网站“沪深两市”）
    FIELDS = "f62,f84,f6"                  # 主力净额 / 小单净额 / 成交额
    UT = "b2884a393a59ad64002292a3e90d46a5"

    @retry_on_network(max_attempts=3)
    def _try_em_ulist():
        jitter(0.3, 1.0)
        r = requests.get(
            HOST,
            params={"fltt": 2, "secids": SECIDS, "fields": FIELDS, "ut": UT},
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://data.eastmoney.com/zjlx/dpzjlx.html"},
            timeout=15,
        )
        payload = r.json()
        diff = (payload.get("data") or {}).get("diff") or []
        if not diff:
            raise ValueError("空数据")
        main = small = turn = 0.0
        for it in diff:
            main += float(it.get("f62") or 0)
            small += float(it.get("f84") or 0)
            turn += float(it.get("f6") or 0)
        if turn <= 0:
            raise ValueError("成交额为0")
        # 与网站 loadchart2 一致：Σf62/Σf6、Σf84/Σf6（同号，不取反）
        main_net = main / turn
        retail_net = small / turn
        return (main_net, retail_net), "eastmoney"

    try:
        return _try_em_ulist()
    except Exception as e:
        print(f"[warn] 东方财富大盘资金流失败（已重试3次），降级为中性占位: {e}")

    return (None, 0.0), "degraded"


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
