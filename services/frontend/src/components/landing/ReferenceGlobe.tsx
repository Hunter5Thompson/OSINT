import { useEffect, useId, useState } from "react";
import { geoGraticule10, geoOrthographic, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";

const projection = geoOrthographic()
  .rotate([-28, -22])
  .translate([260, 260])
  .scale(215);
const path = geoPath(projection);
const graticule = path(geoGraticule10()) ?? "";

/** Geographic reference, independent of live feeds and WebGL. */
export function ReferenceGlobe() {
  const [land, setLand] = useState("");
  const gradientId = useId();
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/countries-110m.json", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Reference map unavailable");
        const topology = (await response.json()) as Topology;
        if (!controller.signal.aborted && topology.objects.countries) {
          setLand(path(feature(topology, topology.objects.countries)) ?? "");
        }
      })
      .catch(() => {
        /* The reference graticule remains available offline. */
      });
    return () => controller.abort();
  }, []);
  return (
    <svg
      className="reference-globe"
      viewBox="0 0 520 520"
      role="img"
      aria-label="Geographic reference globe centered on Europe and Africa"
    >
      <defs>
        <radialGradient id={gradientId} cx="35%" cy="30%" r="75%">
          <stop offset="0" stopColor="#343329" />
          <stop offset="0.65" stopColor="#191c19" />
          <stop offset="1" stopColor="#0b0d0c" />
        </radialGradient>
      </defs>
      <circle
        cx="260"
        cy="260"
        r="249"
        fill="none"
        stroke="var(--granite)"
        strokeDasharray="1 7"
      />
      <circle cx="260" cy="260" r="233" fill="none" stroke="var(--granite)" />
      <path
        d="M 260 9 V 35 M 260 485 V 511 M 9 260 H 35 M 485 260 H 511"
        stroke="var(--amber)"
        opacity="0.7"
      />
      <circle
        cx="260"
        cy="260"
        r="215"
        fill={`url(#${gradientId})`}
        stroke="var(--stone)"
        strokeOpacity="0.45"
      />
      <path
        d={graticule}
        fill="none"
        stroke="var(--stone)"
        strokeWidth="0.5"
        opacity="0.23"
      />
      <path
        d={land}
        fill="#6e7255"
        fillOpacity="0.42"
        stroke="#b3a883"
        strokeWidth="0.65"
        strokeOpacity="0.7"
      />
      <text
        x="260"
        y="26"
        textAnchor="middle"
        fill="var(--stone)"
        fontSize="10"
        className="mono"
      >
        N
      </text>
    </svg>
  );
}
