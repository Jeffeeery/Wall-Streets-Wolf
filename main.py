import os
import json
import requests
from datetime import datetime
import pytz
from fastapi import FastAPI, HTTPException
from upstash_redis import Redis
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ================================
# 环境变量
# ================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
CRON_SECRET = os.environ.get("CRON_SECRET")

UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

TIMEZONE = "Asia/Kuala_Lumpur"

WATCHLIST = [
    "^GSPC",
    "CL=F",
    "GC=F",
    "NVDA",
    "AAPL",
    "^VIX",
    "BTC-USD"
]

app = FastAPI()
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# ================================
# 量化指标
# ================================

def calculate_rsi(prices, period=14):

    if len(prices) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, period+1):

        diff = prices[i] - prices[i-1]

        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period+1, len(prices)):

        diff = prices[i] - prices[i-1]

        gain = max(diff, 0)
        loss = max(-diff, 0)

        avg_gain = (avg_gain * 13 + gain) / 14
        avg_loss = (avg_loss * 13 + loss) / 14

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100/(1+rs))


def calculate_sma(prices, n):

    if len(prices) < n:
        return sum(prices) / len(prices)

    return sum(prices[-n:]) / n


# ================================
# 市场 Regime Detection
# ================================

def detect_regime(market):

    score = 0

    if "^GSPC" in market:
        score += 1 if market["^GSPC"]["pct_change"] > 0 else -1

    if "^VIX" in market:
        score += -2 if market["^VIX"]["pct_change"] > 0 else 2

    if "BTC-USD" in market:
        score += 1 if market["BTC-USD"]["pct_change"] > 0 else -1

    if "GC=F" in market:
        score += -1 if market["GC=F"]["pct_change"] > 0 else 1

    if "CL=F" in market:
        score += -0.5 if market["CL=F"]["pct_change"] > 0 else 0.5

    if score >= 2:
        regime = "RISK_ON"
    elif score <= -2:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"

    return score, regime


# ================================
# Yahoo Data Engine
# ================================

def fetch_symbol(sym):

    headers = {
        'User-Agent':'Mozilla/5.0'
    }

    try:

        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=250d&interval=1d"

        res = requests.get(url, headers=headers, timeout=5).json()

        result = res["chart"]["result"][0]

        closes = [
            c for c in result["indicators"]["quote"][0]["close"]
            if c
        ]

        latest = closes[-1]
        prev = closes[-2]

        pct = ((latest-prev)/prev)*100

        sma50 = calculate_sma(closes,50)
        sma200 = calculate_sma(closes,200)

        rsi = calculate_rsi(closes)

        return sym,{
            "price": round(latest,2),
            "pct_change": round(pct,2),
            "RSI": round(rsi,1),
            "trend": "bull" if sma50 > sma200 else "bear"
        }

    except:
        return None


class QuantDataEngine:

    @staticmethod
    def fetch_and_calculate():

        market = {}

        with ThreadPoolExecutor(max_workers=6) as ex:

            results = ex.map(fetch_symbol, WATCHLIST)

        for r in results:

            if r:

                sym,data = r

                market[sym] = data

        score,regime = detect_regime(market)

        return {
            "market":market,
            "score":score,
            "regime":regime
        }


# ================================
# Marcus AI Agent
# ================================

class MarcusAgent:

    @staticmethod
    def execute_and_send():

        data = QuantDataEngine.fetch_and_calculate()

        market_data = data["market"]
        score = data["score"]
        regime = data["regime"]

        current_data = json.dumps(market_data,indent=2)

        # 读取历史记忆
        last_data = redis.get("marcus_memory")

        last_mem = json.loads(last_data) if last_data else None

        history_context = (
            last_mem["report"]
            if last_mem else "无历史记录"
        )

        prompt = f"""
你是华尔街宏观量化策略师 Marcus。

市场状态已经由量化模型计算完成。

【Market Regime】
{regime}

【Regime Score】
{score}

【市场数据】
{current_data}

【历史研判】
{history_context}

规则：

1 所有事实必须来自输入数据
2 不允许编造数据
3 推测必须基于事实
4 保持简洁专业

输出格式：

🎯核心结论

📊盘面事实

🌍宏观推测

⚖️复盘纠偏

限制：

每部分最多3行
总长度 < 200字
"""

        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents":[
                {"parts":[{"text":prompt}]}
            ]
        }

        gemini_res = requests.post(
            gemini_url,
            json=payload,
            headers={'Content-Type':'application/json'}
        ).json()

        try:

            report = gemini_res["candidates"][0]["content"]["parts"][0]["text"]

        except:

            report = "AI分析失败"

        # Telegram markdown 兼容
        report = report.replace("_","\\_")

        tz = pytz.timezone(TIMEZONE)

        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

        redis.set(
            "marcus_memory",
            json.dumps({
                "time":now,
                "market":market_data,
                "regime":regime,
                "report":report[:600]
            })
        )

        tg_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

        requests.post(
            tg_url,
            json={
                "chat_id":TG_CHAT_ID,
                "text":report,
                "parse_mode":"Markdown",
                "disable_web_page_preview":True
            }
        )

        return report


# ================================
# API
# ================================

@app.get("/")
def health():

    return {"status":"Marcus Quant Engine v2 online"}


@app.get("/api/trigger-analysis")
def trigger(secret:str=""):

    if secret != CRON_SECRET:
        raise HTTPException(status_code=401)

    result = MarcusAgent.execute_and_send()

    return {
        "status":"ok",
        "report":result
    }

if __name__ == "__main__":
    # 模拟触发分析并打印报告
    print("🚀 启动 Marcus 宏观量化引擎分析...")
    try:
        report = MarcusAgent.execute_and_send()
        print("\n" + "="*50)
        print("📊 Marcus 量化报告")
        print("="*50)
        print(report)
        print("="*50)
    except Exception as e:
        print(f"❌ 运行失败: {e}")
