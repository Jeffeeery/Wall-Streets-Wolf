"use client";
import useSWR from "swr";
import { fetchHitRate } from "@/lib/api";
import type { HitBucket, Level } from "@/lib/types";
import { shortName } from "@/lib/brief";
import { LEVEL_LABEL } from "@/lib/format";
import { Dots } from "./Lead";

const LEVELS: Level[] = ["HIGH", "MEDIUM", "LOW"];

function Cells({ b }: { b: HitBucket }) {
  return (
    <>
      <td className="num">{b.hit_rate == null ? <span className="flat">样本不足</span> : `${b.hit_rate.toFixed(1)}%`}</td>
      <td className="num">
        {b.hits} / {b.total}
      </td>
    </>
  );
}

/** 往期利好/利空判断事后对了多少：整体、按把握、按品种，都带样本数 */
export default function HitRate() {
  // 每次请求后端都要重新拉各品种日线，切回页面时不重复请求
  const { data, error } = useSWR("hit-rate", fetchHitRate, { revalidateOnFocus: false });
  const symbols = Object.entries(data?.by_symbol ?? {}).sort((a, b) => b[1].total - a[1].total);

  return (
    <section className="sec">
      <div className="sech">
        <h3>方向命中率</h3>
        <span className="kick">
          {data ? `发出后第 ${data.days} 个交易日收盘价 对比 当期价格 · ` : ""}利好要涨、利空要跌才算中 · 中性不计
        </span>
      </div>
      {error && <p className="state">命中率暂时算不出来，稍后再试。</p>}
      {!data && !error && <p className="state">正在核对往期判断…</p>}
      {data && data.overall.total === 0 && (
        <p className="state">
          还没有到期的方向判断{data.open > 0 ? `（${data.open} 次还在等收盘）` : ""}。
        </p>
      )}
      {data && data.overall.total > 0 && (
        <>
          <div className="rates">
            <table>
              <thead>
                <tr>
                  <th>把握</th>
                  <th className="num">命中率</th>
                  <th className="num">命中 / 样本</th>
                </tr>
              </thead>
              <tbody>
                <tr className="all">
                  <td>全部</td>
                  <Cells b={data.overall} />
                </tr>
                {LEVELS.map((l) => (
                  <tr key={l}>
                    <td>
                      {LEVEL_LABEL[l]} <Dots level={l} />
                    </td>
                    <Cells b={data.by_confidence[l]} />
                  </tr>
                ))}
              </tbody>
            </table>
            <table>
              <thead>
                <tr>
                  <th>品种</th>
                  <th className="num">命中率</th>
                  <th className="num">命中 / 样本</th>
                </tr>
              </thead>
              <tbody>
                {symbols.map(([sym, b]) => (
                  <tr key={sym}>
                    <td>
                      {shortName(sym)}
                      {shortName(sym) !== sym && <small>{sym}</small>}
                    </td>
                    <Cells b={b} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="cap">
            样本少于 {data.min_sample} 次只列次数，不给百分比。
            {data.open > 0 && `另有 ${data.open} 次判断还没到期，未计入。`}
            {data.skipped > 0 && `${data.skipped} 次缺少价格数据，未计入。`}
            同一判断连续几期重复出现时每期各算一次，样本之间并不独立。
          </p>
        </>
      )}
    </section>
  );
}
