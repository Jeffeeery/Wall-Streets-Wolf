export interface SymbolSnapshot {
  name?: string | null;
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

export type Direction = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Level = "HIGH" | "MEDIUM" | "LOW";
export type Sentiment = "RISK_ON" | "RISK_OFF" | "MIXED";

export interface SourceLink {
  id: string;
  title: string;
  uri: string;
  domain?: string;
}

export interface NewsItem {
  title: string;
  summary: string;
  impact?: string;
  importance?: Level;
  links: SourceLink[];
}

export interface OutlookItem {
  symbol: string;
  direction: Direction;
  confidence: Level;
  drivers: string;
  explains_move?: string;
  links: SourceLink[];
  prev?: Direction | null;
}

export interface UpcomingItem {
  date: string;
  event: string;
  affects?: string;
  why?: string;
  links?: SourceLink[];
}

export interface Brief {
  headline: string;
  sentiment: Sentiment;
  changes?: string;
  market_news: NewsItem[];
  outlook: OutlookItem[];
  upcoming: UpcomingItem[];
  watch: string[];
}

export interface MarcusMemory {
  time?: string;
  conclusion?: string;
  sentiment?: Sentiment | null;
  report?: string;
  snapshot?: Record<string, number>;
  sources?: SourceLink[];
  outlook?: Record<string, Direction>;
  brief?: Brief;
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
  sentiment?: Sentiment | null;
  brief?: Brief | null;
}

export interface HistoryResponse {
  history: HistoryRecord[];
}
