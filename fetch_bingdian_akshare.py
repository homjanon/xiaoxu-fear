#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股冰点 · akshare 取数器（仿 fetch_market_akshare.py，含 push2delay 补丁 + 多源兜底）
================================================================================

数据优先级（应你的要求）：**legu 源作为主力 → 东财兜底 → 都无法获取则"暂未获取"**。

  D1 下跌广度   : legu stock_market_activity_legu() 主 → 东财 stock_zh_a_spot_em 兜底（逐股）
  D3 跌停数量   : legu 聚合跌停（板块限制感知）主 → 东财 stock_zh_a_spot_em 逐股兜底。
                 实测：常态日两口径差 2~4 只、冰点日(≥50)差 <10 只，对"跌停≥50 且 比≥3"阈值判定一致；
                 故主用 legu 省去 ~1min 重调用，东财逐股仅 legu 不可达时调用（保留板块差异化+剔除ST 精确兜底）。
  D2 指数/ETF   : 东财 stock_zh_index_spot_em("沪深重要指数") + fund_etf_spot_em（42只核心ETF白名单）
  D4 放量       : 东财/腾讯 上证成交额 vs 上证近20日均值（腾讯 stock_zh_index_daily_tx）

多源容错（绝不静默丢数据）：任一维度取数失败 → 该维度标"暂未获取"；全部失败 → 冰点整体"暂未获取"。
东财端点已迁移 push2*，本模块注入正则幂等补丁（push2/push2his → push2delay，HTTP/1.1 可通）。
"""
import sys, os, re, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import akshare as ak


# ---------------- 东财 push2delay 连通补丁（与 fetch_market_akshare 同思路） ----------------
def _patch_eastmoney_push2delay():
    try:
        import requests
        if getattr(requests.Session.request, "_bd_patched", False):
            return
        _orig = requests.Session.request
        _HOST_RE = re.compile(r'push2(?:his)?\.eastmoney\.com')

        def _w(self, method, url, *a, **k):
            if isinstance(url, str):
                url = _HOST_RE.sub('push2delay.eastmoney.com', url)
            k.setdefault("timeout", 15)
            return _orig(self, method, url, *a, **k)

        _w._bd_patched = True
        requests.Session.request = _w
    except Exception as e:
        print(f"[warn] 冰点 push2delay 补丁注入失败（东财源将降级）: {e}")


_patch_eastmoney_push2delay()


# ---------------- A股核心ETF白名单（固化，与《A股冰点量化框架.md》一致：宽基11 + 行业31 = 42） ----------------
# 已剔除港股通/恒生/中韩/纳指/标普/商品(原油黄金豆粕)等跨境与商品ETF，避免稀释"批量下跌"指标
A_SHARE_CORE_ETF = [
    # 宽基指数（含588750科创芯片ETF，半导体偏重已确认可接受）
    '510300', '510500', '159845', '159915', '588000', '510050', '159901', '159338',
    '159595', '159628', '588750',
    # 主要行业/主题（31）
    '512000', '512800', '512660',                      # 券商/银行/军工
    '588200', '512480', '516160', '159755', '515790',  # 芯片/半导体/新能源/电池/光伏
    '512010', '512170', '159928', '512690', '515170', '159996', '516110',  # 医药/医疗/消费/酒/食品/家电/汽车
    '515220', '512400', '159870', '159825', '512980', '159998', '515880',  # 煤炭/有色/化工/农业/传媒/计算机/通信
    '512200', '515210', '159611', '516950', '512580',  # 房地产/钢铁/电力/基建/环保
    '510880', '159819', '562500', '159852',            # 红利/人工智能/机器人/软件
]


def _board_flags(df):
    """按代码前缀识别板块；ST/*ST 单独标记（不纳入跌停）。返回各板块布尔掩码。"""
    code = df['代码'].astype(str).str.zfill(6)
    name = df['名称'].astype(str)
    is_st = name.str.strip().str.upper().str.startswith(('ST', '*ST'))
    is_cyb = code.str.startswith(('30', '301'))            # 创业板 20%板
    is_kcb = code.str.startswith('688')                    # 科创板 20%板
    is_bse = code.str.startswith(('8', '43', '920'))       # 北交所 30%板
    is_main = ~(is_st | is_cyb | is_kcb | is_bse)          # 主板(含B股) 10%板
    return is_st, is_cyb, is_kcb, is_bse, is_main


def _bj_today():
    BJ = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(BJ).strftime("%Y-%m-%d")


# ---------------- legu 主源（D1/D3 聚合广度） ----------------
def fetch_breadth_legu():
    """legu 盘面广度（一次拿全 上涨/下跌/涨停/跌停家数）。
    本地/CI(美IP) 均通，是广度主源。失败返回 (None, False)。"""
    try:
        d = ak.stock_market_activity_legu()
        m = dict(zip(d["item"], d["value"]))
        down = int(float(m.get("下跌", 0) or 0))
        up = int(float(m.get("上涨", 0) or 0))
        flat = int(float(m.get("平盘", 0) or 0))
        total = int(float(m.get("股票总数", 0) or 0)) or (up + down + flat)
        lu = int(float(m.get("涨停", 0) or 0))
        ld = int(float(m.get("跌停", 0) or 0))
        return {"down": down, "total": total, "limit_up": lu, "limit_down": ld,
                "_src": "legu"}, True
    except Exception as e:
        print(f"[warn] legu 失败（将落东财spot）: {e}")
        return None, False


# ---------------- 东财逐股 spot（D1兜底 + D3板块差异化 唯一数据源） ----------------
def fetch_spot_em():
    """全量A股实时 spot → D1/D3 兜底（板块差异化·剔除ST 精确值）。
    仅当 legu 不可达时调用（重调用，~1min 全市场58页）；正常CI不触发。
    失败返回 (None, False)。"""
    try:
        df = ak.stock_zh_a_spot_em()
        chg = df['涨跌幅']
        n = len(df)
        down = int((chg < 0).sum())
        # D3 跌停/涨停：按各板块涨跌幅限制判定；ST/*ST 不纳入
        # （2026-07-06 起主板ST已由5%放宽至10%，但ST本身不纳入跌停统计）
        is_st, is_cyb, is_kcb, is_bse, is_main = _board_flags(df)
        ld = int(((chg <= -9.5) & is_main).sum()
                 + ((chg <= -19.5) & (is_cyb | is_kcb)).sum()
                 + ((chg <= -29.5) & is_bse).sum())
        lu = int(((chg >= 9.5) & is_main).sum()
                 + ((chg >= 19.5) & (is_cyb | is_kcb)).sum()
                 + ((chg >= 29.5) & is_bse).sum())
        ratio = down / n if n else 0.0
        return {"total": n, "down": down, "down_ratio": ratio,
                "limit_up": lu, "limit_down": ld, "ld_lu_ratio": ld / max(lu, 1),
                "_src": "eastmoney_spot"}, True
    except Exception as e:
        print(f"[warn] 东财spot失败（D1/D3 降级）: {e}")
        return None, False


# ---------------- D2 指数 spot（东财，快，单页） ----------------
def fetch_index_em():
    """上证综指 / 创业板指 涨跌幅 + 上证成交额（D2/D4 用）。失败降级 None。"""
    try:
        idx = ak.stock_zh_index_spot_em(symbol="沪深重要指数")
        sh = idx[idx['名称'] == '上证指数']
        cyb = idx[idx['名称'] == '创业板指']
        sh_chg = float(sh['涨跌幅'].values[0]) if len(sh) else None
        cyb_chg = float(cyb['涨跌幅'].values[0]) if len(cyb) else None
        sh_amt = float(sh['成交额'].values[0]) if len(sh) else None  # 元
        return {"sh_chg": sh_chg, "cyb_chg": cyb_chg, "sh_amount": sh_amt,
                "_src": "eastmoney_index"}
    except Exception as e:
        print(f"[warn] 指数spot失败（D2降级）: {e}")
        return {"sh_chg": None, "cyb_chg": None, "sh_amount": None,
                "_src": "暂未获取"}


# ---------------- D2 核心ETF spot（东财，白名单过滤） ----------------
def fetch_etf_em():
    """固化42只核心ETF内，跌幅<=-2.5%占比 + 平均涨跌幅（D2）。失败降级 None。"""
    try:
        etf = ak.fund_etf_spot_em()
        core = etf[etf['代码'].isin(A_SHARE_CORE_ETF)]
        missing = sorted(set(A_SHARE_CORE_ETF) - set(core['代码']))
        if missing:
            print(f"  [提示] 白名单中 {len(missing)} 只未在实时数据找到: {missing}")
        ratio = (core['涨跌幅'] <= -2.5).sum() / max(len(core), 1)
        avg = core['涨跌幅'].mean() if len(core) else 0.0
        return {"etf_down_ratio": float(ratio), "etf_avg": float(avg),
                "etf_total": int(len(core)), "_src": "eastmoney_etf"}
    except Exception as e:
        print(f"[warn] ETF spot失败（D2降级）: {e}")
        return {"etf_down_ratio": None, "_src": "暂未获取"}


# ---------------- D4 放量倍数（东财当日额 / 腾讯近20日均额） ----------------
def fetch_volume_mult(sh_amount):
    """放量倍数 = 当日上证成交额 / 上证近20日均值成交额（腾讯源，千元->元）。"""
    if sh_amount is None:
        return {"volume_mult": None, "_src": "暂未获取"}
    try:
        h = ak.stock_zh_index_daily_tx(symbol="sh000001")
        mean_amt = float(h['amount'].tail(20).mean()) * 1000  # 千元 -> 元
        if mean_amt <= 0:
            raise ValueError("近20日均成交额=0")
        return {"volume_mult": sh_amount / mean_amt, "_src": "tencent_daily"}
    except Exception as e:
        print(f"[warn] 放量计算失败（D4降级）: {e}")
        return {"volume_mult": None, "_src": "暂未获取"}


# ---------------- 汇总拼装冰点输入 ----------------
def build_bingdian_inputs():
    """按源优先级拼装 4 维度输入，供 bingdian_index.compute() 判定。

    源链：
      D1 : legu 主 → 东财spot 兜底
      D3 : 东财spot 板块差异化（权威） ；legu 聚合跌停仅作交叉参考兜底
      D2 : 东财指数spot + ETF spot
      D4 : 东财当日额 / 腾讯近20日均额
    """
    data_date = _bj_today()
    idx = fetch_index_em()                                   # D2 指数 + D4 上证额
    etf = fetch_etf_em()                                      # D2 ETF
    vol = fetch_volume_mult(idx.get("sh_amount"))             # D4 放量倍数
    legu, legu_ok = fetch_breadth_legu()                      # 广度主源（D1+D3 共用）
    # 仅当 legu 不可达时才拉东财逐股 spot（重调用 ~1min，正常CI不触发）
    spot, spot_ok = (None, False)
    if not legu_ok:
        spot, spot_ok = fetch_spot_em()

    # ---- D1 & D3 统一：legu 主 → 东财逐股 spot 兜底 ----
    if legu_ok:
        d1 = {"down": legu["down"], "total": legu["total"],
              "down_ratio": (legu["down"] / legu["total"] if legu["total"] else 0.0),
              "_src_D1": "legu"}
        d3 = {"limit_down": legu["limit_down"], "limit_up": legu["limit_up"],
              "ld_lu_ratio": (legu["limit_down"] / max(legu["limit_up"], 1)),
              "_src_D3": "legu"}
    elif spot_ok:
        d1 = {"down": spot["down"], "total": spot["total"], "down_ratio": spot["down_ratio"],
              "_src_D1": "eastmoney_spot"}
        d3 = {"limit_down": spot["limit_down"], "limit_up": spot["limit_up"],
              "ld_lu_ratio": spot["ld_lu_ratio"], "_src_D3": "eastmoney_spot"}
    else:
        d1 = {"down": "暂未获取", "total": "暂未获取", "down_ratio": "暂未获取",
              "_src_D1": "暂未获取"}
        d3 = {"limit_down": "暂未获取", "limit_up": "暂未获取", "ld_lu_ratio": "暂未获取",
              "_src_D3": "暂未获取"}

    m = {}
    m.update(d1)
    m.update(d3)
    m.update({
        "sh_chg": idx.get("sh_chg"),
        "cyb_chg": idx.get("cyb_chg"),
        "etf_down_ratio": etf.get("etf_down_ratio"),
        "volume_mult": vol.get("volume_mult"),
        "_src_D2": idx.get("_src", "暂未获取"),
        "_src_D4": vol.get("_src", "暂未获取"),
        "_data_date": data_date,
    })
    return m


if __name__ == "__main__":
    import json
    m = build_bingdian_inputs()
    print(json.dumps(m, ensure_ascii=False, indent=2, default=str))
