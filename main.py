import os
import json
import pandas as pd
import yfinance as yf
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
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

TIMEZONE = "Asia/Kuala_Lumpur"
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

app = FastAPI()
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN) 
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
                
                close_prices = df['Close']
                high_prices = df['High']
                low_prices = df['Low']
                
                # 1. 手写 SMA 200 (200日简单移动平均)
                sma_200 = close_prices.rolling(window=200).mean().iloc[-1]
                
                # 2. 手写 RSI 14 (相对强弱指数，Wilder平滑法)
                delta = close_prices.diff()
                gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                rsi_14 = (100 - (100 / (1 + gain / loss))).iloc[-1]
                
                # 3. 手写 ATR 14 (真实波动幅度)
                tr1 = high_prices - low_prices
                tr2 = (high_prices - close_prices.shift()).abs()
                tr3 = (low_prices - close_prices.shift()).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr_14 = tr.rolling(window=14).mean().iloc[-1]
                
                latest_close = close_prices.iloc[-1]
                prev_close = close_prices.iloc[-2]
                pct_change = ((latest_close - prev_close) / prev_close) * 100
                
                market_state[sym] = {
                    "price": round(float(latest_close), 2),
                    "pct_change": round(float(pct_change), 2),
                    "RSI_14": round(float(rsi_14), 2),
                    "ATR_14": round(float(atr_14), 2),
                    "above_MA200": bool(latest_close > sma_200)
                }
            except Exception as e:
                print(f"数据处理跳过 {sym}: {e}")
                
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
