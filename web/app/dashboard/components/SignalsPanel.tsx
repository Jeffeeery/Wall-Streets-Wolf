"use client";
import useSWR from "swr";
import { fetchSignals } from "@/lib/api";
import type { Signal, SignalStats, SignalStatus } from "@/lib/types";

const STATUS: Record<SignalStatus, { label: string; cls: string }> = {
  PENDING: { label: "待触发", cls: "text-gray-400" },
  OPEN: { label: "持仓中", cls: "text-sky-400" },
  WIN: { label: "止盈", cls: "text-emerald-400" },
  LOSS: { label: "止损", cls: "text-red-400" },
  EXPIRED: { label: "到期", cls: "text-yellow-400" },
  NOT_TRIGGERED: { label: "未触发", cls: "text-gray-600" },
};

const CONF: Record<string, string> = { HIGH: "高", MEDIUM: "中", LOW: "低" };

function Stat({ label, value, cls = "text-gray-100" }: { label: string; value: string; cls?: string }) {
  return (
    <div className="bg-gray-800 rounded px-3 py-2">
      <div className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</div>
      <div className={`text-lg font-mono font-bold ${cls}`}>{value}</div>
    </div>
  );
}

function StatsRow({ stats }: { stats: SignalStats }) {
  const r = (v: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}R`);
  const tone = (v: number | null) =>
    v == null ? "text-gray-400" : v >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
      <Stat label="已结算" value={String(stats.closed)} />
      <Stat label="胜率" value={stats.win_rate == null ? "—" : `${stats.win_rate}%`} />
      <Stat label="平均 R" value={r(stats.avg_r)} cls={tone(stats.avg_r)} />
      <Stat label="累计 R" value={r(stats.total_r)} cls={tone(stats.total_r)} />
      <Stat label="进行中 / 未触发" value={`${stats.open} / ${stats.not_triggered}`} />
    </div>
  );
}

function SignalRow({ s }: { s: Signal }) {
  const st = STATUS[s.status];
  const date = new Date(s.created_ts * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <tr className="border-t border-gray-800 align-top" title={s.rationale}>
      <td className="py-1.5 pr-3 text-gray-500">{date}</td>
      <td className="pr-3 text-gray-100 font-bold">{s.symbol}</td>
      <td className={`pr-3 ${s.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>
        {s.direction === "LONG" ? "多" : "空"}
      </td>
      <td className="pr-3">{s.entry}</td>
      <td className="pr-3 text-red-300">{s.stop}</td>
      <td className="pr-3 text-emerald-300">{s.target}</td>
      <td className="pr-3">{s.rr}</td>
      <td className="pr-3">{CONF[s.confidence]}</td>
      <td className={`pr-3 ${st.cls}`}>{st.label}</td>
      <td className="pr-3">
        {s.r_multiple == null ? "—" : `${s.r_multiple >= 0 ? "+" : ""}${s.r_multiple.toFixed(2)}`}
      </td>
    </tr>
  );
}

export default function SignalsPanel() {
  const { data, isLoading, error } = useSWR("signals", () => fetchSignals(50), {
    refreshInterval: 120_000,
  });

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-3">
      {isLoading && <p className="text-gray-500 text-xs animate-pulse">Loading signals…</p>}
      {error && <p className="text-red-400 text-xs">Error: {error.message}</p>}
      {data && !isLoading && (
        <>
          <StatsRow stats={data.stats} />
          {data.signals.length === 0 ? (
            <p className="text-gray-500 text-xs italic">
              No signals yet. Marcus only issues a signal when the setup passes risk checks.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono whitespace-nowrap text-gray-300">
                <thead>
                  <tr className="text-gray-500 text-left">
                    <th className="pr-3 pb-1 font-normal">时间</th>
                    <th className="pr-3 font-normal">品种</th>
                    <th className="pr-3 font-normal">方向</th>
                    <th className="pr-3 font-normal">入场</th>
                    <th className="pr-3 font-normal">止损</th>
                    <th className="pr-3 font-normal">目标</th>
                    <th className="pr-3 font-normal">R:R</th>
                    <th className="pr-3 font-normal">置信</th>
                    <th className="pr-3 font-normal">状态</th>
                    <th className="pr-3 font-normal">结果 R</th>
                  </tr>
                </thead>
                <tbody>
                  {data.signals.map((s) => (
                    <SignalRow key={s.id} s={s} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
