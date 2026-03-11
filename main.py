"""
Marcus Wolf — 4H Tactical Market Intelligence Agent
=====================================================
优化版 v3.0：
  ✅ 仅保留战术透镜 (4H) — 去掉 1D，Yahoo 请求减半
  ✅ 数据抓取 + Redis 读取完全并行（方案B）
  ✅ Prompt 精简，max_tokens 1024 → 更快生成
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
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

# ✅ 只保留 4H（Yahoo 60m interval，60d range ≈ 60 根 4H K线）
# 请求数：7 个品种 × 1 个时间框架 = 7 次（原来 14 次）
INTERVAL = "60m"
RANGE    = "60d"
TF_LABEL = "战术透镜 (4H)"

app   = FastAPI(title="MarcusWolf", version="3.0")
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)


# ==========================================
# 1. 启动校验
# ==========================================
@app.on_event("startup")
async def validate_env():
    required = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "TG_TOKEN": TG_TOKEN,
        "TG_CHAT_ID": TG_CHAT_ID,
        "CRON_SECRET": CRON_SECRET,
        "UPSTASH_REDIS_REST_URL": UPSTASH_URL,
        "UPSTASH_REDIS_REST_TOKEN": UPSTASH_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"❌ 缺少环境变量：{missing}")
    log.info("✅ 所有环境变量已就绪")


# ==========================================
# 2. Telegram 工具
# ==========================================
def escape_md_v2(text: str) -> str:
    reserved = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(reserved)}])", r"\\\1", text)


async def send_telegram(text: str, parse_mode: str = "MarkdownV2") -> bool:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
        })
        if r.status_code == 200:
            return True

        log.warning(f"TG {parse_mode} 发送失败 ({r.status_code})，降级为纯文本…")
        plain = re.sub(r"[_*`\[\]()~>#+=|{}.!\\-]", "", text)
        r2 = await client.post(url, json={"chat_id": TG_CHAT_ID, "text": plain})
        if r2.status_code == 200:
            return True

        log.error(f"TG 纯文本也失败：{r2.text}")
        return False


# ==========================================
# 3. 量化计算引擎
# ==========================================
class QuantUtils:

    @staticmethod
    def calculate_rsi(prices: list[float], period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains  = [max(0.0, d) for d in deltas[:period]]
        losses = [max(0.0, -d) for d in deltas[:period]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        for delta in deltas[period:]:
            avg_gain = (avg_gain * (period - 1) + max(0.0, delta))  / period
            avg_loss = (avg_loss * (period - 1) + max(0.0, -delta)) / period
        if avg_loss == 0:
            return 100.0
        return round(100.0 - 100.0 / (1.0 + avg_gain / avg_loss), 2)

    @staticmethod
    def detect_ma_trend(closes: list[float], fast: int = 20, slow: int = 50) -> str:
        if len(closes) < slow:
            return "FLAT"
        ma_f = sum(closes[-fast:]) / fast
        ma_s = sum(closes[-slow:]) / slow
        diff = (ma_f - ma_s) / ma_s
        if diff > 0.003:   return "UP"
        if diff < -0.003:  return "DOWN"
        return "FLAT"

    @staticmethod
    def calculate_atr(highs: list[float], lows: list[float],
                      closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i]  - closes[i - 1])
            )
            trs.append(tr)
        atr = sum(trs[-period:]) / period
        return round(atr / closes[-1] * 100, 3)

    @staticmethod
    def safe_vol_ratio(volumes: list[float]) -> float:
        if not volumes or len(volumes) < 2:
            return 1.0
        avg = sum(volumes[-20:]) / len(volumes[-20:])
        return round(volumes[-1] / avg, 2) if avg > 0 else 1.0

    @staticmethod
    def get_rsi_signal(rsi: float) -> str:
        if rsi >= 75: return "严重超买"
        if rsi >= 65: return "超买"
        if rsi <= 25: return "严重超卖"
        if rsi <= 35: return "超卖"
        return "中性"

    @staticmethod
    def classify_vol_ratio(ratio: float) -> str:
        if ratio >= 2.0:  return "放量(>2x)"
        if ratio >= 1.3:  return "温和放量"
        if ratio <= 0.5:  return "缩量"
        return "正常"


# ==========================================
# 4. 异步数据引擎（纯 4H）
# ==========================================
class AsyncDataEngine:

    @staticmethod
    async def _fetch_raw(client: httpx.AsyncClient, sym: str) -> list[dict]:
        url = (
            f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
            f"?range={RANGE}&interval={INTERVAL}"
        )
        resp = await client.get(url, timeout=12)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        q = result["indicators"]["quote"][0]
        return [
            {"c": c, "h": h, "l": l, "v": float(v or 0)}
            for c, h, l, v in zip(q["close"], q["high"], q["low"], q["volume"])
            if c is not None and h is not None and l is not None
        ]

    @staticmethod
    def _compute_metrics(bars: list[dict]) -> dict:
        if len(bars) < 2:
            return {"error": "数据不足"}
        closes  = [b["c"] for b in bars]
        highs   = [b["h"] for b in bars]
        lows    = [b["l"] for b in bars]
        volumes = [b["v"] for b in bars]
        latest, prev = closes[-1], closes[-2]
        pct_change   = round((latest - prev) / prev * 100, 2)
        rsi          = QuantUtils.calculate_rsi(closes)
        trend        = QuantUtils.detect_ma_trend(closes)
        atr_pct      = QuantUtils.calculate_atr(highs, lows, closes)
        vol_ratio    = QuantUtils.safe_vol_ratio(volumes)
        return {
            "price":      round(latest, 4),
            "pct":        pct_change,
            "rsi":        rsi,
            "rsi_signal": QuantUtils.get_rsi_signal(rsi),
            "trend":      trend,
            "atr_pct":    atr_pct,
            "vol_ratio":  vol_ratio,
            "vol_signal": QuantUtils.classify_vol_ratio(vol_ratio),
        }

    @classmethod
    async def _fetch_symbol(cls, client: httpx.AsyncClient,
                            sym: str, retries: int = 2) -> tuple[str, dict]:
        last_err = None
        for attempt in range(retries + 1):
            try:
                bars = await cls._fetch_raw(client, sym)
                return sym, cls._compute_metrics(bars)
            except Exception as e:
                last_err = e
                if attempt < retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
        return sym, {"error": str(last_err)}

    @classmethod
    async def get_market_snapshot(cls, symbols: list[str]) -> dict:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarcusWolf/3.0)"},
            follow_redirects=True,
        ) as client:
            tasks = [cls._fetch_symbol(client, s) for s in symbols]
            results = await asyncio.gather(*tasks)
            return dict(results)


# ==========================================
# 5. Gemini AI 调用
# ==========================================
async def call_gemini(prompt: str, max_tokens: int = 1024) -> str:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,   # ✅ 1024，比原来少一半
            "temperature": 0.65,
            "topP": 0.9,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(GEMINI_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# ==========================================
# 6. Prompt 构造器（精简版，纯 4H）
# ==========================================
def build_prompt(snapshot: dict, memory: dict) -> str:
    # ✅ 只传关键字段，裁掉冗余，节省 input token
    slim_snapshot = {
        sym: {k: v for k, v in data.items()
              if k in ("price", "pct", "rsi", "rsi_signal", "trend", "atr_pct", "vol_ratio", "vol_signal")}
        for sym, data in snapshot.items()
        if "error" not in data
    }
    snapshot_str = json.dumps(slim_snapshot, ensure_ascii=False, separators=(",", ":"))
    memory_str   = memory.get("conclusion", "暂无历史记录")
    last_time    = memory.get("time", "N/A")
    now_str      = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M MYT")

    return f"""你是 Marcus Wolf——顶级量化对冲基金首席分析师。犀利、精准、不废话。

📊 4H 市场快照（{now_str}）
{snapshot_str}

字段：price=价格 pct=涨跌% rsi/rsi_signal=RSI trend=MA趋势(UP/DOWN/FLAT) atr_pct=波动率% vol_ratio/vol_signal=量比

🧠 上次结论（{last_time}）：{memory_str}

━━━ 输出格式（Telegram MarkdownV2，严格遵守）━━━
- 标题用 *粗体*，关键数值用 `代码格式`
- 不用 # 标题，不用 HTML，特殊字符加反斜杠转义
- 每个品种不超过 2 行

*🐺 Marcus Wolf 战情室*
*📅 {now_str}*

*━━━ 品种扫描 \(4H\) ━━━*
[每个品种：趋势+RSI信号+成交量，一句话点出操作意义]

*━━━ 🎯 高概率信号 ━━━*
[列出 1\-3 个最强信号：品种 \| 信号类型 \| 操作建议]

*━━━ 核心结论 ━━━*
[3句话：整体格局 \+ 最值得关注的机会/风险 \+ 与上次对比变化]

*━━━ ⚠️ 风险提示 ━━━*
[1\-2句，指出最大尾部风险]

开始分析。
"""


# ==========================================
# 7. Marcus Wolf 主管线（并行优化版）
# ==========================================
class MarcusWolf:

    @staticmethod
    async def run_pipeline() -> dict:
        now = datetime.now(pytz.timezone(TIMEZONE))
        log.info(f"[{now.isoformat()}] 🚀 启动 Marcus Wolf v3.0…")

        # ✅ 方案B：数据抓取 + Redis 读取 同时并行启动
        log.info("📡 并行启动：市场数据抓取 + Redis 记忆读取…")
        snapshot, raw_mem = await asyncio.gather(
            AsyncDataEngine.get_market_snapshot(WATCHLIST),
            redis.get("marcus_memory_v3"),
        )

        ok_count = sum(1 for d in snapshot.values() if "error" not in d)
        log.info(f"   数据质量：{ok_count}/{len(WATCHLIST)} 个品种成功")

        memory = json.loads(raw_mem) if raw_mem else {}
        log.info(f"   历史记忆：{'有' if memory else '无（首次运行）'}")

        # ── Gemini 分析 ──────────────────────────────────────
        prompt = build_prompt(snapshot, memory)
        log.info("🤖 调用 Gemini（4H 战术分析）…")
        report = await call_gemini(prompt, max_tokens=1024)
        log.info(f"   生成报告：{len(report)} 字符")

        # ── 提取结论 + 持久化记忆 ────────────────────────────
        conclusion_match = re.search(r"核心结论[^\n]*\n(.*?)(?=━|$)", report, re.DOTALL)
        conclusion_text  = conclusion_match.group(1).strip()[:300] if conclusion_match else report[:300]

        new_memory = {
            "time":       now.isoformat(),
            "conclusion": conclusion_text,
            "snapshot_summary": {
                sym: {"trend": data.get("trend"), "rsi": data.get("rsi")}
                for sym, data in snapshot.items()
                if "error" not in data
            }
        }

        # ✅ Redis 写入 + Telegram 推送 同时并行
        log.info("💾📨 并行：Redis 写入 + Telegram 推送…")
        save_task = redis.set("marcus_memory_v3", json.dumps(new_memory, ensure_ascii=False))
        send_task = send_telegram(report, parse_mode="MarkdownV2")
        _, success = await asyncio.gather(save_task, send_task)

        log.info(f"   推送{'成功' if success else '失败（已降级）'}")

        return {
            "status":        "ok" if success else "degraded",
            "symbols":       len(WATCHLIST),
            "timeframe":     "4H only",
            "report_length": len(report),
            "timestamp":     now.isoformat(),
        }


# ==========================================
# 8. FastAPI 路由
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
        "timestamp": datetime.now(pytz.timezone(TIMEZONE)).isoformat(),
        "watchlist": WATCHLIST,
        "timeframe": "4H only",
    }


@app.get("/api/snapshot")
async def get_snapshot(x_cron_secret: Optional[str] = Header(None)):
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    snapshot = await AsyncDataEngine.get_market_snapshot(WATCHLIST)
    return {"data": snapshot, "timeframe": "4H", "interval": INTERVAL, "range": RANGE}


@app.api_route("/api/trigger", methods=["GET", "POST"])
async def handle_trigger(request: Request):
    received_auth = request.headers.get("Authorization")
    env_secret    = os.environ.get("CRON_SECRET", "未设置")
    expected      = f"Bearer {env_secret}"

    if received_auth != expected:
        masked_env = f"{env_secret[:3]}***" if env_secret else "None"
        return {
            "error":                    "钥匙没对上",
            "you_sent":                 received_auth,
            "server_expected_prefix":   f"Bearer {masked_env}",
            "tip":                      "请检查 Bearer 后是否有空格，以及 Vercel 变量是否已 Redeploy"
        }

    return await MarcusWolf.run_pipeline()
