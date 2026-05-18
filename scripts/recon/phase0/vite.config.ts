// Phase 0 harness Vite config.
//
// The Spark 0.1.10 WASM loading problem
// -------------------------------------
// Spark's wasm-bindgen output (node_modules/@sparkjsdev/spark/dist/spark.module.js
// line 706) embeds the compiled WASM module as a base64 `data:application/wasm`
// URL inside a `new URL(..., import.meta.url)` call, then `fetch()`es that URL
// (line 710) and feeds the Response to `WebAssembly.instantiateStreaming`
// (line 595) with an `arrayBuffer()` + `WebAssembly.instantiate` fallback (line
// 605). On 2026-05-18 the operator hit two stacked failures from this path on
// Chromium-family browsers:
//
//   1) `instantiateStreaming` rejects the data-URL Response because Chromium's
//      fetch implementation returns Content-Type '' for `data:application/wasm`
//      URLs (the MIME declared in the prefix is not propagated to the Response).
//   2) The fallback `await response.arrayBuffer()` then returns bytes that fail
//      the WASM magic-number check ("failed to match magic number"). This is a
//      separate, downstream bug in how some browsers materialise large
//      data-URL responses through `fetch()`.
//
// `optimizeDeps.exclude` plus a `.wasm` MIME middleware (commit 5b8bcb8) only
// fixed (1) under the wrong assumption that Vite was rewriting the URL; in
// fact the dev server never sees the request because the data URL is resolved
// internally by the browser. (2) still fired, hence the second iteration.
//
// The fix: rehydrate the embedded WASM
// ------------------------------------
// 1) `extractSparkWasm` plugin: on dev server / build start, read
//    `spark.module.js`, decode the base64 WASM into bytes, write them to
//    `<dist-or-public>/spark_bg.wasm`, and remember a stable virtual URL
//    (`/__spark_bg.wasm`) for the runtime to fetch.
// 2) `patchSparkModule` plugin (`transform` hook): when Vite serves
//    `spark.module.js`, swap the data URL for a normal relative URL that the
//    dev server can serve from disk with `application/wasm`. The transform is
//    text-only, byte-for-byte length-neutral on everything else, and produces
//    no sourcemap drift for the surrounding code.
// 3) `wasmMime` middleware: belt-and-suspenders so the rehydrated `.wasm` is
//    always served with `Content-Type: application/wasm`. Vite's built-in
//    MIME map already covers `.wasm` for production, but `node_modules`-served
//    assets in dev are inconsistent across Vite minor versions.
//
// `optimizeDeps.exclude` is retained: Vite's esbuild pre-bundler corrupts the
// 43 KB data-URL string when it processes `spark.module.js` (esbuild rewrites
// `import.meta.url` and emits a smaller URL that points at the bundle file,
// which is also wrong). Excluding spark keeps the published ESM module
// untouched so our `transform` hook is the only thing operating on it.
//
// Sources / receipts
// ------------------
// - Spark's wasm-bindgen `__wbg_init` data-URL path:
//     node_modules/@sparkjsdev/spark/dist/spark.module.js lines 696-712
// - The `__wbg_load` streaming-then-arrayBuffer fallback that produced the
//   stack trace at `spark.module.js:605:1`:
//     same file, lines 591-613
// - Chromium issue with data: URL Content-Type stripping:
//     https://bugs.chromium.org/p/chromium/issues/detail?id=1313083 (related,
//     historical). The behaviour persists for `data:application/wasm` per
//     2026-05-18 testing.

// We rely on Node's built-in modules to read/write the WASM blob at config
// time. We deliberately avoid pulling in `@types/node` (the rest of the repo
// doesn't have it as a devDep for this harness — see package.json), so we
// type-erase the dynamic imports through `any` and a couple of inline
// signatures. This keeps the build-tooling devDeps to `vite` + `typescript`.
// Vite compiles this config to ESM, so `require` is not available directly;
// `createRequire(import.meta.url)` is the official ESM escape hatch.
// @ts-ignore -- node:module has no @types/node in this project (intentional)
import { createRequire } from "node:module";
const _req = createRequire(import.meta.url);
const { readFileSync, writeFileSync, mkdirSync } = _req("node:fs") as {
  readFileSync: (p: string, enc: string) => string;
  writeFileSync: (p: string, data: Uint8Array) => void;
  mkdirSync: (p: string, opts: { recursive: boolean }) => void;
};
const { dirname, resolve } = _req("node:path") as {
  dirname: (p: string) => string;
  resolve: (...p: string[]) => string;
};
const { fileURLToPath } = _req("node:url") as {
  fileURLToPath: (u: string) => string;
};
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _Buffer = (_req("node:buffer") as { Buffer: any }).Buffer;

import type { Plugin } from "vite";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const SPARK_MODULE_PATH = resolve(
  __dirname,
  "node_modules/@sparkjsdev/spark/dist/spark.module.js",
);
// Where the rehydrated WASM is dropped so Vite serves it statically. Using
// `public/` keeps the URL stable at `/__spark_bg.wasm` for both `vite` (dev)
// and `vite build` + `vite preview`. The `__` prefix marks it as plugin-owned
// so future humans don't confuse it with checked-in assets.
const WASM_PUBLIC_NAME = "__spark_bg.wasm";
const WASM_PUBLIC_PATH = resolve(__dirname, "public", WASM_PUBLIC_NAME);
const WASM_PUBLIC_URL = `/${WASM_PUBLIC_NAME}`;

// Match the wasm-bindgen `new URL("data:application/wasm;base64,<b64>", <base>)`
// invocation. There are TWO call sites in spark.module.js, with different
// base-URL second arguments:
//
//   Main-thread (line 706):
//     new URL("data:application/wasm;base64,...", import.meta.url)
//
//   Worker source inside jsContent string literal (line 8564, runs in a
//   blob-URL worker that has no `import.meta`):
//     new URL("data:application/wasm;base64,...", self.location.href)
//
// We match both by accepting either `import.meta.url` or `self.location.href`
// as the base. The base64 payload is captured as group 1 in case future
// callers want to extract bytes from the match; the entire `new URL(...)`
// expression is the full match so a single `String.replace` swaps the whole
// thing for our static-URL form.
const SPARK_DATA_URL_RE =
  /new URL\("data:application\/wasm;base64,([A-Za-z0-9+/=]+)", (?:import\.meta\.url|self\.location\.href)\)/;

function extractSparkWasm(): Plugin {
  let extracted = false;
  return {
    name: "spark-extract-wasm",
    // `apply: undefined` so the plugin runs for both `serve` and `build`.
    enforce: "pre",
    buildStart() {
      if (extracted) return;
      const src = readFileSync(SPARK_MODULE_PATH, "utf8");
      const match = src.match(SPARK_DATA_URL_RE);
      if (!match) {
        // Spark may have been upgraded past 0.1.x and changed loading
        // strategy. Fail loud so the harness operator sees this before they
        // hit the more confusing runtime error.
        throw new Error(
          "[spark-extract-wasm] could not find data-URL WASM in spark.module.js — " +
            "did @sparkjsdev/spark drop the embedded-base64 strategy? " +
            "Update this plugin or pin spark to 0.1.10.",
        );
      }
      const bytes = _Buffer.from(match[1], "base64") as Uint8Array;
      // Sanity-check the WASM magic number before writing. If the base64
      // somehow decoded to garbage we want to fail here, not at runtime
      // inside `instantiate()`.
      if (
        bytes.length < 8 ||
        bytes[0] !== 0x00 ||
        bytes[1] !== 0x61 ||
        bytes[2] !== 0x73 ||
        bytes[3] !== 0x6d
      ) {
        throw new Error(
          `[spark-extract-wasm] decoded bytes do not start with WASM magic \\0asm; got ${Array.from(bytes.slice(0, 4)).map((b) => b.toString(16).padStart(2, "0")).join("")}`,
        );
      }
      mkdirSync(dirname(WASM_PUBLIC_PATH), { recursive: true });
      writeFileSync(WASM_PUBLIC_PATH, bytes);
      extracted = true;
      // Rollup plugin context exposes `this.info` in modern Vite; cast through
      // any to avoid an `@types/node`-less type lookup on the PluginContext.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ctx = this as any;
      if (typeof ctx?.info === "function") {
        ctx.info(
          `[spark-extract-wasm] rehydrated ${bytes.length} bytes -> public/${WASM_PUBLIC_NAME}`,
        );
      } else {
        // eslint-disable-next-line no-console
        console.log(
          `[spark-extract-wasm] rehydrated ${bytes.length} bytes -> public/${WASM_PUBLIC_NAME}`,
        );
      }
    },
  };
}

function patchSparkModule(): Plugin {
  return {
    name: "spark-patch-data-url",
    enforce: "pre",
    transform(code, id) {
      // `id` is the absolute file path Vite hands to plugins. We only want to
      // touch Spark's own bundle, not the worker-bootstrap string inside it
      // (which is a JS string literal and never executed as a module — but
      // belt-and-suspenders, we still only replace the FIRST occurrence which
      // is the real `__wbg_init` call site at line 706).
      if (!id.includes("@sparkjsdev/spark/dist/spark.module.js")) return null;
      if (!SPARK_DATA_URL_RE.test(code)) return null;
      // There are TWO occurrences of the data URL in spark.module.js:
      //   1) line 706 — the main-thread `__wbg_init` call site
      //   2) line 8564 — the same source embedded as an escaped string inside
      //      `jsContent = '...'`, which is the source code of the splat-sort
      //      Web Worker. The worker calls `__wbg_init()` independently inside
      //      its own scope, so it hits the same data-URL bug. We MUST patch
      //      both or the sort worker will crash the first time `SplatMesh`
      //      schedules a sort (which it does as soon as the splat count is
      //      large enough — i.e. always, on any real PLY).
      //
      // We deliberately do NOT use the `new URL("./foo", import.meta.url)`
      // form here — Vite's built-in asset plugin sees that shape and rewrites
      // it to `/@fs/...` (verified 2026-05-18 by serving the patched file and
      // observing `/@fs/__spark_bg.wasm` in the response). Instead we emit a
      // plain string concatenation that constructs the absolute URL at
      // runtime. Vite has no static AST pattern for this and leaves it
      // alone, so the browser fetches the URL we actually want, served by
      // Vite's static handler from `public/` with `application/wasm` MIME.
      //
      // `location.origin` is defined on both main-thread `window` and on
      // worker `self`, so the same replacement works in both occurrences.
      // The replacement is also pure — no `import.meta.url` reference — so
      // Vite's pre-bundler can't re-mangle it. Globally replace both
      // occurrences using `/g` on a re-built RegExp (the source regex has no
      // /g flag so it'd otherwise replace only the first match).
      //
      // We use ONLY double-quoted string literals in the replacement
      // expression, never single-quotes. The second occurrence of the data
      // URL lives inside the single-quoted `jsContent = '...'` worker-source
      // string (see line 8564). Any single-quote in the replacement would
      // terminate that outer literal and break the worker boot. The empty
      // string "" and the "undefined" literal both use double-quotes for
      // exactly this reason.
      const replacement =
        'new URL((typeof location !== "undefined" ? location.origin : "") + ' +
        JSON.stringify(WASM_PUBLIC_URL) +
        ")";
      const globalRe = new RegExp(SPARK_DATA_URL_RE.source, "g");
      const patched = code.replace(globalRe, replacement);
      return { code: patched, map: null };
    },
  };
}

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
  plugins: [extractSparkWasm(), patchSparkModule(), wasmMime],
  optimizeDeps: {
    // Keep Spark out of esbuild dep-prebundling. Esbuild rewrites
    // `import.meta.url` and corrupts the 43 KB data URL string, and our
    // `transform` hook needs to see the original `spark.module.js` text.
    exclude: ["@sparkjsdev/spark"],
  },
  server: {
    fs: {
      strict: true,
    },
  },
  // Ensure Vite treats our rehydrated WASM as a normal static asset.
  assetsInclude: ["**/*.wasm"],
};

