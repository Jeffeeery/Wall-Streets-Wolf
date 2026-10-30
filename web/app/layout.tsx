import type { Metadata, Viewport } from "next";
import "./globals.css";

// 中文字体由浏览器从 Google Fonts 按需加载（只下载页面用到的字符切片）。
// 不用 next/font：它在构建时要下载上百个 CJK 切片，偶尔超时会让整个部署失败。
const FONTS =
  "https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;700;900&family=DM+Mono:wght@400;500&display=swap";

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
    <html lang="zh-CN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href={FONTS} />
      </head>
      <body>
        <main>{children}</main>
      </body>
    </html>
  );
}
