"use client";
import useSWR from "swr";
import { fetchSnapshot } from "@/lib/api";
import type { SymbolSnapshot } from "@/lib/types";

function RSIBadge({ value }: { value: number }) {
  const color =
    value >= 70
      ? "text-red-400"
      : value <= 30
      ? "text-emerald-400"
      : "text-yellow-400";
  const label =
    value >= 70 ? "OVERBOUGHT" : value <= 30 ? "OVERSOLD" : "NEUTRAL";
  return (
    <span className={`text-xs font-mono ${color}`}>
      RSI {value.toFixed(1)} · {label}
    </span>
  );
}

function TrendBadge({ trend }: { trend: "UP" | "DOWN" | "FLAT" }) {
  const map = {
    UP: { cls: "bg-emerald-900 text-emerald-300", label: "▲ UP" },
    DOWN: { cls: "bg-red-900 text-red-300", label: "▼ DOWN" },
    FLAT: { cls: "bg-gray-800 text-gray-400", label: "— FLAT" },
  };
  const { cls, label } = map[trend];
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-mono ${cls}`}>
      {label}
    </span>
  );
}

function SymbolCard({
  symbol,
  data,
}: {
  symbol: string;
  data: SymbolSnapshot;
}) {
  const changeColor =
    data.pct_change >= 0 ? "text-emerald-400" : "text-red-400";
  const changeSign = data.pct_change >= 0 ? "+" : "";
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-2 hover:border-gray-600 transition-colors">
      <div className="flex items-center justify-between">
        <span className="font-bold text-sm tracking-wider text-gray-100">
          {symbol}
        </span>
        <TrendBadge trend={data.ma_trend} />
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-mono font-bold">
          {data.price.toLocaleString()}
        </span>
        <span className={`text-sm font-mono pb-0.5 ${changeColor}`}>
          {changeSign}
          {data.pct_change.toFixed(2)}%
        </span>
      </div>
      <RSIBadge value={data.RSI_14} />
      <div className="text-xs text-gray-500 flex gap-3">
        <span>Vol×{data.vol_ratio.toFixed(2)}</span>
        <span>ATR {data.ATR_14}</span>
        <span
          className={data.above_MA200 ? "text-emerald-500" : "text-red-500"}
        >
          {data.above_MA200 ? "↑MA200" : "↓MA200"}
        </span>
      </div>
    </div>
  );
}

export default function MarketGrid() {
  const { data, error, isLoading } = useSWR("snapshot", fetchSnapshot, {
    refreshInterval: 60_000,
  });

  if (isLoading)
    return (
      <div className="text-gray-500 text-sm animate-pulse">
        Loading market data…
      </div>
    );
  if (error)
    return (
      <div className="text-red-400 text-sm">
        Failed to load snapshot: {error.message}
      </div>
    );
  if (!data) return null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
      {Object.entries(data).map(([symbol, snap]) => (
        <SymbolCard key={symbol} symbol={symbol} data={snap} />
      ))}
    </div>
  );
}
