#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小旭恐惧指数 · 历史分日回溯取数器（去通达信，本地+GitHub 双通）
================================================================

目标：用 akshare + baostock 重建任意历史交易日的 XXFI，不再依赖通达信连接器。

各分量历史来源（均已验证本地/CI 双通，除零售外）：
  - 指数派生(回撤/动量/高于MA/波动率分位)：akshare stock_zh_index_daily（Sina 全历史）→ 本地/CI 均通
  - 涨停/跌停家数：akshare stock_zt_pool_em / stock_zt_pool_dtgc_em(date=) → 本地/CI 均通（push2）
  - 涨跌家数(广度)：baostock 逐股 pctChg 统计 → 本地/CI 均通（baostock 自有服务器）
  - 散户净流入(贪婪副表用)：akshare stock_market_fund_flow（EM push2his）→ CI 通、本地被代理拦→降级

用法（由 run_xxfi.py --backfill N 调用）：
  backfill_history(n, vol_window=60, out_dir="output")
    → 取最近 n 个交易日，baostock 一次性统计全部日期广度，逐日算 XXFI，
      写入 history.jsonl（按 date 去重），并重算最新一日报告。
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_xxfi import compute, max_drawdown, roll_vol, write_outputs


# ---------------- 工具 ----------------
def _is_astock(code):
    """从 baostock query_all_stock 返回的代码里筛出 A 股（剔除指数/B股）。"""
    if "." not in code:
        return False
    mkt, num = code.split(".")
    if mkt == "sh":
        return num[:3] in ("600", "601", "603", "605", "688", "609")
    if mkt == "sz":
        return num[:3] in ("000", "001", "002", "003", "300", "301")
    if mkt == "bj":
        return num[0] in ("8", "4")
    return False


# ---------------- 指数历史 ----------------
def get_index_series(symbol="sh000001"):
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol=symbol)
    closes = [float(x) for x in df["close"].tolist()]
    dates = [str(x) for x in df["date"].tolist()]
    return closes, dates


def index_comp_at(closes, dates, target, vol_window=60):
    i = dates.index(target)
    sub = closes[:i + 1]
    last20 = sub[-20:]
    dd = max_drawdown(last20)
    ret20 = last20[-1] / last20[0] - 1
    ma20 = sum(last20) / len(last20)
    above = (sub[-1] - ma20) / ma20
    vols = roll_vol(sub, 20)
    cur = vols[-1]
    win = vols[-vol_window:]
    vol_pct = sum(1 for v in win if v <= cur) / len(win) if win else 0.0
    return {"drawdown": dd, "ret20": ret20, "above_ma20": above,
            "vol_pct": vol_pct, "vol_window": vol_window}


# ---------------- baostock 历史广度（一次性遍历全部日期） ----------------
def get_breadth_for_dates(date_list):
    """对 date_list（"YYYY-MM-DD"）一次性逐股统计 up/down，返回 {date:(up,down)}。

    效率：枚举全市场 A 股一次（~5000 只），每只取 date_list 区间的 pctChg，
    按日期归集。约 5000 次查询，回溯多日也只跑一遍。
    """
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        print(f"[err] baostock 登录失败: {lg.error_msg}")
        bs.logout()
        return {d: (1, 1) for d in date_list}
    try:
        latest = max(date_list)
        rs = bs.query_all_stock(latest)
        codes = []
        while rs.next():
            c = rs.get_row_data()[0]
            if _is_astock(c):
                codes.append(c)
        print(f"[info] baostock 枚举 A 股 {len(codes)} 只，统计区间 {min(date_list)}~{max(date_list)}")
        start, end = min(date_list), max(date_list)
        counts = {d: [0, 0, 0] for d in date_list}  # up, down, flat
        for c in codes:
            try:
                rs = bs.query_history_k_data_plus(
                    c, "date,pctChg", start_date=start, end_date=end,
                    frequency="d", adjustflag="3")
                while rs.next():
                    row = rs.get_row_data()
                    d = row[0]
                    if d in counts:
                        try:
                            p = float(row[1])
                        except Exception:
                            continue
                        if p > 0:
                            counts[d][0] += 1
                        elif p < 0:
                            counts[d][1] += 1
                        else:
                            counts[d][2] += 1
            except Exception as e:
                # 单只失败不影响整体（可能是已退市/数据缺失）
                continue
        return {d: (counts[d][0], counts[d][1]) for d in date_list}
    finally:
        bs.logout()


# ---------------- akshare 历史涨跌停 ----------------
def fetch_ztdt(ymd):
    import akshare as ak
    try:
        zt = ak.stock_zt_pool_em(date=ymd)
        dt = ak.stock_zt_pool_dtgc_em(date=ymd)
        return len(zt), len(dt)
    except Exception as e:
        print(f"[warn] 历史涨跌停池失败: {e}")
        return 1, 0


# ---------------- akshare 历史主力/散户净流入（EM，本地可能降级） ----------------
def fetch_fund_flow_at(target):
    """取某历史交易日的主力/散户净流入（净占比口径）→ ((main, retail), source)。

    用 stock_market_fund_flow() 全历史按日一行，按 日期 匹配 target；
    主力=主力净流入-净占比，散户=小单净流入-净占比，均 /100 转小数，与当日口径一致。
    本地若被代理拦 EM(push2his) → 双双降级；GitHub/CI 取真值。
    """
    import akshare as ak
    from datetime import date as _date
    try:
        df = ak.stock_market_fund_flow()
        if df is None or len(df) == 0:
            raise ValueError("空数据")
        tgt = target
        try:
            tgt = _date.fromisoformat(target)
        except Exception:
            pass
        sub = df[df["日期"] == tgt]
        if sub.empty:
            sub = df[df["日期"].astype(str) == str(target)]
        if sub.empty:
            raise ValueError("无该日数据")
        row = sub.iloc[0]
        main = float(row["主力净流入-净占比"]) / 100.0
        retail = float(row["小单净流入-净占比"]) / 100.0
        return (main, retail), "eastmoney_hist"
    except Exception as e:
        print(f"[warn] 历史资金流失败（本地通常被代理拦），降级 main/retail=0: {e}")
        return (0.0, 0.0), "degraded"


# ---------------- 组装单日 market dict ----------------
def build_day(target, breadth_tuple, vol_window, closes, dates):
    up, down = breadth_tuple
    comp = index_comp_at(closes, dates, target, vol_window)
    ymd = target.replace("-", "")
    lu, ld = fetch_ztdt(ymd)
    (rn, mn), rsrc = fetch_fund_flow_at(target)
    m = dict(comp)
    m.update({"up": up, "down": down, "limit_up": lu, "limit_down": ld,
              "retail_net": rn, "main_net": mn})
    m["_breadth_source"] = "baostock"
    m["_retail_net_source"] = rsrc
    m["_main_net_source"] = rsrc
    m["_breadth_provided"] = True
    m["_index_name"] = "上证指数(sh000001)"
    m["_hs300_date"] = target
    m["_hs300_close"] = closes[dates.index(target)]
    return m


# ---------------- 主回溯 ----------------
def backfill_history(n, vol_window=60, out_dir="output"):
    closes, dates = get_index_series()
    target_dates = dates[-n:]
    print(f"[info] 回溯最近 {n} 个交易日: {target_dates[0]} ~ {target_dates[-1]}")
    breadth = get_breadth_for_dates(target_dates)

    hist_path = os.path.join(out_dir, "history.jsonl")
    existing = {}
    if os.path.exists(hist_path):
        with open(hist_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    existing[row.get("date")] = row
                except Exception:
                    pass

    latest_report = None
    for d in target_dates:
        m = build_day(d, breadth.get(d, (1, 1)), vol_window, closes, dates)
        res = compute(m)
        existing[d] = {"date": d, "xxfi": res["XXFI"], "greed": res["GreedIndex"],
                       "signal": res["contrarian_signal"], "level": res["level"]}
        if d == target_dates[-1]:
            latest_report = (res, m)
        print(f"  {d}: XXFI={res['XXFI']}  贪婪={res['GreedIndex']}  {res['contrarian_signal']}  ({res['level']})  [广度 {m['up']}/{m['down']} 源={m['_breadth_source']} 资金={m['_retail_net_source']}]")

    os.makedirs(out_dir, exist_ok=True)
    with open(hist_path, "w", encoding="utf-8") as f:
        for d in sorted(existing.keys()):
            f.write(json.dumps(existing[d], ensure_ascii=False) + "\n")

    if latest_report:
        res, m = latest_report
        write_outputs(res, m, out_dir, vol_window)

    print(f"[done] 回溯完成：{len(target_dates)} 日，history.jsonl 现共 {len(existing)} 行")
    return target_dates


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="XXFI 历史回溯（baostock 广度）")
    ap.add_argument("--n", type=int, default=5, help="回溯最近 N 个交易日")
    ap.add_argument("--vol_window", type=int, default=60)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    backfill_history(args.n, args.vol_window, args.out)
