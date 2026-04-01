# Wall Street's Wolf

An AI-powered quantitative market analyst that fetches live market data, computes technical indicators, generates a structured briefing via Gemini AI, and delivers it to a Telegram channel — all on a scheduled cron trigger.

## How It Works

1. **Data Fetch** — Pulls up to 250 days of daily OHLCV data from Yahoo Finance for a configurable watchlist.
2. **Quant Indicators** — Calculates RSI-14, MA-20/50 trend, ATR-14, and 20-day volume ratio for each asset.
3. **AI Analysis** — Sends the snapshot + last session's memory to Gemini, which responds as *Marcus Wolf*, a cold-and-precise quantitative macro analyst.
4. **Memory** — Stores the current report summary in Upstash Redis so the next run can compare against it.
5. **Telegram Delivery** — Posts the formatted report (Telegram MarkdownV2) to a configured chat. Falls back to plain text if rendering fails.
6. **Cron Trigger** — Exposes a `GET /api/trigger-analysis?secret=<CRON_SECRET>` endpoint that kicks off the full pipeline.

## Default Watchlist

| Symbol   | Asset              |
|----------|--------------------|
| `^GSPC`  | S&P 500            |
| `CL=F`   | Crude Oil Futures  |
| `GC=F`   | Gold Futures       |
| `NVDA`   | NVIDIA             |
| `AAPL`   | Apple              |
| `^VIX`   | CBOE Volatility    |
| `BTC-USD`| Bitcoin            |

## Tech Stack

- **Runtime**: Python 3.11+
- **Web framework**: FastAPI (deployed on Vercel)
- **AI model**: Google Gemini (`gemini-3.1-flash-lite-preview`)
- **Memory store**: Upstash Redis
- **Notifications**: Telegram Bot API

## Environment Variables

| Variable                    | Description                          |
|-----------------------------|--------------------------------------|
| `GEMINI_API_KEY`            | Google Gemini API key                |
| `TG_TOKEN`                  | Telegram bot token                   |
| `TG_CHAT_ID`                | Target Telegram chat/channel ID      |
| `CRON_SECRET`               | Secret token to authenticate cron calls |
| `UPSTASH_REDIS_REST_URL`    | Upstash Redis REST endpoint          |
| `UPSTASH_REDIS_REST_TOKEN`  | Upstash Redis REST token             |

## Deployment (Vercel)

1. Fork/clone this repo and import it into Vercel.
2. Set all environment variables above in the Vercel project settings.
3. Vercel picks up `vercel.json` automatically — no extra configuration needed.
4. Set up a cron job (e.g. via Vercel Cron or any external scheduler) to call:
   ```
   GET https://<your-domain>/api/trigger-analysis?secret=<CRON_SECRET>
   ```

## Local Development

```bash
pip install -r requirements.txt

export GEMINI_API_KEY=...
export TG_TOKEN=...
export TG_CHAT_ID=...
export CRON_SECRET=...
export UPSTASH_REDIS_REST_URL=...
export UPSTASH_REDIS_REST_TOKEN=...

uvicorn main:app --reload
```

Then trigger manually:
```
GET http://localhost:8000/api/trigger-analysis?secret=<CRON_SECRET>
```

## API Endpoints

| Method | Path                        | Description                        |
|--------|-----------------------------|------------------------------------|
| `GET`  | `/`                         | Health check — returns model/version info |
| `GET`  | `/api/trigger-analysis`     | Runs full pipeline (requires `secret` query param) |

## Report Structure

Each Telegram message follows a fixed template:

```
🎯 Core Conclusion
📊 Market Facts       (objective data only)
🌍 Macro Speculation  (each item tagged [Speculation] with confidence level)
⚖️  Correction & Last-Session Review
⚡ Actionable Reference
```
