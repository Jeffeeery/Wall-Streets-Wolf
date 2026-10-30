/* eslint-disable @next/next/no-img-element */
import type { MarcusMemory, Sentiment } from "@/lib/types";
import { CONF_N, DIR_GLYPH, dirTone, shortName } from "@/lib/brief";
import { DIRECTION_LABEL, LEVEL_LABEL, SENTIMENT_LABEL } from "@/lib/format";

const SCALE_POS: Record<Sentiment, number> = { RISK_ON: 8, MIXED: 50, RISK_OFF: 92 };

export function Dots({ level }: { level: keyof typeof CONF_N }) {
  const n = CONF_N[level];
  return (
    <span className="dots" title={`把握${LEVEL_LABEL[level]}`} aria-label={`把握${LEVEL_LABEL[level]}`}>
      {"●".repeat(n)}
      <span className="off">{"●".repeat(3 - n)}</span>
    </span>
  );
}

export default function Lead({ memory }: { memory: MarcusMemory }) {
  const brief = memory.brief;
  const sentiment = brief?.sentiment ?? memory.sentiment ?? null;
  const outlook = brief?.outlook ?? [];
  const turned = outlook.filter((o) => o.prev && o.prev !== o.direction);
  const changes = brief?.changes && brief.changes !== "首次运行" ? brief.changes : null;

  return (
    <section className="lead">
      <div>
        <div className="kick">头条 · 未来 1–5 个交易日</div>
        <h2>{brief?.headline ?? memory.conclusion}</h2>
        {changes && (
          <p className="deck">
            <b>较上期</b>
            {changes}
          </p>
        )}
        <div className="byline">
          <img src="/wolf-face.png" alt="" width={30} height={30} />
          <span>
            Marcus Wolf 撰
            {memory.sources?.length ? ` · 引用 ${memory.sources.length} 个来源` : ""}
            {brief ? ` · ${brief.market_news.length} 条要闻 · ${outlook.length} 个品种` : ""}
          </span>
        </div>
      </div>
      <aside className="climate">
        <div className="kick">市场气候</div>
        <div className={`big ${sentiment === "RISK_ON" ? "up" : sentiment === "MIXED" ? "flat" : "down"}`}>
          {sentiment ? SENTIMENT_LABEL[sentiment] : "—"}
        </div>
        {sentiment && (
          <div className="scale" aria-hidden="true">
            <i style={{ left: `${SCALE_POS[sentiment]}%` }} />
            <span>偏多</span>
            <span className="r">避险</span>
          </div>
        )}
        {outlook.length > 0 && (
          <div className="glance">
            {outlook.map((o) => (
              <div key={o.symbol}>
                <span className={dirTone(o.direction)}>{DIR_GLYPH[o.direction]}</span>
                <span>
                  {shortName(o.symbol)} <small>{o.symbol}</small>
                </span>
                <span className={dirTone(o.direction)}>{DIRECTION_LABEL[o.direction]}</span>
                <Dots level={o.confidence} />
              </div>
            ))}
          </div>
        )}
        {outlook.length > 0 && (
          <div className="same">
            {turned.length ? `转向：${turned.map((o) => shortName(o.symbol)).join("、")}` : "各品种方向与上期相同"}
          </div>
        )}
      </aside>
    </section>
  );
}
