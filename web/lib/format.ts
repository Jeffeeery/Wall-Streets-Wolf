import type { Direction, Level, Sentiment } from "./types";

export const DIRECTION_LABEL: Record<Direction, string> = {
  BULLISH: "利好",
  BEARISH: "利空",
  NEUTRAL: "中性",
};

export const LEVEL_LABEL: Record<Level, string> = { HIGH: "高", MEDIUM: "中", LOW: "低" };

export const SENTIMENT_LABEL: Record<Sentiment, string> = {
  RISK_ON: "偏多",
  RISK_OFF: "避险",
  MIXED: "分化",
};

export function formatPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  const digits = Math.abs(v) >= 10 ? 2 : 4;
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export function toneOf(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-muted";
  return v > 0 ? "text-bull" : "text-bear";
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** 后端时间是吉隆坡时间的 "YYYY-MM-DD HH:mm"，显示成 "10月30日 14:21" */
export function formatRunTime(s: string | undefined): string {
  const m = s?.match(/^\d{4}-(\d{2})-(\d{2}) (\d{2}:\d{2})/);
  return m ? `${Number(m[1])}月${Number(m[2])}日 ${m[3]}` : s ?? "";
}

/** "2026-11-03" → "11月3日 周二"；无法解析时原样返回 */
export function formatEventDate(s: string): string {
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return s;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  const week = "日一二三四五六"[d.getUTCDay()];
  return `${+m[2]}月${+m[3]}日 周${week}`;
}

/** 定时任务在吉隆坡时间 07:00 和 20:00 左右运行 */
export function nextRunLabel(now = new Date()): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hour12: false, timeZone: "Asia/Kuala_Lumpur" }).format(now)
  );
  if (hour < 7) return "今天 07:00";
  if (hour < 20) return "今天 20:00";
  return "明天 07:00";
}
