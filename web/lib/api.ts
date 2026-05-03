import type {
  MarketSnapshot,
  ChartData,
  MarcusMemory,
  WatchlistResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { next: { revalidate: 0 } });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

export const fetchSnapshot = () => get<MarketSnapshot>("/api/snapshot");

export const fetchChartData = (symbol: string) =>
  get<ChartData>(`/api/chart/${encodeURIComponent(symbol)}`);

export const fetchMemory = () => get<MarcusMemory>("/api/memory");

export const fetchWatchlist = () => get<WatchlistResponse>("/api/watchlist");

export async function saveWatchlist(symbols: string[]): Promise<void> {
  const res = await fetch(`${BASE}/api/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbols }),
  });
  if (!res.ok) throw new Error("Failed to save watchlist");
}
