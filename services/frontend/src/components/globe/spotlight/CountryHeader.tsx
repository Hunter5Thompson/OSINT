import { CountryAlmanacPanel } from "./CountryAlmanacPanel";

interface Props {
  name: string;
  iso3: string | null;
  m49: string;
  capital: { name: string; coords: { lon: number; lat: number } } | null;
}

export function CountryHeader({ name, iso3, m49, capital }: Props) {
  return (
    <div className="country-header">
      <div className="eyebrow">§ inspector · country · {iso3 ?? `m49 · ${m49}`}</div>
      <h3 className="country-title">{name}</h3>
      {capital && (
        <dl className="country-grid">
          <dt>capital</dt>
          <dd>{capital.name} · {capital.coords.lat.toFixed(2)}N {capital.coords.lon.toFixed(2)}E</dd>
        </dl>
      )}
      <CountryAlmanacPanel iso3={iso3} m49={m49} />
    </div>
  );
}
