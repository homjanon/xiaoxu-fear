#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_html.py · 将 XXFI 结果渲染为自包含静态 HTML 页面

输入：
  --json      run_xxfi.py 产出的 xxfi_report.json（最新结果）
  --history   累积的 history.jsonl（每日一行，用于趋势）
  --out       生成的 HTML 路径（如 docs/index.html）

输出：自包含 index.html（内联 CSS，含「最新结果卡 + 分项得分 + 完整对照表 + 历史趋势」），
      可直接由 GitHub Pages（main/docs）或任意静态托管发布。
"""
import argparse, json, os

# ---- 静态对照表（XXFI 绝对区间判定，来自 calibration）----
REF_TABLE = [
    (75, 101, "极度恐惧（小旭式恐慌割肉区）", "BUY",
     "历史校准：连跌后恐慌割肉，卖后多现 +9%~+24% 反弹 → 反向强烈看多，分批低吸"),
    (60, 75, "恐惧（偏谨慎，她倾向割肉）", "ACCUMULATE",
     "市场情绪偏弱，接近她‘卖飞’区 → 逢低吸纳，避免跟风杀跌"),
    (40, 60, "中性", "HOLD",
     "恐惧与贪婪均衡，无明显反向极值 → 按自身策略持有，不依赖本指标"),
    (25, 40, "偏贪婪（情绪偏热，她倾向追高）", "REDUCE",
     "热度偏高 → 逢高减仓不追涨；小旭常在连续大涨后追高买在山顶"),
    (0, 25, "极度贪婪（小旭式追涨山顶区）", "SELL",
     "历史校准：追高买在山顶后多现 -12%~-21% 回落 → 反向强烈看空"),
]

SIGNAL_COLOR = {
    "BUY": "#16a34a",
    "ACCUMULATE": "#22c55e",
    "HOLD": "#6b7280",
    "REDUCE": "#ea580c",
    "SELL": "#dc2626",
}

CSS = """
:root{--bg:#f5f7fa;--card:#fff;--ink:#1f2933;--sub:#6b7280;--line:#e5e7eb;--accent:#2563eb;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--ink);line-height:1.6;padding:24px 16px;}
.wrap{max-width:760px;margin:0 auto;}
h1{font-size:22px;font-weight:700;margin-bottom:4px;}
.sub{color:var(--sub);font-size:13px;margin-bottom:20px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:18px;
  box-shadow:0 1px 3px rgba(0,0,0,.04);}
.hero{display:flex;gap:20px;flex-wrap:wrap;align-items:center;}
.hero .main{flex:1 1 240px;}
.hero .gx{flex:1 1 200px;border-left:1px solid var(--line);padding-left:20px;}
.big{font-size:56px;font-weight:800;line-height:1;letter-spacing:-1px;}
.big.sub2{font-size:44px;}
.label{font-size:13px;color:var(--sub);margin-top:6px;}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;color:#fff;font-size:13px;font-weight:600;margin-top:10px;}
.advice{margin-top:14px;font-size:14px;background:#f8fafc;border-radius:10px;padding:12px 14px;border:1px solid var(--line);}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
@media(max-width:560px){.grid{grid-template-columns:1fr}.hero .gx{border-left:none;padding-left:0;border-top:1px solid var(--line);padding-top:16px;margin-top:8px}}
.sec-h{font-size:15px;font-weight:700;margin-bottom:12px;}
.row{margin-bottom:10px;}
.row .rt{display:flex;justify-content:space-between;font-size:13px;margin-bottom:3px;}
.bar{height:8px;background:#eef2f7;border-radius:6px;overflow:hidden;}
.bar>i{display:block;height:100%;background:var(--accent);border-radius:6px;}
.bar.fear>i{background:#0ea5e9;}
.bar.greed>i{background:#f59e0b;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top;}
th{color:var(--sub);font-weight:600;background:#fafbfc;}
.note{font-size:12.5px;color:var(--sub);margin-top:10px;background:#f8fafc;border-radius:8px;padding:10px 12px;}
.trend svg{width:100%;height:auto;display:block;}
.legend{font-size:12px;color:var(--sub);margin:6px 0 12px;}
.legend b{color:var(--ink);}
.muted{color:var(--sub);font-size:13px;}
.foot{font-size:12px;color:var(--sub);margin-top:8px;}
code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12px;}
"""

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_history(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows

def signal_of(xxfi):
    if xxfi >= 75: return "BUY"
    if xxfi >= 60: return "ACCUMULATE"
    if xxfi >= 40: return "HOLD"
    if xxfi >= 25: return "REDUCE"
    return "SELL"

def trend_svg(hist):
    if len(hist) < 2:
        return '<p class="muted">历史数据不足（需 ≥2 个交易日），暂无法绘制趋势。运行数日后会自动出现。</p>'
    w, h = 680, 220
    pad_l, pad_r, pad_t, pad_b = 36, 12, 14, 26
    n = len(hist)
    def X(i): return pad_l + (w - pad_l - pad_r) * i / (n - 1)
    def Y(v): return pad_t + (h - pad_t - pad_b) * (100 - v) / 100
    svg = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="XXFI 与贪婪指数历史趋势">']
    # 网格 + Y 轴刻度
    for g in (0, 25, 50, 75, 100):
        y = Y(g)
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" stroke="#eef2f7"/>')
        svg.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" font-size="10" fill="#9aa3af" text-anchor="end">{g}</text>')
    # 两条折线
    def poly(key, color):
        pts = " ".join(f"{X(i):.1f},{Y(hist[i].get(key,0)):.1f}" for i in range(n))
        return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2"/>'
    svg.append(poly("xxfi", "#2563eb"))
    svg.append(poly("greed", "#f59e0b"))
    # 末点高亮
    lx, ly = X(n-1), Y(hist[-1].get("xxfi", 0))
    svg.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.5" fill="#2563eb"/>')
    svg.append(f'</svg>')
    return "".join(svg)

def bar(score, cls):
    s = max(0, min(100, float(score)))
    return f'<div class="bar {cls}"><i style="width:{s:.1f}%"></i></div>'

def render(r, hist):
    xxfi = float(r.get("XXFI", 0))
    greed = float(r.get("GreedIndex", 0))
    signal = r.get("contrarian_signal") or signal_of(xxfi)
    level = r.get("level", "")
    advice = r.get("advice", "")
    comp = r.get("components", {})
    fear = comp.get("fear", {})
    greed_c = comp.get("greed", {})
    data_date = r.get("_data_date", "")
    idx_name = r.get("_index_name", "")
    vw = r.get("_vol_window", 60)
    bsrc = r.get("_breadth_source") or r.get("inputs", {}).get("_breadth_source", "-")
    rsrc = r.get("_retail_net_source") or r.get("inputs", {}).get("_retail_net_source", "-")
    scolor = SIGNAL_COLOR.get(signal, "#6b7280")

    # 对照表行
    ref_rows = ""
    for lo, hi, lv, sig, desc in REF_TABLE:
        hit = (lo <= xxfi < hi)
        style = ' style="background:#fff7ed;font-weight:600"' if hit else ''
        ref_rows += (f"<tr{style}><td>{'≥'+str(lo) if lo>0 else '<25'}</td><td>{lv}</td>"
                     f"<td><span class='badge' style='background:{SIGNAL_COLOR.get(sig,'#6b7280')}'>{sig}</span></td>"
                     f"<td>{desc}</td></tr>")

    # 历史表（最近 10 行，倒序）
    hist_rows = ""
    for row in hist[-10:][::-1]:
        hist_rows += (f"<tr><td>{row.get('date','')}</td><td>{row.get('xxfi','')}</td>"
                      f"<td>{row.get('greed','')}</td><td>{row.get('signal','')}</td>"
                      f"<td>{row.get('level','')}</td></tr>")
    if not hist_rows:
        hist_rows = '<tr><td colspan="5" class="muted">暂无历史记录</td></tr>'

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>小旭恐惧指数 XXFI · 实时</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>小旭恐惧指数 · XXFI</h1>
<div class="sub">反向情绪指标（散户行为版）　|　数据日期：{data_date}　|　基准：{idx_name}　|　波动率窗口：{vw} 日</div>

<div class="card">
  <div class="hero">
    <div class="main">
      <div class="big" style="color:{scolor}">{xxfi}</div>
      <div class="label">XXFI（主表·决定信号）</div>
      <div class="badge" style="background:{scolor}">{signal}</div>
      <div style="margin-top:6px;font-size:13px;color:var(--sub)">{level}</div>
    </div>
    <div class="gx">
      <div class="big sub2" style="color:#6b7280">{greed}</div>
      <div class="label">贪婪指数（副表·辅助诊断）</div>
      <div class="label" style="margin-top:8px">独立公式 · 非互补</div>
    </div>
  </div>
  <div class="advice">{advice}</div>
</div>

<div class="card">
  <div class="sec-h">分项得分（0–100）</div>
  <div class="grid">
    <div>
      <div class="sec-h" style="font-size:13px;color:#0ea5e9">恐惧分项</div>
      <div class="row"><div class="rt"><span>近20日最大回撤</span><span>{fear.get('drawdown',0)}</span></div>{bar(fear.get('drawdown',0),'fear')}</div>
      <div class="row"><div class="rt"><span>涨跌家数比</span><span>{fear.get('breadth',0)}</span></div>{bar(fear.get('breadth',0),'fear')}</div>
      <div class="row"><div class="rt"><span>跌停/涨停比</span><span>{fear.get('limitdown',0)}</span></div>{bar(fear.get('limitdown',0),'fear')}</div>
      <div class="row"><div class="rt"><span>波动率分位</span><span>{fear.get('vol',0)}</span></div>{bar(fear.get('vol',0),'fear')}</div>
    </div>
    <div>
      <div class="sec-h" style="font-size:13px;color:#f59e0b">贪婪分项</div>
      <div class="row"><div class="rt"><span>近20日动量</span><span>{greed_c.get('momentum',0)}</span></div>{bar(greed_c.get('momentum',0),'greed')}</div>
      <div class="row"><div class="rt"><span>涨停/跌停比</span><span>{greed_c.get('limitup',0)}</span></div>{bar(greed_c.get('limitup',0),'greed')}</div>
      <div class="row"><div class="rt"><span>散户净流入</span><span>{greed_c.get('retailin',0)}</span></div>{bar(greed_c.get('retailin',0),'greed')}</div>
      <div class="row"><div class="rt"><span>高于20日均线</span><span>{greed_c.get('overbought',0)}</span></div>{bar(greed_c.get('overbought',0),'greed')}</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="sec-h">对照参考表（XXFI 绝对区间 → 等级 / 信号）</div>
  <table><thead><tr><th>区间</th><th>等级</th><th>信号</th><th>含义与反向操作</th></tr></thead>
  <tbody>{ref_rows}</tbody></table>
  <div class="note">说明：<b>XXFI 与贪婪指数为两套独立公式，不相加=100、非互补对子</b>。
  以 <b>XXFI（主表）</b> 判定反向信号等级；贪婪指数仅作辅助诊断（如局部热闹但非全面过热）。
  反向指标仅在情绪极端+趋势反转时有效，须配合自身交易系统与止损纪律。</div>
</div>

<div class="card trend">
  <div class="sec-h">历史趋势</div>
  <div class="legend"><b style="color:#2563eb">■</b> XXFI（主）　<b style="color:#f59e0b">■</b> 贪婪指数（副）</div>
  {trend_svg(hist)}
  <table style="margin-top:14px"><thead><tr><th>日期</th><th>XXFI</th><th>贪婪</th><th>信号</th><th>等级</th></tr></thead>
  <tbody>{hist_rows}</tbody></table>
</div>

<div class="foot">
  数据溯源：广度源=<code>{bsrc}</code>　资金流源=<code>{rsrc}</code><br>
  指标为反向情绪参考，非投资建议。生成自 xiaoxu-fear-index 技能 · GitHub Actions 每日盘后自动更新。
</div>
</div></body></html>"""
    return html

def main():
    ap = argparse.ArgumentParser(description="XXFI 结果渲染为静态 HTML")
    ap.add_argument("--json", required=True, help="xxfi_report.json 路径")
    ap.add_argument("--history", default="output/history.jsonl", help="history.jsonl 路径")
    ap.add_argument("--out", required=True, help="输出 HTML 路径，如 docs/index.html")
    args = ap.parse_args()

    r = load_json(args.json)
    hist = load_history(args.history)
    html = render(r, hist)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 已生成: {args.out}（历史样本 {len(hist)} 条）")

if __name__ == "__main__":
    main()
