import hmac
import html
import json
import logging
import os
import re
import traceback as tb
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

from prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

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
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TG_TOKEN       = os.environ.get("TG_TOKEN")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID")
CRON_SECRET    = os.environ.get("CRON_SECRET", "")
UPSTASH_URL    = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN  = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_SERVICE_KEY", "")

TIMEZONE  = "Asia/Kuala_Lumpur"
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]
# Yahoo Finance 代码：NVDA / ^GSPC / CL=F / BTC-USD / 0700.HK / EURUSD=X
YAHOO_SYMBOL_RE = re.compile(r"\^?[A-Z0-9][A-Z0-9.\-]{0,14}(=[FX])?")

GEMINI_MODEL          = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite-preview")

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
            # 表结构未迁移（缺 sentiment/sources/outlook/brief 列）时退回旧字段
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

                meta = result.get("meta") or {}
                market_state[sym] = {
                    "name":        meta.get("shortName") or meta.get("longName"),
                    # 外汇等低价品种保留 4 位小数，否则看不出波动
                    "price":       round(latest, 2 if abs(latest) >= 10 else 4),
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
# 4. Marcus Agent：Tavily 检索 + Gemini 总结 + 发送
# ==========================================
SENTIMENT_CN  = {"RISK_ON": "偏多 Risk-on", "RISK_OFF": "避险 Risk-off", "MIXED": "分化"}
DIRECTION_ICON = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}
DIRECTION_CN   = {"BULLISH": "利好", "BEARISH": "利空", "NEUTRAL": "中性"}
CONFIDENCE_CN  = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
NO_NEWS        = "无实质消息"
IMPORTANCE_ICON = {"HIGH": "🔥", "MEDIUM": "•", "LOW": "·"}
TG_LIMIT      = 4000

# 每期固定的宏观检索主题 (标签, 关键词, 时间范围)；品种检索按 watchlist 动态生成
MACRO_QUERIES = [
    ("宏观/央行", "stock market news today Federal Reserve inflation economy", "day"),
    ("地缘/大宗", "geopolitics oil gold markets news today", "day"),
    # 日历类预告通常在周初发布，放宽到一周
    ("财报日历", "major company earnings reports this week what to expect", "week"),
    ("经济日历", "economic calendar this week Fed CPI jobs report GDP", "week"),
]
# 优先只检索主流财经媒体；某个主题在白名单内搜不到时再放开
TRUSTED_DOMAINS = [
    "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "ft.com", "apnews.com",
    "bbc.com", "cnn.com", "marketwatch.com", "barrons.com", "finance.yahoo.com",
    "investing.com", "fxstreet.com", "coindesk.com", "theblock.co", "kitco.com",
    "economist.com", "axios.com", "nikkei.com", "scmp.com",
]
# Yahoo 代码 → 检索关键词（期货/指数/外汇的代码本身搜不到新闻）
SEARCH_ALIASES = {
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^VIX": "VIX volatility",
    "NQ=F": "Nasdaq 100 futures", "ES=F": "S&P 500 futures", "CL=F": "crude oil",
    "GC=F": "gold price", "SI=F": "silver price", "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
}
TAVILY_MAX_RESULTS  = 4
NEWS_CONTENT_CHARS  = 400
RETRYABLE_STATUS    = (429, 404, 500, 503)


def load_watchlist() -> list[str]:
    return json.loads(get_redis().get("marcus_watchlist") or "null") or WATCHLIST


def search_term(sym: str, market: dict) -> str:
    if sym in SEARCH_ALIASES:
        return SEARCH_ALIASES[sym]
    name = (market.get(sym) or {}).get("name")
    if sym.endswith("=X"):
        pair = sym[:-2]
        return f"{pair[:3]}/{pair[3:]} forex" if len(pair) == 6 else f"{pair} forex"
    return f"{name} ({sym}) stock" if name else f"{sym} stock"


def build_queries(watchlist: list[str], market: dict) -> list[tuple[str, str, str]]:
    return MACRO_QUERIES + [(sym, f"{search_term(sym, market)} news", "day") for sym in watchlist]


def tavily_search(query: str, time_range: str = "day") -> list[dict]:
    def search(domains: list[str] | None) -> list[dict]:
        body = {
            "query":        query,
            "topic":        "news",
            "time_range":   time_range,
            "search_depth": "basic",
            "max_results":  TAVILY_MAX_RESULTS,
        }
        if domains:
            body["include_domains"] = domains
        res = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
            json=body,
            timeout=15,
        )
        res.raise_for_status()
        return res.json().get("results") or []

    return search(TRUSTED_DOMAINS) or search(None)


def clean_title(title: str) -> str:
    """去掉标题里混入的 HTML 注释/标签和多余空白。"""
    return re.sub(r"\s+", " ", re.sub(r"<!--.*?-->|<[^>]+>", "", title)).strip()


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def collect_news(queries: list[tuple[str, str, str]]) -> list[dict]:
    """并行检索，按 URL 去重并编号 S1..Sn。单个检索失败不影响其他检索。"""
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda q: _safe_search(*q), queries))

    sources, seen = [], set()
    for (label, _, _), items in zip(queries, results):
        for r in items:
            url = r.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append({
                "id":        f"S{len(sources) + 1}",
                "topic":     label,
                "title":     clean_title(r.get("title") or url),
                "uri":       url,
                "published": r.get("published_date") or "",
                "content":   (r.get("content") or "").strip()[:NEWS_CONTENT_CHARS],
            })
    return sources


def _safe_search(label: str, query: str, time_range: str) -> list[dict]:
    try:
        return tavily_search(query, time_range)
    except Exception as e:
        log.warning("Tavily 检索失败 [%s]: %s", label, e)
        return []


def format_news_context(sources: list[dict]) -> str:
    blocks, current = [], None
    for s in sources:
        if s["topic"] != current:
            current = s["topic"]
            blocks.append(f"\n### {current}")
        date = f" ({s['published']})" if s["published"] else ""
        blocks.append(f"[{s['id']}]{date} {s['title']}\n{s['content']}")
    return "\n".join(blocks).strip()


def call_gemini(user_prompt: str) -> tuple[dict, str]:
    """不带工具调用 Gemini（免费版可用），返回 (简报 JSON, 实际使用的模型)。
    主模型配额不足/不可用时自动切换到备用模型。"""
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "maxOutputTokens":  8192,
            "responseMimeType": "application/json",
            "responseSchema":   RESPONSE_SCHEMA,
        },
    }
    models = list(dict.fromkeys(m for m in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL) if m))
    last_err = ""
    for model in models:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_API_KEY}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=90,
        )
        res = resp.json()
        if resp.status_code in RETRYABLE_STATUS:
            last_err = f"{model}: {resp.status_code} {str(res)[:200]}"
            log.warning("Gemini 模型不可用，尝试下一个: %s", last_err)
            continue
        try:
            parts = res["candidates"][0]["content"]["parts"]
            text  = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return extract_json(text), model
        except (KeyError, IndexError, ValueError) as e:
            raise RuntimeError(f"Gemini 响应无法解析 [{model}]: {e} | {str(res)[:300]}") from e
    raise RuntimeError(f"所有 Gemini 模型都不可用: {last_err}")


def extract_json(text: str) -> dict:
    """从模型输出中取出 JSON 对象（兼容 ```json 代码块和前后多余文字）。"""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(text[start:end + 1])


def resolve_citations(brief: dict, sources: list[dict]) -> list[dict]:
    """
    把各条目引用的来源编号换成真实链接；引用不存在的编号会被丢弃。
    没有任何有效来源的要闻直接删除（视为编造）。返回被引用到的来源列表。
    """
    by_id = {s["id"]: s for s in sources}
    cited: dict[str, dict] = {}

    def links(item: dict) -> list[dict]:
        out = []
        for sid in item.get("sources") or []:
            s = by_id.get(str(sid).strip().strip("[]"))
            if s and s["id"] not in {x["id"] for x in out}:
                out.append({"id": s["id"], "title": s["title"], "uri": s["uri"],
                            "domain": domain_of(s["uri"])})
                cited[s["id"]] = out[-1]
        return out

    kept = []
    for n in brief.get("market_news") or []:
        n["links"] = links(n)
        if n["links"]:
            kept.append(n)
    brief["market_news"] = kept

    for key in ("outlook", "upcoming"):
        for item in brief.get(key) or []:
            item["links"] = links(item)

    return sorted(cited.values(), key=lambda s: int(s["id"][1:]))


def normalize_outlook(raw: list, symbols: list[str], prev: dict) -> list[dict]:
    """
    按 watchlist 顺序整理每个品种的消息面方向：丢弃不在 watchlist 的品种，
    缺失的补为中性，非法枚举值回落到 NEUTRAL/LOW，没有有效来源的利好/利空降为中性，
    「高」置信度至少需要两个不同网站的来源，否则降为「中」，并附上上期方向用于标注变化。
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
        links      = item.get("links") or []
        drivers    = item.get("drivers") or NO_NEWS
        if direction not in DIRECTION_CN or (direction != "NEUTRAL" and not links):
            direction, confidence, drivers = "NEUTRAL", "LOW", NO_NEWS
        if confidence == "HIGH" and len({l.get("domain") for l in links}) < 2:
            confidence = "MEDIUM"
        out.append({
            "symbol":        sym,
            "direction":     direction,
            "confidence":    confidence if confidence in CONFIDENCE_CN else "LOW",
            "drivers":       drivers,
            "explains_move": item.get("explains_move", ""),
            "links":         links,
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


def _tg_link(links: list[dict]) -> str:
    if not links:
        return ""
    return f' <a href="{html.escape(links[0]["uri"], quote=True)}">↗</a>'


def render_telegram(now: str, brief: dict | None, error: str = "") -> str:
    e = html.escape
    out = [f"🐺 <b>Marcus Wolf · 消息面简报</b>  <code>{e(now)}</code>", ""]

    if not brief:
        out.append(f"⚠️ <b>{e(error or '分析引擎异常')}</b>，本期简报暂不可用，请查看服务端日志。")
        return "\n".join(out)

    sentiment = SENTIMENT_CN.get(brief.get("sentiment"), brief.get("sentiment", ""))
    out += [f"🎯 <b>核心</b> [{e(sentiment)}]", e(brief.get("headline", "")), ""]

    news = brief.get("market_news") or []
    if news:
        out.append("🌍 <b>市场要闻</b>")
        for n in news:
            icon = IMPORTANCE_ICON.get(n.get("importance"), "•")
            out.append(f"{icon} <b>{e(n.get('title', ''))}</b>{_tg_link(n['links'])}")
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
            out.append(f"   {e(o['drivers'])}{_tg_link(o['links'])}")
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

    out.append("<i>↗ 为新闻原文链接 · 完整版见 Dashboard</i>")
    msg = "\n".join(out)
    if len(msg) <= TG_LIMIT:
        return msg
    # 超长时退回纯文本截断，避免截断到 HTML 标签中间
    return html.escape(html.unescape(re.sub(r"<[^>]+>", "", msg)))[:TG_LIMIT]


def render_full_report(now: str, brief: dict | None, sources: list[dict], error: str = "") -> str:
    out = [f"Marcus Wolf · 消息面完整简报 · {now}", ""]
    if not brief:
        out.append(f"【{error or '分析引擎异常'}】本期简报暂不可用。")
        return "\n".join(out)

    def refs(item: dict) -> str:
        return " " + "".join(f"[{l['id']}]" for l in item.get("links") or []) if item.get("links") else ""

    sentiment = SENTIMENT_CN.get(brief.get("sentiment"), brief.get("sentiment", ""))
    out += [f"【核心】[{sentiment}]", brief.get("headline", ""), ""]
    if brief.get("changes"):
        out += ["【相比上期】", brief["changes"], ""]

    out.append("【市场要闻】")
    for n in brief.get("market_news") or []:
        out.append(f"• [{n.get('importance', '')}] {n.get('title', '')}{refs(n)}")
        out.append(f"  {n.get('summary', '')}")
        if n.get("impact"):
            out.append(f"  影响：{n['impact']}")
    out.append("")

    out.append("【消息面方向（1-5 日）】")
    for o in brief.get("outlook") or []:
        out.append(f"• {o['symbol']} {fmt_direction(o)}：{o['drivers']}{refs(o)}")
        if o["explains_move"]:
            out.append(f"  与今日涨跌：{o['explains_move']}")
    out.append("")

    out.append("【未来 5 日事件】")
    for u in brief.get("upcoming") or []:
        out.append(f"• {u.get('date', '')} {u.get('event', '')} | {u.get('affects', '')}{refs(u)}")
        if u.get("why"):
            out.append(f"  {u['why']}")
    out.append("")

    if brief.get("watch"):
        out.append("【重点留意】")
        out += [f"• {w}" for w in brief["watch"]]
        out.append("")

    if sources:
        out.append("【来源】")
        out += [f"[{s['id']}] {s['title']}: {s['uri']}" for s in sources]

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

        # 1. 拉取行情（只用于对照新闻解释涨跌 + 生成检索关键词）
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

        # 3. Tavily 检索新闻
        news = collect_news(build_queries(watchlist, market)) if TAVILY_API_KEY else []

        # 4. Gemini 只做总结（不带搜索工具，免费版可用）
        brief: dict | None = None
        model_used = ""
        error = ""
        sources: list[dict] = []
        if not news:
            error = "新闻检索失败" if TAVILY_API_KEY else "未配置 TAVILY_API_KEY"
            log.error("%s，跳过本期分析", error)
        else:
            user_prompt = USER_PROMPT_TEMPLATE.format(
                now=now,
                timezone=TIMEZONE,
                price_context=format_price_context(market),
                last_brief=last_brief,
                news_context=format_news_context(news),
            )
            try:
                brief, model_used = call_gemini(user_prompt)
            except Exception as e:
                error = "分析引擎异常"
                log.error("Gemini 调用失败: %s", e)
        if brief:
            sources = resolve_citations(brief, news)
            brief["outlook"] = normalize_outlook(brief.get("outlook"), watchlist, prev_outlook)
        outlook_map = {o["symbol"]: o["direction"] for o in (brief or {}).get("outlook", [])}

        # 5. 生成简报 / 完整报告，写入记忆和历史
        tg_text    = render_telegram(now, brief, error)
        report     = render_full_report(now, brief, sources, error)
        conclusion = (brief or {}).get("headline") or f"{error}，本期无简报"
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
                "brief":      brief,
            }, ensure_ascii=False))

            sb_insert({
                "analysis_time": now,
                "conclusion":    conclusion[:200],
                "report":        report,
                "snapshot":      price_snapshot,
                "sentiment":     sentiment,
                "sources":       sources,
                "outlook":       outlook_map,
                "brief":         brief,
            })

        # 6. 发送 Telegram
        send_telegram(tg_text)

        return (
            f"报告已发送 | {now} | 资产覆盖: {list(market.keys())} | "
            f"检索 {len(news)} 条 / 引用 {len(sources)} 条 | "
            f"{model_used or error}"
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
    clean = list(dict.fromkeys(s.upper().strip() for s in body.symbols[:20]))
    invalid = [s for s in clean if not YAHOO_SYMBOL_RE.fullmatch(s)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid Yahoo Finance symbols: {invalid}")
    try:
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
