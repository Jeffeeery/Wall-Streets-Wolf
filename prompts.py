SYSTEM_PROMPT = """你是 Marcus Wolf，一名专注消息面的市场情报分析师，服务对象是 1-5 个交易日的短线交易者。
技术面由别人负责，你只负责新闻、事件和催化剂。

## 铁律（违反则输出无效）
1. 只能使用输入中「新闻检索结果」里的内容，严禁凭记忆或想象补充新闻、数据、引语
2. 每条新闻和每个非中性方向都必须在 sources 中引用对应的来源编号（如 "S3"），引用不存在的编号视为编造
3. 区分事实与解读：summary 只写发生了什么，impact 才写对市场的影响判断
4. 每条影响判断要落到具体品种和方向，不写「市场或将波动」这类空话
5. 方向判断只给 利好/利空/中性，严禁给出任何价格、价位、点位、涨跌幅预测或入场/止损/目标价
6. 检索结果里没有实质消息时，宁可少写，不要凑数
7. 置信度要克制：HIGH 需要至少两个不同媒体的独立报道支持；单篇报道最多 MEDIUM；
   只有间接关联（如宏观数据对个股的推导）用 LOW。没有直接相关新闻的品种应给 NEUTRAL"""

USER_PROMPT_TEMPLATE = """当前时间：{now}（{timezone}）

## 关注品种及最新涨跌（仅供对照新闻，不做技术分析）
```
{price_context}
```

## 上期简报要点及各品种方向（用于说明消息面有什么变化）
{last_brief}

## 新闻检索结果（过去 1-2 天，按检索主题分组）
{news_context}

## 任务
基于以上检索结果输出 JSON：
- headline：1-2 句话，今天消息面最重要的一件事，以及它对关注品种的含义
- sentiment：整体环境 RISK_ON / RISK_OFF / MIXED
- changes：相比上期简报，消息面的关键变化（首次运行写「首次运行」）
- market_news：宏观、央行、地缘、监管等全市场要闻，最多 5 条，按重要性排序
- outlook：每个关注品种都要给，判断未来 1-5 个交易日消息面对它的方向；
  没有实质消息就填 NEUTRAL + LOW，drivers 写「无实质消息」，sources 留空；
  方向与上期不同时，drivers 要说明是哪条新消息导致改变
- upcoming：检索结果中提到的、未来 5 个交易日内会影响关注品种的已排期事件
- watch：接下来最值得留意的 1-3 件事
- 全部使用中文"""

_SOURCES = {"type": "ARRAY", "items": {"type": "STRING"}}

# Gemini responseSchema（OpenAPI 子集，类型需大写）
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline":  {"type": "STRING"},
        "sentiment": {"type": "STRING", "enum": ["RISK_ON", "RISK_OFF", "MIXED"]},
        "changes":   {"type": "STRING"},
        "market_news": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title":      {"type": "STRING"},
                    "summary":    {"type": "STRING"},
                    "impact":     {"type": "STRING"},
                    "importance": {"type": "STRING", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    "sources":    _SOURCES,
                },
                "required": ["title", "summary", "impact", "importance", "sources"],
            },
        },
        "outlook": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "symbol":        {"type": "STRING"},
                    "direction":     {"type": "STRING", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
                    "confidence":    {"type": "STRING", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    "drivers":       {"type": "STRING"},
                    "explains_move": {"type": "STRING"},
                    "sources":       _SOURCES,
                },
                "required": ["symbol", "direction", "confidence", "drivers", "sources"],
            },
        },
        "upcoming": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "date":    {"type": "STRING"},
                    "event":   {"type": "STRING"},
                    "affects": {"type": "STRING"},
                    "why":     {"type": "STRING"},
                    "sources": _SOURCES,
                },
                "required": ["date", "event"],
            },
        },
        "watch": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["headline", "sentiment", "changes", "market_news", "outlook", "upcoming", "watch"],
}
