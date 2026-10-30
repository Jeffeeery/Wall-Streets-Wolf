"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchWatchlist } from "@/lib/api";
import BriefView from "./BriefView";
import HistoryList from "./HistoryList";
import PriceChart from "./PriceChart";
import WatchlistPanel from "./WatchlistPanel";

export default function Dashboard() {
  const { data: wl } = useSWR("watchlist", fetchWatchlist);
  const [picked, setPicked] = useState<string | null>(null);
  // 默认显示自选第一个；被移除后自动回落
  const symbols = wl?.watchlist ?? [];
  const selected = picked && symbols.includes(picked) ? picked : symbols[0] ?? null;

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <BriefView />
        <aside className="space-y-6">
          <WatchlistPanel selected={selected} onSelect={setPicked} />
          <PriceChart symbol={selected} />
        </aside>
      </div>
      <HistoryList />
    </div>
  );
}
