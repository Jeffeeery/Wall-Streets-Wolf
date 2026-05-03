import MarketGrid from "./components/MarketGrid";
import CandleChart from "./components/CandleChart";
import AgentLogPanel from "./components/AgentLogPanel";
import WatchlistEditor from "./components/WatchlistEditor";

export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-6 max-w-[1600px] mx-auto">
      <section>
        <h2 className="text-xs text-gray-500 uppercase tracking-widest mb-3">
          Market Snapshot · Auto-refreshes every 60s
        </h2>
        <MarketGrid />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <CandleChart />
        </div>
        <div className="lg:col-span-1">
          <AgentLogPanel />
        </div>
      </section>

      <section>
        <WatchlistEditor />
      </section>
    </div>
  );
}
