import { defineConfig } from "vite";

// The embeddable widget: one self-contained IIFE file (dist/widget.js), no React, styles inside a
// shadow root so the host page and the widget cannot affect each other's CSS.
export default defineConfig({
  publicDir: false,
  build: {
    outDir: "dist",
    emptyOutDir: false,
    lib: {
      entry: "widget/widget.ts",
      name: "SupportWidget",
      formats: ["iife"],
      fileName: () => "widget.js",
    },
    minify: true,
    sourcemap: false,
  },
});
