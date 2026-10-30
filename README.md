# Wall Street's Wolf

An AI-powered quantitative market analyst that fetches live market data, computes technical indicators, generates a structured briefing via Gemini AI, and delivers it to a Telegram channel — all on a scheduled cron trigger.

## How It Works

Marcus is tuned for **short-term trading (1–5 trading days)** and issues verifiable signals instead of free-form commentary.

1. **Data Fetch** — Pulls 250 days of daily bars and 1 month of hourly bars from Yahoo Finance for the watchlist saved in the dashboard.
2. **Quant Indicators** — Daily: RSI-14, MA-20/50 trend, MA-50/200 position, Wilder ATR-14 (and ATR %), 5-day return, volume ratio, classic pivots (P/R1/S1/R2/S2 from the last completed session), 20-day swing high/low and distance to them in ATR. Hourly: EMA-20/50 trend and RSI.
3. **Signal Settlement** — Before each run, every open signal is settled against hourly bars with conservative rules (fill only when price touches entry; stop wins ties; fill bar checks stop only; gaps fill at the open). Outcomes: `WIN` / `LOSS` / `EXPIRED` (marked to last close) / `NOT_TRIGGERED`.
4. **AI Analysis** — Gemini receives the snapshot plus the code-computed track record and returns structured JSON (`responseSchema`): conclusion, regime, per-asset bias, up to 3 signals with entry/stop/target/horizon/confidence, review and key risk.
5. **Risk Checks** — Code rejects signals with wrong price ordering, R:R < 1.5, stop outside 0.3–3 ATR, entry more than 1.5 ATR from price, or a symbol that already has an open signal.
6. **Delivery** — A short brief goes to Telegram (HTML parse mode, rendered and escaped by code); the full analysis, rejected signals and stats live on the dashboard.
7. **Storage** — Signals and the latest memory in Upstash Redis; each run archived to Supabase `analysis_history`.

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
- **AI model**: Google Gemini (`gemini-3.1-flash-lite`)
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
| `SUPABASE_URL`              | Supabase project URL (optional, history archive) |
| `SUPABASE_SERVICE_KEY`      | Supabase service role key (optional) |

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
| `GET`  | `/api/signals`              | Signal log + win rate / average R stats |
| `GET`  | `/api/memory`               | Latest analysis (full report) |
| `GET`  | `/api/history`              | Archived runs from Supabase |

## Report Structure

Telegram brief (full version on the dashboard):

```
🎯 Core Conclusion [regime]
⚡ Signals          symbol | direction | entry | stop | target | R:R | horizon | confidence
📋 Signal Tracking  settled + still-open signals with R multiple
📈 Track Record     closed trades, win rate, avg R, by confidence
⚠️ Key Risk
```

For short-term use, schedule the trigger at least once per trading day (e.g. before the US open); signals are settled on each run.

## Tests

```bash
pip install -r requirements.txt pytest httpx
pytest tests
```
