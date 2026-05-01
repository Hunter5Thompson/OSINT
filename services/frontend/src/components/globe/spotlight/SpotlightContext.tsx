import { createContext, useContext, useReducer, useEffect, type ReactNode, type Dispatch } from "react";

export type CircleTarget = {
  kind: "circle";
  trigger: "zoom" | "pin" | "search";
  center: { lon: number; lat: number };
  radius: number;        // degrees
  altitude: number;      // meters
  label: string;
  ref?: string;
  sourcePin?: { layer: string; entityId: string };
};

export type CountryTarget = {
  kind: "country";
  trigger: "country";
  m49: string;
  iso3: string | null;
  polygon: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  name: string;
  capital: { name: string; coords: { lon: number; lat: number } } | null;
};

export type FocusTarget = CircleTarget | CountryTarget | null;

export type SpotlightAction =
  | { type: "set"; target: NonNullable<FocusTarget> }
  | { type: "reset" };

export function spotlightReducer(_state: FocusTarget, action: SpotlightAction): FocusTarget {
  switch (action.type) {
    case "set":
      return action.target;
    case "reset":
      return null;
  }
}

interface SpotlightCtx {
  focusTarget: FocusTarget;
  dispatch: Dispatch<SpotlightAction>;
}

const SpotlightContext = createContext<SpotlightCtx | null>(null);

export function SpotlightProvider({ children }: { children: ReactNode }) {
  const [focusTarget, dispatch] = useReducer(spotlightReducer, null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch({ type: "reset" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <SpotlightContext.Provider value={{ focusTarget, dispatch }}>
      {children}
    </SpotlightContext.Provider>
  );
}

export function useSpotlight(): SpotlightCtx {
  const ctx = useContext(SpotlightContext);
  if (!ctx) throw new Error("useSpotlight must be used inside SpotlightProvider");
  return ctx;
}
