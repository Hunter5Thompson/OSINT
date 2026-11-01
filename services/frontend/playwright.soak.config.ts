import base from "./playwright.native.config";
export default { ...base, testMatch: /native\.soak\.perf\.ts$/, timeout: 3720000, globalTimeout: 3900000,
  use: { ...base.use, trace: "off" as const },
};
