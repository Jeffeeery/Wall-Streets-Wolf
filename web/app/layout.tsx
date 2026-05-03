import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Marcus Wolf | Quant Dashboard",
  description: "Real-time market analysis and AI agent monitoring",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#0a0e17] text-gray-100 antialiased">
        <header className="border-b border-gray-800 px-6 py-3 flex items-center gap-3">
          <span className="text-xl font-bold tracking-widest text-emerald-400">
            MARCUS WOLF
          </span>
          <span className="text-xs text-gray-500 uppercase tracking-widest">
            Quant Terminal
          </span>
        </header>
        <main className="px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
