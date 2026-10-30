import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        line: "var(--line)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        accent: "var(--accent)",
        bull: "var(--bull)",
        "bull-soft": "var(--bull-soft)",
        bear: "var(--bear)",
        "bear-soft": "var(--bear-soft)",
        "neutral-soft": "var(--neutral-soft)",
      },
    },
  },
  plugins: [],
};
export default config;
