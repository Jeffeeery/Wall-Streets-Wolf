import type { ReactNode } from "react";
import type { Direction, Level, Sentiment, SourceLink } from "@/lib/types";
import { DIRECTION_LABEL, LEVEL_LABEL, SENTIMENT_LABEL, domainOf } from "@/lib/format";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-surface ${className}`}>{children}</section>;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h3 className="text-sm font-semibold">{children}</h3>
      {aside && <div className="text-xs text-muted">{aside}</div>}
    </div>
  );
}

const DIRECTION_STYLE: Record<Direction, string> = {
  BULLISH: "bg-bull-soft text-bull",
  BEARISH: "bg-bear-soft text-bear",
  NEUTRAL: "bg-neutral-soft text-muted",
};

export function DirectionBadge({ direction, confidence }: { direction: Direction; confidence?: Level }) {
  return (
    <span className={`inline-flex shrink-0 items-center rounded-md px-2 py-0.5 text-xs font-medium ${DIRECTION_STYLE[direction]}`}>
      {DIRECTION_LABEL[direction]}
      {confidence && direction !== "NEUTRAL" && <span className="ml-1 opacity-75">· 置信{LEVEL_LABEL[confidence]}</span>}
    </span>
  );
}

const SENTIMENT_STYLE: Record<Sentiment, string> = {
  RISK_ON: "bg-bull-soft text-bull",
  RISK_OFF: "bg-bear-soft text-bear",
  MIXED: "bg-neutral-soft text-muted",
};

export function SentimentPill({ sentiment }: { sentiment?: Sentiment | null }) {
  if (!sentiment) return null;
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${SENTIMENT_STYLE[sentiment]}`}>
      市场情绪：{SENTIMENT_LABEL[sentiment]}
    </span>
  );
}

export function SourceLinks({ links }: { links?: SourceLink[] }) {
  if (!links?.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {links.map((l) => (
        <a
          key={l.id}
          href={l.uri}
          target="_blank"
          rel="noopener noreferrer"
          title={l.title}
          className="text-accent hover:underline"
        >
          {l.domain || domainOf(l.uri)} ↗
        </a>
      ))}
    </div>
  );
}

export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}
