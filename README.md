# Wall Street's Wolf

An AI-powered quantitative market analyst that fetches live market data, computes technical indicators, generates a structured briefing via Gemini AI, and delivers it to a Telegram channel — all on a scheduled cron trigger.

## How It Works

Marcus is a **news/catalyst analyst** for short-term traders (1–5 trading days). Technical analysis is deliberately out of scope.

1. **Price Context** — Pulls daily bars from Yahoo Finance for the watchlist saved in the dashboard; price, daily change and 5-day return are passed to the model so it can tie news to moves.
2. **News Search (Tavily)** — Code runs one search per watchlist symbol plus three macro topics (central banks/economy, geopolitics/commodities, this week's calendar), news-only and limited to the last day, in parallel. Results are de-duplicated and numbered `S1..Sn`.
3. **Summary (Gemini, no tools)** — Gemini only summarizes the numbered results and returns a JSON brief (`responseSchema`): headline, sentiment, changes since last brief, market news, per-symbol direction, upcoming events and what to watch. No search tool is used, so it works on the free tier. If the primary model hits a quota/availability error, a fallback model is tried.
4. **Citation Check** — Every news item and every bullish/bearish call must cite source IDs. Code drops news that cites no valid source and downgrades uncited directions to neutral. **Direction only — no prices, levels or targets.**
5. **Delivery** — A short brief goes to Telegram (HTML, ↗ links to the original articles); the full brief with the numbered source list lives on the dashboard.
6. **Memory** — The latest brief and per-symbol directions are stored in Upstash Redis so the next run can flag direction changes; each run is archived to Supabase `analysis_history`. A failed run does not overwrite the previous memory.

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
- **AI model**: Google Gemini (`gemini-3.8-flash`, fallback `gemini-3.1-flash-lite-preview`), summarization only
- **News search**: Tavily (free tier: 1,000 credits/month)
- **Memory store**: Upstash Redis
- **Notifications**: Telegram Bot API

## Environment Variables

| Variable                    | Description                          |
|-----------------------------|--------------------------------------|
| `GEMINI_API_KEY`            | Google Gemini API key                |
| `GEMINI_MODEL`              | Optional, defaults to `gemini-3.8-flash` |
| `GEMINI_FALLBACK_MODEL`     | Optional, tried on quota/availability errors; defaults to `gemini-3.1-flash-lite-preview` |
| `TAVILY_API_KEY`            | Tavily API key (news search) |
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
4. `vercel.json` schedules **two runs a day** via Vercel Cron: 23:00 UTC (07:00 Kuala Lumpur, after the US close) and 12:00 UTC (20:00 Kuala Lumpur, before the US open). Vercel sends `Authorization: Bearer <CRON_SECRET>` automatically. If you used an external scheduler before, disable it to avoid duplicate runs; it can still call:
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
| `GET`  | `/api/memory`               | Latest brief (full report + sources) |
| `GET`  | `/api/history`              | Archived runs from Supabase |

## Report Structure

Telegram brief (full version on the dashboard):

```
🎯 Headline [sentiment]
🌍 Market News       up to 5 items: what happened → which assets, which direction
🧭 Direction (1–5d)  🟢 bullish / 🔴 bearish / ⚪ neutral per symbol, confidence, driving news, 🔄 on change
📅 Next 5 Days       earnings, central banks, data releases
👀 Watch
🔗 Sources
```

Search budget: each run uses 3 + (number of watchlist symbols) Tavily credits. At two runs a day an 8-symbol watchlist uses about 660 of the 1,000 free monthly credits; above roughly 13 symbols the free tier runs out.

## Tests

```bash
pip install -r requirements.txt pytest httpx
pytest tests
```
