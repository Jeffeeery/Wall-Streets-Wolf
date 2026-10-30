/* eslint-disable @next/next/no-img-element */
import { datelineOf, editionOf } from "@/lib/brief";
import { nextRunLabel } from "@/lib/format";

export default function Masthead({ time }: { time?: string }) {
  const dl = datelineOf(time);
  return (
    <>
      <div className="strip">
        <span>{dl ? `${dl.date} · ${editionOf(time)} · ${dl.hm} 更新` : "Wall Street's Wolf"}</span>
        <span className="r">下一期 {nextRunLabel()} · 每日 07:00 收盘版 / 20:00 盘前版</span>
      </div>
      <header className="mast">
        <img className="wolf" src="/wolf-full.png" alt="Marcus，华尔街之狼" width={250} height={360} />
        <div className="tt">
          <h1>华尔街之狼</h1>
          <div className="sub">WALL STREET&apos;S WOLF · 消息面日报 · 主笔 MARCUS</div>
        </div>
      </header>
      <div className="dbl" />
    </>
  );
}
