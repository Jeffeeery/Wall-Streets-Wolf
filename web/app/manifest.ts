import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "华尔街之狼 · Marcus 消息面日报",
    short_name: "华尔街之狼",
    description: "每天两次的市场消息面简报",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#F5F3EE",
    theme_color: "#F5F3EE",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
