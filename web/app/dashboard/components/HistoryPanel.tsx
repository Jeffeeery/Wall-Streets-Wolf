"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchHistory } from "@/lib/api";
import type { HistoryRecord } from "@/lib/types";

function HistoryEntry({ record }: { record: HistoryRecord }) {
  const [expanded, setExpanded] = useState(false);

  const date = new Date(record.created_at);
  const label = date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="border border-gray-800 rounded-lg bg-gray-900 overflow-hidden">
      <button
        className="w-full flex items-start gap-3 p-3 text-left hover:bg-gray-800/50 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="text-gray-500 font-mono text-xs mt-0.5 shrink-0">
          {label}
        </span>
        <span className="text-emerald-300 text-xs font-mono leading-relaxed flex-1">
          {record.conclusion}
        </span>
        <span className="text-gray-600 text-xs shrink-0">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-gray-800">
          <div className="bg-[#0a0e17] rounded p-3 mt-2 text-xs text-gray-300 font-mono leading-relaxed whitespace-pre-wrap">
            {record.report}
          </div>

          {record.snapshot && Object.keys(record.snapshot).length > 0 && (
            <div className="grid grid-cols-2 gap-1 mt-2">
              {Object.entries(record.snapshot).map(([sym, price]) => (
                <div
                  key={sym}
                  className="text-xs font-mono flex justify-between bg-gray-800 px-2 py-1 rounded"
                >
                  <span className="text-gray-400">{sym}</span>
                  <span className="text-gray-200">{price}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function HistoryPanel() {
  const { data, isLoading, error, mutate } = useSWR(
    "history",
    () => fetchHistory(30),
    { refreshInterval: 120_000 }
  );

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 uppercase tracking-wider">
          Analysis History
        </span>
        <button
          onClick={() => mutate()}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {isLoading && (
        <p className="text-gray-500 text-xs animate-pulse">Loading history…</p>
      )}
      {error && (
        <p className="text-red-400 text-xs">Error: {error.message}</p>
      )}

      {data && !isLoading && (
        <>
          {data.history.length === 0 ? (
            <p className="text-gray-500 text-xs italic">
              No history yet. Marcus will populate this after his next analysis.
            </p>
          ) : (
            <div className="flex flex-col gap-2 max-h-[600px] overflow-y-auto pr-1">
              {data.history.map((record) => (
                <HistoryEntry key={record.id} record={record} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
