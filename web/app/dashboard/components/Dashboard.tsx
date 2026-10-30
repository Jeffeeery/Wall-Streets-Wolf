"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchMemory, fetchSnapshot, fetchWatchlist } from "@/lib/api";
import Almanac from "./Almanac";
import ChartSection from "./ChartSection";
import DirectionTable from "./DirectionTable";
import Lead from "./Lead";
import Masthead from "./Masthead";
import NewsSection from "./NewsSection";

export default function Dashboard() {
  const { data: memory, error, isLoading } = useSWR("memory", fetchMemory, { refreshInterval: 60_000 });
  const { data: market } = useSWR("snapshot", fetchSnapshot, { refreshInterval: 300_000 });
  const { data: wl } = useSWR("watchlist", fetchWatchlist);
  const [picked, setPicked] = useState<string | null>(null);

  const symbols = wl?.watchlist ?? [];
  // 默认看自选第一个；被移除后自动回落
  const selected = picked && symbols.includes(picked) ? picked : symbols[0] ?? null;
  const brief = memory?.brief;
  const ready = memory && !memory.message;

  return (
    <div className="page">
      <Masthead time={ready ? memory.time : undefined} />

      {isLoading && <p className="state pad">正在加载简报…</p>}
      {error && <p className="state pad">简报暂时加载不了，稍后会自动重试。</p>}
      {memory?.message && <p className="state pad">还没有简报。下一次定时运行后会出现在这里。</p>}

      {ready && <Lead memory={memory} />}
      {ready && brief && <NewsSection news={brief.market_news} symbols={symbols} />}
      {ready && !brief && memory.report && (
        // 旧版记忆没有结构化数据，退回显示文字报告
        <section className="sec">
          <p className="legacy">{memory.report}</p>
        </section>
      )}

      <DirectionTable outlook={brief?.outlook ?? []} market={market} selected={selected} onSelect={setPicked} />
      <ChartSection symbols={symbols} selected={selected} onSelect={setPicked} market={market} />
      <Almanac brief={brief} symbols={symbols} latestTime={memory?.time} />

      {memory?.sources && memory.sources.length > 0 && (
        <section className="notes" aria-label="来源">
          {memory.sources.map((s) => (
            <div key={s.id}>
              <b>{s.id.replace(/^S/, "")}</b>
              {s.title} —{" "}
              <a href={s.uri} target="_blank" rel="noopener noreferrer">
                {s.domain}
              </a>
            </div>
          ))}
        </section>
      )}
      <footer className="foot">
        <span>方向判断只基于公开新闻，不含技术面，不构成投资建议。</span>
        <span>Wall Street&apos;s Wolf</span>
      </footer>
    </div>
  );
}
