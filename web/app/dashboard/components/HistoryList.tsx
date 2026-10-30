"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchHistory } from "@/lib/api";
import type { HistoryRecord } from "@/lib/types";
import { formatRunTime } from "@/lib/format";
import BriefBody from "./BriefBody";
import { Card, Muted, SentimentPill } from "./ui";

const PAGE = 10;

function Entry({ record }: { record: HistoryRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 py-3 text-left hover:opacity-80"
      >
        <span className="num w-28 shrink-0 whitespace-nowrap text-sm text-muted">{formatRunTime(record.analysis_time)}</span>
        <span className="min-w-0 flex-1 text-sm leading-relaxed">{record.conclusion}</span>
        <span className="shrink-0 text-xs text-muted">{open ? "收起" : "展开"}</span>
      </button>
      {open && (
        <div className="pb-4 sm:pl-[124px]">
          <div className="mb-3">
            <SentimentPill sentiment={record.brief?.sentiment ?? record.sentiment} />
          </div>
          {record.brief ? (
            <BriefBody brief={record.brief} />
          ) : (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted">{record.report}</p>
          )}
        </div>
      )}
    </li>
  );
}

export default function HistoryList() {
  const { data, error, isLoading } = useSWR("history", () => fetchHistory(60), { refreshInterval: 300_000 });
  const [shown, setShown] = useState(PAGE);
  const rows = data?.history ?? [];

  return (
    <Card className="p-5 sm:p-6">
      <h2 className="mb-1 text-sm font-semibold">往期简报</h2>
      {isLoading && <Muted>加载中…</Muted>}
      {error && <Muted>往期记录暂时加载不了。</Muted>}
      {data && rows.length === 0 && <Muted>还没有往期记录。</Muted>}
      <ul className="divide-y divide-line">
        {rows.slice(0, shown).map((r) => (
          <Entry key={r.id} record={r} />
        ))}
      </ul>
      {rows.length > shown && (
        <button onClick={() => setShown((n) => n + PAGE)} className="mt-2 text-sm text-accent hover:underline">
          显示更早的 {Math.min(PAGE, rows.length - shown)} 条
        </button>
      )}
    </Card>
  );
}
