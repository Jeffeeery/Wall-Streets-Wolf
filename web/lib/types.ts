export interface SymbolSnapshot {
  price: number;
  pct_change: number;
  ret_5d?: number | null;
  RSI_14: number;
  above_MA200: boolean;
  above_MA50: boolean;
  ma_trend: "UP" | "DOWN" | "FLAT";
  vol_ratio: number | null;
  ATR_14: number;
}

export type MarketSnapshot = Record<string, SymbolSnapshot>;

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface RsiPoint {
  time: number;
  value: number;
}

export interface ChartData {
  symbol: string;
  candles: Candle[];
  rsi: RsiPoint[];
}

export interface MarcusMemory {
  time?: string;
  conclusion?: string;
  sentiment?: string | null;
  report?: string;
  snapshot?: Record<string, number>;
  sources?: { title: string; uri: string }[];
  outlook?: Record<string, "BULLISH" | "BEARISH" | "NEUTRAL">;
  message?: string;
}

export interface WatchlistResponse {
  watchlist: string[];
}

export interface HistoryRecord {
  id: number;
  created_at: string;
  analysis_time: string;
  conclusion: string;
  report: string;
  snapshot: Record<string, number> | null;
}

export interface HistoryResponse {
  history: HistoryRecord[];
}
