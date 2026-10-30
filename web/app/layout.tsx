import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Marcus Wolf · 消息面简报",
  description: "每天两次的市场消息面简报：要闻、各品种方向和未来事件",
  other: {
    "strix-verification": "strix-verify-26fc4070fe31e551ebe10807212e458f",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-6xl items-baseline gap-3 px-4 py-3">
            <span className="text-base font-semibold">Marcus Wolf</span>
            <span className="text-sm text-muted">消息面简报</span>
          </div>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
