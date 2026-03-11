"""
Marcus Wolf — 4H Tactical Market Intelligence Agent
=====================================================
v3.1 修复：
  ✅ 彻底修复 Telegram MarkdownV2 截断问题
     → Gemini 只输出纯结构文本（JSON），代码层统一格式化 + 转义
  ✅ 保留 v3.0 全部并行优化
"""

import os
import json
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
import pytz
from fastapi import FastAPI, HTTPException, Header, Request
from upstash_redis.asyncio import Redis

# ==========================================
# 0. 日志 & 基础配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger("MarcusWolf")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TG_TOKEN       = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")
CRON_SECRET    = os.environ.get("CRON_SECRET", "")
UPSTASH_URL    = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN  = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

TIMEZONE     = "Asia/Kuala_Lumpur"
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]
INTERVAL  = "60m"
RANGE     = "60d"

app   = FastAPI(title="MarcusWolf", version="3.1")
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)


# ==========================================
# 1. 启动校验
# ==========================================
@app.on_event("startup")
async def validate_env():
    missing = [k for k, v in {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "TG_TOKEN":       TG_TOKEN,
        "TG_CHAT_ID":     TG_CHAT_ID,
        "CRON_SECRET":    CRON_SECRET,
        "UPSTASH_REDIS_REST_URL":   UPSTASH_URL,
        "UPSTASH_REDIS_REST_TOKEN": UPSTASH_TOKEN,
    }.items() if not v]
    if missing:
        raise RuntimeError(f"❌ 缺少环境变量：{missing}")
    log.info("✅ 所有环境变量已就绪")


# ==========================================
# 2. Telegram 工具
#    根本修复：代码层转义，而非依赖 Gemini 自己转义
# ==========================================
def escape_mdv2(text: str) -> str:
    """
    对"纯文本内容"转义 MarkdownV2 保留字符。
    注意：只对内容字符串调用，不要对整条消息调用，
    否则会把 *bold* 的星号也转义掉。
    """
    # MarkdownV2 需要转义的 12 个字符
    return re.sub(r"([_*\[\]()~`>#+=|{}.!\\-])", r"\\\1", text)


def build_telegram_message(report: dict, now_str: str) -> str:
    """
    从 Gemini 返回的结构化 JSON 组装 MarkdownV2 消息。
    格式化逻辑在 Python 里，Gemini 只负责内容。
    """
    lines = []

    # ── 标题 ──────────────────────────────────────────────
    lines.append(f"*🐺 Marcus Wolf 战情室*")
    lines.append(f"*📅 {escape_mdv2(now_str)}*")
    lines.append("")

    # ── 品种扫描 ──────────────────────────────────────────
    lines.append("*━━━ 品种扫描 \\(4H\\) ━━━*")
    for item in report.get("scan", []):
        sym    = escape_mdv2(item.get("symbol", ""))
        signal = escape_mdv2(item.get("signal", ""))
        action = escape_mdv2(item.get("action", ""))
        lines.append(f"• `{sym}` {signal} → {action}")
    lines.append("")

    # ── 高概率信号 ────────────────────────────────────────
    lines.append("*━━━ 🎯 高概率信号 ━━━*")
    top_signals = report.get("top_signals", [])
    if top_signals:
        for sig in top_signals:
            sym    = escape_mdv2(sig.get("symbol", ""))
            kind   = escape_mdv2(sig.get("type", ""))
            advice = escape_mdv2(sig.get("advice", ""))
            lines.append(f"• `{sym}` \\| {kind} \\| {advice}")
    else:
        lines.append("• 当前无明确高概率信号，观望")
    lines.append("")

    # ── 核心结论 ──────────────────────────────────────────
    lines.append("*━━━ 核心结论 ━━━*")
    for sentence in report.get("conclusion", []):
        lines.append(escape_mdv2(sentence))
    lines.append("")

    # ── 风险提示 ──────────────────────────────────────────
    lines.append("*━━━ ⚠️ 风险提示 ━━━*")
    for risk in report.get("risks", []):
        lines.append(f"• {escape_mdv2(risk)}")

    return "\n".join(lines)


async def send_telegram(text: str) -> bool:
    """发送 MarkdownV2 消息，失败时自动 fallback 纯文本。"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        # 尝试 MarkdownV2
        resp = await client.post(url, json={
            "chat_id":    TG_CHAT_ID,
            "text":       text,
            "parse_mode": "MarkdownV2",
        })
        data = resp.json()
        if data.get("ok"):
            return True

        log.warning(f"MarkdownV2 发送失败：{data.get('description')} — 降级纯文本")

        # fallback：去掉所有 markdown 符号
        plain = re.sub(r"[\\*_`\[\]()~>#+=|{}.!-]", "", text)
        resp2 = await client.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text":    plain[:4096],   # Telegram 单消息上限
        })
        if resp2.json().get("ok"):
            return True

        log.error(f"纯文本也失败：{resp2.text}")
        return False


# ==========================================
# 3. 量化计算引擎（与 v3.0 相同）
# ==========================================
class QuantUtils:

    @staticmethod
    def calculate_rsi(prices: list[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas   = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        avg_gain = sum(max(0.0, d) for d in deltas[:period]) / period
        avg_loss = sum(max(0.0, -d) for d in deltas[:period]) / period
        for delta in deltas[period:]:
            avg_gain = (avg_gain * (period - 1) + max(0.0,  delta)) / period
            avg_loss = (avg_loss * (period - 1) + max(0.0, -delta)) / period
        return 100.0 if avg_loss == 0 else round(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2)

    @staticmethod
    def detect_ma_trend(closes: list[float], fast: int = 20, slow: int = 50) -> str:
        if len(closes) < slow:
            return "FLAT"
        diff = (sum(closes[-fast:]) / fast - sum(closes[-slow:]) / slow) / (sum(closes[-slow:]) / slow)
        if diff > 0.003:  return "UP"
        if diff < -0.003: return "DOWN"
        return "FLAT"

    @staticmethod
    def calculate_atr_pct(highs, lows, closes, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0
        trs = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            for i in range(1, len(closes))
        ]
        return round(sum(trs[-period:]) / period / closes[-1] * 100, 3)

    @staticmethod
    def vol_ratio(volumes: list[float]) -> float:
        if len(volumes) < 2:
            return 1.0
        avg = sum(volumes[-20:]) / len(volumes[-20:])
        return round(volumes[-1] / avg, 2) if avg > 0 else 1.0

    @staticmethod
    def rsi_signal(rsi: float) -> str:
        if rsi >= 75: return "严重超买"
        if rsi >= 65: return "超买"
        if rsi <= 25: return "严重超卖"
        if rsi <= 35: return "超卖"
        return "中性"

    @staticmethod
    def vol_signal(ratio: float) -> str:
        if ratio >= 2.0:  return "放量>2x"
        if ratio >= 1.3:  return "温和放量"
        if ratio <= 0.5:  return "缩量"
        return "正常"


# ==========================================
# 4. 异步数据引擎
# ==========================================
class AsyncDataEngine:
    HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarcusWolf/3.1)"}

    @classmethod
    async def _fetch_symbol(cls, client: httpx.AsyncClient,
                            sym: str, retries: int = 2) -> tuple[str, dict]:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range={RANGE}&interval={INTERVAL}"
        for attempt in range(retries + 1):
            try:
                resp = await client.get(url, timeout=12)
                resp.raise_for_status()
                result = resp.json()["chart"]["result"][0]
                q = result["indicators"]["quote"][0]
                clean = [
                    (c, h, l, float(v or 0))
                    for c, h, l, v in zip(q["close"], q["high"], q["low"], q["volume"])
                    if None not in (c, h, l)
                ]
                if len(clean) < 2:
                    return sym, {"error": "数据不足"}
                closes, highs, lows, volumes = zip(*clean)
                closes, highs, lows, volumes = list(closes), list(highs), list(lows), list(volumes)
                latest, prev = closes[-1], closes[-2]
                vr = QuantUtils.vol_ratio(volumes)
                rsi = QuantUtils.calculate_rsi(closes)
                return sym, {
                    "price":      round(latest, 4),
                    "pct":        round((latest - prev) / prev * 100, 2),
                    "rsi":        rsi,
                    "rsi_signal": QuantUtils.rsi_signal(rsi),
                    "trend":      QuantUtils.detect_ma_trend(closes),
                    "atr_pct":    QuantUtils.calculate_atr_pct(highs, lows, closes),
                    "vol_ratio":  vr,
                    "vol_signal": QuantUtils.vol_signal(vr),
                }
            except Exception as e:
                if attempt < retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    return sym, {"error": str(e)}

    @classmethod
    async def get_market_snapshot(cls, symbols: list[str]) -> dict:
        async with httpx.AsyncClient(headers=cls.HEADERS, follow_redirects=True) as client:
            results = await asyncio.gather(*[cls._fetch_symbol(client, s) for s in symbols])
            return dict(results)


# ==========================================
# 5. Gemini 调用
#    ✅ 关键改变：要求 Gemini 返回 JSON，不要求它做任何 Markdown 转义
# ==========================================
GEMINI_SYSTEM_PROMPT = """你是 Marcus Wolf，顶级量化对冲基金首席分析师。犀利、精准、不废话。

## 输出规则（严格遵守）
1. 只返回一个合法 JSON 对象，不要加 ```json 围栏，不要任何前缀/后缀文字
2. JSON 结构如下：
{
  "scan": [
    {"symbol": "^GSPC", "signal": "RSI65超买+放量", "action": "关注回调风险"}
    // 每个 WATCHLIST 品种一条
  ],
  "top_signals": [
    {"symbol": "NVDA", "type": "趋势突破", "advice": "站稳MA20可追多，止损ATR1.5倍"}
    // 1-3条最强信号，无明确信号则返回空数组 []
  ],
  "conclusion": [
    "整体格局一句话",
    "最值得关注的机会或风险",
    "与上次分析对比变化"
  ],
  "risks": [
    "最大尾部风险描述"
  ]
}
3. 所有字符串值为纯文本，不要包含 Markdown 符号（* _ ` [ ] 等）
4. 数值保留原始精度，不要四舍五入到整数"""


async def call_gemini(snapshot: dict, memory: dict, now_str: str) -> dict:
    slim = {
        sym: {k: v for k, v in data.items() if "error" not in data}
        for sym, data in snapshot.items()
    }
    user_content = (
        f"当前时间：{now_str}\n"
        f"市场快照（4H）：{json.dumps(slim, ensure_ascii=False, separators=(',', ':'))}\n"
        f"上次结论（{memory.get('time', 'N/A')}）：{memory.get('conclusion', '首次运行')}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
        "contents":           [{"role": "user", "parts": [{"text": user_content}]}],
        "generationConfig":   {"maxOutputTokens": 2000, "temperature": 0.3, "topP": 0.9},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(GEMINI_URL, json=payload)
        resp.raise_for_status()
        raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    # ── 清理 Gemini 偶尔加的 ```json 围栏 ──────────────────
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.error(f"Gemini JSON 解析失败：{e}\n原始输出：{raw_text[:400]}")
        # 兜底结构，确保消息能正常发出
        return {
            "scan":         [],
            "top_signals":  [],
            "conclusion":   [f"AI 解析异常，请检查日志", raw_text[:200]],
            "risks":        ["无法生成风险分析"],
        }


# ==========================================
# 6. Marcus Wolf 主管线
# ==========================================
class MarcusWolf:

    @staticmethod
    async def run_pipeline() -> dict:
        now     = datetime.now(pytz.timezone(TIMEZONE))
        now_str = now.strftime("%Y-%m-%d %H:%M MYT")
        log.info(f"[{now.isoformat()}] 🚀 Marcus Wolf v3.1 启动…")

        # 并行：数据抓取 + Redis 读取
        snapshot, raw_mem = await asyncio.gather(
            AsyncDataEngine.get_market_snapshot(WATCHLIST),
            redis.get("marcus_memory_v3"),
        )
        ok_count = sum(1 for d in snapshot.values() if "error" not in d)
        log.info(f"数据质量：{ok_count}/{len(WATCHLIST)} | 历史记忆：{'有' if raw_mem else '无'}")

        memory = json.loads(raw_mem) if raw_mem else {}

        # Gemini 分析（返回结构化 JSON）
        report_json = await call_gemini(snapshot, memory, now_str)
        log.info(f"Gemini 返回结构：{list(report_json.keys())}")

        # 代码层组装 MarkdownV2（不再依赖 Gemini 转义）
        tg_message = build_telegram_message(report_json, now_str)
        log.info(f"组装消息：{len(tg_message)} 字符")

        # 提取结论用于记忆
        conclusion_text = " ".join(report_json.get("conclusion", []))[:300]
        new_memory = {
            "time":       now.isoformat(),
            "conclusion": conclusion_text,
            "snapshot_summary": {
                sym: {"trend": data.get("trend"), "rsi": data.get("rsi")}
                for sym, data in snapshot.items()
                if "error" not in data
            },
        }

        # 并行：Redis 写入 + Telegram 推送
        _, success = await asyncio.gather(
            redis.set("marcus_memory_v3", json.dumps(new_memory, ensure_ascii=False)),
            send_telegram(tg_message),
        )
        log.info(f"推送{'成功' if success else '失败（已降级）'}")

        return {
            "status":        "ok" if success else "degraded",
            "symbols":       ok_count,
            "report_length": len(tg_message),
            "timestamp":     now_str,
        }


# ==========================================
# 7. FastAPI 路由
# ==========================================
@app.get("/health")
async def health():
    try:
        await redis.ping()
        redis_ok = True
    except Exception as e:
        redis_ok = False
        log.warning(f"Redis ping 失败：{e}")
    return {
        "status":    "ok" if redis_ok else "degraded",
        "redis":     redis_ok,
        "version":   "3.1",
        "timestamp": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
    }


@app.api_route("/api/trigger", methods=["GET", "POST"])
async def handle_trigger(request: Request):
    received = request.headers.get("Authorization", "")
    expected = f"Bearer {CRON_SECRET}"
    if received != expected:
        masked = f"{CRON_SECRET[:3]}***" if CRON_SECRET else "None"
        return {
            "error":    "认证失败",
            "received": received,
            "expected": f"Bearer {masked}...",
            "tip":      "检查 Authorization header 格式是否为 'Bearer <secret>'",
        }
    return await MarcusWolf.run_pipeline()


@app.get("/api/snapshot")
async def get_snapshot(x_cron_secret: Optional[str] = Header(None)):
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    snapshot = await AsyncDataEngine.get_market_snapshot(WATCHLIST)
    return {"data": snapshot, "interval": INTERVAL, "range": RANGE}
