import hmac
import html
import json
import logging
import os
import re
import traceback as tb
from datetime import datetime

from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

import pytz
import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from upstash_redis import Redis

# ==========================================
# 1. 环境变量
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TG_TOKEN       = os.environ.get("TG_TOKEN")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID")
CRON_SECRET    = os.environ.get("CRON_SECRET", "")
UPSTASH_URL    = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN  = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_SERVICE_KEY", "")

TIMEZONE  = "Asia/Kuala_Lumpur"
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 懒加载 Redis，避免模块级 None 初始化崩溃
_redis: Redis | None = None

def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
    return _redis


_SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

_SB_LEGACY_COLUMNS = ("analysis_time", "conclusion", "report", "snapshot")

def sb_insert(row: dict) -> None:
    """Insert one row into analysis_history. Silently logs on failure."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.warning("Supabase env vars not set — skipping history insert")
        return
    try:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/analysis_history",
            headers=_SB_HEADERS,
            json=row,
            timeout=10,
        )
        if res.status_code == 400:
            # 表结构未迁移（缺 sentiment/sources/outlook 列）时退回旧字段
            log.warning("Supabase insert 400, retrying with legacy columns: %s", res.text[:200])
            res = requests.post(
                f"{SUPABASE_URL}/rest/v1/analysis_history",
                headers=_SB_HEADERS,
                json={k: row[k] for k in _SB_LEGACY_COLUMNS if k in row},
                timeout=10,
            )
        if res.status_code not in (200, 201):
            log.warning("Supabase insert failed %s: %s", res.status_code, res.text[:200])
    except Exception:
        log.error("Supabase insert error:\n%s", tb.format_exc())

def sb_fetch_history(limit: int = 30) -> list:
    """Fetch latest N rows from analysis_history."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return []
    try:
        res = requests.get(
            f"{SUPABASE_URL}/rest/v1/analysis_history",
            headers={**_SB_HEADERS, "Prefer": ""},
            params={"order": "created_at.desc", "limit": limit},
            timeout=10,
        )
        if res.status_code == 200:
            return res.json()
        log.warning("Supabase fetch failed %s: %s", res.status_code, res.text[:200])
        return []
    except Exception:
        log.error("Supabase fetch error:\n%s", tb.format_exc())
        return []


# ==========================================
# 2. 量化指标计算
# ==========================================
def calculate_rsi(prices: list[float], period: int = 14) -> float:
    """Wilder 平滑 RSI，数据不足时返回中性值 50。"""
    if len(prices) < period + 1:
        return 50.0

    gains  = [max(0.0, prices[i] - prices[i - 1]) for i in range(1, period + 1)]
    losses = [max(0.0, prices[i - 1] - prices[i]) for i in range(1, period + 1)]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(prices)):
        delta    = prices[i] - prices[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(0.0, delta))  / period
        avg_loss = (avg_loss * (period - 1) + max(0.0, -delta)) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def detect_ma_trend(closes: list[float], fast: int = 20, slow: int = 50) -> str:
    """用快慢双均线判断趋势方向。返回: UP / DOWN / FLAT"""
    if len(closes) < slow:
        return "FLAT"
    ma_fast = sum(closes[-fast:]) / fast
    ma_slow = sum(closes[-slow:]) / slow
    diff_pct = (ma_fast - ma_slow) / ma_slow * 100
    if diff_pct > 0.3:
        return "UP"
    elif diff_pct < -0.3:
        return "DOWN"
    return "FLAT"


def calculate_atr(highs, lows, closes, period: int = 14) -> float:
    """Wilder 平滑 ATR，衡量近期波动率。"""
    if len(closes) < period + 1:
        return 0.0
    trs = [
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        for i in range(1, len(closes))
    ]
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 4)


# ==========================================
# 3. 数据引擎：拉取 + 计算
# ==========================================
class QuantDataEngine:
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    REQUEST_TIMEOUT = 10

    @staticmethod
    def fetch_and_calculate(symbols: list[str]) -> dict:
        market_state: dict[str, dict] = {}

        for sym in symbols:
            try:
                url = (
                    f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
                    f"?range=250d&interval=1d"
                )
                res = requests.get(
                    url,
                    headers=QuantDataEngine.HEADERS,
                    timeout=QuantDataEngine.REQUEST_TIMEOUT,
                ).json()

                result = res["chart"]["result"][0]
                quote  = result["indicators"]["quote"][0]

                # 成交量缺失（指数/外汇等）时按 0 处理，不丢弃整根 K 线
                raw_rows = zip(
                    quote.get("close",  []),
                    quote.get("high",   []),
                    quote.get("low",    []),
                    quote.get("volume", []),
                )
                clean = [
                    (c, h, l, v or 0)
                    for c, h, l, v in raw_rows
                    if None not in (c, h, l)
                ]
                if len(clean) < 2:
                    continue

                closes  = [r[0] for r in clean]
                highs   = [r[1] for r in clean]
                lows    = [r[2] for r in clean]
                volumes = [r[3] for r in clean]

                latest, prev = closes[-1], closes[-2]
                pct_change   = (latest - prev) / prev * 100
                ret_5d = (latest - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else None

                sma200   = sum(closes[-200:]) / min(200, len(closes))
                sma50    = sum(closes[-50:])  / min(50,  len(closes))
                rsi_14   = calculate_rsi(closes)
                ma_trend = detect_ma_trend(closes)
                atr_14   = calculate_atr(highs, lows, closes)

                # 成交量为 0 时量比无意义
                avg_vol20 = sum(volumes[-20:]) / min(20, len(volumes))
                vol_ratio = round(volumes[-1] / avg_vol20, 2) if avg_vol20 and volumes[-1] else None

                market_state[sym] = {
                    "price":       round(latest, 2),
                    "pct_change":  round(pct_change, 2),
                    "ret_5d":      round(ret_5d, 2) if ret_5d is not None else None,
                    "RSI_14":      rsi_14,
                    "above_MA200": latest > sma200,
                    "above_MA50":  latest > sma50,
                    "ma_trend":    ma_trend,
                    "vol_ratio":   vol_ratio,
                    "ATR_14":      atr_14,
                }

            except Exception as e:
                log.warning("[QuantDataEngine] 跳过 %s: %s", sym, e)

        return market_state


# ==========================================
# 4. Marcus Agent：新闻检索 + 简报 + 发送
# ==========================================
SENTIMENT_CN  = {"RISK_ON": "偏多 Risk-on", "RISK_OFF": "避险 Risk-off", "MIXED": "分化"}
DIRECTION_ICON = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}
DIRECTION_CN   = {"BULLISH": "利好", "BEARISH": "利空", "NEUTRAL": "中性"}
CONFIDENCE_CN  = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
NO_NEWS        = "无实质消息"
IMPORTANCE_ICON = {"HIGH": "🔥", "MEDIUM": "•", "LOW": "·"}
TG_LIMIT      = 4000
TG_MAX_SOURCES = 6


def load_watchlist() -> list[str]:
    return json.loads(get_redis().get("marcus_watchlist") or "null") or WATCHLIST


def extract_json(text: str) -> dict:
    """从模型输出中取出 JSON 对象（兼容 ```json 代码块和前后多余文字）。"""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(text[start:end + 1])


def extract_sources(candidate: dict) -> list[dict]:
    """grounding 元数据中的检索来源，按出现顺序去重。"""
    chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
    sources, seen = [], set()
    for ch in chunks:
        web = ch.get("web") or {}
        uri = web.get("uri")
        if uri and uri not in seen:
            seen.add(uri)
            sources.append({"title": web.get("title") or uri, "uri": uri})
    return sources


def call_gemini(user_prompt: str) -> tuple[dict, list[dict]]:
    """开启 Google Search grounding 调用 Gemini，返回 (简报 JSON, 来源列表)。"""
    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192},
    }
    res = requests.post(
        gemini_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=90,
    ).json()
    try:
        candidate = res["candidates"][0]
        text = "".join(
            p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought")
        )
        return extract_json(text), extract_sources(candidate)
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"Gemini 响应无法解析: {e} | {str(res)[:300]}") from e


def normalize_outlook(raw: list, symbols: list[str], prev: dict) -> list[dict]:
    """
    按 watchlist 顺序整理每个品种的消息面方向：丢弃不在 watchlist 的品种，
    缺失的补为中性，非法枚举值回落到 NEUTRAL/LOW，并附上上期方向用于标注变化。
    """
    by_sym = {}
    for item in raw or []:
        sym = str(item.get("symbol", "")).upper().strip()
        if sym in symbols and sym not in by_sym:
            by_sym[sym] = item

    out = []
    for sym in symbols:
        item = by_sym.get(sym, {})
        direction  = str(item.get("direction", "")).upper()
        confidence = str(item.get("confidence", "")).upper()
        out.append({
            "symbol":        sym,
            "direction":     direction if direction in DIRECTION_CN else "NEUTRAL",
            "confidence":    confidence if confidence in CONFIDENCE_CN else "LOW",
            "drivers":       item.get("drivers") or NO_NEWS,
            "explains_move": item.get("explains_move", ""),
            "prev":          prev.get(sym),
        })
    return out


def fmt_direction(o: dict) -> str:
    text = f"{DIRECTION_CN[o['direction']]}（{CONFIDENCE_CN[o['confidence']]}）"
    if o["prev"] and o["prev"] != o["direction"]:
        text += f" 🔄 前次{DIRECTION_CN.get(o['prev'], o['prev'])}"
    return text


def format_price_context(market: dict) -> str:
    lines = []
    for sym, d in market.items():
        ret_5d = f"{d['ret_5d']:+.2f}%" if d.get("ret_5d") is not None else "N/A"
        lines.append(f"{sym}: {d['price']}  日涨跌 {d['pct_change']:+.2f}%  5日 {ret_5d}")
    return "\n".join(lines) or "（行情数据拉取失败）"


def render_telegram(now: str, brief: dict | None, sources: list[dict]) -> str:
    e = html.escape
    out = [f"🐺 <b>Marcus Wolf · 消息面简报</b>  <code>{e(now)}</code>", ""]

    if not brief:
        out.append("⚠️ <b>新闻检索引擎异常</b>，本期简报暂不可用，请查看服务端日志。")
        return "\n".join(out)

    sentiment = SENTIMENT_CN.get(brief.get("sentiment"), brief.get("sentiment", ""))
    out += [f"🎯 <b>核心</b> [{e(sentiment)}]", e(brief.get("headline", "")), ""]

    if not sources:
        out += ["⚠️ <i>本期未检索到来源，以下内容未经验证，请谨慎参考</i>", ""]

    news = brief.get("market_news") or []
    if news:
        out.append("🌍 <b>市场要闻</b>")
        for n in news:
            icon = IMPORTANCE_ICON.get(n.get("importance"), "•")
            out.append(f"{icon} <b>{e(n.get('title', ''))}</b>")
            out.append(f"   {e(n.get('summary', ''))}")
            if n.get("impact"):
                out.append(f"   → {e(n['impact'])}")
        out.append("")

    outlook = brief.get("outlook") or []
    if outlook:
        out.append("🧭 <b>消息面方向</b>（1-5 日）")
        # 中性且无消息、方向也没变的品种合并成一行，节省篇幅
        quiet = [o for o in outlook
                 if o["direction"] == "NEUTRAL" and o["drivers"] == NO_NEWS
                 and o["prev"] in (None, "NEUTRAL")]
        for o in outlook:
            if o in quiet:
                continue
            out.append(f"{DIRECTION_ICON[o['direction']]} <b>{e(o['symbol'])}</b> {e(fmt_direction(o))}")
            out.append(f"   {e(o['drivers'])}")
        if quiet:
            out.append(f"⚪ {NO_NEWS}：{e(', '.join(o['symbol'] for o in quiet))}")
        out.append("")

    upcoming = brief.get("upcoming") or []
    if upcoming:
        out.append("📅 <b>未来 5 日事件</b>")
        for u in upcoming:
            affects = f"（{e(u['affects'])}）" if u.get("affects") else ""
            out.append(f"• {e(u.get('date', ''))} {e(u.get('event', ''))}{affects}")
        out.append("")

    watch = brief.get("watch") or []
    if watch:
        out.append("👀 <b>重点留意</b>")
        out += [f"• {e(w)}" for w in watch]
        out.append("")

    if sources:
        links = " | ".join(
            f'<a href="{e(s["uri"], quote=True)}">{e(s["title"])}</a>'
            for s in sources[:TG_MAX_SOURCES]
        )
        out += [f"🔗 <b>来源</b>：{links}", ""]

    out.append("<i>完整版见 Dashboard</i>")
    msg = "\n".join(out)
    if len(msg) <= TG_LIMIT:
        return msg
    # 超长时丢掉来源行，避免截断到 HTML 标签中间
    msg = "\n".join(line for line in out if not line.startswith("🔗"))
    return msg if len(msg) <= TG_LIMIT else html.escape(html.unescape(re.sub(r"<[^>]+>", "", msg)))[:TG_LIMIT]


def render_full_report(now: str, brief: dict | None, sources: list[dict]) -> str:
    out = [f"Marcus Wolf · 消息面完整简报 · {now}", ""]
    if not brief:
        out.append("【新闻检索引擎异常】本期简报暂不可用。")
        return "\n".join(out)

    sentiment = SENTIMENT_CN.get(brief.get("sentiment"), brief.get("sentiment", ""))
    out += [f"【核心】[{sentiment}]", brief.get("headline", ""), ""]
    if not sources:
        out += ["⚠️ 本期未检索到来源，以下内容未经验证。", ""]
    if brief.get("changes"):
        out += ["【相比上期】", brief["changes"], ""]

    out.append("【市场要闻】")
    for n in brief.get("market_news") or []:
        out.append(f"• [{n.get('importance', '')}] {n.get('title', '')}")
        out.append(f"  {n.get('summary', '')}")
        if n.get("impact"):
            out.append(f"  影响：{n['impact']}")
    out.append("")

    out.append("【消息面方向（1-5 日）】")
    for o in brief.get("outlook") or []:
        out.append(f"• {o['symbol']} {fmt_direction(o)}：{o['drivers']}")
        if o["explains_move"]:
            out.append(f"  与今日涨跌：{o['explains_move']}")
    out.append("")

    out.append("【未来 5 日事件】")
    for u in brief.get("upcoming") or []:
        out.append(f"• {u.get('date', '')} {u.get('event', '')} | {u.get('affects', '')}")
        if u.get("why"):
            out.append(f"  {u['why']}")
    out.append("")

    if brief.get("watch"):
        out.append("【重点留意】")
        out += [f"• {w}" for w in brief["watch"]]
        out.append("")

    if sources:
        out.append("【来源】")
        out += [f"• {s['title']}: {s['uri']}" for s in sources]

    return "\n".join(out)


def send_telegram(text: str) -> None:
    tg_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    res = requests.post(
        tg_url,
        json={
            "chat_id":                  TG_CHAT_ID,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        },
        timeout=10,
    ).json()
    if res.get("ok"):
        return
    # HTML 解析失败时去掉标签发纯文本
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    fallback = requests.post(
        tg_url,
        json={"chat_id": TG_CHAT_ID, "text": plain, "disable_web_page_preview": True},
        timeout=10,
    ).json()
    if not fallback.get("ok"):
        log.error("Telegram 发送彻底失败: %s", fallback)


class MarcusAgent:

    @staticmethod
    def execute_and_send() -> str:
        tz  = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

        # 1. 拉取行情（只用于对照新闻解释涨跌）
        watchlist = load_watchlist()
        market    = QuantDataEngine.fetch_and_calculate(watchlist)

        # 2. 读取上期要点和各品种方向
        last_data = get_redis().get("marcus_memory")
        last_mem  = json.loads(last_data) if last_data else None
        prev_outlook: dict = (last_mem or {}).get("outlook") or {}
        if last_mem:
            last_brief = f"{last_mem.get('time', 'N/A')}：{last_mem.get('conclusion', 'N/A')}"
            if prev_outlook:
                last_brief += "\n" + " | ".join(
                    f"{sym} {DIRECTION_CN.get(d, d)}" for sym, d in prev_outlook.items()
                )
        else:
            last_brief = "无（首次运行）"

        # 3. Gemini + Google Search 生成消息面简报
        user_prompt = USER_PROMPT_TEMPLATE.format(
            now=now,
            timezone=TIMEZONE,
            price_context=format_price_context(market),
            last_brief=last_brief,
        )
        brief: dict | None = None
        sources: list[dict] = []
        try:
            brief, sources = call_gemini(user_prompt)
        except Exception as e:
            log.error("Gemini 调用失败: %s", e)
        if brief and not sources:
            log.warning("本期 Gemini 未返回检索来源，内容可能未经 grounding")
        if brief:
            brief["outlook"] = normalize_outlook(brief.get("outlook"), watchlist, prev_outlook)
        outlook_map = {o["symbol"]: o["direction"] for o in (brief or {}).get("outlook", [])}

        # 4. 生成简报 / 完整报告，写入记忆和历史
        tg_text    = render_telegram(now, brief, sources)
        report     = render_full_report(now, brief, sources)
        conclusion = (brief or {}).get("headline") or "新闻检索引擎异常，本期无简报"
        sentiment  = (brief or {}).get("sentiment")
        price_snapshot = {sym: d.get("price") for sym, d in market.items()}

        if brief:
            # 失败时不覆盖上期记忆，保证下期仍能对比
            get_redis().set("marcus_memory", json.dumps({
                "time":       now,
                "conclusion": conclusion[:200],
                "sentiment":  sentiment,
                "report":     report,
                "snapshot":   price_snapshot,
                "sources":    sources,
                "outlook":    outlook_map,
            }, ensure_ascii=False))

            sb_insert({
                "analysis_time": now,
                "conclusion":    conclusion[:200],
                "report":        report,
                "snapshot":      price_snapshot,
                "sentiment":     sentiment,
                "sources":       sources,
                "outlook":       outlook_map,
            })

        # 5. 发送 Telegram
        send_telegram(tg_text)

        return (
            f"报告已发送 | {now} | 资产覆盖: {list(market.keys())} | "
            f"来源 {len(sources)} 条 | {'OK' if brief else '引擎异常'}"
        )


# ==========================================
# 5. API 路由
# ==========================================
class WatchlistBody(BaseModel):
    symbols: list[str]


@app.get("/api/memory")
def get_memory():
    try:
        data = get_redis().get("marcus_memory")
        return json.loads(data) if data else {"message": "No analysis run yet."}
    except Exception:
        log.error("get_memory 异常:\n%s", tb.format_exc())
        raise HTTPException(status_code=503, detail="Memory unavailable")


@app.get("/api/watchlist")
def get_watchlist():
    try:
        return {"watchlist": load_watchlist()}
    except Exception:
        log.error("get_watchlist 异常:\n%s", tb.format_exc())
        raise HTTPException(status_code=503, detail="Watchlist unavailable")


@app.post("/api/watchlist")
def update_watchlist(body: WatchlistBody):
    if not body.symbols:
        raise HTTPException(status_code=422, detail="symbols list cannot be empty")
    try:
        clean = [s.upper().strip() for s in body.symbols[:20]]
        get_redis().set("marcus_watchlist", json.dumps(clean))
        return {"watchlist": clean, "saved": True}
    except Exception:
        log.error("update_watchlist 异常:\n%s", tb.format_exc())
        raise HTTPException(status_code=503, detail="Failed to save watchlist")


@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str):
    try:
        # watchlist read is the only Redis call here — no caching of chart data
        if symbol not in load_watchlist():
            raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")

        url = (
            f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
            f"?range=90d&interval=1d"
        )
        res = requests.get(
            url, headers=QuantDataEngine.HEADERS, timeout=10
        ).json()
        result = res["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        opens   = quote.get("open",   [None] * len(timestamps))
        highs   = quote.get("high",   [])
        lows    = quote.get("low",    [])
        closes  = quote.get("close",  [])
        volumes = quote.get("volume", [])

        candles = []
        clean_closes = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            raw_o = opens[i] if i < len(opens) else None
            o = raw_o if raw_o is not None else c
            h = highs[i]  if i < len(highs)  else c
            l = lows[i]   if i < len(lows)   else c
            v = volumes[i] if i < len(volumes) else 0
            if None in (c, o, h, l):
                continue
            candles.append({
                "time":   ts,
                "open":   round(float(o), 4),
                "high":   round(float(h), 4),
                "low":    round(float(l), 4),
                "close":  round(float(c), 4),
                "volume": int(v or 0),
            })
            clean_closes.append(float(c))

        rsi_series = []
        for i in range(len(candles)):
            if i < 14:
                continue
            rsi_val = calculate_rsi(clean_closes[: i + 1])
            rsi_series.append({"time": candles[i]["time"], "value": rsi_val})

        return {"symbol": symbol, "candles": candles, "rsi": rsi_series}

    except HTTPException:
        raise
    except Exception:
        log.error("get_chart_data 异常 [%s]:\n%s", symbol, tb.format_exc())
        raise HTTPException(status_code=502, detail="Upstream data fetch failed")


@app.get("/api/snapshot")
def get_snapshot():
    try:
        return QuantDataEngine.fetch_and_calculate(load_watchlist())
    except Exception:
        log.error("get_snapshot 异常:\n%s", tb.format_exc())
        raise HTTPException(status_code=503, detail="Market data temporarily unavailable")


@app.get("/api/history")
def get_history(limit: int = 30):
    try:
        rows = sb_fetch_history(min(limit, 90))
        return {"history": rows}
    except Exception:
        log.error("get_history 异常:\n%s", tb.format_exc())
        raise HTTPException(status_code=503, detail="History unavailable")


@app.get("/")
def health_check():
    return {
        "status":  "Marcus Wolf Online",
        "model":   GEMINI_MODEL,
        "version": "3.0",
    }


@app.get("/api/trigger-analysis")
def trigger_analysis(secret: str = "", authorization: str = Header(default="")):
    # 支持 ?secret= 和 Vercel Cron 自动附带的 Authorization: Bearer <CRON_SECRET>
    token = secret or authorization.removeprefix("Bearer ").strip()
    if not CRON_SECRET or not hmac.compare_digest(token, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        result_msg = MarcusAgent.execute_and_send()
        return {"status": "Success", "detail": result_msg}
    except Exception:
        log.error("trigger_analysis 异常:\n%s", tb.format_exc())
        return {"status": "Failed", "error": "内部错误，请查看服务端日志。"}
