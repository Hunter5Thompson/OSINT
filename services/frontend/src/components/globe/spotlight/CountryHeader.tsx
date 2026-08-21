import { useSpatialCountryAlmanac } from "../../../hooks/useSpatialCountryAlmanac";
import { formatCoords } from "../../../lib/coords";
import type { SpatialQueryRef } from "../../../spatial/contracts";
import type { CountrySelection } from "../../../spatial/selection";
import {
  CountryAlmanacPanel,
  SpatialCountryAlmanacPanel,
} from "./CountryAlmanacPanel";

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
          <dd>{capital.name} · {formatCoords([capital.coords.lat, capital.coords.lon], 2)}</dd>
        </dl>
      )}
      <CountryAlmanacPanel iso3={iso3} m49={m49} />
    </div>
  );
}

export function SpatialCountryHeader({
  selection,
  query,
}: {
  readonly selection: CountrySelection;
  readonly query: SpatialQueryRef | null;
}) {
  const committedQuery = query?.scopeKey === selection.scopeKey ? query : null;
  const facts = useSpatialCountryAlmanac(committedQuery);
  const capital = facts.status === "ready" ? facts.data.capital : null;

  return (
    <div className="country-header">
      <div className="eyebrow">§ inspector · country · {selection.scopeKey}</div>
      <h3 className="country-title">{selection.label}</h3>
      {capital !== null ? (
        <dl className="country-grid">
          <dt>capital</dt>
          <dd>{capital.name} · {formatCoords([capital.lat, capital.lon], 2)}</dd>
        </dl>
      ) : null}
      <SpatialCountryAlmanacPanel facts={facts} query={committedQuery} />
    </div>
  );
}
