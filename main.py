import hmac
import html
import json
import logging
import os
import re
import traceback as tb
from datetime import datetime

from prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from signals import (
    MAX_SIGNALS_PER_RUN,
    OPEN_STATUSES,
    compute_stats,
    evaluate_signal,
    new_signal_record,
    validate_signal,
)

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
MAX_STORED_SIGNALS = 300

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
            # 表结构未迁移（缺 regime/signals 列）时退回旧字段
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


def calculate_ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k   = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def classic_pivots(high: float, low: float, close: float) -> dict:
    p = (high + low + close) / 3
    return {
        "pivot": p,
        "R1":    2 * p - low,
        "S1":    2 * p - high,
        "R2":    p + (high - low),
        "S2":    p - (high - low),
    }


def last_bar_complete(meta: dict, now_ts: int) -> bool:
    """日线最后一根是否已收盘。盘中（含 24/7 的加密货币）返回 False。"""
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = regular.get("start"), regular.get("end")
    if start is None or end is None:
        return False
    return now_ts >= end or now_ts < start


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
    def fetch_bars(sym: str, range_: str, interval: str) -> tuple[dict, list[dict]]:
        """拉取 Yahoo K 线，返回 (meta, bars)。缺 close/high/low 的 K 线被丢弃。"""
        url = (
            f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
            f"?range={range_}&interval={interval}"
        )
        res = requests.get(
            url,
            headers=QuantDataEngine.HEADERS,
            timeout=QuantDataEngine.REQUEST_TIMEOUT,
        ).json()
        result = res["chart"]["result"][0]
        quote  = result["indicators"]["quote"][0]
        timestamps = result.get("timestamp") or []

        def col(name):
            vals = quote.get(name) or []
            return vals + [None] * (len(timestamps) - len(vals))

        bars = []
        for ts, o, h, l, c, v in zip(
            timestamps, col("open"), col("high"), col("low"), col("close"), col("volume")
        ):
            if None in (h, l, c):
                continue
            bars.append({
                "time":   ts,
                "open":   o if o is not None else c,
                "high":   h,
                "low":    l,
                "close":  c,
                "volume": v or 0,
            })
        return result.get("meta") or {}, bars

    @staticmethod
    def daily_metrics(meta: dict, bars: list[dict], now_ts: int) -> dict | None:
        if len(bars) < 2:
            return None
        closes  = [b["close"]  for b in bars]
        highs   = [b["high"]   for b in bars]
        lows    = [b["low"]    for b in bars]
        volumes = [b["volume"] for b in bars]

        latest, prev = closes[-1], closes[-2]
        pct_change   = (latest - prev) / prev * 100
        ret_5d       = (latest - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else None

        sma200 = sum(closes[-200:]) / min(200, len(closes))
        sma50  = sum(closes[-50:])  / min(50,  len(closes))
        sma20  = sum(closes[-20:])  / min(20,  len(closes))
        atr_14 = calculate_atr(highs, lows, closes)

        # 成交量为 0（指数/VIX 等）时量比无意义
        avg_vol20 = sum(volumes[-20:]) / min(20, len(volumes))
        vol_ratio = round(volumes[-1] / avg_vol20, 2) if avg_vol20 and volumes[-1] else None

        # 枢轴价位用上一根已完成的日线
        ref = bars[-1] if last_bar_complete(meta, now_ts) else bars[-2]
        pivots = classic_pivots(ref["high"], ref["low"], ref["close"])

        swing_high = max(highs[-20:])
        swing_low  = min(lows[-20:])

        def r(x):
            return round(x, 4) if x is not None else None

        return {
            "price":         round(latest, 2),
            "pct_change":    round(pct_change, 2),
            "ret_5d":        round(ret_5d, 2) if ret_5d is not None else None,
            "RSI_14":        calculate_rsi(closes),
            "above_MA200":   latest > sma200,
            "above_MA50":    latest > sma50,
            "MA20":          r(sma20),
            "MA50":          r(sma50),
            "ma_trend":      detect_ma_trend(closes),
            "vol_ratio":     vol_ratio,
            "ATR_14":        atr_14,
            "ATR_pct":       round(atr_14 / latest * 100, 2) if latest else None,
            **{k: r(v) for k, v in pivots.items()},
            "swing_high_20": r(swing_high),
            "swing_low_20":  r(swing_low),
            "dist_high_atr": round((swing_high - latest) / atr_14, 2) if atr_14 else None,
            "dist_low_atr":  round((latest - swing_low) / atr_14, 2) if atr_14 else None,
        }

    @staticmethod
    def hourly_metrics(bars: list[dict]) -> dict:
        closes = [b["close"] for b in bars]
        ema20  = calculate_ema(closes, 20)
        ema50  = calculate_ema(closes, 50)
        trend  = "FLAT"
        if ema20 is not None and ema50 is not None and ema50:
            diff = (ema20 - ema50) / ema50 * 100
            trend = "UP" if diff > 0.15 else "DOWN" if diff < -0.15 else "FLAT"
        return {
            "h1_trend": trend,
            "h1_rsi":   calculate_rsi(closes) if len(closes) > 15 else None,
            "h1_ema20": round(ema20, 4) if ema20 is not None else None,
        }

    @staticmethod
    def fetch_full(
        symbols: list[str], intraday: bool = False, extra_hourly: list[str] = ()
    ) -> tuple[dict, dict]:
        """
        返回 (market_state, hourly_bars)。
        intraday=True 时额外拉取 1 个月小时线（用于 h1 指标和信号结算）；
        extra_hourly 是只需要小时线、不在 watchlist 里的品种（有未结算信号）。
        """
        now_ts = int(datetime.now(pytz.utc).timestamp())
        market_state: dict[str, dict] = {}
        hourly: dict[str, list[dict]] = {}

        for sym in symbols:
            try:
                meta, bars = QuantDataEngine.fetch_bars(sym, "250d", "1d")
                metrics = QuantDataEngine.daily_metrics(meta, bars, now_ts)
                if metrics is None:
                    continue
                market_state[sym] = metrics
            except Exception as e:
                log.warning("[QuantDataEngine] 跳过 %s: %s", sym, e)

        if intraday:
            for sym in list(market_state) + [s for s in extra_hourly if s not in market_state]:
                try:
                    _, h1 = QuantDataEngine.fetch_bars(sym, "1mo", "1h")
                    hourly[sym] = h1
                    if sym in market_state:
                        market_state[sym].update(QuantDataEngine.hourly_metrics(h1))
                except Exception as e:
                    log.warning("[QuantDataEngine] 小时线失败 %s: %s", sym, e)

        return market_state, hourly

    @staticmethod
    def fetch_and_calculate(symbols: list[str]) -> dict:
        return QuantDataEngine.fetch_full(symbols)[0]


# ==========================================
# 4. Marcus Agent：分析 + 结算 + 发送
# ==========================================
DIRECTION_CN  = {"LONG": "做多", "SHORT": "做空"}
CONFIDENCE_CN = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
STATUS_CN = {
    "PENDING":       "⏳ 待触发",
    "OPEN":          "🔵 持仓中",
    "WIN":           "✅ 止盈",
    "LOSS":          "❌ 止损",
    "EXPIRED":       "⌛ 到期平仓",
    "NOT_TRIGGERED": "⚪ 未触发",
}
TG_LIMIT = 4000


def load_watchlist() -> list[str]:
    return json.loads(get_redis().get("marcus_watchlist") or "null") or WATCHLIST


def load_signals() -> list[dict]:
    raw = get_redis().get("marcus_signals")
    return json.loads(raw) if raw else []


def save_signals(signals: list[dict]) -> None:
    get_redis().set("marcus_signals", json.dumps(signals[-MAX_STORED_SIGNALS:], ensure_ascii=False))


def fmt_signal(s: dict) -> str:
    return (
        f"{s['symbol']} {DIRECTION_CN[s['direction']]} | 入场 {s['entry']:g} | "
        f"止损 {s['stop']:g} | 目标 {s['target']:g} | R:R {s['rr']} | "
        f"{s['horizon_days']}天 | 置信{CONFIDENCE_CN[s['confidence']]}"
    )


def fmt_settled(s: dict) -> str:
    r = f" {s['r_multiple']:+.2f}R" if s.get("r_multiple") is not None else ""
    return f"{STATUS_CN[s['status']]} {s['symbol']} {DIRECTION_CN[s['direction']]} @ {s['entry']:g}{r}"


def fmt_stats(stats: dict) -> str:
    if not stats["closed"]:
        return f"暂无已结算信号（进行中 {stats['open']}，未触发 {stats['not_triggered']}）"
    line = (
        f"已结算 {stats['closed']} 笔 | 胜率 {stats['win_rate']}% | "
        f"平均 {stats['avg_r']:+.2f}R | 累计 {stats['total_r']:+.2f}R | "
        f"进行中 {stats['open']} | 未触发 {stats['not_triggered']}"
    )
    parts = [
        f"{CONFIDENCE_CN[c]}: {v['n']}笔 胜率{v['win_rate']}% {v['avg_r']:+.2f}R"
        for c, v in stats["by_confidence"].items()
    ]
    return line + ("\n按置信度 → " + "；".join(parts) if parts else "")


def call_gemini(user_prompt: str) -> dict:
    gemini_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature":      0.3,
            "maxOutputTokens":  8192,
            "responseMimeType": "application/json",
            "responseSchema":   RESPONSE_SCHEMA,
        },
    }
    res = requests.post(
        gemini_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=60,
    ).json()
    try:
        parts = res["candidates"][0]["content"]["parts"]
        text  = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return json.loads(text)
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(f"Gemini 响应无法解析: {e} | {str(res)[:300]}") from e


def render_telegram(now, analysis, new_sigs, settled, open_sigs, stats, rejected) -> str:
    e = html.escape
    out = [f"🐺 <b>Marcus Wolf · 短线简报</b>  <code>{e(now)}</code>", ""]

    if analysis:
        out += [f"🎯 <b>核心结论</b> [{e(analysis.get('regime', ''))}]",
                e(analysis.get("conclusion", "")), ""]
    else:
        out += ["⚠️ <b>分析引擎异常</b>，本期无新信号。以下为信号结算。", ""]

    out.append("⚡ <b>本期信号</b>")
    if new_sigs:
        for s in new_sigs:
            out.append(f"• <b>{e(fmt_signal(s))}</b>")
            out.append(f"  理由：{e(s['rationale'])}")
            if s["invalidation"]:
                out.append(f"  作废：{e(s['invalidation'])}")
    else:
        out.append("信号不足，观望")
    if rejected:
        out.append(f"<i>（代码风控剔除 {len(rejected)} 个不合格信号，详见网页）</i>")
    out.append("")

    if settled or open_sigs:
        out.append("📋 <b>信号跟踪</b>")
        out += [e(fmt_settled(s)) for s in settled]
        out += [e(fmt_settled(s)) for s in open_sigs]
        out.append("")

    out += ["📈 <b>战绩</b>", e(fmt_stats(stats)), ""]

    if analysis:
        out.append(f"⚠️ <b>最大不确定因子</b>：{e(analysis.get('risk', ''))}")
        out.append("")
    out.append("<i>完整分析见 Dashboard</i>")

    msg = "\n".join(out)
    return msg if len(msg) <= TG_LIMIT else msg[:TG_LIMIT - 20] + "\n…（已截断）"


def render_full_report(now, analysis, new_sigs, settled, open_sigs, stats, rejected) -> str:
    out = [f"Marcus Wolf · 短线完整分析 · {now}", ""]

    if analysis:
        out += [f"【核心结论】[{analysis.get('regime', '')}]", analysis.get("conclusion", ""), ""]
        out.append("【逐品种技术面】")
        for a in analysis.get("assets", []):
            out.append(f"• {a.get('symbol')} [{a.get('bias')}] {a.get('note', '')}")
            if a.get("levels"):
                out.append(f"  关键价位：{a['levels']}")
        out.append("")
    else:
        out += ["【分析引擎异常】本期无新信号。", ""]

    out.append("【本期信号】")
    if new_sigs:
        for s in new_sigs:
            out.append(f"• {fmt_signal(s)}")
            out.append(f"  止损 = {s['stop_atr']} ATR | 理由：{s['rationale']}")
            if s["invalidation"]:
                out.append(f"  作废条件：{s['invalidation']}")
    else:
        out.append("信号不足，观望")
    out.append("")

    if rejected:
        out.append("【风控剔除】")
        out += [f"• {r}" for r in rejected]
        out.append("")

    out.append("【信号跟踪】")
    if settled or open_sigs:
        out += [f"• {fmt_settled(s)}" for s in settled + open_sigs]
    else:
        out.append("无")
    out.append("")

    out += ["【战绩】", fmt_stats(stats), ""]

    if analysis:
        out += ["【复盘】", analysis.get("review", ""), "",
                "【最大不确定因子】", analysis.get("risk", "")]

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
        tz      = pytz.timezone(TIMEZONE)
        now_dt  = datetime.now(tz)
        now     = now_dt.strftime("%Y-%m-%d %H:%M")
        now_ts  = int(now_dt.timestamp())

        # 1. 读取 watchlist 和历史信号，拉取日线 + 小时线
        watchlist  = load_watchlist()
        signals    = load_signals()
        open_syms  = sorted({s["symbol"] for s in signals if s["status"] in OPEN_STATUSES})
        market, hourly = QuantDataEngine.fetch_full(watchlist, intraday=True, extra_hourly=open_syms)

        # 2. 用小时线客观结算未完成的信号
        settled: list[dict] = []
        for i, s in enumerate(signals):
            if s["status"] not in OPEN_STATUSES or s["symbol"] not in hourly:
                continue
            updated = evaluate_signal(s, hourly[s["symbol"]], now_ts)
            if updated["status"] not in OPEN_STATUSES:
                settled.append(updated)
            signals[i] = updated
        open_sigs = [s for s in signals if s["status"] in OPEN_STATUSES]
        stats     = compute_stats(signals)

        # 3. 构造 Prompt
        signal_review = "\n".join(
            [f"本期结算：{fmt_settled(s)}" for s in settled]
            + [f"进行中：{fmt_settled(s)}（{fmt_signal(s)}）" for s in open_sigs]
        ) or "无"
        user_prompt = USER_PROMPT_TEMPLATE.format(
            current_data=json.dumps(market, indent=2, ensure_ascii=False),
            track_record=fmt_stats(stats),
            signal_review=signal_review,
        )

        # 4. 调用 Gemini → 代码风控校验信号
        analysis: dict | None = None
        try:
            analysis = call_gemini(user_prompt)
        except Exception as e:
            log.error("Gemini 调用失败: %s", e)

        new_sigs: list[dict] = []
        rejected: list[str]  = []
        busy = {s["symbol"] for s in open_sigs}
        for raw in (analysis or {}).get("signals", []):
            sig, reason = validate_signal(raw, market)
            if sig is None:
                rejected.append(reason)
            elif sig["symbol"] in busy:
                rejected.append(f"{sig['symbol']}: 已有进行中信号")
            elif len(new_sigs) >= MAX_SIGNALS_PER_RUN:
                rejected.append(f"{sig['symbol']}: 超过每期 {MAX_SIGNALS_PER_RUN} 个上限")
            else:
                busy.add(sig["symbol"])
                new_sigs.append(new_signal_record(sig, now_dt))
        if rejected:
            log.info("风控剔除信号: %s", rejected)

        signals += new_sigs
        save_signals(signals)
        stats = compute_stats(signals)

        # 5. 生成简报 / 完整报告，写入记忆和历史
        args     = (now, analysis, new_sigs, settled, open_sigs, stats, rejected)
        brief    = render_telegram(*args)
        report   = render_full_report(*args)
        conclusion = (analysis or {}).get("conclusion") or "分析引擎异常，本期无新信号"
        price_snapshot = {sym: d.get("price") for sym, d in market.items()}

        memory_payload = {
            "time":       now,
            "conclusion": conclusion[:200],
            "regime":     (analysis or {}).get("regime"),
            "report":     report,
            "brief":      brief,
            "snapshot":   price_snapshot,
            "signals":    new_sigs,
            "stats":      stats,
        }
        get_redis().set("marcus_memory", json.dumps(memory_payload, ensure_ascii=False))

        sb_insert({
            "analysis_time": now,
            "conclusion":    conclusion[:200],
            "report":        report,
            "snapshot":      price_snapshot,
            "regime":        memory_payload["regime"],
            "signals":       new_sigs,
        })

        # 6. 发送 Telegram
        send_telegram(brief)

        return (
            f"报告已发送 | {now} | 资产覆盖: {list(market.keys())} | "
            f"新信号 {len(new_sigs)} | 结算 {len(settled)} | 剔除 {len(rejected)}"
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


@app.get("/api/signals")
def get_signals(limit: int = 50):
    try:
        signals = load_signals()
        return {
            "signals": list(reversed(signals))[: min(limit, MAX_STORED_SIGNALS)],
            "stats":   compute_stats(signals),
        }
    except Exception:
        log.error("get_signals 异常:\n%s", tb.format_exc())
        raise HTTPException(status_code=503, detail="Signals unavailable")


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
def trigger_analysis(secret: str = ""):
    if not hmac.compare_digest(secret, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        result_msg = MarcusAgent.execute_and_send()
        return {"status": "Success", "detail": result_msg}
    except Exception:
        log.error("trigger_analysis 异常:\n%s", tb.format_exc())
        return {"status": "Failed", "error": "内部错误，请查看服务端日志。"}
