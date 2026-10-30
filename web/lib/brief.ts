import type { Direction, Level } from "./types";

/** 常见代码的中文简称；没有的直接显示代码 */
const SHORT: Record<string, string> = {
  "^GSPC": "标普500",
  "^IXIC": "纳指",
  "^DJI": "道指",
  "NQ=F": "纳指期货",
  "ES=F": "标普期货",
  "CL=F": "原油",
  "GC=F": "黄金",
  "SI=F": "白银",
  "^VIX": "VIX",
  "BTC-USD": "比特币",
  "ETH-USD": "以太坊",
  NVDA: "英伟达",
  AAPL: "苹果",
  MSFT: "微软",
  TSLA: "特斯拉",
};

export const shortName = (s: string) => SHORT[s] ?? s;

export const DIR_GLYPH: Record<Direction, string> = { BULLISH: "▲", BEARISH: "▼", NEUTRAL: "–" };

export const dirTone = (d: Direction | undefined) => (d === "BULLISH" ? "up" : d === "BEARISH" ? "down" : "flat");

export const numTone = (v: number | null | undefined) => (v == null || v === 0 ? "flat" : v > 0 ? "up" : "down");

export const CONF_N: Record<Level, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };

/** 定时任务 07:00 跑在美股收盘后，20:00 跑在开盘前 */
export function editionOf(time: string | undefined) {
  const h = Number(time?.match(/ (\d{2}):/)?.[1] ?? 12);
  return h < 12 ? "收盘版" : "盘前版";
}

/** "2026-10-30 15:05" → { date: "2026年10月30日 星期五", hm: "15:05" } */
export function datelineOf(time: string | undefined) {
  const m = time?.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})/);
  if (!m) return null;
  const wd = "日一二三四五六"[new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()];
  return { date: `${m[1]}年${+m[2]}月${+m[3]}日 星期${wd}`, hm: m[4] };
}

export type Hit = { symbol: string; tone: "up" | "down" | "flat" };

/** 新闻影响里提到了哪些自选品种、往哪个方向：取代码后面最先出现的「利好 / 利空」 */
export function hitsOf(impact: string | undefined, symbols: string[]): Hit[] {
  if (!impact) return [];
  return symbols
    .filter((s) => impact.includes(s))
    .map((s) => {
      const after = impact.slice(impact.indexOf(s));
      const good = after.indexOf("利好"), bad = after.indexOf("利空");
      const tone = good >= 0 && (bad < 0 || good < bad) ? "up" : bad >= 0 ? "down" : "flat";
      return { symbol: s, tone };
    });
}
