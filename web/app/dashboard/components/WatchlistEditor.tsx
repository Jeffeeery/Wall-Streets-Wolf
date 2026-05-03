"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchWatchlist, saveWatchlist } from "@/lib/api";

export default function WatchlistEditor() {
  const { data, mutate } = useSWR("watchlist", fetchWatchlist);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const symbols = data?.watchlist ?? [];

  const handleAdd = async () => {
    const sym = input.trim().toUpperCase();
    if (!sym || symbols.includes(sym)) {
      setInput("");
      return;
    }
    const next = [...symbols, sym];
    setError(null);
    setSaving(true);
    try {
      await saveWatchlist(next);
      await mutate();
      setInput("");
    } catch {
      setError("Failed to save — check backend connection.");
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (sym: string) => {
    const next = symbols.filter((s) => s !== sym);
    if (next.length === 0) return;
    setSaving(true);
    try {
      await saveWatchlist(next);
      await mutate();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col gap-3">
      <span className="text-xs text-gray-400 uppercase tracking-wider">
        Watchlist Config
      </span>

      <div className="flex flex-wrap gap-2">
        {symbols.map((s) => (
          <span
            key={s}
            className="flex items-center gap-1 bg-gray-800 text-gray-200 text-xs font-mono px-2 py-1 rounded"
          >
            {s}
            <button
              onClick={() => handleRemove(s)}
              className="text-gray-500 hover:text-red-400 ml-1 transition-colors"
              aria-label={`Remove ${s}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Add symbol… e.g. MYEG.KL"
          className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 text-xs font-mono px-3 py-2 rounded placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <button
          onClick={handleAdd}
          disabled={saving}
          className="bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-mono px-4 py-2 rounded disabled:opacity-50 transition-colors"
        >
          {saving ? "…" : "Add"}
        </button>
      </div>

      {error && <p className="text-red-400 text-xs">{error}</p>}
      <p className="text-gray-600 text-xs">
        Changes persist to Redis and are used on the next analysis run.
      </p>
    </div>
  );
}
