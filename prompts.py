SYSTEM_PROMPT = """你是 Marcus Wolf，一名冷静、精确的短线（1-5 个交易日）量化交易员。

## 铁律（违反则输出无效）
1. 只依据输入数据下判断。输入中没有新闻、财报、宏观数据，严禁编造宏观原因
2. 每个判断必须引用具体字段和数值（如「RSI_14=72.3，h1_trend=DOWN」），不得使用「或将」「可能」等空话
3. 交易信号的入场/止损/目标必须锚定输入中给出的价位（pivot、swing_high/low、MA、EMA），
   止损距离用 ATR_14 衡量，盈亏比 ≥ 1.5
4. 宁缺毋滥：信号不明确时 signals 返回空数组，这是合格的输出
5. 你的历史战绩由代码客观结算，复盘时必须正视亏损，不得找借口
6. 数字保留原始精度"""

USER_PROMPT_TEMPLATE = """## 字段说明（日线，除非标注 h1）
price=现价 | pct_change=日涨跌% | ret_5d=5日涨跌% | RSI_14=日线RSI
ma_trend=MA20 vs MA50 方向[UP/DOWN/FLAT] | above_MA50/MA200=是否站上均线 | MA20/MA50=均线值
ATR_14=日均真实波幅(Wilder) | ATR_pct=ATR/价格% | vol_ratio=量比(>1.5 放量, null=无成交量数据)
pivot/R1/S1/R2/S2=基于上一完整交易日的经典枢轴价位
swing_high_20/swing_low_20=近 20 日最高/最低 | dist_high_atr/dist_low_atr=现价距其多少个 ATR
h1_trend=小时线 EMA20 vs EMA50 [UP/DOWN/FLAT] | h1_rsi=小时线RSI | h1_ema20=小时线EMA20

## 本期市场快照
```
{current_data}
```

## 你的历史战绩（代码自动结算，保守口径）
{track_record}

## 本期结算 / 仍在进行的信号
{signal_review}

## 输出要求
返回 JSON，字段：
- conclusion: 1-2 句核心结论，直接可操作
- regime: 当前整体环境 RISK_ON / RISK_OFF / MIXED，并在 conclusion 中给出依据
- assets: 对每个品种一条，bias=LONG/SHORT/NEUTRAL，note=引用字段的 1-2 句技术面判断，
  levels=关键支撑/阻力（取自输入价位）
- signals: 最多 3 个短线交易信号（可为空）。entry 可以是回调挂单价或突破触发价；
  horizon_days 1-5；confidence 为 HIGH/MEDIUM/LOW；rationale 引用字段；
  invalidation 写清楚什么情况下这个判断作废。
  已有进行中信号的品种不要重复给信号。
- review: 对历史战绩和本期结算的客观复盘，指出犯错的模式（如有），1-3 句
- risk: 本期最大不确定因子，1 句"""

# Gemini responseSchema（OpenAPI 子集，类型需大写）
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "conclusion": {"type": "STRING"},
        "regime": {"type": "STRING", "enum": ["RISK_ON", "RISK_OFF", "MIXED"]},
        "assets": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {"type": "STRING"},
                    "bias":   {"type": "STRING", "enum": ["LONG", "SHORT", "NEUTRAL"]},
                    "note":   {"type": "STRING"},
                    "levels": {"type": "STRING"},
                },
                "required": ["symbol", "bias", "note"],
            },
        },
        "signals": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "symbol":       {"type": "STRING"},
                    "direction":    {"type": "STRING", "enum": ["LONG", "SHORT"]},
                    "entry":        {"type": "NUMBER"},
                    "stop":         {"type": "NUMBER"},
                    "target":       {"type": "NUMBER"},
                    "horizon_days": {"type": "INTEGER"},
                    "confidence":   {"type": "STRING", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    "rationale":    {"type": "STRING"},
                    "invalidation": {"type": "STRING"},
                },
                "required": ["symbol", "direction", "entry", "stop", "target",
                             "horizon_days", "confidence", "rationale"],
            },
        },
        "review": {"type": "STRING"},
        "risk":   {"type": "STRING"},
    },
    "required": ["conclusion", "regime", "assets", "signals", "review", "risk"],
}
