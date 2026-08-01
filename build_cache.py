#!/usr/bin/env python3
# 由通达信 tdx_kline 拉取的 2026 全市场成交额原始数据，合并为 output/_turnover_cache.json
# 全市场口径 = 上证指数(000001) + 深证成指(399001) 成交额(元，通达信 Amount 已是元，无需换算)
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output", "_turnover_cache.json")
START = "2026-01-01"
END = "2026-07-31"  # 今年8月之前（含7/31最后一个交易日）


def load(path):
    rows = json.load(open(path, encoding="utf-8"))
    d = {}
    for r in rows:
        dt = str(r["Data"])  # YYYYMMDD
        iso = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        d[iso] = float(r["Amount"])
    return d


sh = load(os.path.join(BASE, "sh_kline_raw.txt"))
sz = load(os.path.join(BASE, "sz_kline_raw.txt"))

# 对齐交易日，求和；过滤到 2026-01-01 .. 2026-07-31
cache = {}
for dt in sorted(set(sh) | set(sz)):
    if dt < START or dt > END:
        continue
    if dt in sh and dt in sz:
        cache[dt] = sh[dt] + sz[dt]
    else:
        # 某一侧缺失则仅用存在侧（实际两源交易日应对齐）
        cache[dt] = sh.get(dt, 0) + sz.get(dt, 0)

cache = {k: cache[k] for k in sorted(cache)}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(cache, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

# 校验
y731 = cache.get("2026-07-31")
peak_date = max(cache, key=lambda k: cache[k])
peak_val = cache[peak_date]
print(f"交易日数(2026): {len(cache)}")
print(f"2026-07-31 全市场: {y731:,.0f} 元  (≈{y731/1e12:.4f} 万亿)")
print(f"2026 区间峰值: {peak_date} = {peak_val:,.0f} 元  (≈{peak_val/1e12:.4f} 万亿)")
# 近90日峰值(截至7/31)
vals = list(cache.values())[-90:]
print(f"近90日峰值(截至7/31): {max(vals):,.0f} 元  (≈{max(vals)/1e12:.4f} 万亿)")
print(f"已写入: {OUT}")
