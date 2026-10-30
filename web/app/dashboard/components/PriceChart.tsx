"use client";
import { useEffect, useRef } from "react";
import useSWR from "swr";
import { CandlestickSeries, ColorType, createChart } from "lightweight-charts";
import { fetchChartData, fetchSnapshot } from "@/lib/api";
import { formatPct, formatPrice, toneOf } from "@/lib/format";
import { Card } from "./ui";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export default function PriceChart({ symbol }: { symbol: string | null }) {
  const { data, error, isLoading } = useSWR(symbol ? ["chart", symbol] : null, () => fetchChartData(symbol!), {
    revalidateOnFocus: false,
  });
  const { data: market } = useSWR("snapshot", fetchSnapshot, { refreshInterval: 300_000 });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || !ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: cssVar("--muted"),
      },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--line") } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      handleScroll: false,
      handleScale: false,
    });
    const up = cssVar("--bull");
    const down = cssVar("--bear");
    chart
      .addSeries(CandlestickSeries, {
        upColor: up,
        downColor: down,
        wickUpColor: up,
        wickDownColor: down,
        borderVisible: false,
      })
      .setData(
        data.candles.map((c) => ({
          time: c.time as unknown as string,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  const d = symbol ? market?.[symbol] : undefined;

  return (
    <Card className="p-4">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <span className="text-sm font-semibold">{symbol ?? "—"}</span>
          {d?.name && <span className="ml-2 truncate text-xs text-muted">{d.name}</span>}
        </div>
        <div className="num shrink-0 text-right text-sm">
          {formatPrice(d?.price)} <span className={toneOf(d?.pct_change)}>{formatPct(d?.pct_change)}</span>
        </div>
      </div>
      <div className="relative h-64">
        <div ref={ref} className="absolute inset-0" />
        {(isLoading || error || !symbol) && (
          <p className="absolute inset-0 flex items-center justify-center text-sm text-muted">
            {!symbol ? "在自选里选一个品种" : error ? "走势图加载失败" : "加载中…"}
          </p>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">近 90 个交易日 · 日线</p>
    </Card>
  );
}
