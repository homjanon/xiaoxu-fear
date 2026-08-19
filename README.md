# 小旭恐惧指数 · XiaoXu Fear Index (XXFI)

把当前 A 股市场数据映射为一个 **0–100 的反向情绪指标**（类似 VIX/VXN 的散户行为版），用于判断市场情绪极端点并给出反向操作参考。灵感来自朋友"小旭" 2024–2026 的真实炒股实录：反复"卖飞""买在山顶""恐慌割肉在底部"。

> **核心思想**：散户（尤其小旭式）的"恐惧"常出现在阶段底部、"贪婪"常出现在阶段顶部。把市场当下的恐惧/贪婪量化 → 反向参考：越恐惧越该买、越贪婪越该卖。

### 三个指标（一主两挂）

| 指标 | 角色 | 判定 | 产物 |
|---|---|---|---|
| **XXFI 小旭恐惧指数** | **主指标**，决定信号 | 0–100 反向情绪分 → BUY / ACCUMULATE / HOLD / REDUCE / SELL | `xxfi_report.json` |
| **❄ 冰点参考** | 旁挂，不影响 XXFI | 4 维度（下跌广度 / 指数·ETF跌幅 / 跌停数量 / 放量恐慌）**全部满足**才判冰点（一年 ≤3 次） | `bingdian_report.json` |
| **🌱 底部区域判断** | 旁挂，不影响 XXFI | 地量：当日全市场成交额 **≤ 近90日峰值 × 50%** | `dibudian_report.json` + `dibudian_state.json` |

两个旁挂指标**只做展示与参考**，绝不修改 XXFI 的任何原始计算与输出；任一旁挂取数失败只标「暂未获取」，不拖累主指标。

## 实时结果（GitHub Actions 自动更新）

每个交易日 **15:50（UTC+8）** cron 触发（cron `"50 7 * * 1-5"`），产物提交到 `output/`。GitHub Actions 排队延迟已缩短（2026-08 实测），实跑约 **16:00 北京**，恰在盘后数据定稿之后：

- 📄 [`output/xxfi_report.md`](output/xxfi_report.md) — 当日人类可读报告
- 🧾 [`output/xxfi_report.json`](output/xxfi_report.json) — 当日结构化结果（含 `_breadth_source` / `_retail_net_source` 溯源字段、`_generated_at` 更新时间（北京时间，精确到秒）、`_data_date` 数据日期）
- 📈 [`output/history.jsonl`](output/history.jsonl) — 每日一行历史：`{date, xxfi, greed, signal, level}`（由每日 cron 自动累积）
- ❄ [`output/bingdian_report.json`](output/bingdian_report.json) — 冰点参考结构化结果（4 维度明细 + 判定标准 + 溯源标记），旁挂展示、不影响 XXFI
- 🌱 [`output/dibudian_report.json`](output/dibudian_report.json) — 底部区域判断（地量）结构化结果（当日/近90日峰值成交额 + 比率 + 近30日回看 `hist30`），旁挂展示、不影响 XXFI
- 🗓 [`output/dibudian_state.json`](output/dibudian_state.json) — 底部区域**跨日持久状态**：`{last_bottom_date, last_bottom_volume}`，让"最近一次底部区域日"一直显示到被新的满足日取代
- 💾 [`output/_turnover_cache.json`](output/_turnover_cache.json) — 全市场成交额滚动缓存 `{date: 元}`，底部区域的近90日峰值来源（由 CI 每交易日追加、自动提交持久化）

### 🌐 网页版（GitHub Pages 自动发布）

每次运行后自动生成自包含静态页 **[https://homjanon.github.io/xiaoxu-fear/](https://homjanon.github.io/xiaoxu-fear/)**，内容含：

- **最新结果卡**：大号 XXFI（主表·决定信号）+ 贪婪指数（副表·辅助诊断）+ 信号徽章 + 一句话建议
- **分项得分**：恐惧 4 项 / 贪婪 5 项进度条（恐惧/贪婪两表列宽对齐、手机端自适应不溢出）
- **对照参考表**：XXFI 绝对区间 → 等级 / 信号 / 含义，并标注「两表独立、非互补」
- **历史趋势**：内联 SVG 折线（XXFI vs 贪婪）+ 近 10 日数据表（运行数日后自动出现）
- **冰点参考卡**（旁挂右侧）：独立"A股冰点"参考指标（不影响 XXFI 任何原始计算/展示）。含冰点结论 + 4 格冰冷计（满足维度点亮）+ 4 维度明细（下跌广度 / 指数·ETF跌幅 / 跌停数量 / 放量恐慌），**每个维度下方用小字标注判定标准**（如 `D1 下跌广度` 下注明 `（下跌≥4000 且 占比≥85%）`），溯源标记（legu / sina_spot / eastmoney_spot）一并呈现
- **底部区域判断卡**（旁挂，🌱 地量区域）：独立参考指标（同样不影响 XXFI）。含判定状态（底部区域日 / 非底部区域日）+ **最近一次底部区域日**（跨日持久显示）+ 3 格明细（当日全市场成交额 / 近90日最高 / 当前比率与阈值）+ 比率进度条（50% 处标红线阈值）+ **近30日成交额趋势柱图**
- **近30日趋势柱图**（底部区域卡内，内联 SVG）：柱体 ≤ 阈值染绿、其余灰，最右一根为当日（加描边）；灰色虚线=近90日峰值、红色虚线=底部阈值（峰值×50%，标注具体万亿值），**参考线与文字绘制在柱体之上并带白色描边 halo**，任何底色下都清晰；x 轴标注首/中/尾三日，并额外用绿色加粗 + ▲ 标出**窗口内成交额最低日**（若最低日恰为首/中/尾则不重复标注）；日期统一 `MM-DD` 不含年份，跨年窗口直接显示 `12-31` / `01-05`
- **页头时间标识**：顶部一行同时标注「数据日期」（数据所属交易日，周末/非交易日运行时≠当天）与「更新时间」（数据生成的**北京时间，精确到秒**，如 `2026-07-20 16:35:12`），与 douban-tracker 看板口径一致，便于核对数据时效

由 `render_html.py` 读取 `xxfi_report.json` + `history.jsonl` + `bingdian_report.json` + `dibudian_report.json` 渲染，并经 Actions 提交到 `docs/index.html`；GitHub Pages 源已设为 `main/docs` 自动发布，永远是最新结果。

## 自动运行触发方案

针对"开盘瞬间资金流向缺失、非交易日空跑"的问题，重新设计了触发逻辑。依据 A 股数据更新节奏（北京时间）：

```
09:30 开盘 → 15:00 收盘 → 15:00~16:00 涨跌家数 / 涨停跌停池 / 主力资金流向 陆续定稿（注：上证指数日K接口滞后约1天，当日指数值改由新浪实时 spot 补充）
                              ↑ 15:50 cron（CI 实跑约 16:00 前后，数据已就绪）
```

三条约束的落地：

| 约束 | 方案 | 实现 |
|---|---|---|
| **① 交易日筛选** | 仅在交易日执行，非交易日（含节假日/休市）完全不触发 | cron 仅覆盖周一至五；`check` 步骤用 `tool_trade_date_hist_sina()` **精确排除法定节假日/休市日（含调休）**，不靠"周一到五"硬猜 |
| **② 执行时机** | 避开开盘数据空窗，待资金流向定稿后执行 | cron `"50 7 * * 1-5"` = **北京 15:50**（GitHub Actions 延迟已缩短，实跑约 16:00 前后）；`check` 步骤改判「交易日历 + 北京时间≥15:00 收盘后」，不再依赖滞后的指数日K末根（当日指数值由实时 spot 补充，见 `fetch_market_akshare.fetch_index_spot`） |
| **③ 每日频次** | 单日单次，不产生无效执行 | 盘后单次运行；非交易日 / 数据未就绪由 `check` 步骤 `skip`，后续步骤 `if: steps.check.outputs.trade == '1'` 全部跳过 |

- **三个指标同进同退**：XXFI 主表、冰点参考、底部区域判断没有各自独立的触发器，都是 `xxfi-daily.yml` 里的并列 step，`if` 条件逐字相同（`steps.check.outputs.trade == '1' || github.event_name == 'workflow_dispatch'`）——同一个 cron、同一个交易日闸门、同一次提交。
- 也可在 Actions 页面 **手动触发**（`workflow_dispatch`，无参数）：任意时间强制重算「当日」XXFI——盘中出**盘中快照**、收盘后出**当日收盘值**（周末/非交易日仍取最近交易日），用于验证链路或补算。
- 防污染：仅当 `_data_date` == 当天 且 已收盘（北京时间 ≥15:00）才写入历史趋势；`_data_date` ≠ 当天（周末/非交易日）或盘中快照（<15:00）均跳过写入，避免脏数据/盘中值污染趋势；同日已存在则跳过（防手动触发与 cron 重复追加）。
- **桌面 tdx 实时播报仍保留 09:30**：那是 WorkBuddy 交互场景（用通达信连接器实时取数，小旭可在开盘看一眼），与 Actions 盘后跑（akshare 开盘数据不全）职责互补。

## 数据源与降级顺序（多源容错）

> **关键事实**：akshare 单个函数只绑定一个数据源，**函数本身不会自动换源**。本取数器自行实现「源链」——任一源失败自动切下一个，全部失败才降级，**绝不静默丢数据**。当前实际命中源记录在产品 `_breadth_source` / `_retail_net_source` 字段中。

| 计算分量 | 主源 | 兜底 1 | 兜底 2 | 兜底 3 | 全失败 |
|---|---|---|---|---|---|
| **指数分量**（回撤/动量/均线/波动率） | 新浪 `stock_zh_index_daily(sh000001)` | 腾讯 `stock_zh_index_daily_tx`（`proxy.finance.qq.com`，收盘价偏差 < 0.0001% 可透明兜底） | — | — | 双源均不通时报错（CI 告警） |
| **盘面广度**（up / down / 涨停 / 跌停） | `legu`（legu host，本地/CI 均通） | 新浪 `stock_zh_a_spot`（Sina host） | — | — | 退化指数版（up/down=1/1，广度分量失效） |
| **资金流** `retail_net`（散户·小单净占比）+ `main_net`（主力净占比） | 东方财富「大盘资金流」`ulist.np/get`（`上证+深证成指` secid 求和 `主力/小单净额÷成交额`，经 push2delay 补丁取真值） | — | — | — | 双双降级 `(None, 0.0)` 由 compute() 置中性占位 |

> 主力与散户净流入统一用东方财富大盘资金流的「净占比」（`Σ主力净额÷Σ成交额`、`Σ小单净额÷Σ成交额`，小数），**两者同口径可直接相减得 v2「主力—散户背离」**。该值复刻东财 zjlx 大盘页（dpzjlx.html / dapan.js）`loadchart2` 的口径：以 `secids=1.000001,0.399001`（上证+深证成指=“沪深两市”）请求 `ulist.np/get`，将两行求和，单请求无分页截断、与网站显示完全一致。东财 host 已从 `push2his` 迁移至 `push2delay`，且 `push2` 在境外 IP 亦被重置；本取数器在模块加载时注入 `push2his/push2→push2delay` URL 改写补丁（含 15s 超时防挂起，正则幂等），使两端均可直连取真值；仅当皆不可达才降级。

### v2 新增：主力—散户背离维度

XXFI 原为「散户情绪反向器」，v2 引入**聪明钱确认**——把主力资金流向作为散户情绪的对照：

- **背离 = 主力净占比 − 散户(小单)净占比**（同口径小数，均来自 `ulist.np/get` 的 `Σ净额÷Σ成交额`）。
  - 负 且「散户追高·主力派发」→ **顶部出货**（危险，强化 REDUCE/SELL）；
  - 正 且「散户割肉·主力进场」→ **底部吸筹**（机会，强化 BUY/ACCUMULATE）。
- 实现：作为**贪婪副表第 5 个分量**（权重 0.20），其余 4 项重平衡为 0.25/0.15/0.20/0.20；
  显著背离时还在报告/网页附「背离确认/提示」标注。**XXFI 主表（决定信号）的合同不变**，背离仅作辅助诊断与确认。
- 数据源同「资金流」：东方财富「大盘资金流」`ulist.np/get`（经 `push2delay` 补丁两端直连取真值）；仅当两端皆不可达时降级取中性占位（不影响主信号，网页标注「无数据（资金流降级）」）。

## 数据源扩展评估（已调研，维持三源现状）

> 2026-07-11 对「东方财富全面接管」「雪球新增散户热度分量」两类扩展做了实证评估，结论均为**维持现状**。记录于此，避免重复调研。

### 东方财富全面接管评估（结论：不采用）

逐一实测东财各 host 在本地（中国 IP）的可达性：

| 接管目标 | 东财函数 | host | 实测结果 |
|---|---|---|---|
| 指数派生 4 项（回撤/动量/均线/波动率） | `stock_zh_index_daily_em` | push2his | 原始 RST；改写 push2delay 后 **返回空**（kline 端点 push2delay 不支持）→ 不可用 |
| 广度 up/down | `stock_zh_a_spot_em` | 82.push2 | 改写 `82.push2delay` 可通但 **77s 极慢**（58 页全量）→ legu 秒级完胜 |
| 涨停家数 | `stock_zt_pool_em` | push2ex | 直通 0.3s，92 行明细 ✅ |
| 跌停家数 | `stock_zt_pool_dtgc_em` | push2ex | 直通 0.1s，含封板/连板明细 ✅ |
| 资金流 2 项 | `stock_market_fund_flow`(daykline) → 改 `ulist.np/get`(大盘) | push2his→push2 / push2delay | daykline/get 端点**已废弃**（任何日期均 `data:null`）；2026-07-14 改用 `ulist.np/get`（大盘资金流，单请求求和沪深两市，无分页截断），经 push2delay 补丁两端直连 ✅ |

- 东财各接口分布在不同 host、封锁状态各异；`push2delay` 补丁对 `ulist` / `fflow` 端点有效，对 kline 端点返回空，故**指数派生无法换东财，新浪不可替代**。
- 即便换涨跌停，同日口径断层（legu 93/7 vs 东财封板池 92/4），会让历史曲线出现一次性台阶。
- **结论**：东财实际只能多接涨跌停，收益有限且付出口径代价；当前 9 分量已全真值、零降级，无痛点需要东财补位。

### 雪球 `stock_hot_*` 新增第 10 分量评估（结论：不采用）

- 本地实测 `stock_hot_tweet_xq` / `stock_hot_follow_xq` / `stock_hot_deal_xq` **全部连通**（~14s/个），返回的是**全市场 ~5610 只股票的完整注意力列表**（非排行榜）；但**无涨跌幅列**，需 join 新浪 spot 才得方向。
- 属性评估：雪球「零售关注度」本质与现有 `retail_in`（散户净流入）高度共线，属同一潜在因子 double-count，会损害信息多样性与稳健性；且绝对关注度日度不可比、需历史基线校准。
- **结论**：不增加第 10 分量。若未来要做「零售注意力」展示，属独立新功能（需另立项 + 权重重平衡 + GitHub 美 IP 连通验证），不在此列。

### 当前终态（三源分工，9 分量全有兜底）

- **新浪 → 腾讯**（指数 4 项）：回撤/波动率/动量/高于20日线 → `stock_zh_index_daily` 主力，`stock_zh_index_daily_tx` 兜底（收盘价偏差 < 0.0001%，透明容灾）。
- **legu → 新浪 spot**（广度 3 项）：涨跌家数比 / 跌停·涨停比 → `stock_market_activity_legu` 主力，`stock_zh_a_spot` 兜底。
- **东方财富**（资金流 2 项）：散户净流入 / 主力—散户背离 → `ulist.np/get`（大盘资金流，push2delay 补丁）。
- 9 个输入全真值、零降级维度；代码已清理死代码 `_fetch_up_down` 与副表对齐回填机制。
- **溯源字段**：`_index_source`（sina/tx）、`_breadth_source`（legu/sina_spot）、`_retail_net_source`（eastmoney/degraded）。
- **为何 legu 广度保持主力、新浪 spot 兜底**：legu 在本地与 GitHub（美国 IP）两端均验证过直通，保证两端 XXFI 完全一致；新浪 spot 在 GitHub 美 IP 未实测，翻转为主力有两端不一致风险。

### 冰点参考（旁挂指标）的数据源与判定

> 冰点参考是**独立于 XXFI 的参考指标**，仅作旁挂展示，**不修改 XXFI 任何原始计算/展示**。4 个维度**全部同时满足**才判为冰点（一年 3 次以内，纪律不出手）。

**4 维度判定标准**（全部满足 = 冰点）：

| 维度 | 判定标准 | 主源 | 兜底 1 | 兜度 2 |
|---|---|---|---|---|
| **D1 下跌广度** | 下跌 ≥ 4000 且 下跌占比 ≥ 85% | [P0] 复用同轮 XXFI 的 `legu` 广度 → 否则 `legu`（聚合家数） | 新浪 `stock_zh_a_spot`（板块差异化·剔除 ST） | 东财 `stock_zh_a_spot_em`（板块差异化·剔除 ST） |
| **D2 指数/ETF 跌幅** | 上证 ≤ -2.0% 且 创业板指 ≤ -2.5% 且 核心 ETF 跌幅≤-2.5% 占比 ≥ 60% | 东财 `stock_zh_index_spot_em` + `ulist.np/get`（secids 精确查 45 只核心 ETF 白名单，~0.1s） | `fund_etf_spot_em` 全量（命中不足/异常时兜底） | — |
| **D3 跌停数量** | 跌停 ≥ 50 且 跌停/涨停 ≥ 3 | [P0] 复用同轮 XXFI 的 `legu` 广度 → 否则 `legu`（聚合跌停） | 新浪 `stock_zh_a_spot`（板块差异化·剔除 ST） | 东财 `stock_zh_a_spot_em`（板块差异化·剔除 ST） |
| **D4 放量恐慌** | 放量倍数（当日上证成交额 / 上证近 20 日均）≥ 1.3 | [P2] 东财当日额（复用 `fetch_index_em`）+ 本地滚动缓存 `_sh_amt_cache.json` 近 20 日均额 | 腾讯 `stock_zh_index_daily_tx` 近 20 日均额（仅首次/缓存不足建基准） | — |

- **源链**：
  - **D1/D3（[P0] 优先复用 XXFI 广度）**：同轮 `run_xxfi` 已用 `legu` 取过广度并写入 `xxfi_report.json` 的 `inputs`；冰点直接复用其 `down/up/limit_down/limit_up`（**零额外取数**），仅 `total`（总家数）用 `legu` 补取精确值，legu 不可达时退化为 `up+down` 近似（忽略平盘，源标记 `legu(reuse)-approx`）。仅当 XXFI 广度缺失/降级才回退自有 `legu → 新浪 spot → 东财 spot` 链——**规避「冰点 legu 抖动失败 → 新浪/东财逐股兜底」14~63s 耗时**。
  - **D2（东财快）**：指数 spot（`stock_zh_index_spot_em`，~0.1s）+ ETF spot（**[提速] 改用东财 `ulist.np/get` + secids 精确查询 45 只核心 ETF 白名单，~0.1s**，替代原 `fund_etf_spot_em` 全量分页 37 页 ~18s；命中 <40 或异常时回退 `fund_etf_spot_em` 全量兜底，源标记 `eastmoney_etf(secids)`）。白名单 = 宽基11（含国证2000 `159628`、中证2000 `563300` 微盘高β）+ 行业34（补 `512070` 保险 / `159930` 能源 / `159666` 交运；半导体仍含 `588200`）。
  - **D4（[P2] 去腾讯日K）**：当日上证成交额复用 `fetch_index_em` 已取到的 `sh_amount`（~0.1s），近 20 日均额由本地滚动缓存 `output/_sh_amt_cache.json`（每日滚动保留 20 日）提供；**仅首次/缓存样本不足时用腾讯日K一次性建基准（~17s），之后纯东财零额外网络**。实测滚动均值与腾讯全量重算差异 <1.2%，对「≥1.3」阈值判定无影响。
- **板块差异化跌停**：主板 ±10%（≤-9.5%）、创业板/科创板 ±20%（≤-19.5%）、北交所 ±30%（≤-29.5%）、**ST/*ST 不纳入跌停统计**（按代码前缀 + 名称识别）。
- **溯源标记**：维度命中源记入 `_src_D1/D2/D3/D4`，取值 `legu` / `legu(reuse)` / `legu(reuse)-approx` / `sina_spot` / `eastmoney_spot` / `eastmoney_index` / `eastmoney_etf` / `eastmoney_etf(secids)` / `eastmoney_spot+cache`；任一维度取数失败 → 该维度标 `暂未获取`；全部失败 → 冰点整体 `暂未获取`。

### 冰点实操计划（战术桶 · 仅抢反弹，非长持）

冰点触发时，网页冰点卡底部展示的**实战操作计划**（固化于 `render_html.py` 的 `ICE_OP_PLAN`，纯宽基指数 ETF、不做行业周期押注）：

| 批次 | 触发条件 | 标的 | 仓位 |
|---|---|---|---|
| 第一批 | 触发当日尾盘 14:30–15:00 / 最迟次日开盘 | 中证2000增强(159552) + 中证1000 + 创业板 + 科创50 | 战术桶 1/3 |
| 第二批 | 触发后 3–5 日不破前低 | 中证500 + 沪深300 + 中证2000 | 1/3 |
| 第三批 | 5–8 日收盘不破冰点日低点即补 | 补齐 + 恒生科技（卫星仓） | 1/3 |

- **退出**：沪深300 自低点 +8~12% / 高β +15~25% 分批止盈；D1 下跌<2000、涨停>跌停连续 2 日退场。
- **铁律**：战术桶 ≠ 战略桶（红利/债券不动）· 单信号 ≤ 1/3 · 获利转回红利/债券。
- **修订依据（2026-08-19，7-17 冰点实战 20 交易日回测）**：原计划含行业 ETF（半导体/券商/新能源），组合收益仅 +2.02%；改为纯宽基后组合 +3.02%（首批由 +2.85% 提至 +6.03%）。单标的中 **159552 中证2000增强 +12.22%** 最优（vs 563300 纯指数 +7.23%，增强超额逐日扩大、回撤更小）；第三批「右侧站上 5/10 日线」过晚（8-04 实测 -1.63%），改为「5–8 日不破低点即补」。

### 底部区域判断（旁挂指标 · 地量区域）

> 与冰点参考平行的**第二个旁挂指标**，同样**独立于 XXFI**，不修改 XXFI 任何原始计算/展示。

**判定逻辑**（`dibudian_index.py`，纯标准库、零依赖）：

```
底部区域日  ⇔  当日全市场成交额 ≤ 近 90 个交易日最高成交额 × 50%
```

立场：**底部区域 = 地量区域**。成交额缩至近一个季度峰值的一半及以下，视为市场极度冷清、抛压衰竭。它是一个**状态标记而非瞬时值**——某日一旦满足，该日期就持续显示在卡片上，直到下一个满足条件的日期取代它（由 `run_dibudian.py` 编排层读写 `dibudian_state.json` 实现跨日持久）。

**口径：全市场，非指数成分股**

`全市场成交额 = 上证指数(sh000001) + 深证成指(sz399001) 的全市场成交额之和`（单位：元）。当日与历史峰值**必须同口径**，否则比率失真。

| 分量 | 数据源 | 说明 |
|---|---|---|
| **当日** `today_total` | 新浪实时 spot `stock_zh_index_spot_sina()` | 返回**全市场**成交额，本地/CI 均直连可用（实测 2026-07-31 ≈ 2.542 万亿） |
| **近90日峰值** `max90_total`<br>**近30日回看** `hist30` | 本地滚动缓存 `output/_turnover_cache.json` | 冷启动由**通达信连接器 `tdx_kline`** 一次性回填 2026 全年交易日（139 天，2026-01-05 ~ 07-31），经 `build_cache.py` 合并为 `{date: 元}` 提交入库；此后每个交易日把当日值追加进缓存，保留最近 `CACHE_KEEP=400` 日滚动，由 CI 的 `git-auto-commit` 持久化回仓库 |

**弃用记录（避免重复踩坑）**：

- ❌ 东财 `stock_zh_index_daily_em`（push2his）/ 东财指数 spot：本机被代理拦截、`push2delay` 改写后 kline 端点返回空，**不可靠**。
- ❌ 腾讯 `stock_zh_index_daily_tx`：其 `amount` 是**指数成分股成交额（约半量，≈1.3 万亿）**，与全市场口径（≈2.54 万亿）对不上，会让卡片绝对值与用户实际查到的数字不符。
- ❌ 新浪历史日线 `stock_zh_index_daily`：**不含成交额列**，故历史峰值只能走缓存。

**防污染**：仅在 **`_data_date` == 当天(北京) 且 已收盘(北京时间 ≥15:00) 且 工作日(周一~周五) 且 同日未写过** 时才写入历史缓存；盘中快照(<15:00) / 周末 / 非交易日(`_data_date`≠当天) 一律跳过写入，避免脏数据/盘中值污染 90 日峰值窗口；同日已存在则跳过（防手动触发与 cron 重复追加）——已在 `fetch_dibudian_akshare.fetch_em_total()` 与 `run_dibudian.py` 的 state 更新处用**收盘闸门 + `date not in cache`** 双重拦截（根治 2026-08-03 盘中手动触发污染事件）。

**降级**：新浪 spot 不可达时全部字段返回 `None`，卡片显示「暂未获取」，**不影响 XXFI 与冰点**。

## 运行方式

### 1) 纯 akshare 模式（CI / 无通达信环境，直接联网）

```bash
pip install -r requirements.txt
python run_xxfi.py --akshare --vol_window 60 --out output
```

- 指数：新浪 `stock_zh_index_daily` → 腾讯 `stock_zh_index_daily_tx` 兜底（偏差 < 0.0001%）
- 盘面广度：`legu` → 新浪 `stock_zh_a_spot`（多源兜底，任一源失败自动切换）
- 资金流 `retail_net` / `main_net`：东方财富「大盘资金流」`ulist.np/get` 经 `push2delay` 补丁取真值（净占比口径，两端直连；复刻 zjlx 大盘页 loadchart2 求和算法）
- `--vol_window`：波动率分位窗口。`60`=近 60 日纯情绪相对冷热（默认）；`260`=相对全年极端程度。
- **多源容错**：akshare 单函数只绑一个源、不会自动换源；本取数器实现「源链」，产物含 `_breadth_source` / `_retail_net_source` 溯源字段，报告展示当前实际命中源。

### 2) 通达信模式（WorkBuddy 技能交互 / 历史复盘）

```bash
python run_xxfi.py --hs300 <指数日K文件路径> \
                   --breadth '{"up":2400,"down":2600,"limit_up":55,"limit_down":25,"retail_net":-0.01}' \
                   --out <目录>
# 或
python run_xxfi.py --json '{"drawdown":-0.08,"ret20":0.02,"above_ma20":0.01,"up":1800,"down":3200,"limit_up":40,"limit_down":30,"vol_pct":0.78,"retail_net":-0.02}'
```

### 3) 旁挂参考指标（冰点 / 底部区域）

两者均**独立于 XXFI**，可单独运行，产物各自落到 `output/`，由 `render_html.py` 旁挂渲染：

```bash
# 冰点参考（4 维度全满足才判冰点）
python run_bingdian.py --akshare --out output

# 底部区域判断（地量：当日 ≤ 近90日峰值×50%）
python run_dibudian.py --akshare --out output
```

底部区域首次部署需**冷启动缓存**（仅一次）：用通达信连接器 `tdx_kline` 导出上证/深证日 K 原始数据到 `sh_kline_raw.txt` / `sz_kline_raw.txt`，再执行 `python build_cache.py` 合并为 `output/_turnover_cache.json`。之后每交易日由 CI 自动滚动追加，无需再手动干预。

渲染完整页面（含两张旁挂卡）：

```bash
python render_html.py --json output/xxfi_report.json \
                      --history output/history.jsonl \
                      --bingdian output/bingdian_report.json \
                      --dibudian output/dibudian_report.json \
                      --out docs/index.html
```

### 4) 自检

```bash
python xiaoxu_fear_index.py --demo         # 内置恐慌/贪婪样例，应分别输出 BUY / SELL
python run_dibudian.py --demo-bottom --out output   # 地量样例：比率 0.375 ≤ 0.5 → 底部区域日
python run_dibudian.py --demo-normal --out output   # 正常量样例：比率 1.125 > 0.5 → 非底部区域日
```

## 指标定义

- **XXFI（0–100）**：越大 = 越恐惧。≥75 极度恐惧，≤25 极度贪婪。
- **反向信号五档**（按 XXFI 绝对区间，非相对比较）：
  `BUY`(≥75) / `ACCUMULATE`(60–75) / `HOLD`(40–60) / `REDUCE`(25–40) / `SELL`(<25)。
  *注意：XXFI 越低 = 越贪婪，低分区应判 REDUCE/SELL，勿误判为 BUY。*

| XXFI | 市场状态 | 信号 | 建议 |
|---|---|---|---|
| ≥75 | 极度恐惧 | BUY | 分批低吸 |
| 60–75 | 恐惧 | ACCUMULATE | 逢低吸纳，不杀跌 |
| 40–60 | 中性 | HOLD | 按自身策略 |
| 25–40 | 偏贪婪 | REDUCE | 逢高减仓，不追涨 |
| <25 | 极度贪婪 | SELL | 减仓避险 |

> 反向指标仅在「情绪极端 + 趋势反转」时有效，震荡市会频繁假信号。务必与自身交易系统、止损纪律配合，切勿单独作为买卖依据。

## 作为 WorkBuddy 技能使用

本仓库即一个 WorkBuddy 技能。克隆到技能目录即可：

```bash
git clone <this-repo> ~/.workbuddy/skills/xiaoxu-fear-index
```

## 文件结构

| 文件 | 作用 |
|---|---|
| `xiaoxu_fear_index.py` | 纯计算（仅标准库，零外部依赖）★ 数据源解耦 |
| `fetch_market_akshare.py` | 纯 akshare 取数器（CI/实时，新浪→腾讯指数日K + legu 广度 + 东财大盘资金流 ulist.np/get（push2delay 补丁），含多源兜底与重试） |
| `run_xxfi.py` | 编排入口（`--akshare` / `--hs300` / `--json`） |
| `bingdian_index.py` | 冰点纯计算（仅标准库，零外部依赖）：输入 4 维度实测 → 输出冰点判定 + 维度明细（含 `threshold` 判定标准）+ 溯源标记 |
| `fetch_bingdian_akshare.py` | 冰点 akshare 取数器（[P0] D1/D3 优先复用同轮 XXFI 的 legu 广度 → 否则 legu→新浪→东财；D2: 东财指数 + `ulist.np/get`(secids) 精确查 45 只核心 ETF（宽基含中证2000微盘、行业补保险/能源/交运），替代全量分页；[P2] D4: 东财当日额 + 本地滚动缓存近20日均额，去腾讯日K；含多源兜底） |
| `run_bingdian.py` | 冰点编排入口（`--akshare` / `--demo` / `--json`），产出 `output/bingdian_report.json` + `.md` |
| `dibudian_index.py` | 底部区域纯计算（仅标准库，零外部依赖）：输入当日 + 近90日峰值成交额 → 输出是否底部区域日 + 比率 + 判定文案 |
| `fetch_dibudian_akshare.py` | 底部区域取数器：当日走**新浪实时 spot**（全市场口径），近90日峰值 + 近30日回看走**本地滚动缓存**（通达信冷启动回填）；含周末写入闸门防污染 |
| `run_dibudian.py` | 底部区域编排入口（`--akshare` / `--demo-bottom` / `--demo-normal` / `--json`），产出 `output/dibudian_report.json` + 跨日持久的 `dibudian_state.json` |
| `build_cache.py` | **冷启动一次性工具**：把通达信 `tdx_kline` 导出的上证/深证日 K 原始数据合并为 `output/_turnover_cache.json`（全市场成交额 `{date: 元}`） |
| `render_html.py` | 把 `xxfi_report.json` + `history.jsonl` + `bingdian_report.json` + `dibudian_report.json` 渲染为自包含静态页 `docs/index.html`（含冰点参考卡 + 底部区域判断卡与30日趋势图，GitHub Pages） |
| `retry_utils.py` | 网络调用通用工具：指数退避 + 随机间隔 + UA 轮换 |
| `calibration.json` | 实证统计、关键案例、权重、解读区间 |
| `references/` | 港股核验 K 线（akshare 新浪源） |
| `SKILL.md` | WorkBuddy 技能文档 |
| `.github/workflows/xxfi-daily.yml` | 每日自动播报（15:50 cron · 仅交易日 · 数据就绪校验；实跑约 16:00 前后）。XXFI / 冰点 / 底部区域三个计算步骤**共用同一闸门**，产物由 `git-auto-commit`（`file_pattern: "output/* docs/*"`）持久化 |
| `output/_turnover_cache.json` | 全市场成交额滚动缓存（底部区域近90日峰值来源），每交易日由 CI 自动追加并提交 |

## License

[MIT](LICENSE)
