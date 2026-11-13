import type {
  MarketSnapshot,
  ChartData,
  Timeframe,
  MarcusMemory,
  WatchlistResponse,
  HistoryResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchSnapshot = () => get<MarketSnapshot>("/api/snapshot");

export const fetchChartData = (symbol: string, tf: Timeframe = "D") =>
  get<ChartData>(`/api/chart/${encodeURIComponent(symbol)}?tf=${tf}`);

export const fetchMemory = () => get<MarcusMemory>("/api/memory");

export const fetchWatchlist = () => get<WatchlistResponse>("/api/watchlist");

export const fetchHistory = (limit = 30) =>
  get<HistoryResponse>(`/api/history?limit=${limit}`);

/** 带 HTTP 状态码的错误，界面按状态码给出对应提示 */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function saveWatchlist(symbols: string[], token: string): Promise<void> {
  const res = await fetch(`${BASE}/api/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ symbols }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? "Failed to save watchlist");
  }
}
