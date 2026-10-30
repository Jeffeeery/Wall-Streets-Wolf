"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { fetchChartData } from "@/lib/api";
import type { Candle, MarketSnapshot } from "@/lib/types";
import { numTone, shortName } from "@/lib/brief";
import { formatPct, formatPrice } from "@/lib/format";

const UP = "#1E5E3B", DOWN = "#8C1D18", GRID = "#E2DDD3", TEXT = "#8a857b", INK = "#141414";
const label = (v: number) => formatPrice(v).replace(/\.00$/, "");

/** 日线蜡烛图：画布宽度跟随容器，字号不会被缩放 */
function Candles({ candles, width }: { candles: Candle[]; width: number }) {
  const h = width < 600 ? 220 : 300, padR = 66, padB = 22, w = Math.max(width, 280);
  const lo = Math.min(...candles.map((c) => c.low)), hi = Math.max(...candles.map((c) => c.high));
  const pad = (hi - lo) * 0.06, L = lo - pad, H = hi + pad;
  const cw = (w - padR) / candles.length;
  const y = (v: number) => ((H - v) / (H - L)) * (h - padB);
  const raw = (H - L) / 4, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let v = Math.ceil(L / step) * step; v <= H; v += step) ticks.push(v);
  const months: { x: number; m: number }[] = [];
  candles.forEach((c, i) => {
    const m = new Date(c.time * 1000).getUTCMonth();
    if (i > 2 && m !== new Date(candles[i - 1].time * 1000).getUTCMonth()) months.push({ x: i * cw, m });
  });
  const last = candles[candles.length - 1].close, ly = y(last);
  return (
    <svg className="candles" viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label="日线走势">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={0} x2={w - padR} y1={y(v)} y2={y(v)} stroke={GRID} />
          <text x={w - padR + 8} y={y(v) + 4} fill={TEXT} fontSize="11">{label(v)}</text>
        </g>
      ))}
      {months.map((m) => (
        <text key={m.x} x={m.x} y={h - 6} fill={TEXT} fontSize="11">{m.m + 1}月</text>
      ))}
      {candles.map((c, i) => {
        const col = c.close >= c.open ? UP : DOWN, x = i * cw + cw / 2, bw = Math.max(1.5, cw * 0.62);
        return (
          <g key={c.time}>
            <line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} stroke={col} />
            <rect x={x - bw / 2} y={y(Math.max(c.open, c.close))} width={bw} height={Math.max(1, Math.abs(y(c.open) - y(c.close)))} fill={col} />
          </g>
        );
      })}
      <line x1={0} x2={w - padR} y1={ly} y2={ly} stroke={INK} strokeDasharray="2 3" />
      <rect x={w - padR + 2} y={ly - 9} width={padR - 4} height={18} fill={INK} />
      <text x={w - padR + 7} y={ly + 4} fill="#fff" fontSize="11" fontWeight="600">{label(last)}</text>
    </svg>
  );
}

export default function ChartSection({
  symbols,
  selected,
  onSelect,
  market,
}: {
  symbols: string[];
  selected: string | null;
  onSelect: (s: string) => void;
  market?: MarketSnapshot;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const { data, error, isLoading } = useSWR(selected ? ["chart", selected] : null, () => fetchChartData(selected!), {
    revalidateOnFocus: false,
    dedupingInterval: 600_000,
  });
  const s = selected ? market?.[selected] : undefined;

  return (
    <section className="sec">
      <div className="sech">
        <h3>走势</h3>
        <div className="tabs" role="tablist">
          {symbols.map((sym) => (
            <button key={sym} type="button" role="tab" aria-selected={sym === selected} className={sym === selected ? "on" : ""} onClick={() => onSelect(sym)}>
              {shortName(sym)}
            </button>
          ))}
        </div>
      </div>
      <div className="chart" ref={box}>
        {isLoading && <p className="state">正在加载走势…</p>}
        {error && <p className="state">走势暂时加载不了。</p>}
        {data && data.candles.length > 0 && width > 0 && <Candles candles={data.candles} width={width} />}
      </div>
      {data && s && (
        <div className="cap">
          {s.name ?? selected} · 日线 · 近 {data.candles.length} 个交易日 · 最新 {formatPrice(s.price)}{" "}
          <span className={numTone(s.pct_change)}>{formatPct(s.pct_change)}</span>
        </div>
      )}
    </section>
  );
}
