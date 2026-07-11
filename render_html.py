#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_html.py · 将 XXFI 结果渲染为自包含静态 HTML 页面

输入：
  --json      run_xxfi.py 产出的 xxfi_report.json（最新结果）
  --history   累积的 history.jsonl（每日一行，用于趋势）
  --out       生成的 HTML 路径（如 docs/index.html）

输出：自包含 index.html（内联 CSS，含「最新结果卡 + 分项(原始值+得分) + 完整对照表 + 历史趋势」），
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
:root{
  --bg:#eef2f7;--card:#fff;--ink:#1f2937;--sub:#64748b;--line:#e8edf3;
  --accent:#2563eb;--fear:#0ea5e9;--greed:#f59e0b;
  --shadow:0 1px 2px rgba(15,23,42,.05),0 6px 20px rgba(15,23,42,.05);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--ink);line-height:1.6;padding:28px 16px;-webkit-font-smoothing:antialiased;}
.wrap{max-width:780px;margin:0 auto;}
h1{font-size:22px;font-weight:800;letter-spacing:-.3px;}
.sub{color:var(--sub);font-size:12.5px;margin:6px 0 22px;line-height:1.55;}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:18px;
  box-shadow:var(--shadow);}
.hero{display:flex;gap:22px;flex-wrap:wrap;align-items:center;}
.hero .main{flex:1 1 230px;min-width:0;}
.hero .gx{flex:1 1 190px;min-width:0;border-left:1px solid var(--line);padding-left:22px;}
.big{font-size:clamp(46px,13vw,60px);font-weight:800;line-height:1;letter-spacing:-1.5px;}
.big.sub2{font-size:clamp(36px,11vw,46px);}
.label{font-size:13px;color:var(--sub);margin-top:8px;}
.badge{display:inline-block;padding:4px 12px;border-radius:999px;color:#fff;font-size:13px;font-weight:700;
  margin-top:12px;letter-spacing:.3px;}
.advice{margin-top:16px;font-size:14px;background:#f8fafc;border-radius:12px;padding:12px 14px;
  border:1px solid var(--line);line-height:1.55;}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start;}
.panel-h{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:700;margin-bottom:10px;}
.panel-h.fear{color:var(--fear);} .panel-h.greed{color:var(--greed);}
.panel-h .dot{width:9px;height:9px;border-radius:50%;flex:none;}
.panel-h.fear .dot{background:var(--fear);} .panel-h.greed .dot{background:var(--greed);}
.sec-h{font-size:15px;font-weight:700;margin-bottom:12px;}
.score-tbl{table-layout:fixed;width:100%;border-collapse:collapse;font-size:13px;margin-bottom:2px;}
.score-tbl th,.score-tbl td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:middle;}
.score-tbl th{color:var(--sub);font-weight:600;background:#f8fafc;font-size:11.5px;}
.score-tbl td.dim{font-weight:600;font-size:13px;color:var(--ink);}
.score-tbl td.raw{font-size:11.5px;color:var(--sub);overflow-wrap:anywhere;line-height:1.35;word-break:break-word;}
.score-tbl td.sc{vertical-align:middle;}
.sc-num{display:block;font-weight:800;font-size:15px;font-variant-numeric:tabular-nums;margin-bottom:5px;}
.bar{height:6px;background:#eef2f7;border-radius:6px;overflow:hidden;width:100%;}
.bar>i{display:block;height:100%;border-radius:6px;}
.bar.fear>i{background:var(--fear);}
.bar.greed>i{background:var(--greed);}
table{width:100%;border-collapse:collapse;font-size:13px;}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:middle;}
th{color:var(--sub);font-weight:600;background:#fafbfc;font-size:12px;}
td.raw-gen{font-size:12px;color:var(--sub);font-variant-numeric:tabular-nums;}
.note{font-size:12.5px;color:var(--sub);margin-top:10px;background:#f8fafc;border-radius:8px;padding:10px 12px;line-height:1.5;}
.note b{color:var(--ink);}
.trend svg{width:100%;height:auto;display:block;}
.legend{font-size:12px;color:var(--sub);margin:6px 0 12px;}
.legend b{color:var(--ink);}
.muted{color:var(--sub);font-size:13px;}
.foot{font-size:12px;color:var(--sub);margin-top:8px;line-height:1.6;}
code{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12px;}
.tbl-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -2px;}
.tbl-scroll .ref-tbl{min-width:460px;}
.tbl-scroll .hist-tbl{min-width:540px;}
@media(max-width:560px){
  body{padding:18px 12px;}
  .grid{grid-template-columns:1fr;}
  .hero .gx{border-left:none;padding-left:0;border-top:1px solid var(--line);padding-top:16px;margin-top:6px;}
}
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
    for g in (0, 25, 50, 75, 100):
        y = Y(g)
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" stroke="#eef2f7"/>')
        svg.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" font-size="10" fill="#9aa3af" text-anchor="end">{g}</text>')
    def poly(key, color):
        pts = " ".join(f"{X(i):.1f},{Y(hist[i].get(key,0)):.1f}" for i in range(n))
        return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2"/>'
    svg.append(poly("xxfi", "#2563eb"))
    svg.append(poly("greed", "#f59e0b"))
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
    inp = r.get("inputs", {})
    data_date = r.get("_data_date", "")
    idx_name = r.get("_index_name", "")
    vw = r.get("_vol_window", 60)
    bsrc = r.get("_breadth_source") or inp.get("_breadth_source", "-")
    rsrc = r.get("_retail_net_source") or inp.get("_retail_net_source", "-")
    scolor = SIGNAL_COLOR.get(signal, "#6b7280")

    # 原始值 + 得分 两列构造
    def pct(v):
        try:
            fv = float(v)
            if fv != fv:  # NaN
                return "—"
            return f"{fv*100:.2f}%"
        except Exception:
            return "-"
    du = max(1.0, float(inp.get("up", 1) or 1))
    dd = float(inp.get("down", 0) or 0)
    lu = max(1.0, float(inp.get("limit_up", 1) or 1))
    ld = float(inp.get("limit_down", 0) or 0)
    # 散户净流入：若本地降级（源以 degraded 开头），明确标注而非显示 0.00%
    if str(rsrc).startswith("degraded"):
        retail_raw = "未提供（本地降级）"
    else:
        retail_raw = pct(inp.get("retail_net", 0))
    msrc = r.get("_main_net_source") or inp.get("_main_net_source", "-")
    if str(msrc).startswith("degraded"):
        main_raw = "未提供（本地降级）"
    else:
        main_raw = pct(inp.get("main_net", 0))
    div_state = r.get("divergence_state", "无数据（资金流降级）")
    div_raw = f"主力 {main_raw} ／ 散户 {retail_raw}"
    fear_rows = [
        ("近20日最大回撤", pct(inp.get("drawdown", 0)), fear.get("drawdown", 0)),
        ("涨跌家数比", f"{int(dd)}/{int(du)}（比 {dd/du:.2f}）", fear.get("breadth", 0)),
        ("跌停/涨停比", f"{int(ld)}/{int(lu)}（比 {ld/lu:.2f}）", fear.get("limitdown", 0)),
        ("波动率分位", pct(inp.get("vol_pct", 0)), fear.get("vol", 0)),
    ]
    greed_rows = [
        ("近20日动量", pct(inp.get("ret20", 0)), greed_c.get("momentum", 0)),
        ("涨停/跌停比", f"{int(lu)}/{int(ld)}（比 {lu/ld:.2f}）", greed_c.get("limitup", 0)),
        ("散户净流入", retail_raw, greed_c.get("retailin", 0)),
        ("高于20日均线", pct(inp.get("above_ma20", 0)), greed_c.get("overbought", 0)),
        ("主力—散户背离", div_raw, greed_c.get("divergence", 0)),
    ]
    def rows_html(rows, cls, accent):
        h = ""
        for label, raw, score in rows:
            h += (f"<tr><td class='dim'>{label}</td>"
                  f"<td class='raw'>{raw}</td>"
                  f"<td class='sc'><span class='sc-num' style='color:{accent}'>{score}</span>{bar(score, cls)}</td></tr>")
        return h
    fear_html = rows_html(fear_rows, "fear", "var(--fear)")
    greed_html = rows_html(greed_rows, "greed", "var(--greed)")

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

<div class="card" style="border-top:4px solid {scolor}">
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

<div class="card" style="border-color:#fcd34d">
  <div class="sec-h" style="color:#b45309">主力—散户背离诊断（v2）</div>
  <div style="font-size:16px;font-weight:700;color:#b45309">{div_state}</div>
  <div class="muted" style="margin-top:6px">主力净流入：<b>{main_raw}</b>　|　散户净流入：<b>{retail_raw}</b></div>
  <div class="note">背离 = 主力净占比 − 散户净占比。负且「散户追·主力派」→ 顶部出货（危险）；正且「散户割·主力进」→ 底部吸筹（机会）。仅资金流源为 eastmoney 时有真值；本地降级时显示占位中性，不影响主信号。</div>
</div>

<div class="card">
  <div class="sec-h">分项得分（0–100）· 含原始值</div>
  <div class="grid">
    <div>
      <div class="panel-h fear"><span class="dot"></span>恐惧分项</div>
      <table class="score-tbl"><colgroup><col style="width:40%"><col style="width:32%"><col style="width:28%"></colgroup>
        <thead><tr><th>维度</th><th>原始值</th><th>得分</th></tr></thead>
        <tbody>{fear_html}</tbody></table>
    </div>
    <div>
      <div class="panel-h greed"><span class="dot"></span>贪婪分项</div>
      <table class="score-tbl"><colgroup><col style="width:40%"><col style="width:32%"><col style="width:28%"></colgroup>
        <thead><tr><th>维度</th><th>原始值</th><th>得分</th></tr></thead>
        <tbody>{greed_html}</tbody></table>
    </div>
  </div>
  <div class="note">说明：原始值有数据但接近中性时，得分会被公式夹到 0（属正常，非缺失）。<b>得分=0 不代表没数据</b>；唯有原始值本身为 0 / 缺失（如资金流降级）才需关注。</div>
</div>

<div class="card">
  <div class="sec-h">对照参考表（XXFI 绝对区间 → 等级 / 信号）</div>
  <div class="tbl-scroll"><table class="ref-tbl"><thead><tr><th>区间</th><th>等级</th><th>信号</th><th>含义与反向操作</th></tr></thead>
  <tbody>{ref_rows}</tbody></table></div>
  <div class="note">说明：<b>XXFI 与贪婪指数为两套独立公式，不相加=100、非互补对子</b>。
  以 <b>XXFI（主表）</b> 判定反向信号等级；贪婪指数仅作辅助诊断（如局部热闹但非全面过热）。
  反向指标仅在情绪极端+趋势反转时有效，须配合自身交易系统与止损纪律。</div>
</div>

<div class="card trend">
  <div class="sec-h">历史趋势</div>
  <div class="legend"><b style="color:#2563eb">■</b> XXFI（主）　<b style="color:#f59e0b">■</b> 贪婪指数（副）</div>
  {trend_svg(hist)}
  <div class="tbl-scroll"><table class="hist-tbl" style="margin-top:14px"><thead><tr><th>日期</th><th>XXFI</th><th>贪婪</th><th>信号</th><th>等级</th></tr></thead>
  <tbody>{hist_rows}</tbody></table></div>
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
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    # 一并发布 xxfi_report.json 到 Pages 源目录（docs/），供本地端从云端回填
    # main_net/retail_net，使副表（散户净流入 + 主力—散户背离）与 GitHub 完全对齐。
    # workflow 已提交 docs/*，无需改动 CI 逻辑。
    json_out = os.path.join(out_dir, "xxfi_report.json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print(f"HTML 已生成: {args.out}（历史样本 {len(hist)} 条）")
    print(f"JSON 已发布: {json_out}（含 inputs.main_net / inputs.retail_net，供本地对齐副表）")

if __name__ == "__main__":
    main()
