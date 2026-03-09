import os
import json
import requests
from datetime import datetime
import pytz
from fastapi import FastAPI, BackgroundTasks, HTTPException
from upstash_redis import Redis

# ==========================================
# 1. 显式声明环境变量
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
CRON_SECRET = os.environ.get("CRON_SECRET")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

TIMEZONE = "Asia/Kuala_Lumpur"
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

app = FastAPI()
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN) 

# ==========================================
# 2. 原生 Python 手写量化算法 (避开 Pandas)
# ==========================================
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return 50.0
    gains = [max(0, prices[i] - prices[i-1]) for i in range(1, period+1)]
    losses = [max(0, prices[i-1] - prices[i]) for i in range(1, period+1)]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period+1, len(prices)):
        gain = max(0, prices[i] - prices[i-1])
        loss = max(0, prices[i-1] - prices[i])
        avg_gain = (avg_gain * 13 + gain) / 14
        avg_loss = (avg_loss * 13 + loss) / 14
    if avg_loss == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

class QuantDataEngine:
    @staticmethod
    def fetch_and_calculate(symbols: list) -> str:
        market_state = {}
        # 伪装 User-Agent 直接调用 Yahoo 底层 API
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        for sym in symbols:
            try:
                url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=250d&interval=1d"
                res = requests.get(url, headers=headers).json()
                
                # 提取收盘价并过滤空值
                result = res['chart']['result'][0]
                closes = [c for c in result['indicators']['quote'][0]['close'] if c is not None]
                
                if len(closes) >= 2:
                    latest = closes[-1]
                    prev = closes[-2]
                    pct_change = ((latest - prev) / prev) * 100
                    sma200 = sum(closes[-200:]) / min(200, len(closes))
                    rsi_14 = calculate_rsi(closes)
                    
                    market_state[sym] = {
                        "price": round(latest, 2),
                        "pct_change": round(pct_change, 2),
                        "RSI_14": round(rsi_14, 2),
                        "above_MA200": bool(latest > sma200)
                    }
            except Exception as e:
                print(f"数据处理跳过 {sym}: {e}")
                
        return json.dumps(market_state, indent=2)

# ==========================================
# 3. 剥离官方 SDK，直接用 HTTP 裸连 Gemini 大脑
# ==========================================
class MarcusAgent:
    @staticmethod
    def execute_and_send():
        current_data = QuantDataEngine.fetch_and_calculate(WATCHLIST)
        
        last_data = redis.get("marcus_memory")
        last_mem = json.loads(last_data) if last_data else None
        history_context = f"【上期研判回顾】: {last_mem['report']}" if last_mem else "无历史记录。"
        
        prompt = f"""
        你是华尔街量化分析师。
        【纪律】：事实与推测严格隔离。客观数据为事实，地缘推演为推测。结论先行。保持中性冷酷。
        【输入数据】：{current_data}
        【历史记忆】：{history_context}
        请使用 Telegram Markdown 输出简报：包含 🎯核心结论, 📊盘面事实, 🌍宏观推测, ⚖️纠偏。
        """
        
        # 抛弃 google-generativeai，直接调用底层 REST API
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts":[{"text": prompt}]}]}
        gemini_res = requests.post(gemini_url, json=payload, headers={'Content-Type': 'application/json'}).json()
        
        # 提取 AI 回复
        report = gemini_res['candidates'][0]['content']['parts'][0]['text']
        
        # 更新 Upstash 记忆
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        redis.set("marcus_memory", json.dumps({"time": now, "report": report[:600]}))
        
        # 发送 Telegram
        tg_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(tg_url, json={"chat_id": TG_CHAT_ID, "text": report, "parse_mode": "Markdown", "disable_web_page_preview": True})

# ==========================================
# 4. API 路由 (强制前台同步版本)
# ==========================================
@app.get("/")
def health_check():
    return {"status": "Marcus Wolf Engine Zero-Fat Edition Online"}

@app.get("/api/trigger-analysis")
def trigger_analysis(secret: str = ""):
    if secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # 抛弃后台任务，强行前台同步执行！
        # 此时 Vercel 必须等这行代码彻底跑完（发完 TG 消息），才会返回结果。
        result_msg = MarcusAgent.execute_and_send()
        return {"status": "Success", "detail": result_msg}
    except Exception as e:
        # 如果崩溃，真凶会直接暴露在屏幕上
        return {"status": "Failed", "error": str(e)}
