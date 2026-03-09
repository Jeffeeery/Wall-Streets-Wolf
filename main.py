import os
import json
import requests
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI, HTTPException
from upstash_redis import Redis

# ==========================================
# 1. 显式声明环境变量（添加默认值 fallback 以防未设置）
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TG_TOKEN = os.environ.get("TG_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
CRON_SECRET = os.environ.get("CRON_SECRET")
UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kuala_Lumpur")  # 默认值以防未设置
WATCHLIST = ["^GSPC", "CL=F", "GC=F", "NVDA", "AAPL", "^VIX", "BTC-USD"]

app = FastAPI()
redis = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN)

# ==========================================
# 2. 原生 Python 手写量化算法 (优化 RSI 计算逻辑，避免不必要的列表创建)
# ==========================================
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0  # 默认中性值
    
    # 初始化平均收益和损失
    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    # 平滑计算后续值
    for i in range(period + 1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gain = max(0, delta)
        loss = max(0, -delta)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

class QuantDataEngine:
    @staticmethod
    def fetch_symbol_data(sym: str) -> dict:
        """并行化单个符号的数据获取和计算"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=250d&interval=1d"
            res = requests.get(url, headers=headers, timeout=10).json()  # 添加超时
            result = res['chart']['result'][0]
            closes = [c for c in result['indicators']['quote'][0]['close'] if c is not None]
            
            if len(closes) < 2:
                return {sym: {"error": "Insufficient data"}}
            
            latest = closes[-1]
            prev = closes[-2]
            pct_change = ((latest - prev) / prev) * 100
            sma200 = sum(closes[-200:]) / min(200, len(closes))
            rsi_14 = calculate_rsi(closes)
            
            return {sym: {
                "price": round(latest, 2),
                "pct_change": round(pct_change, 2),
                "RSI_14": round(rsi_14, 2),
                "above_MA200": bool(latest > sma200)
            }}
        except Exception as e:
            print(f"数据处理跳过 {sym}: {e}")
            return {sym: {"error": str(e)}}

    @staticmethod
    def fetch_and_calculate(symbols: list) -> str:
        market_state = {}
        # 使用线程池并行获取数据，提高效率（尤其是 WATCHLIST 增长时）
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(QuantDataEngine.fetch_symbol_data, sym) for sym in symbols]
            for future in as_completed(futures):
                market_state.update(future.result())
        
        return json.dumps(market_state, indent=2)

# ==========================================
# 3. 剥离官方 SDK，直接用 HTTP 裸连 Gemini 大脑（优化 Prompt，添加重试机制）
# ==========================================
class MarcusAgent:
    @staticmethod
    def generate_report_with_gemini(current_data: str, history_context: str) -> str:
        """调用 Gemini API 生成报告，支持重试"""
        prompt = f"""
你是一位经验丰富的华尔街量化分析师，专注于金融市场趋势分析。你的分析必须基于数据驱动，严格区分事实与推测。

【核心原则】：
- **结论先行**：在开头直接给出核心结论，包括整体市场情绪（牛市/熊市/中性）、关键风险和机会。
- **事实与推测隔离**：📊盘面事实部分只包含客观数据和计算指标（如价格、变化%、RSI、MA200位置）。🌍宏观推测部分允许基于地缘政治、经济事件的地缘推演，但必须标注为“推测”并提供依据。
- **中性冷酷**：避免情绪化语言，保持专业、客观。使用数据支持所有声明。
- **纠偏机制**：在⚖️纠偏部分，比较当前数据与历史记忆，指出偏差或确认趋势。
- **输出结构**：严格使用 Telegram Markdown 格式，确保可读性。包括标题、 bullet points 和 emoji。保持简洁，总长度不超过800字。
- **增强分析**：整合RSI（超买>70，超卖<30）、MA200（上方为强势，下方为弱势）、波动率（^VIX>20为高波动）和资产相关性（例如BTC与NVDA的相关）。

【输入数据】：{current_data}
【历史记忆】：{history_context}

输出格式示例：
🎯 **核心结论**： [简短总结，例如“市场整体偏牛，但波动率上升需警惕。”]

📊 **盘面事实**：
- [符号]：价格 [X]，变化 [Y]%，RSI [Z]，[上方/下方]MA200。
- ...

🌍 **宏观推测**：
- [推测1]：基于[依据]，可能[影响]。
- ...

⚖️ **纠偏**：
- 与上期相比，[变化描述]，[调整建议]。
"""
        
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {'Content-Type': 'application/json'}
        
        # 添加重试机制（最多3次）
        for attempt in range(3):
            try:
                res = requests.post(gemini_url, json=payload, headers=headers, timeout=30).json()
                return res['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                print(f"Gemini API 调用失败 (尝试 {attempt+1}): {e}")
                if attempt == 2:
                    raise e  # 最后一次失败抛出异常

    @staticmethod
    def execute_and_send():
        current_data = QuantDataEngine.fetch_and_calculate(WATCHLIST)
        
        last_data = redis.get("marcus_memory")
        last_mem = json.loads(last_data) if last_data else None
        history_context = f"【上期研判回顾】: {last_mem['report']}" if last_mem else "无历史记录。"
        
        report = MarcusAgent.generate_report_with_gemini(current_data, history_context)
        
        # 更新 Upstash 记忆（存储完整报告，但截断到2000字以防过长）
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        redis.set("marcus_memory", json.dumps({"time": now, "report": report[:2000]}))
        
        # 发送 Telegram（添加 parse_mode 为 Markdown）
        tg_url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(tg_url, json={
            "chat_id": TG_CHAT_ID,
            "text": report,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })

# ==========================================
# 4. API 路由 (强制前台同步版本，添加日志)
# ==========================================
@app.get("/")
def health_check():
    return {"status": "Marcus Wolf Engine Zero-Fat Edition Online"}

@app.get("/api/trigger-analysis")
def trigger_analysis(secret: str = ""):
    if secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        MarcusAgent.execute_and_send()
        return {"status": "Success", "detail": "Analysis executed and sent"}
    except Exception as e:
        print(f"执行失败: {e}")  # 添加控制台日志
        return {"status": "Failed", "error": str(e)}
