# 小旭恐惧指数 · XiaoXu Fear Index (XXFI)

把当前 A 股市场数据映射为一个 **0–100 的反向情绪指标**（类似 VIX/VXN 的散户行为版），用于判断市场情绪极端点并给出反向操作参考。灵感来自朋友"小旭" 2024–2026 的真实炒股实录：反复"卖飞""买在山顶""恐慌割肉在底部"。

> **核心思想**：散户（尤其小旭式）的"恐惧"常出现在阶段底部、"贪婪"常出现在阶段顶部。把市场当下的恐惧/贪婪量化 → 反向参考：越恐惧越该买、越贪婪越该卖。

## 实时结果（GitHub Actions 自动更新）

每个交易日 **16:30（北京时间 · 盘后）** 自动运行，产物提交到 `output/`：

- 📄 [`output/xxfi_report.md`](output/xxfi_report.md) — 当日人类可读报告
- 🧾 [`output/xxfi_report.json`](output/xxfi_report.json) — 当日结构化结果（含 `_breadth_source` / `_retail_net_source` 溯源字段）
- 📈 [`output/history.jsonl`](output/history.jsonl) — 每日一行历史：`{date, xxfi, greed, signal, level}`（由每日 cron 自动累积）

### 🌐 网页版（GitHub Pages 自动发布）

每次运行后自动生成自包含静态页 **[https://homjanon.github.io/xiaoxu-fear/](https://homjanon.github.io/xiaoxu-fear/)**，内容含：

- **最新结果卡**：大号 XXFI（主表·决定信号）+ 贪婪指数（副表·辅助诊断）+ 信号徽章 + 一句话建议
- **分项得分**：恐惧 4 项 / 贪婪 5 项进度条（恐惧/贪婪两表列宽对齐、手机端自适应不溢出）
- **对照参考表**：XXFI 绝对区间 → 等级 / 信号 / 含义，并标注「两表独立、非互补」
- **历史趋势**：内联 SVG 折线（XXFI vs 贪婪）+ 近 10 日数据表（运行数日后自动出现）

由 `render_html.py` 读取 `xxfi_report.json` + `history.jsonl` 渲染，并经 Actions 提交到 `docs/index.html`；GitHub Pages 源已设为 `main/docs` 自动发布，永远是最新结果。

> **副表对齐机制**：`render_html.py` 在生成 `docs/index.html` 的同时，会把 `xxfi_report.json`（含 `inputs.main_net` / `inputs.retail_net`）一并写入 `docs/` 并提交。本地运行 `run_xxfi.py` 时，`fetch_market_akshare._fetch_published_fund_flow()` 会自动从 Pages 抓取云端已算出的主力/散户净占比，使**本地副表（散户净流入 + 主力—散户背离）与 GitHub 完全一致**，彻底消除本地/云端不一致。

## 自动运行触发方案

针对"开盘瞬间资金流向缺失、非交易日空跑"的问题，重新设计了触发逻辑。依据 A 股数据更新节奏（北京时间）：

```
09:30 开盘 → 15:00 收盘 → 15:00~16:00 指数日K / 涨跌家数 / 涨停跌停池 / 主力资金流向 陆续定稿
                              ↑ 16:30 触发（确保当日完整数据已就绪）
```

三条约束的落地：

| 约束 | 方案 | 实现 |
|---|---|---|
| **① 交易日筛选** | 仅在交易日执行，非交易日（含节假日/休市）完全不触发 | cron 仅覆盖周一至五；`check` 步骤用 `tool_trade_date_hist_sina()` **精确排除法定节假日/休市日（含调休）**，不靠"周一到五"硬猜 |
| **② 执行时机** | 避开开盘数据空窗，待资金流向定稿后执行 | cron `"30 8 * * 1-5"` = **北京 16:30 盘后**；`check` 步骤再校验「上证指数日K末交易日 == 今天」双保险，未更新则 skip |
| **③ 每日频次** | 单日单次，不产生无效执行 | 盘后单次运行；非交易日 / 数据未就绪由 `check` 步骤 `skip`，后续步骤 `if: steps.check.outputs.trade == '1'` 全部跳过 |

- 也可在 Actions 页面 **手动触发**（`workflow_dispatch`，无参数）：任意时间强制重算「最近一个交易日」XXFI（周末也能取周五数据），用于验证链路或补算。
- 防污染：若产物 `_data_date` ≠ 当天（极端数据延迟 / 周末手动触发），`Append to history` 步骤跳过写入，避免脏数据进入历史趋势；同日已存在则跳过（防手动触发与 cron 重复追加）。
- **桌面 tdx 实时播报仍保留 09:30**：那是 WorkBuddy 交互场景（用通达信连接器实时取数，小旭可在开盘看一眼），与 Actions 盘后跑（akshare 开盘数据不全）职责互补。

## 数据源与降级顺序（多源容错）

> **关键事实**：akshare 单个函数只绑定一个数据源，**函数本身不会自动换源**。本取数器自行实现「源链」——任一源失败自动切下一个，全部失败才降级，**绝不静默丢数据**。当前实际命中源记录在产品 `_breadth_source` / `_retail_net_source` 字段中。

| 计算分量 | 主源 | 兜底 1 | 兜底 2 | 兜底 3 | 全失败 |
|---|---|---|---|---|---|
| **指数分量**（回撤/动量/均线/波动率） | 新浪 `stock_zh_index_daily(sh000001)` | — | — | — | 无（脚本报错，CI 会告警） |
| **盘面广度**（up / down / 涨停 / 跌停） | `legu`（legu host，本地/CI 均通） | 新浪 `stock_zh_a_spot`（Sina host） | — | — | 退化指数版（up/down=1/1，广度分量失效） |
| **资金流** `retail_net`（散户·小单净占比）+ `main_net`（主力净占比） | 东方财富 `stock_market_fund_flow()`（`主力/小单净流入-净占比`，经 push2delay 补丁取真值） | 本地回退：同花顺 `stock_fund_flow_individual` 聚合代理 / **GitHub 已发布值回填** | — | — | 双双降级 `0.0`（两端均不可达时） |

> 主力与散户净流入统一用东方财富大盘资金流的「净占比/100」，**两者同口径可直接相减得 v2「主力—散户背离」**。东财已将接口从 `push2his` 迁移至 `push2delay`，但 akshare 仍硬编码旧端点 → 直连被重置；本取数器在模块加载时注入 `push2his→push2delay` URL 改写补丁（含 15s 超时防挂起），使两端均可直连取真值；仅当皆不可达才降级。

### v2 新增：主力—散户背离维度

XXFI 原为「散户情绪反向器」，v2 引入**聪明钱确认**——把主力资金流向作为散户情绪的对照：

- **背离 = 主力净占比 − 散户(小单)净占比**（同口径小数，均来自 `stock_market_fund_flow` 的 净占比/100）。
  - 负 且「散户追高·主力派发」→ **顶部出货**（危险，强化 REDUCE/SELL）；
  - 正 且「散户割肉·主力进场」→ **底部吸筹**（机会，强化 BUY/ACCUMULATE）。
- 实现：作为**贪婪副表第 5 个分量**（权重 0.20），其余 4 项重平衡为 0.25/0.15/0.20/0.20；
  显著背离时还在报告/网页附「背离确认/提示」标注。**XXFI 主表（决定信号）的合同不变**，背离仅作辅助诊断与确认。
- 数据源同「资金流」：东方财富 `stock_market_fund_flow()`（经 `push2delay` 补丁两端直连取真值）；仅当两端皆不可达时降级取中性占位（不影响主信号，网页标注「无数据（资金流降级）」）。

## 运行方式

### 1) 纯 akshare 模式（CI / 无通达信环境，直接联网）

```bash
pip install -r requirements.txt
python run_xxfi.py --akshare --vol_window 60 --out output
```

- 指数：`akshare.stock_zh_index_daily(sh000001)`
- 盘面广度：`legu` → 新浪 `stock_zh_a_spot`（多源兜底，任一源失败自动切换）
- 资金流 `retail_net` / `main_net`：东方财富 `stock_market_fund_flow()` 经 `push2delay` 补丁取真值（净占比口径，两端直连）；本地失败回退同花顺代理 / GitHub 发布值回填
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

### 3) 自检

```bash
python xiaoxu_fear_index.py --demo   # 内置恐慌/贪婪样例，应分别输出 BUY / SELL
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
| `fetch_market_akshare.py` | 纯 akshare 取数器（CI/实时，legu 广度 + 新浪指数 + push2delay 资金流，含多源兜底与重试） |
| `run_xxfi.py` | 编排入口（`--akshare` / `--hs300` / `--json`） |
| `render_html.py` | 把 `xxfi_report.json` + `history.jsonl` 渲染为自包含静态页 `docs/index.html`（GitHub Pages） |
| `retry_utils.py` | 网络调用通用工具：指数退避 + 随机间隔 + UA 轮换 |
| `calibration.json` | 实证统计、关键案例、权重、解读区间 |
| `references/` | 港股核验 K 线（akshare 新浪源） |
| `SKILL.md` | WorkBuddy 技能文档 |
| `.github/workflows/xxfi-daily.yml` | 每日自动播报（盘后 16:30 · 仅交易日 · 数据就绪校验） |

## License

[MIT](LICENSE)
