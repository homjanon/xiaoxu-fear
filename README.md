# 小旭恐惧指数 · XiaoXu Fear Index (XXFI)

把当前 A 股市场数据映射为一个 **0–100 的反向情绪指标**（类似 VIX/VXN 的散户行为版），用于判断市场情绪极端点并给出反向操作参考。灵感来自朋友"小旭" 2024–2026 的真实炒股实录：反复"卖飞""买在山顶""恐慌割肉在底部"。

> **核心思想**：散户（尤其小旭式）的"恐惧"常出现在阶段底部、"贪婪"常出现在阶段顶部。把市场当下的恐惧/贪婪量化 → 反向参考：越恐惧越该买、越贪婪越该卖。

## 实时结果（GitHub Actions 自动更新）

每个交易日 **09:30（北京时间）** 自动运行，产物提交到 `output/`：

- 📄 [`output/xxfi_report.md`](output/xxfi_report.md) — 当日人类可读报告
- 🧾 [`output/xxfi_report.json`](output/xxfi_report.json) — 当日结构化结果
- 📈 [`output/history.jsonl`](output/history.jsonl) — 每日一行历史：`{date, xxfi, greed, signal, level}`

> ⚠️ 数据为「当日快照」（akshare 盘面广度仅返回最新交易日）。历史周度复盘请在本机用 WorkBuddy + 通达信连接器完成。

## 运行方式

### 1) 纯 akshare 模式（CI / 无通达信环境，直接联网）

```bash
pip install -r requirements.txt
python run_xxfi.py --akshare --vol_window 60 --out output
```

- 指数：`akshare.stock_zh_index_daily(sh000001)`
- 盘面广度：`akshare.stock_market_activity_legu()`（一次拿 上涨/下跌/涨停/跌停家数；失败退用涨跌停池计数）
- `--vol_window`：波动率分位窗口。`60`=近 60 日纯情绪相对冷热（默认）；`260`=相对全年极端程度。

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
| `fetch_market_akshare.py` | 纯 akshare 取数器（CI/实时） |
| `run_xxfi.py` | 编排入口（`--akshare` / `--hs300` / `--json`） |
| `calibration.json` | 实证统计、关键案例、权重、解读区间 |
| `references/` | 港股核验 K 线（akshare 新浪源） |
| `SKILL.md` | WorkBuddy 技能文档 |
| `.github/workflows/xxfi-daily.yml` | 每日自动播报 |

## License

[MIT](LICENSE)
