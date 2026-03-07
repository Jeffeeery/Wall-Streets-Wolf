import os
import json
import pandas as pd
import yfinance as yf
import pandas_ta as ta
from datetime import datetime
import pytz
import google.generativeai as genai
import requests
from fastapi import FastAPI, BackgroundTasks, HTTPException
from upstash_redis import Redis

# 初始化环境变量与核心组件
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
CRON_SECRET = os.environ.get("CRON_SECRET")
TIMEZONE = "Asia/Kuala_Lumpur"
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

app = FastAPI()
redis = Redis.from_env() 
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

class QuantDataEngine:
    @staticmethod
    def fetch_and_calculate(symbols: list) -> str:
        data = yf.download(symbols, period="1y", interval="1d", group_by='ticker', progress=False)
        market_state = {}
        for sym in symbols:
            try:
                df = data[sym].dropna() if len(symbols) > 1 else data.dropna()
                df.ta.atr(length=14, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.sma(length=200, append=True)
                latest = df.iloc[-1]
                prev = df.iloc[-2]
                pct_change = ((latest['Close'] - prev['Close']) / prev['Close']) * 100
                market_state[sym] = {
                    "price": round(latest['Close'], 2),
                    "pct_change": round(pct_change, 2),
                    "RSI_14": round(latest['RSI_14'], 2),
                    "ATR_14": round(latest['ATRr_14'], 2),
                    "above_MA200": bool(latest['Close'] > latest['SMA_200'])
                }
            except Exception as e:
                pass
        return json.dumps(market_state, indent=2)

class MarcusAgent:
    @staticmethod
    def execute_and_send():
        # 1. 抓取数据
        current_data = QuantDataEngine.fetch_and_calculate(WATCHLIST)
        
        # 2. 读取 Upstash 记忆
        last_data = redis.get("marcus_memory")
        last_mem = json.loads(last_data) if last_data else None
        history_context = f"【上期研判回顾】: {last_mem['report']}" if last_mem else "无历史记录。"
        
        # 3. 构造系统提示词
        prompt = f"""
        你是华尔街量化分析师。
        【纪律】：事实与推测严格隔离。客观数据为事实，地缘推演为推测。结论先行。
        【输入数据】：{current_data}
        【历史记忆】：{history_context}
        请使用 Telegram Markdown 输出简报：包含 🎯核心结论, 📊盘面事实, 🌍宏观推测, ⚖️纠偏。
        """
        
        # 4. AI 推演
        response = model.generate_content(prompt)
        report = response.text
        
        # 5. 更新 Upstash 记忆
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        redis.set("marcus_memory", json.dumps({"time": now, "report": report[:600]}))
        
        # 6. 发送 Telegram
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": report, "parse_mode": "Markdown", "disable_web_page_preview": True})

@app.get("/")
def health_check():
    return {"status": "Marcus Wolf Engine Online"}

@app.get("/api/trigger-analysis")
def trigger_analysis(background_tasks: BackgroundTasks, secret: str = ""):
    if secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    background_tasks.add_task(MarcusAgent.execute_and_send)
    return {"status": "Task running in background"}
