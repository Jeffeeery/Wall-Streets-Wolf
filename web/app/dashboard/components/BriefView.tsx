"use client";
import useSWR from "swr";
import { fetchMemory, fetchSnapshot } from "@/lib/api";
import { formatRunTime, nextRunLabel } from "@/lib/format";
import BriefBody from "./BriefBody";
import { Card, Muted, SentimentPill } from "./ui";

export default function BriefView() {
  const { data, error, isLoading } = useSWR("memory", fetchMemory, { refreshInterval: 60_000 });
  const { data: market } = useSWR("snapshot", fetchSnapshot, { refreshInterval: 300_000 });

  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm text-muted">
          {data?.time ? `${formatRunTime(data.time)} 更新` : "最新简报"}
          <span className="mx-1.5">·</span>下次约 {nextRunLabel()}
        </h2>
        <SentimentPill sentiment={data?.brief?.sentiment ?? data?.sentiment} />
      </div>

      {isLoading && <Muted>正在加载简报…</Muted>}
      {error && <Muted>简报暂时加载不了，稍后会自动重试。</Muted>}
      {data?.message && <Muted>还没有简报。下一次定时运行后会出现在这里。</Muted>}

      {data && !data.message && (
        <>
          <p className="text-lg font-semibold leading-snug sm:text-xl">{data.brief?.headline ?? data.conclusion}</p>
          {data.brief?.changes && data.brief.changes !== "首次运行" && (
            <p className="mt-2 text-sm text-muted">相比上期：{data.brief.changes}</p>
          )}
          <div className="mt-6">
            {data.brief ? (
              <BriefBody brief={data.brief} market={market} />
            ) : (
              // 旧版记忆没有结构化数据，退回显示文本报告
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{data.report}</p>
            )}
          </div>
          <p className="mt-6 border-t border-line pt-3 text-xs text-muted">
            方向判断只基于公开新闻，不包含技术面，也不构成投资建议。
          </p>
        </>
      )}
    </Card>
  );
}
