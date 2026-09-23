#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋哥操作 · 实盘模拟 → 网页区块（动态拉取版）

参考 cmb-tracker/scripts/xq_table_block.py 的「雪球大V 追踪」模式：
render_html.py 每次生成 docs/index.html 时固定内联本模块的
  SIM_CSS（样式） + SIM_HTML（容器占位） + SIM_JS（运行时渲染脚本），
页面加载时 JS 从本仓 output/simulation_state.json / accuracy_stats.json /
simulation_history.jsonl 动态拉取并渲染「秋哥操作 · 实盘模拟」区块。

== 为什么这样不会消失（2026-08-26 根治） ==
- xiaoxu-fear 的 CI（xxfi-daily.yml）每天 16:35 用 render_html.py 覆盖 docs/index.html，
  但 render_html.py 每次都重新生成 SIM_HTML 容器 + SIM_JS —— 覆盖 = 重新生成同一容器，
  板块永不丢失（此前手动 render_simulation.py 注入的内容会被 CI 覆盖抹掉）。
- 数据来自 output/simulation_*.json（本地秋哥操作后推送，像 qiuge_report.json 一样），
  页面每次打开实时拉最新 —— 不依赖 CI 时序，本地推完立即生效。

双通道拉取（照抄 xq_table_block）：用户自建 CORS 代理优先（无缓存、实时）→ GitHub Contents API 兜底（base64）。
"""
import json
import os

# ---------------------------------------------------------------- CSS（补充样式，基础样式复用 render_html.py 的 dip-* / score-tbl）
SIM_CSS = """
/* —— 秋哥操作 · 实盘模拟 区块（sim_block.py 动态渲染） —— */
#qiuge-sim .sim-empty{color:#94a3b8;font-size:12.5px;padding:14px 0;text-align:center;}
#qiuge-sim .sim-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;}
#qiuge-sim .sim-kpis .dip-cell{margin:0;}
#qiuge-sim .sim-tbl-wrap{overflow-x:auto;}
#qiuge-sim .sim-note{font-size:10.5px;color:#94a3b8;margin-top:12px;line-height:1.6;}
#qiuge-sim .sim-tag{font-size:9px;color:#94a3b8;margin-left:3px;border:1px solid #e2e8f0;border-radius:3px;padding:0 3px;}
#qiuge-sim .sim-num{font-variant-numeric:tabular-nums;}
@media(max-width:640px){#qiuge-sim .sim-kpis{grid-template-columns:repeat(2,1fr);}}
/* —— 移动端（≤640px）：持仓/交易表转卡片；主页面 .score-tbl 是 table-layout:fixed+width:100%，
      9 列在窄屏会被压成每列约 40px（中文竖排），这里改为卡片式重排 —— */
@media(max-width:640px){
  #qiuge-sim .sim-tbl-wrap{overflow:visible;}
  #qiuge-sim table.sim-tbl-pos,#qiuge-sim table.sim-tbl-trade{table-layout:auto;display:block;margin-bottom:10px;}
  #qiuge-sim .sim-tbl-pos thead,#qiuge-sim .sim-tbl-trade thead{display:none;}
  #qiuge-sim .sim-tbl-pos tbody,#qiuge-sim .sim-tbl-trade tbody{display:block;}
  /* 持仓卡片：首行 代码 | 名称(+底仓) | 收益率；其后 6 字段 3 列 × 2 行 */
  #qiuge-sim .sim-tbl-pos tr{display:grid;grid-template-columns:3.3fr 4.6fr 3.3fr;gap:8px 10px;border:1px solid var(--line);border-radius:11px;padding:12px 13px 13px;margin-bottom:10px;background:#fff;}
  #qiuge-sim .sim-tbl-pos td{display:flex;flex-direction:column;gap:2px;border:none;padding:0;min-width:0;font-size:13px;}
  #qiuge-sim .sim-tbl-pos td::before{font-size:11px;color:#94a3b8;font-weight:500;line-height:1.3;}
  #qiuge-sim .sim-tbl-pos td:nth-child(1){grid-row:1;grid-column:1;font-size:12px;color:#8a9099;justify-content:center;white-space:nowrap;}
  #qiuge-sim .sim-tbl-pos td:nth-child(1)::before{display:none;}
  #qiuge-sim .sim-tbl-pos td:nth-child(2){grid-row:1;grid-column:2;flex-direction:row;align-items:center;flex-wrap:wrap;gap:5px;font-weight:700;font-size:14px;color:var(--ink);}
  #qiuge-sim .sim-tbl-pos td:nth-child(2)::before{display:none;}
  #qiuge-sim .sim-tbl-pos td:nth-child(9){grid-row:1;grid-column:3;align-items:flex-end;font-weight:700;font-size:15px;justify-content:center;}
  #qiuge-sim .sim-tbl-pos td:nth-child(9)::before{content:"浮动盈亏";font-weight:500;}
  /* 实际收益率：独立一行（底仓显示 —） */
  #qiuge-sim .sim-tbl-pos td:nth-child(10){grid-row:4;grid-column:1/-1;flex-direction:row;justify-content:space-between;align-items:center;border-top:1px dashed #eef0f3;padding-top:6px;margin-top:3px;color:#64748b;font-size:12.5px;}
  #qiuge-sim .sim-tbl-pos td:nth-child(10)::before{content:"实际收益率（含已实现）";}
  #qiuge-sim .sim-tbl-pos td:nth-child(3){grid-row:2;grid-column:1;}
  #qiuge-sim .sim-tbl-pos td:nth-child(3)::before{content:"成本价*";}
  #qiuge-sim .sim-tbl-pos td:nth-child(4){grid-row:2;grid-column:2;}
  #qiuge-sim .sim-tbl-pos td:nth-child(4)::before{content:"数量";}
  #qiuge-sim .sim-tbl-pos td:nth-child(5){grid-row:2;grid-column:3;}
  #qiuge-sim .sim-tbl-pos td:nth-child(5)::before{content:"最新收盘";}
  #qiuge-sim .sim-tbl-pos td:nth-child(6){grid-row:3;grid-column:1;}
  #qiuge-sim .sim-tbl-pos td:nth-child(6)::before{content:"当日涨跌";}
  #qiuge-sim .sim-tbl-pos td:nth-child(7){grid-row:3;grid-column:2;}
  #qiuge-sim .sim-tbl-pos td:nth-child(7)::before{content:"当日盈亏";}
  #qiuge-sim .sim-tbl-pos td:nth-child(8){grid-row:3;grid-column:3;}
  #qiuge-sim .sim-tbl-pos td:nth-child(8)::before{content:"总盈亏";}
  /* 交易卡片：日期 类型 标的 价格 数量 一行 + 原因独立一行 */
  #qiuge-sim .sim-tbl-trade tr{display:grid;grid-template-columns:5.4fr 3fr 5.6fr 3.4fr 3.4fr;gap:5px 6px;border:1px solid var(--line);border-radius:11px;padding:10px 12px;margin-bottom:8px;background:#fff;}
  #qiuge-sim .sim-tbl-trade td{display:block;border:none;padding:0;min-width:0;font-size:12.5px;overflow-wrap:anywhere;}
  #qiuge-sim .sim-tbl-trade td:nth-child(1){grid-row:1;grid-column:1;color:#6b7280;font-size:11.5px;white-space:nowrap;}
  #qiuge-sim .sim-tbl-trade td:nth-child(2){grid-row:1;grid-column:2;font-weight:600;font-size:11.5px;}
  #qiuge-sim .sim-tbl-trade td:nth-child(3){grid-row:1;grid-column:3;font-weight:600;}
  #qiuge-sim .sim-tbl-trade td:nth-child(4){grid-row:1;grid-column:4;text-align:right;}
  #qiuge-sim .sim-tbl-trade td:nth-child(5){grid-row:1;grid-column:5;text-align:right;color:#6b7280;font-size:11.5px;}
  #qiuge-sim .sim-tbl-trade td:nth-child(6){grid-row:2;grid-column:1/-1;font-size:11.5px;color:#64748b;line-height:1.5;border-top:1px dashed #eef0f3;padding-top:6px;margin-top:3px;}
  /* 底仓标签：窄屏改浅底胶囊，避免显示成空心小方框 */
  #qiuge-sim .sim-tag{background:#f1f5f9;border:none;border-radius:4px;padding:1px 5px;font-size:10px;color:#94a3b8;margin-left:5px;}
}
"""

# ---------------------------------------------------------------- HTML 容器（render_html.py 固定内联）
SIM_HTML = """
<!-- ===== 秋哥操作 · 实盘模拟区块（sim_block.py 动态拉取，2026-08-26 起） ===== -->
<div class="card" id="qiuge-sim" style="margin-top:18px;">
  <div class="dip-head">📊 秋哥操作 · 实盘模拟 <span style="font-size:10px;color:#94a3b8;font-weight:600;margin-left:6px;">模拟账户 · 非真实资金 · 按既定纪律自动判定 · 数据来自本仓 output/</span></div>
  <div id="qiuge-sim-body"><div class="sim-empty">模拟数据加载中…</div></div>
  <div class="sim-note">⚠️ 本区块为模拟账户记录，按既定纪律自动判定，仅供记录与验证，<b>不构成任何投资建议</b>。数据为本地采集，每日盘后同步至 output/。</div>
</div>
<!-- ===== 秋哥操作 · 实盘模拟区块结束 ===== -->
"""

# ---------------------------------------------------------------- 渲染脚本（运行时拉取 output/simulation_*.json）
SIM_JS = r"""
(function(){
  var PROXY_URL="https://proxy.hellohopo.dpdns.org/?url=";
  var STATE_RAW="https://raw.githubusercontent.com/homjanon/xiaoxu-fear/main/output/simulation_state.json";
  var STATS_RAW="https://raw.githubusercontent.com/homjanon/xiaoxu-fear/main/output/accuracy_stats.json";
  var HIST_RAW="https://raw.githubusercontent.com/homjanon/xiaoxu-fear/main/output/simulation_history.jsonl";
  var STATE_API="https://api.github.com/repos/homjanon/xiaoxu-fear/contents/output/simulation_state.json";
  var STATS_API="https://api.github.com/repos/homjanon/xiaoxu-fear/contents/output/accuracy_stats.json";
  var HIST_API="https://api.github.com/repos/homjanon/xiaoxu-fear/contents/output/simulation_history.jsonl";

  function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
  function fmtN(n){return (n==null||isNaN(n))?"—":Number(n).toLocaleString("zh-CN",{maximumFractionDigits:0});}
  function fmtP(n){return (n==null||isNaN(n))?"—":(Number(n)>=0?"+":"")+Number(n).toFixed(2)+"%";}
  function red(n){return n>=0?"#dc2626":"#16a34a";}  // 红涨绿跌
  function b64ToObj(b64){
    var bin=atob(String(b64).replace(/\s/g,''));var bytes=new Uint8Array(bin.length);
    for(var i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
    return JSON.parse(new TextDecoder('utf-8').decode(bytes));
  }
  function fetchSmart(rawUrl,apiUrl){
    var proxyUrl=PROXY_URL+encodeURIComponent(rawUrl);
    var order=['proxy','raw','api'];
    var urls={proxy:proxyUrl,raw:rawUrl,api:apiUrl};
    function tryFetch(url,isApi){
      return fetch(url,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);
        if(isApi) return r.json().then(function(d){
          if(!d||!d.content)throw new Error('no content');
          var bin=atob(String(d.content).replace(/\s/g,''));
          var bytes=new Uint8Array(bin.length);
          for(var i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
          return JSON.parse(new TextDecoder('utf-8').decode(bytes));
        });
        return r.json();
      });
    }
    function trySeq(i){
      if(i>=order.length)throw new Error('all sources failed');
      return tryFetch(urls[order[i]],order[i]==='api').catch(function(){return trySeq(i+1);});
    }
    return trySeq(0);
  }
  function loadJson(rawUrl,apiUrl){return fetchSmart(rawUrl,apiUrl);}
  function loadHist(rawUrl,apiUrl){
    // JSONL 不是合法 JSON，不能用 r.json()，必须用 r.text() 获取原始文本
    function fetchTextSmart(rawUrl,apiUrl){
      var proxyUrl=PROXY_URL+encodeURIComponent(rawUrl);
      var order=['proxy','raw','api'];
      var urls={proxy:proxyUrl,raw:rawUrl,api:apiUrl};
      function fetchText(url,isApi){
        return fetch(url,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);
          if(isApi) return r.json().then(function(d){
            if(!d||!d.content)throw new Error('no content');
            var bin=atob(String(d.content).replace(/\s/g,''));
            var bytes=new Uint8Array(bin.length);
            for(var i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
            return new TextDecoder('utf-8').decode(bytes);
          });
          return r.text();
        });
      }
      function trySeq(i){
        if(i>=order.length)throw new Error('all sources failed');
        return fetchText(urls[order[i]],order[i]==='api').catch(function(){return trySeq(i+1);});
      }
      return trySeq(0);
    }
    function parseJsonl(txt){
      if(typeof txt!=='string')return Array.isArray(txt)?txt:[];
      var out={};var lines=txt.split('\n').filter(function(l){return l.trim();});
      for(var i=0;i<lines.length;i++){try{var rec=JSON.parse(lines[i]);out[rec.date]=rec;}catch(e){}}
      return Object.keys(out).sort().map(function(k){return out[k];});
    }
    return fetchTextSmart(rawUrl,apiUrl).then(parseJsonl);
  }

  function buildSvg(history){
    if(!history||!history.length)return '<div class="sim-empty">暂无净值数据（每日盘后自动累积）</div>';
    var hs=history.slice(-180);var navs=hs.map(function(h){return h.nav;});
    var ds=hs.map(function(h){return String(h.date).slice(5);});
    var w=680,h=200,pl=44,pr=12,pt=24,pb=22;
    var vmin=Math.min.apply(null,navs),vmax=Math.max.apply(null,navs);
    if(vmax===vmin)vmax=vmin+1;
    var lo=vmin-(vmax-vmin)*0.08,hi=vmax+(vmax-vmin)*0.08;
    function x(i){return pl+i*(w-pl-pr)/Math.max(1,navs.length-1);}
    function y(v){return pt+(1-(v-lo)/(hi-lo))*(h-pt-pb);}
    var grid="";
    for(var g=0;g<5;g++){var gy=pt+g*(h-pt-pb)/4,val=lo+(hi-lo)*(1-g/4);
      grid+='<line x1="'+pl+'" y1="'+gy.toFixed(1)+'" x2="'+(w-pr)+'" y2="'+gy.toFixed(1)+'" stroke="#eef2f7"/>'
        +'<text x="'+(pl-6)+'" y="'+(gy+3).toFixed(1)+'" font-size="9" fill="#9aa3af" text-anchor="end">'+(val/10000).toFixed(2)+'万</text>';}
    var pts=navs.map(function(v,i){return x(i).toFixed(1)+","+y(v).toFixed(1);}).join(" ");
    var labels="";
    [0,Math.floor(ds.length/2),ds.length-1].forEach(function(idx){
      labels+='<text x="'+x(idx).toFixed(1)+'" y="'+(h-6)+'" font-size="9" fill="#9aa3af" text-anchor="middle">'+ds[idx]+'</text>';});
    var color=navs[navs.length-1]>=navs[0]?"#dc2626":"#16a34a";
    return '<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="模拟净值曲线">'+grid
      +'<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linejoin="round"/>'
      +'<circle cx="'+x(navs.length-1).toFixed(1)+'" cy="'+y(navs[navs.length-1]).toFixed(1)+'" r="3.5" fill="'+color+'"/>'
      +labels+'</svg>';
  }

  function buildPositions(state){
    var positions=(state&&state.positions)||{};
    var keys=Object.keys(positions);
    if(!keys.length)return '<tr><td colspan="10" style="text-align:center;color:#94a3b8">当前无持仓</td></tr>';
    return keys.map(function(code){
      var p=positions[code]||{};
      var name=esc(p.name||code);
      var tag=(code==="600036")?'<span class="sim-tag">底仓</span>':"";
      // D1'（2026-09-23 用户确认 · 券商口径）：**所有标的**成本列统一用 `cost_diluted`
      //   （摊薄成本 = 券商 App「成本价」），「浮动盈亏」按此计算 → 与真实股票账户观感一致。
      //   ⚠️ 摊薄成本会把历次卖出的已实现盈利摊回剩余持仓 → 分批止盈过的标的浮盈%会**虚高**
      //     （券商就是这样显示的，非 bug）→ 故另设「实际收益率」列（cum_ret，含已实现，真金白银口径）。
      //   ⚠️ 底仓（招行·只买不卖）不显示「实际收益率」→ 显示 —（用户 2026-09-23 指定）。
      //   ⚠️ **卖出判定口径完全不受影响**：仍按买入均价（cost_raw）的 10/20/40 档（在 simulate_qiuge 内）。
      var cost=(p.cost_diluted!=null?p.cost_diluted:p.cost)||0,px=p.last_close||p.cost||0;
      var chg=p.chg_pct||0,day=p.day_pnl||0;
      var tot=p.total_pnl!==undefined?p.total_pnl:((px-cost)*p.shares||0);
      // 浮动盈亏%（= 券商 App「持仓盈亏%」）：与成本列同口径
      var gain=(cost&&px)?(px/cost-1)*100:null;
      // 实际收益率（累计收益率·含已实现）；底仓不列（只买不卖）
      var actual=(code==="600036")?null:((p.cum_ret!==undefined&&p.cum_ret!==null)?p.cum_ret:null);
      return '<tr><td>'+code+'</td><td>'+name+tag+'</td>'
        +'<td class="sim-num">'+cost.toFixed(2)+'</td><td class="sim-num">'+p.shares+'</td>'
        +'<td class="sim-num">'+px.toFixed(2)+'</td>'
        +'<td class="sim-num" style="color:'+red(chg)+'">'+fmtP(chg)+'</td>'
        +'<td class="sim-num" style="color:'+red(day)+'">'+(day>=0?"+":"")+day.toLocaleString("zh-CN",{maximumFractionDigits:0})+'</td>'
        +'<td class="sim-num" style="color:'+red(tot)+'">'+(tot>=0?"+":"")+tot.toLocaleString("zh-CN",{maximumFractionDigits:0})+'</td>'
        +'<td class="sim-num"'+(gain==null?'':' style="color:'+red(gain)+'"')+'>'+fmtP(gain)+'</td>'
        +'<td class="sim-num"'+(actual==null?' style="color:#94a3b8"':' style="color:'+red(actual)+'"')+'>'
          +(actual==null?'—':fmtP(actual))+'</td></tr>';
    }).join("");
  }

  function buildTrades(state){
    var log=(state&&state.log)||[];
    if(!log.length)return '<tr><td colspan="6" style="text-align:center;color:#94a3b8">暂无交易记录</td></tr>';
    return log.slice(-10).reverse().map(function(t){
      return '<tr><td>'+esc(t.date||"")+'</td><td>'+esc(t.type||"")+'</td>'
        +'<td>'+esc(t.name||"")+'</td><td class="sim-num">'+esc(t.price||"")+'</td>'
        +'<td class="sim-num">'+esc(t.shares!=null?t.shares:"")+'</td><td style="font-size:11.5px;color:#64748b">'+esc(t.reason||"")+'</td></tr>';
    }).join("");
  }

  function excessCell(title,ex,baseRet){
    if(ex===null||ex===undefined)return '<div class="dip-cell"><div class="k">'+title+'</div><div class="v">—</div><div class="th">基准数据缺失</div></div>';
    return '<div class="dip-cell"><div class="k">'+title+'</div><div class="v" style="color:'+red(ex)+'">'+fmtP(ex)+' pp</div>'
      +'<div class="th">基准同期 '+(baseRet!=null?fmtP(baseRet):"—")+'</div></div>';
  }

  function render(state,stats,history){
    var root=document.getElementById("qiuge-sim-body");
    if(!root)return;
    if(!state&&!stats){
      root.innerHTML='<div class="sim-empty">暂无模拟数据（output/simulation_*.json 未推送）</div>';return;
    }
    stats=stats||{};
    var nav=stats.latest_nav!==undefined?stats.latest_nav:1000000;
    var ret=stats.total_return||0;
    var pnl=stats.total_pnl!==undefined?stats.total_pnl:(ret/100*1103600);
    var win=stats.win_rate||0;
    var openN=stats.open!==undefined?stats.open:(state&&state.positions?Object.keys(state.positions).length:0);
    var winDisp=(stats.total_trades||0)>=5?fmtP(win):"待样本";
    var kpis=
      '<div class="dip-cell"><div class="k">模拟净值</div><div class="v sim-num">'+fmtN(nav)+'</div><div class="th">起点 ¥1,103,600（8/3）</div></div>'
      +'<div class="dip-cell"><div class="k">总盈亏</div><div class="v sim-num" style="color:'+red(pnl)+'">'+(pnl>=0?"+":"")+fmtN(pnl)+'</div><div class="th">含交易成本</div></div>'
      +'<div class="dip-cell"><div class="k">累计收益</div><div class="v sim-num" style="color:'+red(ret)+'">'+fmtP(ret)+'</div><div class="th">vs 起点（8/3）</div></div>'
      +excessCell("vs 沪深300",stats.excess_hs300,stats.hs300_return)
      +excessCell("vs 红利低波",stats.excess_divlow,stats.divlow_return)
      +'<div class="dip-cell"><div class="k">当前持仓 '+openN+' 只</div><div class="v">'+winDisp+'</div><div class="th">命中率（≥5笔才统计）· 上限5只</div></div>';
    var html='<div class="sim-kpis">'+kpis+'</div>'
      +'<div class="dip-trend">'+buildSvg(history)+'<div class="dip-trend-note">模拟账户净值曲线（自 8/3 起逐日累积，最近 180 交易日）</div></div>'
      +'<div style="font-size:13px;font-weight:700;margin:14px 0 8px;">📌 当前持仓</div>'
      +'<div class="sim-tbl-wrap"><table class="score-tbl sim-tbl-pos"><thead><tr><th>代码</th><th>名称</th><th>成本价*</th><th>数量</th><th>最新收盘</th><th>当日涨跌</th><th>当日盈亏</th><th>总盈亏</th><th>浮动盈亏*</th><th>实际收益率</th></tr></thead>'
      +'<tbody>'+buildPositions(state)+'</tbody></table></div>'
      +'<div class="sim-note" style="margin-top:6px;">* 「成本价」统一为<b>摊薄成本</b>口径（= 券商 App「成本价」，已把历次卖出的实现盈亏摊回剩余持仓），「浮动盈亏」按此计算 —— 与真实股票账户观感一致。因摊薄会把已实现盈利摊回，<b>分批止盈过的标的浮盈%会偏高</b>（券商口径固有特性，非计算错误）。「实际收益率」为<b>累计收益率</b>（含已实现，按下单投入计），更贴近真实战绩；底仓（招商银行）属只买不卖的长线底仓，不列此项（显示 —）。<b>上述均为展示口径；卖出判定仍按买入均价计算的 10/20/40 档，不受影响。</b></div>'
      +'<div style="font-size:13px;font-weight:700;margin:14px 0 8px;">🔄 最近交易（买卖点复盘）</div>'
      +'<div class="sim-tbl-wrap"><table class="score-tbl sim-tbl-trade"><thead><tr><th>日期</th><th>类型</th><th>标的</th><th>价格</th><th>数量</th><th>原因</th></tr></thead>'
      +'<tbody>'+buildTrades(state)+'</tbody></table></div>';
    root.innerHTML=html;
  }

  Promise.all([loadJson(STATE_RAW,STATE_API),loadJson(STATS_RAW,STATS_API),loadHist(HIST_RAW,HIST_API)])
    .then(function(r){render(r[0],r[1],r[2]);})
    .catch(function(){
      var root=document.getElementById("qiuge-sim-body");
      if(root)root.innerHTML='<div class="sim-empty">（模拟数据暂不可得，请稍后刷新）</div>';
    });
})();
"""
