"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchMemory, fetchSnapshot, fetchWatchlist, saveWatchlist } from "@/lib/api";
import { formatPct, formatPrice, toneOf } from "@/lib/format";
import { Card, DirectionBadge, SectionTitle } from "./ui";

export default function WatchlistPanel({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (symbol: string) => void;
}) {
  const { data: wl, mutate: mutateWl } = useSWR("watchlist", fetchWatchlist);
  const { data: market, error, isLoading, mutate: mutateMarket } = useSWR("snapshot", fetchSnapshot, {
    refreshInterval: 300_000,
  });
  const { data: memory } = useSWR("memory", fetchMemory, { refreshInterval: 60_000 });

  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const symbols = wl?.watchlist ?? [];
  const outlook = memory?.outlook ?? {};

  const save = async (next: string[]) => {
    setSaving(true);
    setMessage(null);
    try {
      await saveWatchlist(next);
      await mutateWl();
      mutateMarket();
      return true;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "保存失败，请稍后再试");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const add = async () => {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    if (symbols.includes(sym)) {
      setMessage(`${sym} 已经在自选里了`);
      return;
    }
    if (await save([...symbols, sym])) setInput("");
  };

  const remove = (sym: string) => {
    if (symbols.length <= 1) {
      setMessage("至少保留一个品种");
      return;
    }
    save(symbols.filter((s) => s !== sym));
  };

  return (
    <Card className="p-4">
      <SectionTitle
        aside={
          <button
            onClick={() => {
              setEditing((v) => !v);
              setMessage(null);
            }}
            className="rounded-md px-2 py-1 text-sm text-accent hover:bg-surface-2"
          >
            {editing ? "完成" : "编辑"}
          </button>
        }
      >
        自选
      </SectionTitle>

      {error && <p className="mb-2 text-sm text-muted">行情暂时拉取失败，稍后会自动重试。</p>}

      <ul className="-mx-2">
        {symbols.map((sym) => {
          const d = market?.[sym];
          const dir = outlook[sym];
          const active = sym === selected;
          return (
            <li key={sym} className="flex items-center">
              <button
                onClick={() => onSelect(sym)}
                aria-pressed={active}
                className={`flex min-w-0 flex-1 items-center gap-3 rounded-lg px-2 py-2 text-left ${
                  active ? "bg-surface-2" : "hover:bg-surface-2"
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{sym}</span>
                  <span className="block truncate text-xs text-muted">
                    {d?.name ?? (isLoading ? "加载中…" : "暂无数据")}
                  </span>
                </span>
                {dir && !editing && <DirectionBadge direction={dir} />}
                <span className="num w-24 shrink-0 text-right">
                  <span className="block text-sm">{formatPrice(d?.price)}</span>
                  <span className={`block text-xs ${toneOf(d?.pct_change)}`}>{formatPct(d?.pct_change)}</span>
                </span>
              </button>
              {editing && (
                <button
                  onClick={() => remove(sym)}
                  disabled={saving}
                  aria-label={`移除 ${sym}`}
                  className="ml-1 rounded-md px-2 py-1 text-sm text-bear hover:bg-bear-soft disabled:opacity-50"
                >
                  移除
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {editing && (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Yahoo 代码，如 AAPL、0700.HK、BTC-USD"
            className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm placeholder:text-muted focus:border-accent focus:outline-none"
          />
          <button
            type="submit"
            disabled={saving || !input.trim()}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            添加
          </button>
        </form>
      )}
      {message && <p className="mt-2 text-sm text-bear">{message}</p>}
      {editing && <p className="mt-2 text-xs text-muted">改动会在下一次简报生效。</p>}
    </Card>
  );
}
