"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import type { Vela as VelaChart, VelaTheme } from "@luxalgo/vela";
import { fetchChartData, fetchSnapshot } from "@/lib/api";
import { formatPct, formatPrice, toneOf } from "@/lib/format";
import { Card } from "./ui";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** 用页面的颜色变量生成 Vela 主题，跟随浅色/深色模式 */
function pageTheme(): VelaTheme {
  return {
    background: cssVar("--surface"),
    textColor: cssVar("--muted"),
    gridColor: cssVar("--line"),
    borderColor: cssVar("--line"),
    upColor: cssVar("--bull"),
    downColor: cssVar("--bear"),
    fontFamily: getComputedStyle(document.body).fontFamily,
  };
}

export default function PriceChart({ symbol }: { symbol: string | null }) {
  const { data, error, isLoading } = useSWR(symbol ? ["chart", symbol] : null, () => fetchChartData(symbol!), {
    revalidateOnFocus: false,
  });
  const { data: market } = useSWR("snapshot", fetchSnapshot, { refreshInterval: 300_000 });
  const ref = useRef<HTMLDivElement>(null);
  const [chartError, setChartError] = useState(false);

  useEffect(() => {
    if (!data || !ref.current) return;
    const el = ref.current;
    let chart: VelaChart | null = null;
    let disposed = false;
    setChartError(false);

    const bars = data.candles.map((c) => ({
      time: c.time * 1000, // 后端是秒，Vela 要毫秒
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
      volume: c.volume,
    }));

    // Vela 依赖 WebGL/Canvas，只能在浏览器里加载
    Promise.all([import("@luxalgo/vela"), import("@luxalgo/vela/locales/zh-Hans")])
      .then(([{ Vela, registerLocale }, { default: zhHans }]) => {
        if (disposed) return;
        registerLocale(zhHans);
        const theme = pageTheme();
        chart = new Vela(el, {
          data: bars,
          timeframe: "D",
          theme,
          upColor: theme.upColor,
          downColor: theme.downColor,
          locale: "zh-Hans",
          drawings: false,
          volume: bars.some((b) => b.volume > 0),
          animations: { intro: false },
        });
      })
      .catch((e) => {
        console.error("Vela 初始化失败", e);
        if (!disposed) setChartError(true);
      });

    // 跟随系统深浅色切换
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onScheme = () => chart?.setTheme(pageTheme());
    media.addEventListener("change", onScheme);
    const resizeObs = new ResizeObserver(() => chart?.resize());
    resizeObs.observe(el);

    return () => {
      disposed = true;
      media.removeEventListener("change", onScheme);
      resizeObs.disconnect();
      chart?.destroy();
    };
  }, [data]);

  const d = symbol ? market?.[symbol] : undefined;
  const overlay = !symbol
    ? "在自选里选一个品种"
    : error || chartError
      ? "走势图加载失败"
      : isLoading
        ? "加载中…"
        : null;

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
      <div className="relative h-72 overflow-hidden rounded-lg">
        <div ref={ref} className="absolute inset-0" />
        {overlay && (
          <p className="absolute inset-0 flex items-center justify-center bg-surface text-sm text-muted">{overlay}</p>
        )}
      </div>
      <p className="mt-1 text-xs text-muted">近 90 个交易日 · 日线 · 可拖动和缩放</p>
    </Card>
  );
}
