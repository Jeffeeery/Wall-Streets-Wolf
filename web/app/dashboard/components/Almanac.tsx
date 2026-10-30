"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchHistory } from "@/lib/api";
import type { Brief, HistoryRecord } from "@/lib/types";
import { DIR_GLYPH, dirTone, shortName } from "@/lib/brief";
import { DIRECTION_LABEL, SENTIMENT_LABEL } from "@/lib/format";
import { Chevron, Hits } from "./NewsSection";
import Reveal from "./Reveal";

const PAGE = 6;

/** 旧版文字报告的 Markdown 记号去掉，直接当正文读 */
const plain = (t: string) => t.replace(/[*`]/g, "").replace(/^-{3,}\s*$/gm, "").trim();

/** 旧版记录 conclusion 是 "---"，标题取「核心结论」下一行 */
function legacyTitle(r: HistoryRecord) {
  if (r.conclusion && !/^-+$/.test(r.conclusion.trim())) return plain(r.conclusion);
  const lines = (r.report ?? "").split("\n").map((l) => plain(l).replace(/^🎯\s*/, "")).filter(Boolean);
  const i = lines.findIndex((l) => l.includes("核心结论"));
  return (i >= 0 ? lines[i + 1] : lines[0]) ?? "旧版文字报告";
}

/** 分析引擎出错的那几次只有一行错误提示，不列出来 */
const failed = (r: HistoryRecord) => !r.brief && /分析引擎异常/.test(r.report ?? r.conclusion ?? "");

/** "2026-11-04" → "11/4" + "周三" */
function EventDate({ date }: { date: string }) {
  const m = date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return <div className="d"><b>{date}</b></div>;
  const wd = "日一二三四五六"[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()];
  return (
    <div className="d">
      <b>
        {+m[2]}/{+m[3]}
      </b>
      周{wd}
    </div>
  );
}

/** 往期简报展开后：要闻标题 + 各品种方向，够回看当时的判断 */
function PastBrief({ brief, symbols }: { brief: Brief; symbols: string[] }) {
  return (
    <div className="past">
      {brief.market_news.map((n, i) => (
        <div key={i} className="pn">
          <b>{n.title}</b>
          <Hits impact={n.impact} symbols={symbols} />
        </div>
      ))}
      {brief.outlook.length > 0 && (
        <div className="pd">
          {brief.outlook.map((o) => (
            <span key={o.symbol} className={dirTone(o.direction)}>
              {shortName(o.symbol)} {DIR_GLYPH[o.direction]}
              {DIRECTION_LABEL[o.direction]}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Edition({ r, symbols }: { r: HistoryRecord; symbols: string[] }) {
  const [open, setOpen] = useState(false);
  const sentiment = r.brief?.sentiment ?? r.sentiment;
  const legacy = !r.brief;
  const title = r.brief?.headline ?? legacyTitle(r);
  return (
    <div className={`ed${open ? " open" : ""}`}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <small>
          {r.analysis_time.slice(5)}
          <em className={sentiment === "RISK_OFF" ? "down" : sentiment === "RISK_ON" ? "up" : ""}>
            {sentiment ? SENTIMENT_LABEL[sentiment] : "旧版"}
          </em>
        </small>
        <span>{title}</span>
        <Chevron />
      </button>
      <Reveal open={open}>
        {legacy ? <p className="legacy">{plain(r.report ?? "")}</p> : <PastBrief brief={r.brief!} symbols={symbols} />}
      </Reveal>
    </div>
  );
}

export default function Almanac({ brief, symbols, latestTime }: { brief?: Brief; symbols: string[]; latestTime?: string }) {
  const { data, error } = useSWR("history", () => fetchHistory(60), { refreshInterval: 300_000 });
  const [shown, setShown] = useState(PAGE);
  // 最新一期已经在上面整版显示，往期从上一期开始
  const rows = (data?.history ?? []).filter((r) => r.analysis_time !== latestTime && !failed(r));

  return (
    <section className="sec calm">
      <div className="cb">
        <h2>未来五日</h2>
        {brief?.upcoming.length ? (
          brief.upcoming.map((u, i) => (
            <div key={i} className="ev">
              <EventDate date={u.date} />
              <div>
                <h4>{u.event}</h4>
                <p>{[u.affects, u.why].filter(Boolean).join(" · ")}</p>
              </div>
            </div>
          ))
        ) : (
          <p className="state">暂无已知事件</p>
        )}
      </div>
      <div className="cb">
        <h2>接下来留意</h2>
        {brief?.watch.length ? (
          <ul className="checks">
            {brief.watch.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        ) : (
          <p className="state">暂无</p>
        )}
      </div>
      <div className="cb">
        <h2>
          往期 <small>点开回看当期要闻和方向</small>
        </h2>
        {error && <p className="state">往期记录暂时加载不了。</p>}
        {data && rows.length === 0 && <p className="state">还没有往期记录。</p>}
        <div className="hist">
          {rows.slice(0, shown).map((r) => (
            <Edition key={r.id} r={r} symbols={symbols} />
          ))}
        </div>
        {rows.length > shown && (
          <button type="button" className="more" onClick={() => setShown((n) => n + PAGE)}>
            更早的 {Math.min(PAGE, rows.length - shown)} 期
          </button>
        )}
      </div>
    </section>
  );
}
