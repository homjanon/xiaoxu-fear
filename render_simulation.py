#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋哥操作 · 实盘模拟 → 网页区块渲染（xiaoxu-fear docs/index.html）

把「📊 秋哥操作 · 实盘模拟」区块注入到「底部区域判断」卡片下方：
  4 个 KPI（净值/收益/命中率/持仓数）→ 净值曲线 SVG → 当前持仓表 → 买卖复盘表
  → 免责声明

用法：python render_simulation.py [--index path] [--state path] [--stats path] [--hist path]
默认读 xiaoxu-fear 仓 output/ 下 simulation_*.json/jsonl，渲染进 docs/index.html。
"""
import argparse
import json
import os
import sys
import re

# ---------------- 默认路径（xiaoxu-fear 仓相对本脚本） ----------------
BASE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE, "docs", "index.html")
STATE_PATH = os.path.join(BASE, "output", "simulation_state.json")
STATS_PATH = os.path.join(BASE, "output", "accuracy_stats.json")
HIST_PATH = os.path.join(BASE, "output", "simulation_history.jsonl")


def load_state(state_path):
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_stats(stats_path):
    try:
        with open(stats_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_history(hist_path):
    out = []
    try:
        with open(hist_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except Exception:
        pass
    return out


def build_svg(history):
    """净值曲线 SVG（折线），宽度 680 高 200"""
    if not history:
        return "<div class='sim-empty'>暂无净值数据（每日盘后自动累积）</div>"
    navs = [h["nav"] for h in history]
    ds = [h["date"][5:] for h in history]
    w, h = 680, 200
    pad_l, pad_r, pad_t, pad_b = 44, 12, 24, 22
    vmin, vmax = min(navs), max(navs)
    if vmax == vmin:
        vmax = vmin + 1
    lo, hi = vmin - (vmax - vmin) * 0.08, vmax + (vmax - vmin) * 0.08
    def x(i): return pad_l + i * (w - pad_l - pad_r) / max(1, len(navs) - 1)
    def y(v): return pad_t + (1 - (v - lo) / (hi - lo)) * (h - pad_t - pad_b)
    # 网格线（4 档）
    grid = []
    for g in range(5):
        gy = pad_t + g * (h - pad_t - pad_b) / 4
        val = lo + (hi - lo) * (1 - g / 4)
        grid.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" stroke="#eef2f7"/>'
                    f'<text x="{pad_l - 6}" y="{gy + 3:.1f}" font-size="9" fill="#9aa3af" text-anchor="end">{val / 10000:.2f}万</text>')
    grid_html = "".join(grid)
    # 折线
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(navs))
    # 日期刻度（首/中/尾）
    labels = ""
    for idx in (0, len(ds) // 2, len(ds) - 1):
        labels += f'<text x="{x(idx):.1f}" y="{h - 6:.0f}" font-size="9" fill="#9aa3af" text-anchor="middle">{ds[idx]}</text>'
    color = "#16a34a" if navs[-1] >= navs[0] else "#dc2626"
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="模拟净值曲线">'
            f'{grid_html}'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            f'<circle cx="{x(len(navs) - 1):.1f}" cy="{y(navs[-1]):.1f}" r="3.5" fill="{color}"/>'
            f'{labels}</svg>')


def build_positions_table(state):
    positions = (state or {}).get("positions", {}) or {}
    if not positions:
        return "<tr><td colspan='6' style='text-align:center;color:#94a3b8'>当前无持仓</td></tr>"
    rows = []
    for code, p in positions.items():
        rows.append(
            f"<tr><td>{code}</td><td>{p.get('name','')}</td>"
            f"<td>{p.get('cost',0):.2f}</td><td>{p.get('shares',0)}</td>"
            f"<td>{p.get('buy_date','')}</td><td>{p.get('buy_price',0):.2f}</td></tr>"
        )
    return "".join(rows)


def build_trades_table(state):
    log = (state or {}).get("log", []) or []
    if not log:
        return "<tr><td colspan='6' style='text-align:center;color:#94a3b8'>暂无交易记录</td></tr>"
    rows = []
    for t in log[-15:][::-1]:
        rows.append(
            f"<tr><td>{t.get('date','')}</td><td>{t.get('type','')}</td>"
            f"<td>{t.get('name','')}</td><td>{t.get('price','')}</td>"
            f"<td>{t.get('shares','')}</td><td>{t.get('reason','')}</td></tr>"
        )
    return "".join(rows)


def build_block(state, stats, history):
    stats = stats or {}
    nav = stats.get("latest_nav", 1_000_000)
    ret = stats.get("total_return", 0)
    win = stats.get("win_rate", 0)
    open_n = stats.get("open", 0)
    ret_color = "#16a34a" if ret >= 0 else "#dc2626"
    return f"""
  <!-- ===== 秋哥操作 · 实盘模拟区块（render_simulation.py 自动生成） ===== -->
  <div class="card" id="qiuge-sim" style="margin-top:18px;">
    <div class="dip-head">📊 秋哥操作 · 实盘模拟 <span style="font-size:10px;color:#94a3b8;font-weight:600;margin-left:6px;">模拟账户 · 非真实资金 · 按回踩买点纪律自动判定</span></div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px;">
      <div class="dip-cell"><div class="k">模拟净值</div><div class="v" style="font-variant-numeric:tabular-nums;">{nav:,.0f}</div><div class="th">初始 ¥1,000,000</div></div>
      <div class="dip-cell"><div class="k">累计收益</div><div class="v" style="color:{ret_color};">{ret:+.2f}%</div><div class="th">vs 初始资金</div></div>
      <div class="dip-cell"><div class="k">推荐命中率</div><div class="v">{win}%</div><div class="th">已平仓盈利交易占比</div></div>
      <div class="dip-cell"><div class="k">当前持仓</div><div class="v">{open_n} 只</div><div class="th">上限 5 只</div></div>
    </div>
    <div class="dip-trend">{build_svg(history)}<div class="dip-trend-note">模拟账户净值曲线（每日盘后累积）</div></div>
    <div style="font-size:13px;font-weight:700;margin:14px 0 8px;">📌 当前持仓</div>
    <table class="score-tbl"><thead><tr><th>代码</th><th>名称</th><th>成本</th><th>数量</th><th>买入日</th><th>买入价</th></tr></thead>
    <tbody>{build_positions_table(state)}</tbody></table>
    <div style="font-size:13px;font-weight:700;margin:14px 0 8px;">🔄 最近交易（买卖点复盘）</div>
    <table class="score-tbl"><thead><tr><th>日期</th><th>类型</th><th>标的</th><th>价格</th><th>数量</th><th>原因</th></tr></thead>
    <tbody>{build_trades_table(state)}</tbody></table>
    <div style="font-size:10.5px;color:#94a3b8;margin-top:12px;line-height:1.6;">⚠️ 本区块为策略方法验证的模拟账户：按秋哥纪律（回踩 MA5/MA10 买点 + 主力确认 / 破 MA20 减仓 / 破 MA60 离场 / 止盈 10–20%）自动判定，仅供回测验证，<b>不构成任何投资建议</b>。数据源：东财/腾讯公开行情。</div>
  </div>
  <!-- ===== 秋哥操作 · 实盘模拟区块结束 ===== -->
"""


def inject(index_path, block):
    with open(index_path, encoding="utf-8") as f:
        html = f.read()
    # 定位「底部区域判断」卡片结束位置：找 "dip-note" 的闭合 div（底部区域卡的最后一句说明）
    # 「底部区域判断」卡以 <div class="dip-note">…</div> 结尾，后面跟 </div>（卡片闭合）
    marker = re.search(r'(<div class="dip-note">.*?</div>\s*</div>)', html, re.S)
    if not marker:
        print("❌ 未找到「底部区域判断」卡结束位置（dip-note），无法注入")
        sys.exit(1)
    insert_pos = marker.end()
    new_html = html[:insert_pos] + "\n" + block + html[insert_pos:]
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"✅ 已注入模拟区块到 {index_path}（底部区域判断卡下方）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=INDEX_PATH)
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--stats", default=STATS_PATH)
    ap.add_argument("--hist", default=HIST_PATH)
    args = ap.parse_args()
    state = load_state(args.state)
    stats = load_stats(args.stats)
    history = load_history(args.hist)
    if not state and not stats:
        print("⚠️ 无模拟数据（state/stats 均缺失）——仍渲染空区块占位")
    block = build_block(state, stats, history)
    inject(args.index, block)


if __name__ == "__main__":
    main()