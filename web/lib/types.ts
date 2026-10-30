export interface SymbolSnapshot {
  price: number;
  pct_change: number;
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
  regime?: string | null;
  report?: string;
  snapshot?: Record<string, number>;
  message?: string;
}

export type SignalStatus =
  | "PENDING"
  | "OPEN"
  | "WIN"
  | "LOSS"
  | "EXPIRED"
  | "NOT_TRIGGERED";

export interface Signal {
  id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  entry: number;
  stop: number;
  target: number;
  rr: number;
  horizon_days: number;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  rationale: string;
  invalidation: string;
  created_ts: number;
  expires_ts: number;
  status: SignalStatus;
  fill_price: number | null;
  exit_price: number | null;
  r_multiple: number | null;
}

export interface SignalStats {
  closed: number;
  open: number;
  not_triggered: number;
  win_rate: number | null;
  avg_r: number | null;
  total_r: number;
  by_confidence: Record<string, { n: number; win_rate: number; avg_r: number }>;
}

export interface SignalsResponse {
  signals: Signal[];
  stats: SignalStats;
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
