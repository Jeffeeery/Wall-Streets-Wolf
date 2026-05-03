"use client";
import useSWR from "swr";
import { fetchMemory } from "@/lib/api";

export default function AgentLogPanel() {
  const { data, isLoading, error, mutate } = useSWR("memory", fetchMemory, {
    refreshInterval: 30_000,
  });

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-3 h-full">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 uppercase tracking-wider">
          Agent Log · Marcus Wolf
        </span>
        <button
          onClick={() => mutate()}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          ↻ Refresh
        </button>
      </div>

      {isLoading && (
        <p className="text-gray-500 text-xs animate-pulse">Fetching memory…</p>
      )}
      {error && (
        <p className="text-red-400 text-xs">Error: {error.message}</p>
      )}

      {data && !isLoading && (
        <>
          {data.message ? (
            <p className="text-gray-500 text-xs italic">{data.message}</p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-xs text-gray-400 font-mono">
                  {data.time}
                </span>
              </div>

              <div className="bg-gray-800 rounded p-3 text-xs text-emerald-300 font-mono leading-relaxed">
                {data.conclusion}
              </div>

              <div className="mt-2">
                <p className="text-xs text-gray-500 mb-1 uppercase tracking-wider">
                  Full Report
                </p>
                <div className="bg-[#0a0e17] rounded p-3 text-xs text-gray-300 font-mono leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap">
                  {data.report}
                </div>
              </div>

              {data.snapshot && (
                <div className="mt-2">
                  <p className="text-xs text-gray-500 mb-1 uppercase tracking-wider">
                    Snapshot at time of analysis
                  </p>
                  <div className="grid grid-cols-2 gap-1">
                    {Object.entries(data.snapshot).map(([sym, price]) => (
                      <div
                        key={sym}
                        className="text-xs font-mono flex justify-between bg-gray-800 px-2 py-1 rounded"
                      >
                        <span className="text-gray-400">{sym}</span>
                        <span className="text-gray-200">{price}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
