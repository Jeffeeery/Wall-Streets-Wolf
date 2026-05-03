export interface SymbolSnapshot {
  price: number;
  pct_change: number;
  RSI_14: number;
  above_MA200: boolean;
  above_MA50: boolean;
  ma_trend: "UP" | "DOWN" | "FLAT";
  vol_ratio: number;
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
  report?: string;
  snapshot?: Record<string, number>;
  message?: string;
}

export interface WatchlistResponse {
  watchlist: string[];
}
