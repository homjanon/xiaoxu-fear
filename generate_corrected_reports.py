#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用已修正(通达信真值)的本地滚动缓存，重新生成 dibudian_report.json / dibudian_state.json。
- 8-03 由盘中脏值 0.666万亿 修正为 通达信收盘真值 1.997万亿
- 8-04/8-05 已用通达信核真值
- last_bottom_date 回退到最近一个真实底部点(滚动窗口 ratio<=0.5)：2026-04-07，并带对应成交额
仅本地修正，不推 GitHub。
"""
import json, os, datetime

CACHE = "output/_turnover_cache.json"
OUT = "output"
CST = datetime.timezone(datetime.timedelta(hours=8))

with open(CACHE, encoding="utf-8") as f:
    cache = json.load(f)

items = sorted(cache.items())
dates = [d for d, _ in items]
totals = [float(v) for _, v in items]
n = len(items)

today_date = dates[-1]
today_total = totals[-1]
max90 = max(totals[-90:]) if n >= 90 else max(totals)
ratio = today_total / max90

# 从后往前找最近一个真实底部点（滚动90日窗口 ratio<=0.5）
last_date = None
last_vol = None
for i in range(n - 1, -1, -1):
    lo = max(0, i - 89)
    wmax = max(totals[lo:i + 1])
    if totals[i] / wmax <= 0.5:
        last_date = dates[i]
        last_vol = totals[i]
        break

hist30 = [{"date": dates[i], "total": totals[i]} for i in range(max(0, n - 30), n)]

# 8-05 真实收盘沪/深(通达信核验)
sh = 1208723046400.0
sz = 1450911465472.0

report = {
    "today_total": today_total, "sh_today": sh, "sz_today": sz,
    "max90_total": max90, "ratio": ratio, "threshold": 0.5,
    "is_bottom_today": False, "verdict_text": "非底部区域日", "verdict_emoji": "⚪",
    "_data_date": today_date, "_src": "tdx_verified+cache(" + today_date + ")",
    "last_bottom_date": last_date, "last_bottom_volume": last_vol,
    "_note": "参考指标，不纳入XXFI计算口径，不影响小旭恐惧指数",
    "hist30": hist30,
    "inputs": {"today_total": today_total, "sh_today": sh, "sz_today": sz,
               "max90_total": max90, "hist30": hist30},
}

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "dibudian_report.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

state = {
    "last_bottom_date": last_date,
    "last_bottom_volume": last_vol,
    "_updated_at": datetime.datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
}
with open(os.path.join(OUT, "dibudian_state.json"), "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print("today      :", today_date, f"{today_total/1e12:.3f}万亿")
print("max90      :", f"{max90/1e12:.3f}万亿")
print("ratio      :", round(ratio, 4), "(阈值 0.5)")
print("last_bottom:", last_date, f"{last_vol/1e12:.3f}万亿" if last_vol else "无")
print("8-03 修正后:", f"{cache.get('2026-08-03')/1e12:.3f}万亿 (原脏值 0.666万亿)")
print("已写: output/dibudian_report.json + output/dibudian_state.json")
