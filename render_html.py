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
import datetime

# ===== 秋哥操作 · 实盘模拟 区块【2026-10-23 用户决定：撤出本页】=====
# 历史：2026-08-26 起用 sim_block.py 的 CSS/容器/JS 三件套内联，数据运行时从 output/ 拉取。
# 现在：净值 / 胜率 / 持仓属**个人资产数据**，不应在公开页面长期暴露 —— 已整体迁到
#       qg 盘中检测页（Cloudflare Worker，需 INTRADAY_KEY 才能看），同页合并「实盘模拟」卡。
# 因此这里恒置空：模板中的 {SIM_CSS} / {SIM_HTML} / {SIM_JS} 渲染成空串，页面不再出现该区块。
# 回滚：把下面三行改为 `from sim_block import SIM_CSS, SIM_HTML, SIM_JS` 即可（sim_block.py 未删）。
SIM_CSS = ""
SIM_HTML = ""
SIM_JS = ""

CST = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间 UTC+8

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
/* —— 冰点参考卡（方案B·全宽横条，独立于hero，置于背离诊断上方）—— */
.ice-card{background:linear-gradient(160deg,#f0f9ff 0%,#e0f2fe 100%);border:1px solid #bae6fd;border-radius:16px;
  padding:16px 18px;box-shadow:var(--shadow);}
.ice-head{font-size:13px;font-weight:800;color:#0369a1;display:flex;align-items:center;gap:5px;margin-bottom:11px;}
.ice-tag{font-size:10px;font-weight:600;color:#0284c7;background:#e0f2fe;border:1px solid #bae6fd;
  border-radius:999px;padding:1px 7px;margin-left:auto;white-space:nowrap;}
.ice-verdict{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;}
.ice-status{font-size:clamp(21px,5.5vw,30px);font-weight:800;line-height:1.1;}
.ice-status.fire{color:#dc2626;}      /* 冰点触发 = 恐慌带血筹码 */
.ice-status.cool{color:#0ea5e9;}      /* 未至冰点 = 冷静 */
.ice-sub{font-size:11.5px;color:#475569;margin-top:2px;line-height:1.3;}
.ice-right{text-align:right;min-width:140px;}
.ice-meter{display:flex;gap:6px;max-width:240px;margin-left:auto;}
.ice-cube{flex:1;height:8px;border-radius:5px;background:#cbd5e1;}
.ice-cube.on{background:linear-gradient(90deg,#7dd3fc,#0ea5e9);box-shadow:0 0 6px rgba(14,165,233,.55);}
.ice-met{font-size:11.5px;color:#0369a1;font-weight:700;margin-top:6px;}
.ice-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:13px;
  border-top:1px dashed #bae6fd;padding-top:12px;}
.ice-cell{background:rgba(255,255,255,.65);border:1px solid #cbe8fb;border-radius:10px;
  padding:9px 10px;display:flex;flex-direction:column;gap:3px;min-width:0;}
.ice-cell .k{font-size:11px;font-weight:700;color:#0369a1;display:flex;align-items:center;gap:5px;}
.ice-cell .k .key{background:#bae6fd;color:#0369a1;border-radius:4px;padding:0 5px;font-size:10px;font-weight:800;}
.ice-cell .k .st{margin-left:auto;font-size:12px;line-height:1;}
.ice-cell .v{font-size:13.5px;font-weight:700;font-variant-numeric:tabular-nums;color:#1f2937;line-height:1.3;overflow-wrap:anywhere;}
.ice-cell .v.pass{color:#16a34a;} .ice-cell .v.fail{color:#dc2626;} .ice-cell .v.na{color:#94a3b8;}
.ice-cell .th{font-size:10px;color:#94a3b8;line-height:1.3;overflow-wrap:anywhere;}
.ice-plan{margin-top:12px;padding:10px 12px;border-top:1px dashed #bae6fd;background:rgba(255,255,255,.55);
  border-radius:0 0 10px 10px;font-size:11px;line-height:1.75;color:#64748b;}
.ice-plan .ttl{font-weight:800;color:#dc2626;margin-bottom:4px;font-size:11.5px;}
.ice-plan .rw{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
@media(max-width:560px){ .ice-plan{font-size:10.5px;} }
/* —— 底部区域判断卡（旁挂 XXFI，置于冰点参考与背离诊断之间）—— */
.dip-card{background:linear-gradient(160deg,#f0fdf4 0%,#dcfce7 100%);border:1px solid #bbf7d0;border-radius:16px;
  padding:16px 18px;box-shadow:var(--shadow);}
.dip-head{font-size:13px;font-weight:800;color:#15803d;display:flex;align-items:center;gap:5px;margin-bottom:11px;}
.dip-tag{font-size:10px;font-weight:600;color:#16a34a;background:#dcfce7;border:1px solid #bbf7d0;
  border-radius:999px;padding:1px 7px;margin-left:auto;white-space:nowrap;}
.dip-main{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;}
.dip-status{font-size:clamp(21px,5.5vw,30px);font-weight:800;line-height:1.1;}
.dip-status.hit{color:#16a34a;}        /* 底部区域日 = 地量机会 */
.dip-status.idle{color:#64748b;}       /* 非底部区域日 */
.dip-status.na{color:#94a3b8;}         /* 暂未获取 */
.dip-sub{font-size:11.5px;color:#475569;margin-top:2px;line-height:1.3;}
.dip-right{text-align:right;min-width:150px;}
.dip-date{font-size:15px;font-weight:800;color:#15803d;font-variant-numeric:tabular-nums;}
.dip-date-label{font-size:10px;color:#94a3b8;font-weight:600;margin-bottom:2px;}
.dip-date-vol{font-size:12px;color:#0f766e;font-weight:700;font-variant-numeric:tabular-nums;margin-top:1px;}
.dip-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:13px;
  border-top:1px dashed #bbf7d0;padding-top:12px;}
.dip-cell{background:rgba(255,255,255,.65);border:1px solid #c7f0d2;border-radius:10px;
  padding:9px 10px;display:flex;flex-direction:column;gap:3px;min-width:0;}
.dip-cell .k{font-size:11px;font-weight:700;color:#15803d;}
.dip-cell .v{font-size:13.5px;font-weight:700;font-variant-numeric:tabular-nums;color:#1f2937;line-height:1.3;overflow-wrap:anywhere;}
.dip-cell .th{font-size:10px;color:#94a3b8;line-height:1.3;}
.dip-bar-wrap{margin-top:12px;}
.dip-bar-track{height:10px;background:#e8edf3;border-radius:6px;overflow:hidden;position:relative;}
.dip-bar-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#86efac,#16a34a);}
.dip-bar-mark{position:absolute;top:-3px;bottom:-3px;left:50%;width:2px;background:#dc2626;}  /* 50%阈值线 */
.dip-bar-labels{display:flex;justify-content:space-between;font-size:10px;color:#94a3b8;margin-top:4px;}
.dip-note{font-size:11px;color:#64748b;margin-top:11px;line-height:1.6;}
.dip-trend{margin-top:14px;}
.dip-trend svg{width:100%;height:auto;display:block;}
.dip-trend-note{font-size:10.5px;color:#94a3b8;margin-top:6px;line-height:1.5;}
/* —— 850天线抄底坐标卡（旁挂 XXFI，置于冰点参考与底部区域之间）—— */
.ma850-card{background:linear-gradient(160deg,#f7f9ff 0%,#edf1fa 100%);border:1px solid #dbe3f2;border-radius:16px;
  padding:16px 18px;box-shadow:var(--shadow);}
.ma850-head{font-size:13px;font-weight:800;color:#3f5b8a;display:flex;align-items:center;gap:5px;margin-bottom:11px;}
.ma850-tag{font-size:10px;font-weight:600;color:#4c6b9a;background:#eef2fa;border:1px solid #dbe3f2;
  border-radius:999px;padding:1px 7px;margin-left:auto;white-space:nowrap;}
.ma850-main{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;}
.ma850-status{font-size:clamp(21px,5.5vw,30px);font-weight:800;line-height:1.1;}
.ma850-status.entered{color:#15803d;}   /* 收盘进入 850 抄底区 */
.ma850-status.touched{color:#3f5b8a;}   /* 盘中跌破后收回（雾蓝，不用亮琥珀） */
.ma850-status.idle{color:#64748b;}      /* 未到 */
.ma850-status.na{color:#94a3b8;}
.ma850-sub{font-size:11.5px;color:#5b6b82;margin-top:2px;line-height:1.3;}
.ma850-right{text-align:right;min-width:170px;}
.ma850-ref-label{font-size:10px;color:#94a3b8;font-weight:600;margin-bottom:2px;}
.ma850-ref-date{font-size:15px;font-weight:800;color:#334e7a;font-variant-numeric:tabular-nums;}
.ma850-ref-sub{font-size:10.5px;color:#4c6b9a;font-weight:600;margin-top:1px;line-height:1.4;}
.ma850-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:13px;
  border-top:1px dashed #dbe3f2;padding-top:12px;}
.ma850-cell{background:rgba(255,255,255,.78);border:1px solid #e2e8f5;border-radius:10px;
  padding:9px 10px;display:flex;flex-direction:column;gap:3px;min-width:0;}
.ma850-cell.primary{border-color:#8aa4d6;box-shadow:inset 0 0 0 1px #8aa4d6;}
.ma850-cell .k{font-size:11px;font-weight:700;color:#3f5b8a;display:flex;align-items:center;gap:4px;min-width:0;}
.ma850-cell .k .st{margin-left:auto;font-size:9.5px;font-weight:800;padding:0 4px;border-radius:4px;white-space:nowrap;flex:none;}
.ma850-cell .k .st.below{color:#15803d;background:#dcfce7;}
.ma850-cell .k .st.touched{color:#3f5b8a;background:#e6edf9;}
.ma850-cell .k .st.above{color:#64748b;background:#f1f5f9;}
.ma850-cell .k .st.na{color:#94a3b8;background:#f1f5f9;}
.ma850-cell .v{font-size:15px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.2;}
.ma850-cell .v.up{color:#dc2626;}      /* 线上（A股红涨） */
.ma850-cell .v.down{color:#16a34a;}    /* 线下（A股绿跌） */
.ma850-cell .v.flat{color:#64748b;}
.ma850-cell .line{font-size:10.5px;color:#5f6b80;font-variant-numeric:tabular-nums;line-height:1.3;overflow-wrap:anywhere;}
.ma850-cell .low{font-size:10px;color:#94a3b8;font-variant-numeric:tabular-nums;line-height:1.3;overflow-wrap:anywhere;}
.ma850-note{font-size:10.5px;color:#6b7280;margin-top:11px;line-height:1.6;}
.ma850-note b{color:#3f5b8a;}
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
  .ice-grid{grid-template-columns:repeat(2,1fr);}
  .ice-right{text-align:left;min-width:0;}
  .ice-meter{margin-left:0;}
  .dip-grid{grid-template-columns:repeat(2,1fr);}
  .dip-right{text-align:left;min-width:0;}
  .ma850-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
  .ma850-right{text-align:left;min-width:0;}
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


def dip_trend_svg(hist, peak90=None):
    """底部区域判断卡 · 近30日全市场成交额趋势（内联 SVG，无 JS/CDN）。

    hist: list[{"date":"YYYY-MM-DD","total":float(元)}]（通常尾部 30 日）。
    peak90: 真·近90日峰值（来自 _turnover_cache.json 滚动窗口的 max90_total）。
        参考线与柱体染色统一用它——与卡片右上角明细、is_bottom_today 判定同口径。
        缺失时回退 hist 窗口内最大值（兼容旧数据；此时标签语义为「窗口内峰值」）。
    绘制：柱体（低于红色阈值线=底部区域日，绿色；其余浅灰）
        + 淡灰虚线（近90日峰值 100%）+ 红色虚线（峰值×50% 底部阈值）。
    图层顺序：网格 → 柱体 → 参考线 → 文字（参考线与文字始终压在柱体之上，
        并带白色描边 halo，避免被柱体遮挡）。
    x 轴日期标注：首 / 中 / 尾 + 窗口内成交额最低日（若最低日恰为首/中/尾则不重复标注）。
    日期一律 MM-DD，跨年时按自然日显示（如 12-31 → 01-05）。
    Y 轴以「万亿」刻度。无/不足 2 点返回提示。
    """
    if not hist or len(hist) < 2:
        return '<p class="muted">近30日成交额样本不足（需 ≥2 个交易日），暂无法绘制趋势。</p>'
    pts = [(h.get("date", ""), float(h.get("total", 0)))
           for h in hist if isinstance(h.get("total"), (int, float)) and h.get("total", 0) > 0]
    if len(pts) < 2:
        return '<p class="muted">近30日成交额样本不足，暂无法绘制趋势。</p>'
    w, h = 680, 200
    # pad_b 留出两行标签空间：柱底三角 + 日期（最低日与首/中/尾过近时可上移一行）
    pad_l, pad_r, pad_t, pad_b = 44, 12, 14, 30
    n = len(pts)
    totals = [v for _, v in pts]
    # 峰值口径修复(2026-08-25)：优先用真·近90日峰值（与右上角明细/is_bottom_today 同源），
    # 避免此前用 hist30 窗口内最大值冒充「近90日峰值」导致两处数值自相矛盾。
    try:
        p90 = float(peak90) if peak90 else 0.0
    except (TypeError, ValueError):
        p90 = 0.0
    peak = p90 if p90 > 0 else max(totals)
    threshold = peak * 0.5
    vmin, vmax = 0.0, peak * 1.08

    def X(i):
        return pad_l + (w - pad_l - pad_r) * i / (n - 1)

    def Y(v):
        return pad_t + (h - pad_t - pad_b) * (vmax - v) / (vmax - vmin)

    svg = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="近30日全市场成交额趋势">']
    # 横向网格 + 万亿刻度
    for g in (0.0, 0.25, 0.5, 0.75, 1.0):
        val = vmin + (vmax - vmin) * g
        y = Y(val)
        svg.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w-pad_r}" y2="{y:.1f}" stroke="#eef2f7"/>')
        svg.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" font-size="10" fill="#9aa3af" text-anchor="end">{val/1e12:.2f}万亿</text>')
    # 柱体（先画，后续参考线与文字覆盖其上）
    bw = (w - pad_l - pad_r) / n * 0.62
    base = h - pad_b
    for i, (_, v) in enumerate(pts):
        x = X(i) - bw / 2
        yv = Y(v)
        bh = base - yv
        is_today = (i == n - 1)
        is_bottom = v <= threshold
        fill = "#22c55e" if is_bottom else "#cbd5e1"
        stroke = "#15803d" if is_today else "none"
        sw = 1.4 if is_today else 0
        svg.append(f'<rect x="{x:.1f}" y="{yv:.1f}" width="{bw:.1f}" height="{max(bh,0.5):.1f}" rx="1.5" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    # 白色描边 halo：保证文字压在任意颜色柱体上仍清晰
    halo = 'paint-order="stroke" stroke="#ffffff" stroke-width="3" stroke-linejoin="round"'
    # 峰值参考线（淡灰虚线，画在柱体之上）
    yp = Y(peak)
    svg.append(f'<line x1="{pad_l}" y1="{yp:.1f}" x2="{w-pad_r}" y2="{yp:.1f}" stroke="#94a3b8" stroke-width="1" stroke-dasharray="4 3"/>')
    svg.append(f'<text x="{w-pad_r}" y="{yp-4:.1f}" font-size="9" fill="#94a3b8" text-anchor="end" {halo}>近90日峰值 {peak/1e12:.2f}万亿</text>')
    # 底部阈值线（红虚线 = 峰值×50%，画在柱体之上；文字置于线上方）
    yt = Y(threshold)
    svg.append(f'<line x1="{pad_l}" y1="{yt:.1f}" x2="{w-pad_r}" y2="{yt:.1f}" stroke="#dc2626" stroke-width="1.2" stroke-dasharray="5 3"/>')
    svg.append(f'<text x="{w-pad_r}" y="{yt-4:.1f}" font-size="9" font-weight="600" fill="#dc2626" text-anchor="end" {halo}>底部阈值(峰值×50%) {threshold/1e12:.2f}万亿</text>')
    # x 轴日期标签：首 / 中 / 尾 + 窗口内成交额最低日
    base_idx = [0, n // 2, n - 1]
    imin = min(range(n), key=lambda i: pts[i][1])
    mark_min = imin not in base_idx          # 最低日恰为首/中/尾时不重复标注
    for i in sorted(set(base_idx)):
        d = pts[i][0][5:]  # MM-DD（跨年按自然日显示）
        svg.append(f'<text x="{X(i):.1f}" y="{h-8:.1f}" font-size="9" fill="#9aa3af" text-anchor="middle" {halo}>{d}</text>')
    if mark_min:
        d = pts[imin][0][5:]
        xm = X(imin)
        # 与首/中/尾标签过近（横向 <30px）时上移一行，避免重叠
        too_close = any(abs(xm - X(j)) < 30 for j in base_idx)
        if too_close:
            svg.append(f'<text x="{xm:.1f}" y="{h-19:.1f}" font-size="9" font-weight="700" fill="#16a34a" text-anchor="middle" {halo}>{d}</text>')
        else:
            # 柱底向上三角，指向窗口内成交额最低日；位于绘图区之外，绝不与参考线/文字冲突
            svg.append(f'<path d="M{xm:.1f},{base+1:.1f} L{xm-4:.1f},{base+7:.1f} L{xm+4:.1f},{base+7:.1f} Z" fill="#16a34a"/>')
            svg.append(f'<text x="{xm:.1f}" y="{h-8:.1f}" font-size="9" font-weight="700" fill="#16a34a" text-anchor="middle" {halo}>{d}</text>')
    svg.append('</svg>')
    return "".join(svg)

def bar(score, cls):
    s = max(0, min(100, float(score)))
    return f'<div class="bar {cls}"><i style="width:{s:.1f}%"></i></div>'


# ---------------- 冰点实操计划（固化·仅冰点触发时显示；纯名称不带代码） ----------------
# v2026-08-19 修订：标的池改为纯宽基指数 ETF（不做行业周期押注）；
#   中证2000 优选增强 159552（7-17 冰点实测 20 交易日 +12.22% vs 563300 +7.23%，增强超额 ~+5pp 且回撤减半）；
#   首批加入中证500/沪深300 大盘宽基对冲，第三批提前至「5-8 日不破低点」避免右侧过晚（8-04 实测 -1.63%）。
ICE_OP_PLAN = '''
    <div class="ice-plan">
      <div class="ttl">📋 冰点实操计划（战术桶·仅抢反弹，非长持）</div>
      <div class="rw">• 第一批（触发当日尾盘 14:30–15:00 / 最迟次日开盘）：中证2000增强(159552) + 中证1000 + 创业板 + 科创50，占战术桶 1/3</div>
      <div class="rw">• 第二批（触发后 3–5 日不破前低）：+ 中证500 + 沪深300 + 中证2000，占 1/3</div>
      <div class="rw">• 第三批（5–8 日收盘不破冰点日低点即补）：补齐 + 恒生科技（卫星仓），占 1/3</div>
      <div class="rw">• 退出：沪深300 自低点 +8~12% / 高β +15~25% 分批止盈；D1 下跌&lt;2000、涨停&gt;跌停连续 2 日退场</div>
      <div class="rw">• 铁律：战术桶 ≠ 战略桶（红利/债券不动）· 单信号 ≤ 1/3 · 获利转回红利/债券</div>
    </div>'''


def render_ice_card(b):
    """冰点参考卡（旁挂 XXFI，独立、不影响原指标）。无数据返回空串。
    方案B：全宽卡片，置于「主力—散户背离诊断」上方。
    结构：标题栏 + 结论区（左 emoji/状态/副标题 · 右 冰晶计横条 + x/4 满足）+ 4 列维度网格。
    每个维度格：维度名(含 Dx 徽标) + 状态图标 + 实测值(粗体) + 判定标准(10px灰·完整)。
    冰点触发时，卡片底部追加「冰点实操计划」小字块（ICE_OP_PLAN，纯名称）；未触发不显示。
    """
    if not b:
        return ""
    verdict = b.get("verdict")
    dims = b.get("dimensions", [])
    emoji = b.get("verdict_emoji", "🧊")
    if verdict:
        s_cls, s_txt, sub = "fire", "冰点触发", "极端恐慌 · 带血筹码居多的时机"
    else:
        s_cls, s_txt, sub = "cool", "非冰点", "未至极端 · 纪律不出手"
    met = sum(1 for d in dims if d.get("pass") is True)
    na = sum(1 for d in dims if d.get("pass") is None)
    cubes = "".join(
        f'<div class="ice-cube {"on" if d.get("pass") is True else ""}" title="{d.get("key","")} {d.get("name","")}"></div>'
        for d in dims
    )
    cells = ""
    for d in dims:
        p = d.get("pass")
        if p is True:
            pc, pt = "pass", "✅"
        elif p is False:
            pc, pt = "fail", "❌"
        else:
            pc, pt = "na", "—"
        cells += (f'<div class="ice-cell">'
                  f'<div class="k"><span class="key">{d.get("key","")}</span>{d.get("name","")}'
                  f'<span class="st">{pt}</span></div>'
                  f'<div class="v {pc}">{d.get("value","—")}</div>'
                  f'<div class="th">（{d.get("threshold","")}）</div>'
                  f'</div>')
    na_txt = f" · {na}项暂未获取" if na else ""
    plan_html = ICE_OP_PLAN
    return f'''
    <div class="card ice-card">
      <div class="ice-head">❄ 冰点参考（A股极端恐慌） <span class="ice-tag">参考指标·不影响XXFI</span></div>
      <div class="ice-verdict">
        <div>
          <div class="ice-status {s_cls}">{emoji} {s_txt}</div>
          <div class="ice-sub">{sub}</div>
        </div>
        <div class="ice-right">
          <div class="ice-meter" title="{met}/{len(dims)} 维度满足">{cubes}</div>
          <div class="ice-met">{met} / {len(dims)} 维度满足{na_txt}</div>
        </div>
      </div>
      <div class="ice-grid">{cells}</div>{plan_html}
    </div>'''

def _fmt_yi(v):
    """元 → 亿元字符串（NaN/None 返回 —）"""
    try:
        fv = float(v)
        if fv != fv:
            return "—"
        return f"{fv/1e8:.0f} 亿"
    except Exception:
        return "—"


def _fmt_wanyi(v):
    """元 → 万亿元字符串（NaN/None/≤0 返回 —）"""
    try:
        fv = float(v)
        if fv != fv or fv <= 0:
            return "—"
        return f"{fv/1e12:.2f} 万亿"
    except Exception:
        return "—"


def render_dibudian_card(d):
    """底部区域判断卡（旁挂 XXFI，独立、不影响原指标）。无数据返回空串。
    结构：标题栏 + 主区（左 状态/副标题 · 右 持久日期）+ 3列明细网格 + 比率进度条(含50%阈值线)
          + 近30日成交额趋势柱图（峰值 / 底部阈值 参考线）。
    """
    if not d:
        return ""
    is_hit = d.get("is_bottom_today")
    last_date = d.get("last_bottom_date") or "暂未记录"
    last_vol = d.get("last_bottom_volume")
    ratio = d.get("ratio")
    today_total = d.get("today_total")
    max90 = d.get("max90_total")
    threshold = d.get("threshold", 0.5)
    emoji = d.get("verdict_emoji", "—")
    src = d.get("_src") or "—"

    if is_hit is True:
        s_cls, s_txt, sub = "hit", "底部区域日", "地量 · 抛压衰竭，关注机会区域"
    elif is_hit is False:
        s_cls, s_txt, sub = "idle", "非底部区域日", "成交额未缩至近90日峰值一半以下"
    else:
        s_cls, s_txt, sub = "na", "暂未获取", "数据源暂不可用"

    # 进度条：以近90日最高为 100%，当日占比填充；50% 处红线即阈值
    pct_fill = min(100.0, float(ratio) * 100.0) if ratio is not None and max90 else 0.0
    ratio_txt = f"{ratio*100:.1f}%" if ratio is not None else "—"

    detail = (
        f'<div class="dip-cell"><div class="k">当日全市场成交额</div>'
        f'<div class="v">{_fmt_wanyi(today_total)}</div>'
        f'<div class="th">上证+深证 · 全市场口径</div></div>'
        f'<div class="dip-cell"><div class="k">近90日最高成交额</div>'
        f'<div class="v">{_fmt_wanyi(max90)}</div>'
        f'<div class="th">约一个完整季度峰值</div></div>'
        f'<div class="dip-cell"><div class="k">当前比率 / 阈值</div>'
        f'<div class="v">{ratio_txt} / {int(threshold*100)}%</div>'
        f'<div class="th">当日 ≤ 峰值×{int(threshold*100)}% 即底部区域</div></div>'
    )

    # 近30日成交额趋势（柱 + 峰值 / 底部阈值参考线）
    hist30 = d.get("hist30") or ((d.get("inputs") or {}) or {}).get("hist30")
    if hist30:
        trend_html = (
            '<div class="dip-trend">'
            + dip_trend_svg(hist30, peak90=max90)
            + f'<div class="dip-trend-note">柱体低于红色虚线（近90日峰值×50%）即触发底部区域；最右一根为当日；绿色 ▲ 标记为窗口内成交额最低日。'
            + f'数据来源：{src}</div></div>'
        )
    else:
        trend_html = '<div class="dip-trend"><p class="muted">近30日成交额样本不足，暂无法绘制趋势。</p></div>'

    return f'''
    <div class="card dip-card">
      <div class="dip-head">🌱 底部区域判断（地量区域） <span class="dip-tag">参考指标·不影响XXFI</span></div>
      <div class="dip-main">
        <div>
          <div class="dip-status {s_cls}">{emoji} {s_txt}</div>
          <div class="dip-sub">{sub}</div>
        </div>
        <div class="dip-right">
          <div class="dip-date-label">最近一次底部区域日</div>
          <div class="dip-date">{last_date}</div>
          <div class="dip-date-vol">{_fmt_wanyi(last_vol) if last_vol else '—'}</div>
        </div>
      </div>
      <div class="dip-grid">{detail}</div>
      <div class="dip-bar-wrap">
        <div class="dip-bar-track">
          <div class="dip-bar-fill" style="width:{pct_fill:.1f}%"></div>
          <div class="dip-bar-mark"></div>
        </div>
        <div class="dip-bar-labels"><span>0%</span><span style="color:#dc2626">阈值 {int(threshold*100)}%</span><span>100%（近90日峰值）</span></div>
      </div>
      {trend_html}
      <div class="dip-note">底部区域 = 地量区域。当日全市场成交额缩至近90日最高的一半及以下，视为抛压衰竭的底部信号。该日期持续显示，直到被下一个满足条件的交易日取代。</div>
    </div>'''


def _pct2(v):
    """小数 → 带符号百分比（None 返回 —）"""
    try:
        fv = float(v)
        if fv != fv:
            return "—"
        return f"{fv*100:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _px2(v):
    """指数点位 → 两位小数（None 返回 —）"""
    try:
        fv = float(v)
        if fv != fv:
            return "—"
        return f"{fv:.2f}"
    except (TypeError, ValueError):
        return "—"


def render_ma850_card(m):
    """850天线抄底坐标卡（旁挂 XXFI，独立、不影响原指标）。无数据返回空串。

    观点来源：plutus（2026-10）——各大指数跌至 850 天线为大资金抄底位。
    结构：标题栏 + 主区（左 综合状态/副标题 · 右 中证1000 最近触发）
          + 4 列指数坐标格（现价 / 850线 / 收盘偏离 / 当日最低偏离）。
    状态：收盘跌破 > 盘中跌破 > 线上；盘中跌破单独成态，避免漏掉「深V收回」。
    """
    if not m:
        return ""
    verdict = m.get("verdict") or "na"
    indices = m.get("indices") or []
    below = m.get("below_count", 0)
    touch = m.get("touch_count", 0)
    closest_name = m.get("closest_name") or "—"
    closest_dev = m.get("closest_dev")
    primary = m.get("primary") or {}
    data_date = m.get("_data_date") or "—"
    src = m.get("_src") or "—"

    if verdict.startswith("entered"):
        s_cls = "entered"
        sub = f"{below}/4 指数收盘在 850 线下"
        if touch:
            sub += f" · 另有 {touch} 个盘中跌破"
    elif verdict == "touched":
        s_cls = "touched"
        sub = f"{touch}/4 盘中跌破后收回 · 收盘未跌破"
    elif verdict == "not_reached":
        s_cls = "idle"
        sub = f"最近：{closest_name} 距 850 线 {_pct2(closest_dev)}"
    else:
        s_cls, sub = "na", "数据源暂不可用"

    # 右侧锚点：固定中证1000（plutus 原文举例）
    if primary.get("name"):
        ref_label = f"{primary.get('name')} · 上次收盘跌破"
        ref_date = primary.get("last_close_below") or "—"
        d_since = primary.get("days_since_close_below")
        d_touch = primary.get("days_since_low_touch")
        if primary.get("state") == "below":
            db = primary.get("days_below") or 0
            ref_sub = ("今天收盘跌破 850 线" if db <= 1
                       else f"今天收盘跌破 · 已连续 {db} 个交易日收在线下")
        else:
            ref_sub = ("今天盘中跌破后收回" if d_touch == 0 else "今天没有跌破")
            if d_since is not None:
                ref_sub += f" · 距上次收盘跌破已 {d_since} 个交易日"
    else:
        ref_label, ref_date, ref_sub = "中证1000 · 上次收盘跌破", "—", "暂未获取"

    chip = {"below": "收盘跌破", "touched": "盘中跌破", "above": "线上", "na": "—"}
    cells = ""
    for x in indices:
        state = x.get("state") if x.get("state") in chip else "na"
        dev = x.get("dev")
        dev_cls = "up" if (dev is not None and dev > 0) else ("down" if dev is not None and dev < 0 else "flat")
        low_txt = "当日最低 —"
        if x.get("low") is not None:
            low_txt = f"最低 {_px2(x.get('low'))}（{_pct2(x.get('low_dev'))}）"
        cells += (
            f'<div class="ma850-cell{" primary" if x.get("is_primary") else ""}">'
            f'<div class="k">{x.get("name","—")}'
            f'<span class="st {state}">{chip[state]}</span></div>'
            f'<div class="v {dev_cls}">{_pct2(dev)}</div>'
            f'<div class="line">850线 {_px2(x.get("ma850"))}</div>'
            f'<div class="line">收盘 {_px2(x.get("close"))}</div>'
            f'<div class="low">{low_txt}</div>'
            f'</div>'
        )

    return f'''
    <div class="card ma850-card">
      <div class="ma850-head">📐 850天线抄底坐标（plutus） <span class="ma850-tag">短线参考·不影响XXFI</span></div>
      <div class="ma850-main">
        <div>
          <div class="ma850-status {s_cls}">{m.get("verdict_emoji","—")} {m.get("verdict_text","暂未获取")}</div>
          <div class="ma850-sub">{sub}</div>
        </div>
        <div class="ma850-right">
          <div class="ma850-ref-label">{ref_label}</div>
          <div class="ma850-ref-date">{ref_date}</div>
          <div class="ma850-ref-sub">{ref_sub}</div>
        </div>
      </div>
      <div class="ma850-grid">{cells}</div>
      <div class="ma850-note">
        <b>850线</b> = 最近 850 个交易日收盘均价（移动靶/滞后指标）；收盘跌破 ≠ 立刻见底。
        数据：{src}｜截至 {data_date}。<br>
        历史小注：中证1000 深度跌破（低于5%）8 次，抄底后 1 年 7/8 为正，但信号后平均仍先跌 10.3%（2010以来周K近似，样本少）。观点来源：plutus（2026-10）。本卡为坐标提示，非投资建议。
      </div>
    </div>'''


GUARD_CSS = r"""
/* —— 国家队护盘追踪卡（旁挂 XXFI，置于冰点参考与 850 坐标之间）—— */
.guard-card{background:linear-gradient(160deg,#fbfaff 0%,#f4f1fc 100%);border:1px solid #e9e3f7;border-radius:16px;
  padding:18px 20px;box-shadow:var(--shadow);overflow:hidden;}
.guard-head{font-size:13px;font-weight:800;color:#6a5aa8;display:flex;align-items:center;gap:5px;margin-bottom:14px;flex-wrap:wrap;}
.guard-tag{font-size:10px;font-weight:600;color:#7a6bb5;background:#f1ecfb;border:1px solid #e9e3f7;
  border-radius:999px;padding:1px 7px;margin-left:auto;white-space:nowrap;}
.g-main{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;}
.g-left{min-width:0;}
.g-verdict{font-size:clamp(22px,6vw,28px);font-weight:800;line-height:1.15;display:flex;align-items:center;gap:9px;}
.g-verdict .g-dot{width:13px;height:13px;border-radius:50%;flex:none;display:inline-block;}
.g-verdict.buy{color:#5b4a9e;}
.g-verdict.buy .g-dot{background:#8b7ad6;box-shadow:0 0 0 4px #ece7fa;}
.g-verdict.weak{color:#8a7fb8;}
.g-verdict.weak .g-dot{background:#b8abdf;box-shadow:0 0 0 4px #f2eefb;}
.g-verdict.none{color:#8d93a3;}
.g-verdict.none .g-dot{background:#c3c9d4;box-shadow:0 0 0 4px #f1f3f6;}
.g-verdict.na{color:#a6abba;}
.g-verdict.na .g-dot{background:#d5d9e2;box-shadow:0 0 0 4px #f4f6f9;}
.g-sub{font-size:12px;color:#7f7796;margin-top:7px;line-height:1.45;}
.g-right{text-align:right;min-width:150px;}
.g-k{font-size:10px;color:#9d97b3;font-weight:600;letter-spacing:.2px;}
.g-time{font-size:19px;font-weight:800;color:#5b4a9e;font-variant-numeric:tabular-nums;line-height:1.25;margin-top:1px;}
.g-k2{font-size:10.5px;color:#8b84a3;margin-top:2px;}
.g-sec{margin-top:16px;border-top:1px solid #efeaf9;padding-top:13px;}
.g-sec-h{font-size:12px;font-weight:800;color:#5b4a9e;}
.g-sec-h b{color:#7d68c6;}
.g-sec-h span{font-weight:500;color:#9d97b3;font-size:10.5px;margin-left:6px;}
.g-legend{display:flex;align-items:center;gap:5px;font-size:9.5px;color:#a29cb8;margin:7px 0 9px;flex-wrap:wrap;}
.g-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;}
.g-legend i.am{background:#ded5f2;}
.g-legend i.md{background:#b6a3e3;margin-left:8px;}
.g-legend i.tl{background:#7d68c6;margin-left:8px;}
.gr{display:grid;grid-template-columns:96px 1fr 74px 40px;align-items:center;gap:9px;padding:5px 0;}
.gr-h{padding:0 0 2px;align-items:end;}
.gr-h div{font-size:9px;font-weight:600;color:#a9a2c0;text-align:right;line-height:1.2;}
.gr-h .nh{text-align:left;font-size:9px;color:#b3adc4;}
.gr-n{font-size:11.5px;font-weight:700;color:#3f3766;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;letter-spacing:-.2px;}
.gr.hit .gr-n{color:#5b4a9e;}
.gr-b{height:15px;border-radius:5px;overflow:hidden;display:flex;background:#f4f1fb;box-shadow:inset 0 0 0 1px #efeaf9;}
.gr-b .sg{display:block;height:100%;}
.gr-b .sg.am{background:#ded5f2;}
.gr-b .sg.md{background:#b6a3e3;}
.gr-b .sg.tl{background:#7d68c6;}
.gr.hit .gr-b .sg.tl{background:#6a55b8;}
.gr-v{font-size:13px;font-weight:800;color:#3f3766;text-align:right;font-variant-numeric:tabular-nums;}
.gr-v span{font-size:9px;font-weight:600;color:#a29cb8;margin-left:1px;}
.gr-p{font-size:11px;font-weight:700;color:#8b84a3;text-align:right;font-variant-numeric:tabular-nums;}
.gr.hit .gr-p{color:#5b4a9e;}
.g-rest{font-size:10.5px;color:#9d97b3;margin-top:9px;line-height:1.5;}
.g-rest b{color:#5b4a9e;}
.g-sep{height:1px;background:linear-gradient(90deg,transparent,#e6e0f5,transparent);margin:16px 0 13px;}
.g-share{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;}
.g-share-l{min-width:0;}
.g-share-v{font-size:23px;font-weight:800;color:#6a5aa8;font-variant-numeric:tabular-nums;margin-top:3px;}
.g-share-m{font-size:10.5px;color:#8b84a3;margin-top:1px;}
.g-share-r{flex:0 1 330px;min-width:150px;}
.g-share-r svg{width:100%;max-width:100%;height:auto;display:block;}
.g-share-r svg .pos{fill:#a892e0;}
.g-share-r svg .neg{fill:#cfd5df;}
.g-x{display:flex;justify-content:space-between;font-size:9px;color:#a29cb8;font-variant-numeric:tabular-nums;margin-top:2px;}
.guard-note{font-size:10px;color:#a29cb8;margin-top:12px;line-height:1.6;}
.guard-more{display:inline-block;margin-top:8px;font-size:11px;font-weight:700;color:#7d68c6;text-decoration:none;}
.guard-more:hover{text-decoration:underline;}
.gp-tbl{width:100%;border-collapse:collapse;font-size:12px;}
.gp-tbl th{font-size:10px;font-weight:600;color:#9d97b3;text-align:right;padding:4px 6px;border-bottom:1px solid #efeaf9;white-space:nowrap;}
.gp-tbl th:first-child,.gp-tbl th:nth-child(2){text-align:left;}
.gp-tbl td{padding:6px;border-bottom:1px solid #f6f3fc;color:#3f3766;}
.gp-tbl tr.hit td{background:#faf8ff;}
.gp-tbl .nm{font-weight:700;white-space:nowrap;}
.gp-tbl .gp{font-size:10px;color:#9d97b3;white-space:nowrap;}
.gp-tbl .num{text-align:right;font-variant-numeric:tabular-nums;}
.gp-tbl .b{font-weight:800;color:#5b4a9e;}
.gp-bar{display:flex;height:12px;border-radius:4px;overflow:hidden;background:#f4f1fb;min-width:110px;}
.gp-bar i{display:block;height:100%;}
.gp-bar .am{background:#ded5f2;} .gp-bar .md{background:#b6a3e3;} .gp-bar .tl{background:#7d68c6;}
tr.hit .gp-bar .tl{background:#6a55b8;}
.gp-two{display:grid;grid-template-columns:1fr 1fr;gap:14px;}
@media(max-width:640px){.gp-two{grid-template-columns:1fr;}.gp-tbl{font-size:11px;}}
.gp-back{font-size:12px;color:#6a5aa8;text-decoration:none;display:inline-block;margin-bottom:10px;}

@media(max-width:640px){
  .gr{grid-template-columns:84px 1fr 66px 34px;gap:6px;}
  .gr-n{font-size:11px;}
  .gr-h div{font-size:8.5px;}
  .g-right{text-align:left;}
  .g-share-r{flex:1 1 100%;}
}
"""

# ============================================================ 国家队护盘追踪卡
GUARD_RIGHT = {
    "buy": ("买入时段", True),
    "weak": ("买入时段", True),
    "none": ("最活跃 5 分钟", False),
    "na": ("时段", False),
}


def _g_pct(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _g_trend(series):
    """近 20 日净申购柱（A股配色在浅紫系下改为：正=紫，负=灰）"""
    if not series:
        return "", ""
    vals = [(_g_pct(x.get("net_yi"))) for x in series]
    mx = max([abs(v) for v in vals] + [1.0])
    W, H, pad = 660, 84, 6
    bw = (W - pad * 2) / len(vals)
    zero = H / 2 + 2
    seg = ['<svg viewBox="0 0 %d %d" role="img" aria-label="近20日护盘篮子净申购">' % (W, H)]
    for i, v in enumerate(vals):
        h = max(1.2, abs(v) / mx * (H / 2 - 6))
        x = pad + i * bw + bw * 0.22
        y = zero - h if v > 0 else zero
        cls = "pos" if v > 0 else "neg"
        seg.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1"/>'
                   % (cls, x, y, bw * 0.56, h))
    seg.append("</svg>")
    pick = sorted({0, len(vals) // 3, len(vals) * 2 // 3, len(vals) - 1})
    labs = "".join("<span>%s</span>" % (series[k].get("date", "")[5:]) for k in pick)
    return "".join(seg), '<div class="g-x">%s</div>' % labs


def render_guard_card(g):
    if not g:
        return ""
    kind = g.get("verdict") or "na"
    if kind not in GUARD_RIGHT:
        kind = "na"
    right_label, tail_scope = GUARD_RIGHT[kind]

    rows_html = ""
    for x in (g.get("rows") or []):
        am = _g_pct(x.get("am_pct"))
        md = _g_pct(x.get("md_pct"))
        tl = max(0.0, 100.0 - am - md)
        rows_html += (
            '<div class="gr%s">'
            '<div class="gr-n">%s</div>'
            '<div class="gr-b"><span class="sg am" style="width:%.2f%%"></span>'
            '<span class="sg md" style="width:%.2f%%"></span>'
            '<span class="sg tl" style="width:%.2f%%"></span></div>'
            '<div class="gr-v">%s %.0f</div>'
            '<div class="gr-p">%.0f%%</div>'
            '</div>' % (" hit" if x.get("hit") else "", x.get("label", ""), am, md, tl,
                        (x.get("dom_seg") or "尾盘"),
                        _g_pct(x.get("dom_yi", x.get("tail_yi"))),
                        _g_pct(x.get("dom_pct", x.get("tail_pct"))))
        )
    if not rows_html:
        rows_html = '<div class="g-rest">今日分时暂未获取，无法判断时段分布。</div>'

    rest = ""
    if g.get("rest_n"):
        rest = ('<div class="g-rest">其余 %d 只尾盘合计 %.0f 亿 · 全部 %d 只合计 <b>%.0f 亿</b></div>'
                % (g.get("rest_n", 0), _g_pct(g.get("rest_tail_yi")),
                   g.get("n_etf", 0), _g_pct(g.get("total_tail_yi"))))

    sh = g.get("share") or {}
    s_date = sh.get("date") or "—"
    s_net = _g_pct(sh.get("net_yi"))
    share_html = ""
    if sh.get("date"):
        share_html = (
            '<div class="g-share-v">%+.0f 亿</div>'
            '<div class="g-share-m">%d/%d 只沪市 ETF 净申购 · 连续 %d 日 · 近5日 %+.0f 亿</div>'
            % (s_net, sh.get("pos_cnt", 0), sh.get("basket_cnt", 0),
               sh.get("days_pos", 0), _g_pct(sh.get("d5_yi")))
        )
    else:
        share_html = ('<div class="g-share-v">暂未获取</div>'
                      '<div class="g-share-m">上交所份额接口未返回数据</div>')
    svg, xlab = _g_trend(sh.get("series") or [])

    if kind in ("buy", "weak"):
        peak_line = "最集中 %s · %s 亿" % (g.get("peak_window") or "—", g.get("peak_amt_yi") or 0)
        time_txt = g.get("window") or "14:45–15:00"
    elif kind == "none":
        peak_line = "尾盘未放量"
        time_txt = g.get("peak_window") or "—"
    else:
        peak_line = ""
        time_txt = "—"

    note_extra = ""
    if (g.get("share") or {}).get("src") == "history":
        note_extra += "　份额为最近一次本地推送（交易所份额接口在 CI 侧不可达，跑批只用形态）。"
    if g.get("missing"):
        note_extra += "　今日分时未取到：%s。" % "、".join(g["missing"][:4])

    return (
        '<div class="card guard-card">\n'
        '  <div class="guard-head">🛡️ 国家队护盘追踪 <span class="guard-tag">旁挂·不影响XXFI</span></div>\n'
        '  <div class="g-main">\n'
        '    <div class="g-left">\n'
        '      <div class="g-verdict %s"><span class="g-dot"></span>%s</div>\n'
        '      <div class="g-sub">%s</div>\n'
        '    </div>\n'
        '    <div class="g-right">\n'
        '      <div class="g-k">%s</div>\n'
        '      <div class="g-time">%s</div>\n'
        '      <div class="g-k2">%s</div>\n'
        '    </div>\n'
        '  </div>\n'
        '  <div class="g-sec">\n'
        '    <div class="g-sec-h"><b>①</b> 今天买了什么 <span>条形 = 全天成交额，越靠右越接近收盘</span></div>\n'
        '    <div class="g-legend"><i class="am"></i>上午 09:30–11:30<i class="md"></i>午后 13:00–14:45<i class="tl"></i>尾盘 14:45–15:00</div>\n'
        '    <div class="gr gr-h"><div></div><div class="nh">↑ 全天成交额</div><div>最大时段(亿)</div><div>占比</div></div>\n'
        '    %s\n'
        '    %s\n'
        '  </div>\n'
        '  <div class="g-sep"></div>\n'
        '  <div class="g-share">\n'
        '    <div class="g-share-l">\n'
        '      <div class="g-sec-h"><b>②</b> 昨日份额确认 <span>%s · T+1 发布，用来验证"是不是真的净买入"</span></div>\n'
        '      %s\n'
        '    </div>\n'
        '    <div class="g-share-r">%s%s</div>\n'
        '  </div>\n'
        '  <div style="text-align:right"><a class="guard-more" href="./guard.html">查看 11 只明细与份额曲线 →</a></div>'
        '  <div class="guard-note">口径：尾盘 = 14:45–15:00；份额 = 上交所按日归档的全市场 ETF 份额，'
        '深市（嘉实300 / 创业板两只）无历史份额接口，靠每日快照累积。%s</div>\n'
        '</div>'
        % (kind, (g.get("verdict_text") or "暂未获取"), (g.get("verdict_sub") or ""),
           right_label, time_txt, peak_line,
           rows_html, rest, s_date, share_html, svg, xlab, note_extra)
    )



def render_guard_page(g):
    """详情页 docs/guard.html：11 只全表 + 份额曲线 + 判定流水"""
    if not g:
        return ""
    kind = g.get("verdict") or "na"
    if kind not in GUARD_RIGHT:
        kind = "na"
    rows = g.get("rows_all") or g.get("rows") or []
    rows_html = ""
    for x in rows:
        am = _g_pct(x.get("am_pct"))
        md = _g_pct(x.get("md_pct"))
        tl = max(0.0, 100.0 - am - md)
        mv = x.get("mult")
        rows_html += (
            '<tr%s><td class="nm">%s</td><td class="gp">%s</td>'
            '<td><div class="gp-bar"><i class="am" style="width:%.2f%%"></i>'
            '<i class="md" style="width:%.2f%%"></i><i class="tl" style="width:%.2f%%"></i></div></td>'
            '<td class="num">%s %.1f</td><td class="num b">%.1f%%</td><td class="num">%.1f</td>'
            '<td class="num">%s</td><td class="num">%+.2f%%</td></tr>'
            % (' class="hit"' if x.get("hit") else "", x.get("label", ""), x.get("group", ""),
               am, md, tl, (x.get("dom_seg") or "尾盘"), _g_pct(x.get("dom_yi", x.get("tail_yi"))),
               _g_pct(x.get("dom_pct", x.get("tail_pct"))),
               _g_pct(x.get("all_yi")), ("%.1fx" % mv) if mv else "—",
               _g_pct(x.get("tail_ret"))))

    sh = g.get("share") or {}
    series = sh.get("series") or []
    svg, xlab = _g_trend(series) if False else ("", "")
    # 大号净申购图（详情页专用，尺寸更大）
    if series:
        vals = [_g_pct(s.get("net_yi")) for s in series]
        mx = max([abs(v) for v in vals] + [1.0])
        W, H, pad = 660, 120, 8
        bw = (W - pad * 2) / len(vals)
        zero = H / 2 + 6
        seg = ['<svg viewBox="0 0 %d %d" role="img" aria-label="近20日份额净申购">' % (W, H)]
        seg.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e9e3f7"/>' % (pad, zero, W - pad, zero))
        for i, v in enumerate(vals):
            h = max(1.5, abs(v) / mx * (H / 2 - 10))
            x = pad + i * bw + bw * 0.2
            y = zero - h if v > 0 else zero
            seg.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5"/>'
                       % ("pos" if v > 0 else "neg", x, y, bw * 0.6, h))
        seg.append("</svg>")
        pick = sorted({0, len(vals) // 3, len(vals) * 2 // 3, len(vals) - 1})
        xlab = '<div class="g-x">%s</div>' % "".join(
            "<span>%s</span>" % series[k].get("date", "")[5:] for k in pick)
        svg = "".join(seg)
    else:
        svg, xlab = "", ""

    hist_all = []
    p = os.path.join("output", "guard_share_history.jsonl")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        hist_all.append(json.loads(line))
        except Exception:
            hist_all = []
    det = (hist_all[-1].get("detail") if hist_all else {}) or {}
    det_rows = ""
    name_map = {c: l for c, l in PANEL_FOR_PAGE}
    for c, v in sorted(det.items(), key=lambda kv: -abs(kv[1].get("amt_yi", 0)))[:12]:
        det_rows += ('<tr><td class="nm">%s</td><td class="num">%+.2f</td><td class="num b">%+.1f</td></tr>'
                     % (name_map.get(c, c), _g_pct(v.get("dsh_yi")), _g_pct(v.get("amt_yi"))))
    if not det_rows:
        det_rows = '<tr><td colspan="3" style="color:#9d97b3">暂未获取</td></tr>'

    last_d = hist_all[-1] if hist_all else {}
    # 判定流水：读 guard_verdict_history.jsonl（最多 20 行，倒序）；文件缺失时退化为当日 1 行
    VERDICT_KEEP = 20
    vp = os.path.join("output", "guard_verdict_history.jsonl")
    vrows = []
    if os.path.exists(vp):
        try:
            with open(vp, encoding="utf-8") as f:
                vrows = [json.loads(x) for x in f if x.strip()]
        except Exception:
            vrows = []
    if not vrows:
        vrows = [{"date": g.get("_data_date"), "text": g.get("verdict_text"),
                  "tail_yi": g.get("total_tail_yi"), "net_yi": _g_pct(sh.get("net_yi"))}]
    vrows = sorted([x for x in vrows if x.get("date")], key=lambda x: x["date"])[-VERDICT_KEEP:][::-1]
    verdict_rows = ""
    for x in vrows:
        verdict_rows += ('<tr><td class="nm">%s</td><td>%s</td><td class="num">%s</td>'
                         '<td class="num b">%+.1f</td></tr>'
                         % (x.get("date"), x.get("text") or "—", x.get("tail_yi") or 0,
                            _g_pct(x.get("net_yi"))))

    return (
        '<div class="card guard-card">\n'
        '  <div class="guard-head">🛡️ 今日结论 <span class="guard-tag">旁挂·不影响XXFI</span></div>\n'
        '  <div class="g-main">\n'
        '    <div class="g-left">\n'
        '      <div class="g-verdict %s"><span class="g-dot"></span>%s</div>\n'
        '      <div class="g-sub">%s</div>\n'
        '    </div>\n'
        '    <div class="g-right">\n'
        '      <div class="g-k">买入时段</div>\n'
        '      <div class="g-time">%s</div>\n'
        '      <div class="g-k2">最集中 %s · %s 亿</div>\n'
        '    </div>\n'
        '  </div>\n'
        '</div>\n'
        '<div class="card">\n'
        '  <div class="sec-h">11 只宽基 ETF · 尾盘三段分布</div>\n'
        '  <div style="overflow-x:auto"><table class="gp-tbl"><thead><tr><th>ETF</th><th>指数</th>'
        '<th>上午 → 午后 → 尾盘</th><th>最大时段</th><th>占比</th><th>全天(亿)</th>'
        '<th>放量</th><th>尾盘涨跌</th></tr></thead><tbody>%s</tbody></table></div>\n'
        '  <div class="note">深色 = 尾盘 14:45–15:00；行高亮 = 满足「占比 ≥50%% 且 ≥20 亿」。</div>\n'
        '</div>\n'
        '<div class="card">\n'
        '  <div class="sec-h">份额净申购 · 近 %d 个交易日</div>\n'
        '  <div class="g-share-r" style="flex:1 1 100%%;max-width:100%%">%s%s</div>\n'
        '  <div class="note">单位：亿元；正 = 净申购（紫），负 = 净赎回（灰）。</div>\n'
        '  <div style="font-size:11px;color:#9d97b3;margin:12px 0 4px">最近一日明细 · %s（%+.1f 亿）</div>\n'
        '  <div class="gp-two"><div style="overflow-x:auto"><table class="gp-tbl"><thead><tr><th>ETF</th>'
        '<th>Δ份额(亿份)</th><th>净申购(亿)</th></tr></thead><tbody>%s</tbody></table></div><div></div></div>\n'
        '</div>\n'
        '<div class="card">\n'
        '  <div class="sec-h">判定流水</div>\n'
        '  <div style="overflow-x:auto"><table class="gp-tbl"><thead><tr><th>日期</th><th>判定</th>'
        '<th>尾盘合计(亿)</th><th>份额净申购(亿)</th></tr></thead><tbody>%s</tbody></table></div>\n'
        '  <div class="note">最多保留最近 20 个交易日（倒序）；份额为 T-1 口径，故当日行的份额列为上一交易日数据。</div>\n'
        '</div>\n'
        '<div class="card">\n'
        '  <div class="sec-h">口径</div>\n'
        '  <div class="note">'
        '① 尾盘 = 14:45–15:00（5 分钟 bar 以结束时间标注，故取 14:50 / 14:55 / 15:00 三根）。<br>'
        '② 份额 = 上交所按日归档的全市场 ETF 份额，T+1 发布；沪市可回补，深市无历史接口、只能逐日快照。<br>'
        '③ 判定只回答「有没有疑似买入 / 哪只 / 几点」，不识别资金身份；成交量含双边，不能等同于净买入。'
        '</div>\n'
        '</div>'
        % (kind, (g.get("verdict_text") or "暂未获取"), (g.get("verdict_sub") or ""),
           (g.get("window") or "—"), (g.get("peak_window") or "—"), (g.get("peak_amt_yi") or 0),
           rows_html, len(series), svg, xlab,
           last_d.get("date", "—"), _g_pct(last_d.get("net_yi")), det_rows, verdict_rows)
    )


def render_guard_shell(guard_card_html, data_date, src):
    """把详情页卡片包成完整 HTML（复用 CSS）"""
    return (
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>国家队护盘追踪 · 明细</title><style>%s%s</style></head>\n'
        '<body><div class="wrap">\n'
        '<a class="gp-back" href="./index.html">← 返回首页</a>\n'
        '<h1>国家队护盘追踪 · 明细</h1>\n'
        '<div class="sub">数据日期 %s　|　数据源 %s</div>\n'
        '%s\n'
        '</div></body></html>\n'
        % ("__CSS__", "__MORECSS__", data_date, src, guard_card_html)
    )


PANEL_FOR_PAGE = [
    ("sh510050", "上证50ETF"), ("sh510300", "300ETF·华泰"), ("sz159919", "300ETF·嘉实"),
    ("sh510310", "300ETF·易方达"), ("sh510330", "300ETF·华夏"), ("sh510500", "中证500ETF"),
    ("sz159922", "500ETF·嘉实"), ("sz159949", "创业板50ETF"), ("sz159915", "创业板ETF"),
    ("sh588000", "科创50ETF"), ("sh588080", "科创50·易方达"),
]

def render(r, hist, bingdian=None, dibudian=None, ma850=None, guard=None):
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
    gen_at = r.get("_generated_at", "")
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
        ("涨停/跌停比", (f"{int(lu)}/{int(ld)}（比 {lu/ld:.2f}）" if ld else f"{int(lu)}/0（比 ∞）"), greed_c.get("limitup", 0)),
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
    ice_html = render_ice_card(bingdian)
    ma_html = render_ma850_card(ma850)
    guard_html = render_guard_card(guard)
    dip_html = render_dibudian_card(dibudian)

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
<title>小旭恐惧指数 XXFI · 实时</title><style>{CSS}{SIM_CSS}{GUARD_CSS}</style></head>
<body><div class="wrap">
<h1>小旭恐惧指数 · XXFI</h1>
<div class="sub">反向情绪指标（散户行为版）　|　数据日期：{data_date}　|　更新时间：{gen_at}　|　基准：{idx_name}　|　波动率窗口：{vw} 日</div>

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

{ice_html}
{guard_html}
{ma_html}
{dip_html}
{SIM_HTML}

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
</div><script>{SIM_JS}</script></body></html>"""
    return html

def main():
    ap = argparse.ArgumentParser(description="XXFI 结果渲染为静态 HTML")
    ap.add_argument("--json", required=True, help="xxfi_report.json 路径")
    ap.add_argument("--history", default="output/history.jsonl", help="history.jsonl 路径")
    ap.add_argument("--bingdian", default=None, help="冰点参考 bingdian_report.json 路径（可选·旁挂展示；缺省自动探测 output/）")
    ap.add_argument("--dibudian", default=None, help="底部区域判断 dibudian_report.json 路径（可选·旁挂展示；缺省自动探测 output/）")
    ap.add_argument("--ma850", default=None, help="850天线抄底坐标 ma850_report.json 路径（可选·旁挂展示；缺省自动探测 output/）")
    ap.add_argument("--guard", default=None, help="国家队护盘追踪 guard_report.json 路径（可选·旁挂展示；缺省自动探测 output/）")
    ap.add_argument("--guard-page", default=None, help="详情页输出路径（可选，如 docs/guard.html；不给则不生成）")
    ap.add_argument("--out", required=True, help="输出 HTML 路径，如 docs/index.html")
    args = ap.parse_args()

    # 2026-08-27 加固：--bingdian/--dibudian 未显式传参时自动探测 output/ 默认产物，
    # 防止漏参数导致冰点卡/底部区域卡静默丢失（曾致 8/27 cef5750 事故，两卡被删 46 行）。
    if not args.bingdian and os.path.exists("output/bingdian_report.json"):
        args.bingdian = "output/bingdian_report.json"
    if not args.dibudian and os.path.exists("output/dibudian_report.json"):
        args.dibudian = "output/dibudian_report.json"
    if not args.ma850 and os.path.exists("output/ma850_report.json"):
        args.ma850 = "output/ma850_report.json"

    r = load_json(args.json)
    hist = load_history(args.history)
    # 冰点参考卡：独立产物，存在才加载；缺失则页面不显示该卡（XXFI 不受影响）
    bingdian = None
    if args.bingdian and os.path.exists(args.bingdian):
        try:
            bingdian = load_json(args.bingdian)
        except Exception as e:
            print(f"[warn] 冰点报告读取失败，跳过冰点卡: {e}")
    # 底部区域判断卡：独立产物，存在才加载；缺失则页面不显示该卡（XXFI 不受影响）
    dibudian = None
    if args.dibudian and os.path.exists(args.dibudian):
        try:
            dibudian = load_json(args.dibudian)
        except Exception as e:
            print(f"[warn] 底部区域报告读取失败，跳过该卡: {e}")
    # 850天线抄底坐标卡：独立产物，存在才加载；缺失则页面不显示该卡（XXFI 不受影响）
    ma850 = None
    if args.ma850 and os.path.exists(args.ma850):
        try:
            ma850 = load_json(args.ma850)
        except Exception as e:
            print(f"[warn] 850天线报告读取失败，跳过该卡: {e}")
    # 国家队护盘追踪卡：独立产物，存在才加载；缺失则页面不显示该卡（XXFI 不受影响）
    guard = None
    if not args.guard and os.path.exists("output/guard_report.json"):
        args.guard = "output/guard_report.json"
    if args.guard and os.path.exists(args.guard):
        try:
            guard = load_json(args.guard)
        except Exception as e:
            print(f"[warn] 护盘报告读取失败，跳过该卡: {e}")
    html = render(r, hist, bingdian, dibudian, ma850, guard)
    # 详情页（可选）：11 只全表 + 份额曲线 + 判定流水
    if args.guard_page and guard:
        page = render_guard_page(guard)
        shell = render_guard_shell(page, guard.get("_data_date", ""), guard.get("_src", ""))
        shell = shell.replace("__CSS__", CSS + SIM_CSS).replace("__MORECSS__", GUARD_CSS)
        os.makedirs(os.path.dirname(os.path.abspath(args.guard_page)), exist_ok=True)
        with open(args.guard_page, "w", encoding="utf-8") as f:
            f.write(shell)
        print("详情页已生成: %s" % args.guard_page)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    # 2026-08-27 加固：生成后自检板块，任一缺失即打印 warn，防止残缺页被静默提交。
    # 2026-10-23：自检清单由「三大板块」改为「两大板块」——「秋哥操作·实盘模拟」已按用户决定
    #   撤出本页（迁至 qg 盘中检测页），再自检它会永远报缺失。
    missing = [k for k, kw in [
        ("冰点参考卡", 'class="card ice-card"'),
        ("护盘追踪卡", 'class="card guard-card"'),
        ("850天线抄底卡", 'class="card ma850-card"'),
        ("底部区域判断卡", 'class="card dip-card"'),
    ] if kw not in html]
    if missing:
        print(f"[warn] 生成页面缺少板块: {', '.join(missing)}（请检查 --bingdian/--ma850/--dibudian 参数与产物）")
    else:
        print("[ok] 四大板块齐全：冰点参考卡 / 护盘追踪卡 / 850天线抄底卡 / 底部区域判断卡")
    # 一并输出 xxfi_report.json 到 Pages 源目录（docs/），供外部读取原始数据或调试。
    json_out = os.path.join(out_dir, "xxfi_report.json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print(f"HTML 已生成: {args.out}（历史样本 {len(hist)} 条）")
    print(f"JSON 已发布: {json_out}（含完整 inputs 字段）")

if __name__ == "__main__":
    main()
