"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetchChartData, fetchWatchlist, saveWatchlist } from "@/lib/api";
import type { MarketSnapshot, OutlookItem } from "@/lib/types";
import { DIR_GLYPH, dirTone, numTone, shortName } from "@/lib/brief";
import { DIRECTION_LABEL, formatPct, formatPrice } from "@/lib/format";
import { Dots } from "./Lead";

const chartOpts = { revalidateOnFocus: false, dedupingInterval: 600_000 };

/** 近 30 根收盘价的走势线 */
function Spark({ symbol }: { symbol: string }) {
  const { data } = useSWR(["chart", symbol], () => fetchChartData(symbol), chartOpts);
  const c = data?.candles.slice(-30).map((k) => k.close) ?? [];
  if (c.length < 2) return <span className="spark-empty" />;
  const w = 100, h = 26, lo = Math.min(...c), hi = Math.max(...c), k = hi - lo || 1;
  const d = c.map((v, i) => `${i ? "L" : "M"}${((i / (c.length - 1)) * w).toFixed(1)} ${(h - 2 - ((v - lo) / k) * (h - 4)).toFixed(1)}`).join("");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function Refs({ item }: { item?: OutlookItem }) {
  if (!item?.links.length) return null;
  return (
    <>
      {item.links.map((l) => (
        <a key={l.id} className="ref" href={l.uri} target="_blank" rel="noopener noreferrer" title={l.title}>
          {l.id.replace(/^S/, "")}
        </a>
      ))}
    </>
  );
}

export default function DirectionTable({
  outlook,
  market,
  selected,
  onSelect,
}: {
  outlook: OutlookItem[];
  market?: MarketSnapshot;
  selected: string | null;
  onSelect: (s: string) => void;
}) {
  const { data: wl, mutate } = useSWR("watchlist", fetchWatchlist);
  const symbols = wl?.watchlist ?? [];
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const save = async (next: string[]) => {
    setSaving(true);
    setMessage(null);
    try {
      await saveWatchlist(next);
      await mutate();
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
    if (symbols.includes(sym)) return setMessage(`${sym} 已经在自选里了`);
    if (await save([...symbols, sym])) setInput("");
  };
  const remove = (sym: string) => {
    if (symbols.length <= 1) return setMessage("至少保留一个品种");
    save(symbols.filter((s) => s !== sym));
  };

  return (
    <section className="sec">
      <div className="sech">
        <h3>各品种方向</h3>
        <span className="kick">
          只基于新闻 · 不含技术面 · 点选一行看走势 ·{" "}
          <button
            type="button"
            className="link"
            onClick={() => {
              setEditing((v) => !v);
              setMessage(null);
            }}
          >
            {editing ? "完成" : "编辑自选"}
          </button>
        </span>
      </div>
      <table className={`dirs${editing ? " editing" : ""}`}>
        <thead>
          <tr>
            <th>品种</th>
            <th className="num">现价</th>
            <th className="num">日涨跌</th>
            <th className="num">5日</th>
            <th>30日</th>
            <th>方向</th>
            <th>把握</th>
            <th>依据</th>
            <th>{editing ? "" : "来源"}</th>
          </tr>
        </thead>
        <tbody>
          {symbols.map((sym) => {
            const s = market?.[sym];
            const o = outlook.find((x) => x.symbol === sym);
            return (
              <tr key={sym} className={sym === selected ? "sel" : ""} onClick={() => onSelect(sym)}>
                <td className="sym">
                  <b>{shortName(sym)}</b>
                  <small>
                    {sym}
                    {s?.name ? ` · ${s.name}` : ""}
                  </small>
                </td>
                <td className="num price">{formatPrice(s?.price)}</td>
                <td className={`num chg ${numTone(s?.pct_change)}`}>{formatPct(s?.pct_change)}</td>
                <td className={`num r5 ${numTone(s?.ret_5d)}`}>{formatPct(s?.ret_5d)}</td>
                <td className="spk">
                  <Spark symbol={sym} />
                </td>
                <td className={`dir ${dirTone(o?.direction)}`}>
                  {o ? `${DIR_GLYPH[o.direction]} ${DIRECTION_LABEL[o.direction]}` : "—"}
                </td>
                <td className="conf">{o && <Dots level={o.confidence} />}</td>
                <td className="why">{o?.drivers ?? (editing ? "" : "下一期简报起会给出方向")}</td>
                <td className="refs">
                  {editing ? (
                    <button
                      type="button"
                      className="rm"
                      disabled={saving}
                      onClick={(e) => {
                        e.stopPropagation();
                        remove(sym);
                      }}
                    >
                      移除
                    </button>
                  ) : (
                    <Refs item={o} />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {editing && (
        <form
          className="addsym"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Yahoo 代码，如 AAPL、0700.HK、BTC-USD"
            autoCapitalize="characters"
            autoCorrect="off"
          />
          <button type="submit" disabled={saving || !input.trim()}>
            添加
          </button>
          <span className="hint">改动会在下一期简报生效</span>
        </form>
      )}
      {message && <p className="err">{message}</p>}
    </section>
  );
}
