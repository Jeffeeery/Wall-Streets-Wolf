"""
Marcus Wolf — Multi-Timeframe Market Intelligence Agent
========================================================
架构：FastAPI + Gemini 2.5 Flash + Upstash Redis + Telegram
分析框架：
  - 宏观透镜 (1D)  → 识别基本面趋势，过滤噪音
  - 战术透镜 (4H)  → 寻找精准介入点，捕捉回踩/突破机会
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
from fastapi import FastAPI, HTTPException, Header
from upstash_redis.asyncio import Redis  # ✅ 异步 SDK

# ==========================================
# 0. 日志 & 基础配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
log = logging.getLogger("MarcusWolf")

# 环境变量（启动时统一校验）
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TG_TOKEN       = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID     = os.environ.get("TG_CHAT_ID", "")
CRON_SECRET    = os.environ.get("CRON_SECRET", "")
UPSTASH_URL    = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN  = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

TIMEZONE      = "Asia/Kuala_Lumpur"
GEMINI_MODEL  = "gemini-2.5-flash"
GEMINI_URL    = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

# 监控列表：每个品种都会抓取 1D + 4H 两个时间框架
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

# 时间框架配置：(Yahoo interval, Yahoo range, 显示名称)
TIMEFRAMES = {
    "1d": ("1d",  "250d", "宏观透镜 (1D)"),
    "4h": ("60m", "60d",  "战术透镜 (4H)"),   # Yahoo 最细 60m，60d = ~60 根 4H K线
}

app = FastAPI(title="MarcusWolf", version="2.0")
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)


# ==========================================
# 1. 启动校验：任何环境变量缺失则立即报错
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
    """转义 MarkdownV2 保留字符（不转义已有的 Markdown 语法标记）。"""
    reserved = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(reserved)}])", r"\\\1", text)


async def send_telegram(text: str, parse_mode: str = "MarkdownV2") -> bool:
    """
    发送 Telegram 消息，自带降级策略：
      MarkdownV2 失败 → HTML 模式 → 纯文本
    """
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    async with httpx.AsyncClient(timeout=15) as client:
        # 尝试 1：指定 parse_mode
        r = await client.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
        })
        if r.status_code == 200:
            return True

        log.warning(f"TG {parse_mode} 发送失败 ({r.status_code})，尝试纯文本降级…")

        # 降级：剥除所有 Markdown 符号，以纯文本发送
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
        """Wilder 平滑 RSI（修复 off-by-one）。"""
        if len(prices) < period + 1:
            return 50.0

        # ✅ 修复：初始化用前 period 个涨跌，平滑从第 period 根开始
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
        if diff > 0.003:
            return "UP"
        if diff < -0.003:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def calculate_atr(highs: list[float], lows: list[float],
                      closes: list[float], period: int = 14) -> float:
        """Average True Range（衡量近期波动性）。"""
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
        # 归一化为百分比，便于跨品种比较
        return round(atr / closes[-1] * 100, 3)

    @staticmethod
    def safe_vol_ratio(volumes: list[float]) -> float:
        """✅ 修复：避免除零错误。"""
        if not volumes or len(volumes) < 2:
            return 1.0
        avg = sum(volumes[-20:]) / len(volumes[-20:])
        return round(volumes[-1] / avg, 2) if avg > 0 else 1.0

    @staticmethod
    def get_rsi_signal(rsi: float) -> str:
        if rsi >= 75:   return "严重超买"
        if rsi >= 65:   return "超买"
        if rsi <= 25:   return "严重超卖"
        if rsi <= 35:   return "超卖"
        return "中性"

    @staticmethod
    def classify_vol_ratio(ratio: float) -> str:
        if ratio >= 2.0:  return "放量 (>2x)"
        if ratio >= 1.3:  return "温和放量"
        if ratio <= 0.5:  return "缩量萎缩"
        return "正常"


# ==========================================
# 4. 异步多时间框架数据引擎
# ==========================================
class AsyncDataEngine:

    @staticmethod
    async def _fetch_raw(client: httpx.AsyncClient,
                         sym: str, interval: str, range_: str) -> dict:
        """底层抓取 + 清洗，返回 OHLCV 列表。"""
        url = (
            f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
            f"?range={range_}&interval={interval}"
        )
        resp = await client.get(url, timeout=12)
        resp.raise_for_status()

        result = resp.json()["chart"]["result"][0]
        q = result["indicators"]["quote"][0]

        # 数据清洗：过滤含 None 的 bar
        bars = [
            {"c": c, "h": h, "l": l, "v": float(v or 0)}
            for c, h, l, v in zip(q["close"], q["high"], q["low"], q["volume"])
            if c is not None and h is not None and l is not None
        ]
        return bars

    @staticmethod
    def _compute_metrics(bars: list[dict]) -> dict:
        """将 OHLCV bar 列表计算为结构化指标。"""
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
            "bars_used":  len(bars),
        }

    @classmethod
    async def fetch_symbol_mtf(
        cls,
        client: httpx.AsyncClient,
        sym: str,
        retries: int = 2
    ) -> tuple[str, dict]:
        """
        抓取单品种的所有时间框架数据，含重试逻辑。
        返回：(symbol, {"1d": {...}, "4h": {...}})
        """
        result = {}
        for tf_key, (interval, range_, label) in TIMEFRAMES.items():
            last_err = None
            for attempt in range(retries + 1):
                try:
                    bars = await cls._fetch_raw(client, sym, interval, range_)
                    result[tf_key] = cls._compute_metrics(bars)
                    break
                except Exception as e:
                    last_err = e
                    if attempt < retries:
                        await asyncio.sleep(1.5 * (attempt + 1))
            else:
                result[tf_key] = {"error": str(last_err)}

        return sym, result

    @classmethod
    async def get_market_snapshot(cls, symbols: list[str]) -> dict:
        """并发抓取所有品种的多时间框架数据。"""
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; MarcusWolf/2.0)"},
            follow_redirects=True,
        ) as client:
            tasks = [cls.fetch_symbol_mtf(client, s) for s in symbols]
            results = await asyncio.gather(*tasks)
            return dict(results)


# ==========================================
# 5. Gemini AI 调用
# ==========================================
async def call_gemini(prompt: str, max_tokens: int = 2048) -> str:
    """调用 Gemini API，返回生成文本。"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
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
# 6. Marcus Wolf Prompt 构造器
# ==========================================
def build_prompt(snapshot: dict, memory: dict) -> str:
    """
    构建 Marcus Wolf 的分析 Prompt。
    核心框架：宏观透镜 (1D) → 战术透镜 (4H) → 多框架共振结论
    """

    # 将快照序列化为紧凑 JSON，节省 Token
    snapshot_str = json.dumps(snapshot, ensure_ascii=False, indent=2)
    memory_str   = memory.get("conclusion", "暂无历史记录")
    last_time    = memory.get("time", "N/A")
    now_str      = datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M MYT")

    return f"""你是 Marcus Wolf——一位顶级量化对冲基金的首席市场分析师。
你的分析框架融合了宏观趋势判断、多时间框架共振，以及量化指标交叉验证。
你的语言风格：犀利、精准、有信心，像狼一样嗅觉灵敏，不废话。

═══════════════════════════════════════════
📊 实时市场数据快照（{now_str}）
═══════════════════════════════════════════
{snapshot_str}

数据字段说明：
- price: 最新收盘价
- pct: 最新涨跌幅 (%)
- rsi / rsi_signal: RSI 值及信号（超买/超卖/中性）
- trend: MA 趋势（UP / DOWN / FLAT）
- atr_pct: ATR 波动率（归一化为价格百分比）
- vol_ratio / vol_signal: 成交量相对20日均量比值及信号
- 每个品种包含 "1d"（日线）和 "4h"（4小时线）两组数据

═══════════════════════════════════════════
🧠 上次分析记忆（{last_time}）
═══════════════════════════════════════════
{memory_str}

═══════════════════════════════════════════
🔍 分析框架：双镜头多时间框架法
═══════════════════════════════════════════

**宏观透镜 (1D)**：这是你的"方向罗盘"。
- 日线趋势决定了交易的整体方向偏见。
- 若 1D 趋势为 DOWN，则 4H 的任何上涨均视为"空头反弹"，而非趋势反转。
- 若 1D 趋势为 UP，则 4H 的回踩+超卖是优质多头入场机会。

**战术透镜 (4H)**：这是你的"精准狙击镜"。
- 在 1D 方向确认的前提下，用 4H RSI、趋势和成交量寻找最优介入点。
- 4H RSI 超卖 + 1D 上升趋势 = 回踩买入信号（高概率）
- 4H RSI 超买 + 1D 下降趋势 = 反弹做空信号（高概率）
- 1D 与 4H 趋势方向相同 = 共振信号（最强信号）
- 1D 与 4H 趋势方向相反 = 矛盾信号（谨慎操作）

═══════════════════════════════════════════
📋 输出格式（严格遵守 Telegram MarkdownV2）
═══════════════════════════════════════════

请按以下结构输出，使用 Telegram MarkdownV2 格式：
- 标题用 *粗体*
- 关键数字/结论用 `代码格式`
- 每个品种分析不超过 4 行
- 不使用 # 标题，不使用 HTML
- 禁止使用未转义的特殊字符（`.` `-` `(` `)` `!` 等需加反斜杠）

---

*🐺 Marcus Wolf 市场战情室*
*📅 {now_str}*

*━━━ 宏观透镜 \(1D\) ━━━*
[对每个品种：一句话点出 1D 趋势方向 + 关键指标，识别当前宏观结构是多头/空头/盘整]

*━━━ 战术透镜 \(4H\) ━━━*
[对每个品种：基于 1D 判断，分析 4H 是否出现回踩/突破/反弹信号，明确指出操作意义]

*━━━ 多框架共振信号 ━━━*
[列出本次扫描中发现的最高质量共振信号，格式：
品种 | 1D趋势 | 4H信号 | 共振结论 | 操作建议]

*━━━ 🎯 核心结论 ━━━*
[用 3-5 句话总结当前整体市场格局，点出最值得关注的 1-2 个机会或风险，
并与上次分析对比说明市场有何变化]

*━━━ ⚠️ 风险提示 ━━━*
[简短指出当前最大的尾部风险或需要警惕的信号]

---

现在开始分析。保持锋利，不要废话。
"""


# ==========================================
# 7. Marcus Wolf 主管线
# ==========================================
class MarcusWolf:

    @staticmethod
    async def run_pipeline() -> dict:
        now = datetime.now(pytz.timezone(TIMEZONE))
        log.info(f"[{now.isoformat()}] 🚀 启动 Marcus Wolf 分析管线…")

        # ── Step 1: 并发多时间框架数据抓取 ──────────────────
        log.info("📡 抓取多时间框架市场数据…")
        snapshot = await AsyncDataEngine.get_market_snapshot(WATCHLIST)

        # 统计数据质量
        ok_count = sum(
            1 for sym_data in snapshot.values()
            for tf_data in sym_data.values()
            if "error" not in tf_data
        )
        log.info(f"   数据质量：{ok_count}/{len(WATCHLIST) * len(TIMEFRAMES)} 个时间框架成功")

        # ── Step 2: 读取历史记忆 ─────────────────────────────
        raw_mem  = await redis.get("marcus_memory_v3")
        memory   = json.loads(raw_mem) if raw_mem else {}
        log.info(f"   历史记忆：{'有' if memory else '无（首次运行）'}")

        # ── Step 3: 构造 Prompt 并调用 Gemini ────────────────
        prompt = build_prompt(snapshot, memory)
        log.info("🤖 调用 Gemini 进行多框架分析…")
        report = await call_gemini(prompt, max_tokens=2048)
        log.info(f"   生成报告：{len(report)} 字符")

        # ── Step 4: 提取核心结论用于记忆存储 ─────────────────
        # 截取"核心结论"段落，最多 300 字
        conclusion_match = re.search(r"核心结论[^\n]*\n(.*?)(?=━|$)", report, re.DOTALL)
        conclusion_text  = conclusion_match.group(1).strip()[:300] if conclusion_match else report[:300]

        # ── Step 5: 持久化记忆 ───────────────────────────────
        new_memory = {
            "time":       now.isoformat(),
            "conclusion": conclusion_text,
            "snapshot_summary": {
                sym: {
                    tf: {"trend": data.get("trend"), "rsi": data.get("rsi")}
                    for tf, data in tf_data.items()
                    if "error" not in data
                }
                for sym, tf_data in snapshot.items()
            }
        }
        await redis.set("marcus_memory_v3", json.dumps(new_memory, ensure_ascii=False))
        log.info("💾 记忆已更新至 Redis")

        # ── Step 6: 推送 Telegram ────────────────────────────
        log.info("📨 推送至 Telegram…")
        success = await send_telegram(report, parse_mode="MarkdownV2")
        log.info(f"   推送{'成功' if success else '失败（已降级）'}")

        return {
            "status":        "ok" if success else "degraded",
            "symbols":       len(WATCHLIST),
            "timeframes":    list(TIMEFRAMES.keys()),
            "report_length": len(report),
            "timestamp":     now.isoformat(),
        }


# ==========================================
# 8. FastAPI 路由
# ==========================================

@app.get("/health")
async def health():
    """健康检查：验证 Redis 连通性。"""
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
        "timeframes": list(TIMEFRAMES.keys()),
    }


@app.get("/api/snapshot")
async def get_snapshot(x_cron_secret: Optional[str] = Header(None)):
    """
    仅返回市场快照数据，不触发 AI 分析或 Telegram 推送。
    用于调试数据质量。
    """
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    snapshot = await AsyncDataEngine.get_market_snapshot(WATCHLIST)
    return {"data": snapshot, "timeframes": TIMEFRAMES}


@app.post("/api/trigger")
async def handle_trigger(x_cron_secret: Optional[str] = Header(None)):
    """Cron 触发端点（由 Vercel Cron / 外部调度器调用）。"""
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = await MarcusWolf.run_pipeline()
    return result
