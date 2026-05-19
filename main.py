import hmac
import json
import logging
import os
import traceback as tb
from datetime import datetime

from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

import pytz
import requests
from fastapi import FastAPI, HTTPException
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

GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

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
    """平均真实波幅（ATR），衡量近期波动率。"""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        )
        trs.append(tr)
    recent = trs[-period:]
    return round(sum(recent) / len(recent), 4)


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

                raw_rows = zip(
                    quote.get("close",  []),
                    quote.get("high",   []),
                    quote.get("low",    []),
                    quote.get("volume", []),
                )
                clean = [
                    (c, h, l, v)
                    for c, h, l, v in raw_rows
                    if None not in (c, h, l, v)
                ]
                if len(clean) < 2:
                    continue

                closes  = [r[0] for r in clean]
                highs   = [r[1] for r in clean]
                lows    = [r[2] for r in clean]
                volumes = [r[3] for r in clean]

                latest, prev = closes[-1], closes[-2]
                pct_change   = (latest - prev) / prev * 100

                sma200   = sum(closes[-200:]) / min(200, len(closes))
                sma50    = sum(closes[-50:])  / min(50,  len(closes))
                rsi_14   = calculate_rsi(closes)
                ma_trend = detect_ma_trend(closes)
                atr_14   = calculate_atr(highs, lows, closes)

                avg_vol20 = sum(volumes[-20:]) / min(20, len(volumes))
                vol_ratio = round(volumes[-1] / avg_vol20, 2) if avg_vol20 else 1.0

                market_state[sym] = {
                    "price":       round(latest, 2),
                    "pct_change":  round(pct_change, 2),
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
# 4. Marcus Agent：分析 + 发送
# ==========================================
class MarcusAgent:

    @staticmethod
    def execute_and_send() -> str:
        # 1. 拉取量化数据，过滤掉拉取失败的品种
        raw_data = QuantDataEngine.fetch_and_calculate(WATCHLIST)
        current_data_dict = {k: v for k, v in raw_data.items() if "error" not in v}
        current_data_json = json.dumps(current_data_dict, indent=2, ensure_ascii=False)

        # 2. 读取历史记忆
        last_data = get_redis().get("marcus_memory")
        last_mem  = json.loads(last_data) if last_data else None
        if last_mem:
            history_context = (
                f"时间：{last_mem.get('time', 'N/A')}\n"
                f"结论：{last_mem.get('conclusion', 'N/A')}\n"
                f"摘要：{last_mem.get('report', 'N/A')}"
            )
        else:
            history_context = "无历史记录（首次运行）。"

        # 3. 构造 Prompt
        user_prompt = USER_PROMPT_TEMPLATE.format(
            current_data=current_data_json,
            history_context=history_context,
        )

        # 4. 调用 Gemini
        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024},
        }

        gemini_res: dict = {}
        try:
            gemini_res = requests.post(
                gemini_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            ).json()
            report = gemini_res["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, requests.RequestException) as e:
            log.error("Gemini 调用失败: %s | 响应: %s", e, str(gemini_res)[:300])
            report = "⚠️ *Marcus Wolf 分析引擎异常*\n`分析暂时不可用，请稍后重试。`"

        # 5. 更新结构化记忆
        tz  = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        conclusion = next(
            (line.strip() for line in report.splitlines() if line.strip()),
            report[:80]
        )
        price_snapshot = {
            sym: data.get("price")
            for sym, data in current_data_dict.items()
        }
        memory_payload = {
            "time":       now,
            "conclusion": conclusion[:120],
            "report":     report,
            "snapshot":   price_snapshot,
        }
        get_redis().set("marcus_memory", json.dumps(memory_payload, ensure_ascii=False))

        # 5b. 写入 Supabase 历史存档
        sb_insert({
            "analysis_time": now,
            "conclusion":    conclusion[:120],
            "report":        report,
            "snapshot":      price_snapshot,
        })

        # 6. 发送 Telegram（启用 MarkdownV2，失败时 fallback 纯文本）
        tg_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        tg_res = requests.post(
            tg_url,
            json={
                "chat_id":                  TG_CHAT_ID,
                "text":                     report,
                "parse_mode":               "MarkdownV2",
                "disable_web_page_preview": True,
            },
            timeout=10,
        ).json()

        if not tg_res.get("ok"):
            fallback = requests.post(
                tg_url,
                json={
                    "chat_id":                  TG_CHAT_ID,
                    "text":                     report,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            ).json()
            if not fallback.get("ok"):
                log.error("Telegram 发送彻底失败: %s", fallback)

        return f"报告已发送 | {now} | 资产覆盖: {list(current_data_dict.keys())}"


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
        saved = get_redis().get("marcus_watchlist")
        return {"watchlist": json.loads(saved) if saved else WATCHLIST}
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
        watchlist = json.loads(get_redis().get("marcus_watchlist") or "null") or WATCHLIST
        if symbol not in watchlist:
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
        watchlist = json.loads(get_redis().get("marcus_watchlist") or "null") or WATCHLIST
        data = QuantDataEngine.fetch_and_calculate(watchlist)
        return data
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
        "version": "2.0",
    }


@app.get("/api/trigger-analysis")
def trigger_analysis(secret: str = ""):
    if not hmac.compare_digest(secret, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        result_msg = MarcusAgent.execute_and_send()
        return {"status": "Success", "detail": result_msg}
    except Exception:
        log.error("trigger_analysis 异常:\n%s", tb.format_exc())
        return {"status": "Failed", "error": "内部错误，请查看服务端日志。"}
