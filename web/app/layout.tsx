import type { Metadata, Viewport } from "next";
import { Noto_Sans_SC, Noto_Serif_SC } from "next/font/google";
import "./globals.css";

// 中文字体很大，不预加载；Google 按字符区间切片，浏览器只下载页面用到的部分
const serif = Noto_Serif_SC({ weight: ["400", "700", "900"], preload: false, display: "swap", variable: "--font-serif" });
const sans = Noto_Sans_SC({ weight: ["400", "500", "700"], preload: false, display: "swap", variable: "--font-sans" });

export const metadata: Metadata = {
  title: "华尔街之狼 · Marcus 消息面日报",
  description: "每天两次的市场消息面简报：要闻、各品种方向和未来事件",
  applicationName: "华尔街之狼",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "华尔街之狼", statusBarStyle: "default" },
  other: {
    "strix-verification": "strix-verify-26fc4070fe31e551ebe10807212e458f",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#F5F3EE",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${serif.variable} ${sans.variable}`}>
      <body>
        <main>{children}</main>
      </body>
    </html>
  );
}
