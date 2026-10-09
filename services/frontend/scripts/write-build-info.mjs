import { mkdirSync, writeFileSync } from "node:fs";

const input = process.env.ODIN_BUILD_REVISION ?? "unknown";
if (input !== "unknown" && !/^[0-9a-f]{40}$/.test(input)) {
  throw new Error("ODIN_BUILD_REVISION must be a full Git SHA or unknown");
}

mkdirSync("public", { recursive: true });
writeFileSync("public/build-info.json", JSON.stringify({
  revision: input === "unknown" ? null : input,
}) + "\n");
