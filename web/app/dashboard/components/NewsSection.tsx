"use client";
import { useState } from "react";
import type { NewsItem } from "@/lib/types";
import { hitsOf, shortName } from "@/lib/brief";
import Reveal from "./Reveal";

export function Chevron() {
  return (
    <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M2.5 4.5 6 8l3.5-3.5" />
    </svg>
  );
}

export function Hits({ impact, symbols }: { impact?: string; symbols: string[] }) {
  const hits = hitsOf(impact, symbols);
  if (!hits.length) return null;
  return (
    <span className="hit">
      {hits.map((h) => (
        <span key={h.symbol} className={h.tone}>
          {shortName(h.symbol)} {h.tone === "up" ? "▲利好" : h.tone === "down" ? "▼利空" : "–"}
        </span>
      ))}
    </span>
  );
}

/** 一条要闻：收起时只有标签、标题、受影响品种；点标题展开全文、影响和来源 */
function Story({ item, lead, symbols }: { item: NewsItem; lead: boolean; symbols: string[] }) {
  const [open, setOpen] = useState(lead);
  const major = item.importance === "HIGH";
  return (
    <article className={`art${lead ? " lead1" : ""}${open ? " open" : ""}`}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="top">
          <span className={`kick${major ? " red" : ""}`}>{major ? "重要" : "关注"}</span>
          <span className="tog">
            {open ? "收起" : "展开"}
            <Chevron />
          </span>
        </span>
        <h4>{item.title}</h4>
        <Hits impact={item.impact} symbols={symbols} />
      </button>
      <Reveal open={open}>
        <p>{item.summary}</p>
        {item.impact && <div className="impact">{item.impact}</div>}
        {item.links.length > 0 && (
          <div className="srcl">
            {item.links.map((l) => (
              <a key={l.id} href={l.uri} target="_blank" rel="noopener noreferrer">
                <span>{l.domain}</span>
                <b>{l.title}</b>
              </a>
            ))}
          </div>
        )}
      </Reveal>
    </article>
  );
}

export default function NewsSection({ news, symbols }: { news: NewsItem[]; symbols: string[] }) {
  if (!news.length) return null;
  const [first, ...rest] = news;
  return (
    <section className="sec">
      <div className="sech">
        <h3>要闻</h3>
        <span className="kick">按重要性排列 · 点标题展开全文和来源</span>
      </div>
      <div className="news">
        <Story item={first} lead symbols={symbols} />
        {rest.length > 0 && (
          <div className="side">
            {rest.map((n, i) => (
              <Story key={i} item={n} lead={false} symbols={symbols} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
