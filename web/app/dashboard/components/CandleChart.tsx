"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  createChart,
  ColorType,
  LineStyle,
  CandlestickSeries,
  LineSeries,
} from "lightweight-charts";
import { fetchChartData, fetchWatchlist } from "@/lib/api";

export default function CandleChart() {
  const [symbol, setSymbol] = useState("^GSPC");
  const { data: wlData } = useSWR("watchlist", fetchWatchlist);
  const { data, isLoading } = useSWR(
    ["chart", symbol],
    () => fetchChartData(symbol),
    { revalidateOnFocus: false }
  );

  const containerRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || !containerRef.current || !rsiRef.current) return;

    const opts = {
      layout: {
        background: { type: ColorType.Solid, color: "#111827" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      rightPriceScale: { borderColor: "#1f2937" },
      timeScale: { borderColor: "#1f2937", timeVisible: true },
    };

    const mainChart = createChart(containerRef.current, {
      ...opts,
      height: 260,
    });
    const rsiChart = createChart(rsiRef.current, { ...opts, height: 100 });

    const candleSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });
    candleSeries.setData(
      data.candles.map((c) => ({
        time: c.time as unknown as string,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );

    const rsiSeries = rsiChart.addSeries(LineSeries, {
      color: "#3b82f6",
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
    });
    rsiSeries.setData(
      data.rsi.map((r) => ({
        time: r.time as unknown as string,
        value: r.value,
      }))
    );
    rsiSeries.createPriceLine({
      price: 70,
      color: "#ef4444",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: "OB",
      axisLabelVisible: false,
    });
    rsiSeries.createPriceLine({
      price: 30,
      color: "#10b981",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: "OS",
      axisLabelVisible: false,
    });

    mainChart.timeScale().fitContent();
    rsiChart.timeScale().fitContent();

    const resizeObs = new ResizeObserver(() => {
      if (containerRef.current)
        mainChart.applyOptions({ width: containerRef.current.clientWidth });
      if (rsiRef.current)
        rsiChart.applyOptions({ width: rsiRef.current.clientWidth });
    });
    if (containerRef.current) resizeObs.observe(containerRef.current);

    return () => {
      resizeObs.disconnect();
      mainChart.remove();
      rsiChart.remove();
    };
  }, [data]);

  const watchlist = wlData?.watchlist ?? ["^GSPC", "NVDA", "AAPL", "BTC-USD"];

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <span className="text-xs text-gray-400 uppercase tracking-wider">
          Chart
        </span>
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="bg-gray-800 text-gray-100 text-sm border border-gray-700 rounded px-2 py-1 font-mono"
        >
          {watchlist.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {isLoading && (
          <span className="text-xs text-gray-500 animate-pulse">
            Loading…
          </span>
        )}
      </div>

      <div ref={containerRef} className="w-full" />
      <div className="text-xs text-gray-500 pl-1">RSI (14)</div>
      <div ref={rsiRef} className="w-full" />
    </div>
  );
}
