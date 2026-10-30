"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import type { OHLCV, Vela as VelaChart, VelaTheme, VisibleRange } from "@luxalgo/vela";
import { fetchChartData } from "@/lib/api";
import type { ChartData, MarketSnapshot, Timeframe } from "@/lib/types";
import { numTone, shortName } from "@/lib/brief";
import { formatPct, formatPrice } from "@/lib/format";

const TIMEFRAMES: { tf: Timeframe; label: string; unit: string }[] = [
  { tf: "15", label: "15分", unit: "15 分钟线" },
  { tf: "60", label: "1小时", unit: "小时线" },
  { tf: "D", label: "日", unit: "日线" },
  { tf: "W", label: "周", unit: "周线" },
];

/** 报纸版配色：纸色底、绿涨红跌 */
const THEME: VelaTheme = {
  background: "#f5f3ee",
  textColor: "#8a857b",
  gridColor: "#e2ddd3",
  borderColor: "#d3cec4",
  upColor: "#1e5e3b",
  downColor: "#8c1d18",
  fontFamily: '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
};

const toBars = (data: ChartData): OHLCV[] =>
  data.candles.map((c) => ({
    time: c.time * 1000, // 后端是秒，Vela 要毫秒
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume,
  }));

/** 切换品种/周期时回到最近一段行情（约 120 根），更早的拖动查看 */
const VISIBLE_BARS = 120;
function recentRange(bars: OHLCV[]): VisibleRange {
  const first = bars[Math.max(0, bars.length - VISIBLE_BARS)].time;
  const last = bars[bars.length - 1].time;
  const step = bars.length > 1 ? last - bars[bars.length - 2].time : 0;
  return { from: first, to: last + step * 3 }; // 右侧留几根的空白，最新一根不贴边
}

/** Vela 依赖 WebGL/Canvas，只在浏览器里按需加载一次 */
let velaModule: Promise<typeof import("@luxalgo/vela")> | null = null;
function loadVela() {
  velaModule ??= Promise.all([import("@luxalgo/vela"), import("@luxalgo/vela/locales/zh-Hans")]).then(
    ([mod, { default: zhHans }]) => {
      mod.registerLocale(zhHans);
      return mod;
    }
  );
  return velaModule;
}

function VelaCandles({ data }: { data: ChartData }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<VelaChart | null>(null);
  const [failed, setFailed] = useState(false);

  // 创建一次，组件卸载时销毁
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.current?.destroy();
      chart.current = null;
    };
  }, []);

  // 换品种或周期时原地切换数据，不重建图表
  useEffect(() => {
    let cancelled = false;
    const bars = toBars(data);
    const hasVolume = bars.some((b) => (b.volume ?? 0) > 0);
    loadVela()
      .then(({ Vela }) => {
        if (cancelled || !box.current) return;
        if (!chart.current) {
          chart.current = new Vela(box.current, {
            data: bars,
            timeframe: data.tf,
            visibleRange: recentRange(bars),
            theme: THEME,
            upColor: THEME.upColor,
            downColor: THEME.downColor,
            locale: "zh-Hans",
            drawings: false,
            volume: hasVolume,
            animations: { intro: false },
          });
        } else {
          chart.current.setMarket({ data: bars, timeframe: data.tf, visibleRange: recentRange(bars) });
        }
        setFailed(false);
      })
      .catch((e) => {
        console.error("Vela 初始化失败", e);
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [data]);

  return (
    <div className="vela">
      <div ref={box} className="vela-box" />
      {failed && <p className="state vela-over">走势图加载失败，请刷新重试。</p>}
    </div>
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
  const [tf, setTf] = useState<Timeframe>("D");
  const { data, error, isLoading } = useSWR(
    selected ? ["chart", selected, tf] : null,
    () => fetchChartData(selected!, tf),
    { revalidateOnFocus: false, dedupingInterval: 600_000, keepPreviousData: true }
  );
  const s = selected ? market?.[selected] : undefined;
  const unit = TIMEFRAMES.find((t) => t.tf === (data?.tf ?? tf))?.unit;

  return (
    <section className="sec">
      <div className="sech">
        <h3>走势</h3>
        <div className="tabs" role="tablist" aria-label="品种">
          {symbols.map((sym) => (
            <button key={sym} type="button" role="tab" aria-selected={sym === selected} className={sym === selected ? "on" : ""} onClick={() => onSelect(sym)}>
              {shortName(sym)}
            </button>
          ))}
        </div>
      </div>
      <div className="tfbar">
        <div className="tfs" role="radiogroup" aria-label="周期">
          {TIMEFRAMES.map((t) => (
            <button key={t.tf} type="button" role="radio" aria-checked={t.tf === tf} className={t.tf === tf ? "on" : ""} onClick={() => setTf(t.tf)}>
              {t.label}
            </button>
          ))}
        </div>
        <span className="hint">{isLoading ? "加载中…" : "拖动平移 · 滚轮或双指缩放"}</span>
      </div>
      <div className="chart">
        {!data && isLoading && <p className="state">正在加载走势…</p>}
        {error && !data && <p className="state">走势暂时加载不了。</p>}
        {data && data.candles.length === 0 && <p className="state">这个周期暂时没有数据。</p>}
        {data && data.candles.length > 0 && <VelaCandles data={data} />}
      </div>
      {data && s && (
        <div className="cap">
          {s.name ?? selected} · {unit} · 共 {data.candles.length} 根 K 线 · 最新 {formatPrice(s.price)}{" "}
          <span className={numTone(s.pct_change)}>{formatPct(s.pct_change)}</span>
        </div>
      )}
    </section>
  );
}
