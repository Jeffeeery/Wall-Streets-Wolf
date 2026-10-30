"use client";
import { useLayoutEffect, useRef } from "react";

/**
 * 展开 / 收起的内容区：先量高度再做动画（CSS grid 0fr→1fr 的写法在部分浏览器里会直接跳变）。
 * 收起时高度为 0，内容仍在 DOM 里，所以展开的瞬间就能量到目标高度。
 */
export default function Reveal({ open, children }: { open: boolean; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const first = useRef(true);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (first.current) {
      first.current = false;
      return;
    }
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.getAnimations().forEach((a) => a.cancel());
    const to = open ? el.scrollHeight : 0;
    const from = open ? 0 : el.scrollHeight;
    el.animate(
      [
        { height: `${from}px`, opacity: open ? 0 : 1 },
        { height: `${to}px`, opacity: open ? 1 : 0 },
      ],
      { duration: open ? 300 : 220, easing: open ? "cubic-bezier(.22,.8,.24,1)" : "cubic-bezier(.4,0,.6,1)" }
    );
  }, [open]);

  return (
    <div ref={ref} className={`reveal${open ? " open" : ""}`} aria-hidden={!open}>
      {children}
    </div>
  );
}
