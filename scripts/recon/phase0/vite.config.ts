// Phase 0 harness Vite config.
// Two fixes for the renderers' load paths:
//
// 1) optimizeDeps.exclude: ["@sparkjsdev/spark"]
//    Spark inlines its WASM as a `data:application/wasm;base64,...` URL inside
//    a `new URL(..., import.meta.url)` call (verified in
//    node_modules/@sparkjsdev/spark/dist/spark.module.js line 706, original
//    line 769 in node_modules/.vite/deps/@sparkjsdev_spark.js after Vite's
//    esbuild dep optimization). When Vite's dep-optimizer pre-bundles Spark,
//    that data-URL fetch path produces the "Response has unsupported MIME
//    type ''" / "failed to match magic number" failure the operator hit on
//    2026-05-18. Excluding Spark from dep optimization tells Vite to serve
//    Spark's published ESM module unmodified; the data URL is then fetched
//    directly with the correct `Content-Type: application/wasm` header that
//    `WebAssembly.instantiateStreaming` requires.
//
// 2) wasm-mime middleware
//    Belt-and-suspenders so any future native `.wasm` fetch (e.g. if Spark's
//    2.x rewrite stops inlining the WASM, or if mkk grows a wasm dep) is
//    served with `Content-Type: application/wasm`. Vite's built-in MIME
//    table sets this for production builds but not always for dev `fs.serve`
//    of files under node_modules; this middleware is the canonical fix.

import type { Plugin } from "vite";

const wasmMime: Plugin = {
  name: "wasm-mime",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      // `req.url` is provided by node's http.IncomingMessage. We avoid pulling
      // in @types/node just for this single property and cast through unknown.
      const url = (req as unknown as { url?: string }).url;
      if (url && (url.endsWith(".wasm") || url.includes(".wasm?"))) {
        res.setHeader("Content-Type", "application/wasm");
      }
      next();
    });
  },
};

export default {
  plugins: [wasmMime],
  optimizeDeps: {
    // Spark's data-URL WASM init breaks when esbuild-prebundled by Vite 5.4.x.
    // Serving the published ESM module directly bypasses the issue. The cost
    // is a few extra HTTP requests on first load (one per Spark import); this
    // is a smoke harness, not a production build, so that's fine.
    exclude: ["@sparkjsdev/spark"],
  },
  server: {
    fs: {
      // node_modules is allowed by default; this is just explicit so a future
      // reader doesn't have to look it up. The PLY itself lives under
      // ./public which Vite serves at the root URL automatically.
      strict: true,
    },
  },
};
