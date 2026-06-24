import { useEffect, useMemo, useState } from "react";

import { getCountryAlmanac, getCountryAlmanacSignals } from "../services/api";
import type { AlmanacSignalResponse, CountryAlmanac } from "../types/almanac";

type LoadState<T> =
  | { status: "idle"; data: null; error: null }
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: string };

const idle = <T>(): LoadState<T> => ({ status: "idle", data: null, error: null });
const loading = <T>(): LoadState<T> => ({ status: "loading", data: null, error: null });

interface Params {
  iso3: string | null;
  m49: string;
}

export function useCountryAlmanac({ iso3, m49 }: Params) {
  const countryId = useMemo(() => iso3 ?? m49, [iso3, m49]);
  const [facts, setFacts] = useState<LoadState<CountryAlmanac>>(idle);
  const [signals, setSignals] = useState<LoadState<AlmanacSignalResponse>>(idle);

  useEffect(() => {
    const controller = new AbortController();
    setFacts(loading<CountryAlmanac>());
    setSignals(loading<AlmanacSignalResponse>());

    getCountryAlmanac(countryId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setFacts({ status: "ready", data, error: null });
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setFacts({ status: "error", data: null, error: String(err) });
        }
      });

    getCountryAlmanacSignals(countryId, 5, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setSignals({ status: "ready", data, error: null });
        }
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setSignals({ status: "error", data: null, error: String(err) });
        }
      });

    return () => controller.abort();
  }, [countryId]);

  return { countryId, facts, signals };
}
