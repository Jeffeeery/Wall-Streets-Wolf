import type { Brief, MarketSnapshot, OutlookItem } from "@/lib/types";
import { DIRECTION_LABEL, formatEventDate } from "@/lib/format";
import { DirectionBadge, SectionTitle, SourceLinks } from "./ui";

const NO_NEWS = "无实质消息";

function OutlookRow({ o, name }: { o: OutlookItem; name?: string | null }) {
  const changed = o.prev && o.prev !== o.direction;
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{o.symbol}</span>
        {name && <span className="truncate text-sm text-muted">{name}</span>}
        <DirectionBadge direction={o.direction} confidence={o.confidence} />
        {changed && (
          <span className="text-xs text-muted">
            上期{DIRECTION_LABEL[o.prev!]} → 本期{DIRECTION_LABEL[o.direction]}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm leading-relaxed">{o.drivers}</p>
      {o.explains_move && <p className="mt-0.5 text-xs text-muted">与今日涨跌：{o.explains_move}</p>}
      <SourceLinks links={o.links} />
    </li>
  );
}

export default function BriefBody({ brief, market }: { brief: Brief; market?: MarketSnapshot }) {
  const outlook = brief.outlook ?? [];
  const active = outlook.filter((o) => !(o.direction === "NEUTRAL" && o.drivers === NO_NEWS && !o.prev));
  const quiet = outlook.filter((o) => !active.includes(o));

  return (
    <div className="space-y-6">
      {outlook.length > 0 && (
        <div>
          <SectionTitle aside="未来 1–5 个交易日，仅基于新闻">各品种方向</SectionTitle>
          <ul className="divide-y divide-line">
            {active.map((o) => (
              <OutlookRow key={o.symbol} o={o} name={market?.[o.symbol]?.name} />
            ))}
          </ul>
          {quiet.length > 0 && (
            <p className="mt-3 text-sm text-muted">
              {NO_NEWS}：{quiet.map((o) => o.symbol).join("、")}
            </p>
          )}
        </div>
      )}

      {brief.market_news?.length > 0 && (
        <div>
          <SectionTitle>要闻</SectionTitle>
          <ul className="space-y-4">
            {brief.market_news.map((n, i) => (
              <li key={i}>
                <div className="flex items-start gap-2">
                  {n.importance === "HIGH" && (
                    <span className="mt-0.5 shrink-0 rounded bg-bear-soft px-1.5 text-xs font-medium text-bear">重要</span>
                  )}
                  <a
                    href={n.links[0]?.uri}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium leading-snug hover:underline"
                  >
                    {n.title}
                  </a>
                </div>
                <p className="mt-1 text-sm leading-relaxed text-muted">{n.summary}</p>
                {n.impact && <p className="mt-1 text-sm leading-relaxed">影响：{n.impact}</p>}
                <SourceLinks links={n.links} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {brief.upcoming?.length > 0 && (
        <div>
          <SectionTitle>未来 5 日事件</SectionTitle>
          <ul className="space-y-2">
            {brief.upcoming.map((u, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="num w-24 shrink-0 text-muted">{formatEventDate(u.date)}</span>
                <span>
                  {u.event}
                  {u.affects && <span className="text-muted">（{u.affects}）</span>}
                  {u.why && <span className="block text-xs text-muted">{u.why}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {brief.watch?.length > 0 && (
        <div>
          <SectionTitle>重点留意</SectionTitle>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {brief.watch.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
