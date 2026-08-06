import { useEffect, useState, type ReactNode } from "react";
import { useSpotlight, type FocusTarget } from "./SpotlightContext";

interface EndonymJson {
  countries: Record<string, {
    iso3: string;
    names?: { en: string; official: string; native: string; endonyms: Record<string, string> };
  }>;
}

export function renderCartouche(
  t: FocusTarget,
  endo?: EndonymJson | null,
  allowCountry = true,
): ReactNode {
  if (t == null) return null;
  if (t.kind === "circle") {
    return (
      <div className="cartouche cartouche-circle">
        <div className="cartouche-headline">{t.label}</div>
        <div className="cartouche-sub">
          {t.center.lat.toFixed(2)}N · {t.center.lon.toFixed(2)}E
        </div>
      </div>
    );
  }
  if (!allowCountry) return null;
  // country
  const datum = t.iso3 && endo ? endo.countries[t.iso3] : null;
  const endonyms = datum?.names?.endonyms ?? {};
  const cyrillic = endonyms.ru ?? endonyms.uk ?? null;
  return (
    <div className="cartouche cartouche-country">
      <div className="cartouche-endonyms">
        {Object.entries(endonyms).slice(0, 8).map(([lang, value]) => (
          <div key={lang} className="cartouche-endo">{value}</div>
        ))}
      </div>
      <h2 className="cartouche-title">{t.name}</h2>
      {cyrillic && <div className="cartouche-cyrillic">{cyrillic}</div>}
    </div>
  );
}

export function SpotlightCartouche({ allowCountry = true }: { readonly allowCountry?: boolean }) {
  const { focusTarget } = useSpotlight();
  const [endo, setEndo] = useState<EndonymJson | null>(null);
  useEffect(() => {
    if (!allowCountry) return;
    fetch("/country-endonyms.json").then((r) => r.json()).then(setEndo).catch(() => setEndo(null));
  }, [allowCountry]);
  return <>{renderCartouche(focusTarget, endo, allowCountry)}</>;
}
